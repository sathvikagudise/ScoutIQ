"""Phase 11 candidate-classification tests — fully offline, deterministic.

Exercise the run-scoped candidate analysis + classification exposed by
``GET /api/runs/{run_id}/results`` (``candidate_summary`` + ``candidates``)
against a temp SQLite database.

Contract under test:

  1. a candidate whose three persisted company criteria all PASS and whose
     persisted overall status is PASS is COMPANY_QUALIFIED (passed = 3)
  2. exactly two PASS + one INSUFFICIENT_EVIDENCE  -> NEAR_QUALIFIED
  3. exactly two PASS + one FAIL                   -> NEAR_QUALIFIED
  4. exactly one PASS                              -> NOT_QUALIFIED (never
     qualified or near)
  5. zero PASS                                     -> NOT_QUALIFIED
  6. classification is run-scoped: persisted criteria decide each candidate
     independently
  7. candidates from OTHER runs never appear in this run's candidate list
  8. a candidate with no persisted decision is NOT_EVALUATED (truthful), never
     "failed"
  9. blocking criteria reflect the persisted statuses verbatim (FAIL stays
     FAIL; INSUFFICIENT_EVIDENCE stays INSUFFICIENT_EVIDENCE) and carry the
     persisted reasons
 10. the company-qualified count matches the persisted-overall-PASS contract
     (== funnel.company_qualified and == leads for that run)
 11. near-qualified never leaks into the qualified-lead count
 12. contact readiness never influences any classification
 13. the Phase 10 funnel remains correct alongside the new fields
 14. reading results is read-only and idempotent
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import (
    ContactReadiness,
    FetchStatus,
    QualificationCriterion,
    QualificationStatus,
    RunStatus,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.lead import QualifiedLead
from app.models.qualification import CriterionResult, QualificationResult
from app.models.run import DiscoveryRun, SearchQuery
from app.models.source import Source
from app.repositories.company_repository import CompanyRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.query_repository import QueryRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run
from app.repositories.source_repository import SourceRepository

CRITERIA = (
    QualificationCriterion.FUNDING_OR_REVENUE,
    QualificationCriterion.TECH_PLATFORM,
    QualificationCriterion.US_PRESENCE,
)

ALL_PASS = {criterion: QualificationStatus.PASS for criterion in CRITERIA}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase11.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    def _enable_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _override_db(app_obj, persistence_db):
    def override_get_db():
        yield persistence_db

    app_obj.dependency_overrides[get_db] = override_get_db


def _create_run(db: Session, *, completed: bool = False) -> DiscoveryRun:
    return make_owned_run(db, completed=completed)


def _create_query(db: Session, run_id: UUID) -> SearchQuery:
    return QueryRepository(db).create(
        SearchQuery(run_id=run_id, query_text="acme logistics funding")
    )


def _create_source(
    db: Session, query_id: UUID, *, fetch_status: FetchStatus | None = None
) -> Source:
    source = SourceRepository(db).create(
        Source(
            url=f"https://example.com/source-{uuid4().hex}",
            normalized_url=f"https://example.com/norm-{uuid4().hex}",
            title="Source",
            provider="test",
            discovered_by_query_id=query_id,
        )
    )
    if fetch_status is not None:
        source = SourceRepository(db).update_validation(
            source.source_id, fetch_status=fetch_status
        )
    return source


def _create_candidate(
    db: Session, run_id: UUID, *, name: str = "Acme Robotics"
) -> CompanyCandidate:
    return CompanyRepository(db).create_candidate(
        CompanyCandidate(run_id=run_id, company_name=name)
    )


def _save_profile(db: Session, candidate_id, *, description: str, industry: str):
    CompanyRepository(db).save_profile(
        CompanyProfile(
            candidate_id=candidate_id,
            description=description,
            industry_or_sector=industry,
        )
    )


def _persist_qualification(
    db: Session,
    candidate_id,
    results: dict,
    *,
    overall: QualificationStatus,
    criterion_reasons: dict | None = None,
):
    return QualificationRepository(db).save(
        QualificationResult(
            candidate_id=candidate_id,
            criteria=[
                CriterionResult(
                    criterion=criterion,
                    status=results[criterion],
                    reasons=list((criterion_reasons or {}).get(criterion, [])),
                )
                for criterion in CRITERIA
            ],
            overall_status=overall,
        )
    )


def _persist_lead(
    db: Session,
    run_id: UUID,
    candidate: CompanyCandidate,
    *,
    readiness: ContactReadiness | None = None,
) -> QualifiedLead:
    return LeadRepository(db).create(
        QualifiedLead(
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
            contact_readiness=readiness,
        )
    )


def _get_results(client: TestClient, run_id):
    return client.get(f"/api/runs/{run_id}/results")


def _candidate_by_name(body: dict, name: str) -> dict:
    match = [item for item in body["candidates"] if item["company_name"] == name]
    assert len(match) == 1
    return match[0]


# ---------------------------------------------------------------------------
# 1. all three PASS with overall PASS -> COMPANY_QUALIFIED
# ---------------------------------------------------------------------------


def test_all_three_pass_is_company_qualified(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id, name="Acme")
    _save_profile(
        persistence_db,
        candidate.candidate_id,
        description="Logistics robotics",
        industry="Robotics",
    )
    _persist_qualification(
        persistence_db, candidate.candidate_id, ALL_PASS, overall=QualificationStatus.PASS
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "Acme")
    assert item["classification"] == "company_qualified"
    assert item["passed_criteria_count"] == 3
    assert item["overall_status"] == "pass"
    # The queue-question: profile description/industry come from persistence.
    assert item["description"] == "Logistics robotics"
    assert item["industry_or_sector"] == "Robotics"
    assert all(
        item["criteria"][key]["status"] == QualificationStatus.PASS.value
        for key in ("financial", "tech_platform", "us_presence")
    )
    assert body["candidate_summary"]["company_qualified"] == 1
    assert body["candidate_summary"]["near_qualified"] == 0


# ---------------------------------------------------------------------------
# 2-3. exactly two PASS + third INSUFFICIENT or FAIL -> NEAR_QUALIFIED
# ---------------------------------------------------------------------------


def test_two_pass_one_insufficient_is_near_qualified(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id, name="Beta")
    results = dict(ALL_PASS)
    results[QualificationCriterion.US_PRESENCE] = QualificationStatus.INSUFFICIENT_EVIDENCE
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        results,
        overall=QualificationStatus.INSUFFICIENT_EVIDENCE,
        criterion_reasons={
            QualificationCriterion.US_PRESENCE: ["No explicit base location found."]
        },
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "Beta")
    assert item["classification"] == "near_qualified"
    assert item["passed_criteria_count"] == 2
    assert item["overall_status"] == QualificationStatus.INSUFFICIENT_EVIDENCE.value
    us_presence = item["blocking_criteria"][0]
    assert us_presence["criterion"] == "us_presence"
    assert us_presence["status"] == QualificationStatus.INSUFFICIENT_EVIDENCE.value
    assert us_presence["reasons"] == ["No explicit base location found."]
    assert body["candidate_summary"]["near_qualified"] == 1
    assert body["candidate_summary"]["company_qualified"] == 0


def test_two_pass_one_fail_is_near_qualified(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id, name="Gamma")
    results = dict(ALL_PASS)
    results[QualificationCriterion.TECH_PLATFORM] = QualificationStatus.FAIL
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        results,
        overall=QualificationStatus.FAIL,
        criterion_reasons={
            QualificationCriterion.TECH_PLATFORM: ["Not a technology platform."]
        },
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "Gamma")
    assert item["classification"] == "near_qualified"
    assert item["passed_criteria_count"] == 2
    assert item["overall_status"] == QualificationStatus.FAIL.value
    blocker = item["blocking_criteria"][0]
    assert blocker["criterion"] == "tech_platform"
    # FAIL is never rewritten as "missing evidence" — it stays FAIL.
    assert blocker["status"] == QualificationStatus.FAIL.value
    assert blocker["reasons"] == ["Not a technology platform."]


# ---------------------------------------------------------------------------
# 4-5. one or zero PASS -> NOT_QUALIFIED
# ---------------------------------------------------------------------------


def test_one_pass_is_not_qualified(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id, name="Delta")
    results = dict(ALL_PASS)
    results[QualificationCriterion.FUNDING_OR_REVENUE] = QualificationStatus.PASS
    results[QualificationCriterion.TECH_PLATFORM] = QualificationStatus.FAIL
    results[QualificationCriterion.US_PRESENCE] = QualificationStatus.INSUFFICIENT_EVIDENCE
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        results,
        overall=QualificationStatus.FAIL,
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "Delta")
    assert item["classification"] == "not_qualified"
    assert item["classification"] != "near_qualified"
    assert item["passed_criteria_count"] == 1
    assert {b["status"] for b in item["blocking_criteria"]} == {
        QualificationStatus.FAIL.value,
        QualificationStatus.INSUFFICIENT_EVIDENCE.value,
    }


def test_zero_pass_is_not_qualified(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id, name="Epsilon")
    results = {
        criterion: QualificationStatus.INSUFFICIENT_EVIDENCE for criterion in CRITERIA
    }
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        results,
        overall=QualificationStatus.INSUFFICIENT_EVIDENCE,
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "Epsilon")
    assert item["classification"] == "not_qualified"
    assert item["passed_criteria_count"] == 0
    assert body["candidate_summary"]["not_qualified"] == 1


# ---------------------------------------------------------------------------
# 6-8. run scoping, foreign candidates, and truthful not_evaluated
# ---------------------------------------------------------------------------


def test_classification_is_considered_independently_per_candidate(persistence_db):
    run = _create_run(persistence_db)
    qualified = _create_candidate(persistence_db, run.run_id, name="Alpha")
    near = _create_candidate(persistence_db, run.run_id, name="Beta")
    other = _create_candidate(persistence_db, run.run_id, name="Gamma")

    _persist_qualification(
        persistence_db, qualified.candidate_id, ALL_PASS, overall=QualificationStatus.PASS
    )
    near_results = dict(ALL_PASS)
    near_results[QualificationCriterion.US_PRESENCE] = QualificationStatus.FAIL
    _persist_qualification(
        persistence_db,
        near.candidate_id,
        near_results,
        overall=QualificationStatus.FAIL,
    )
    other_results = {
        criterion: QualificationStatus.INSUFFICIENT_EVIDENCE for criterion in CRITERIA
    }
    _persist_qualification(
        persistence_db,
        other.candidate_id,
        other_results,
        overall=QualificationStatus.INSUFFICIENT_EVIDENCE,
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    assert _candidate_by_name(body, "Alpha")["classification"] == "company_qualified"
    assert _candidate_by_name(body, "Beta")["classification"] == "near_qualified"
    assert _candidate_by_name(body, "Gamma")["classification"] == "not_qualified"


def test_other_runs_candidates_never_appear(persistence_db):
    run = _create_run(persistence_db)
    other_run = _create_run(persistence_db)
    own = _create_candidate(persistence_db, run.run_id, name="Own")
    _persist_qualification(
        persistence_db, own.candidate_id, ALL_PASS, overall=QualificationStatus.PASS
    )
    foreign = _create_candidate(persistence_db, other_run.run_id, name="Foreign")
    _persist_qualification(
        persistence_db, foreign.candidate_id, ALL_PASS, overall=QualificationStatus.PASS
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    names = {item["company_name"] for item in body["candidates"]}
    assert names == {"Own"}
    assert body["candidate_summary"] == {
        "company_qualified": 1,
        "near_qualified": 0,
        "not_qualified": 0,
        "not_evaluated": 0,
        "analyzed_total": 1,
    }


def test_unevaluated_candidate_is_not_evaluated_truthfully(persistence_db):
    run = _create_run(persistence_db)
    also_run = _create_run(persistence_db)
    unevaluated = _create_candidate(persistence_db, run.run_id, name="NoDecision")
    _create_candidate(persistence_db, also_run.run_id, name="ForeignNoDecision")

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "NoDecision")
    assert item["classification"] == "not_evaluated"
    assert item["overall_status"] is None
    assert item["passed_criteria_count"] == 0
    # The absent decision is NOT "failed" — the truthful state is explicit.
    assert item["classification"] != "not_qualified"
    assert all(c["status"] == "none" for c in item["criteria"].values())
    assert item["blocking_criteria"] == []
    assert body["candidate_summary"]["not_evaluated"] == 1
    assert body["candidate_summary"]["not_qualified"] == 0


# ---------------------------------------------------------------------------
# 9-11. blocking fidelity, contract count, near-qualified never leaks
# ---------------------------------------------------------------------------


def test_all_pass_but_overall_fail_is_never_company_qualified(persistence_db):
    """Edge: the financial-conflict guard can persist overall FAIL while all
    three criterion rows PASS. Such a candidate must be reported truthfully as
    not company-qualified (and not near) — never counted as a lead."""

    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id, name="Conflict")
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        ALL_PASS,
        overall=QualificationStatus.FAIL,
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    item = _candidate_by_name(body, "Conflict")
    assert item["classification"] == "not_qualified"
    assert item["classification"] != "company_qualified"
    assert item["overall_status"] == QualificationStatus.FAIL.value
    assert item["passed_criteria_count"] == 3
    assert body["candidate_summary"]["company_qualified"] == 0
    assert body["candidate_summary"]["near_qualified"] == 0
    assert body["funnel"]["company_qualified"] == 0


def test_company_qualified_count_matches_contract_and_leads(persistence_db):
    run = _create_run(persistence_db)
    query = _create_query(persistence_db, run.run_id)
    _create_source(persistence_db, query.query_id, fetch_status=FetchStatus.SUCCESS)

    qualified = _create_candidate(persistence_db, run.run_id, name="Qualified")
    _persist_qualification(
        persistence_db, qualified.candidate_id, ALL_PASS, overall=QualificationStatus.PASS
    )
    _persist_lead(
        persistence_db,
        run.run_id,
        qualified,
        readiness=ContactReadiness.EVIDENCED_CONTACT,
    )
    near = _create_candidate(persistence_db, run.run_id, name="Near")
    near_results = dict(ALL_PASS)
    near_results[QualificationCriterion.US_PRESENCE] = QualificationStatus.INSUFFICIENT_EVIDENCE
    _persist_qualification(
        persistence_db,
        near.candidate_id,
        near_results,
        overall=QualificationStatus.INSUFFICIENT_EVIDENCE,
    )
    # Mirror the pipeline: finalize recomputes the stored qualified count from
    # the persisted lead rows AFTER leads exist.
    RunRepository(persistence_db).update_progress(
        run.run_id,
        status=RunStatus.COMPLETED,
        qualified_lead_count=len(LeadRepository(persistence_db).list_by_run(run.run_id)),
        completed_at=datetime.datetime.now(datetime.timezone.utc),
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    assert body["funnel"]["company_qualified"] == 1
    assert body["candidate_summary"]["company_qualified"] == 1
    assert len(body["leads"]) == 1
    assert [lead["company_name"] for lead in body["leads"]] == ["Qualified"]
    # Near-qualified never becomes a lead and never inflates the run's count.
    assert body["run"]["qualified_lead_count"] == 1
    assert body["candidate_summary"]["near_qualified"] == 1
    assert "Near" not in [lead["company_name"] for lead in body["leads"]]


def test_near_qualified_never_counts_as_qualified_lead(persistence_db):
    run = _create_run(persistence_db, completed=True)
    near = _create_candidate(persistence_db, run.run_id, name="NearOnly")
    results = dict(ALL_PASS)
    results[QualificationCriterion.TECH_PLATFORM] = QualificationStatus.FAIL
    _persist_qualification(
        persistence_db,
        near.candidate_id,
        results,
        overall=QualificationStatus.FAIL,
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    assert body["candidate_summary"]["near_qualified"] == 1
    assert body["candidate_summary"]["company_qualified"] == 0
    assert body["funnel"]["company_qualified"] == 0
    assert body["run"]["qualified_lead_count"] == 0
    assert body["leads"] == []


# ---------------------------------------------------------------------------
# 12. contact readiness never influences classification
# ---------------------------------------------------------------------------


def test_contact_readiness_never_changes_classification(persistence_db):
    run = _create_run(persistence_db)
    with_contact = _create_candidate(persistence_db, run.run_id, name="WithContact")
    without_contact = _create_candidate(persistence_db, run.run_id, name="WithoutContact")
    for candidate in (with_contact, without_contact):
        _persist_qualification(
            persistence_db,
            candidate.candidate_id,
            ALL_PASS,
            overall=QualificationStatus.PASS,
        )
    _persist_lead(
        persistence_db,
        run.run_id,
        with_contact,
        readiness=ContactReadiness.PUBLIC_EMAIL_AVAILABLE,
    )

    _override_db(app, persistence_db)
    try:
        body = _get_results(authed_client(app, persistence_db), run.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    # Same persisted qualification, different contact readiness: classification
    # and the qualified count are driven ONLY by company criteria.
    assert _candidate_by_name(body, "WithContact")["classification"] == "company_qualified"
    assert _candidate_by_name(body, "WithoutContact")["classification"] == "company_qualified"
    assert body["candidate_summary"]["company_qualified"] == 2
    assert body["contact_breakdown"]["public_email_available"] == 1
    assert body["candidate_summary"]["near_qualified"] == 0

    # A near-qualified candidate stays near even when a lead row exists with a
    # strong readiness (in practice the pipeline never writes that lead, but the
    # classification must not depend on contact state at all).
    run2 = _create_run(persistence_db)
    forced_near = _create_candidate(persistence_db, run2.run_id, name="NearWithLead")
    near_results = dict(ALL_PASS)
    near_results[QualificationCriterion.US_PRESENCE] = QualificationStatus.FAIL
    _persist_qualification(
        persistence_db,
        forced_near.candidate_id,
        near_results,
        overall=QualificationStatus.FAIL,
    )
    _persist_lead(
        persistence_db,
        run2.run_id,
        forced_near,
        readiness=ContactReadiness.EVIDENCED_CONTACT,
    )

    _override_db(app, persistence_db)
    try:
        body2 = _get_results(authed_client(app, persistence_db), run2.run_id).json()
    finally:
        app.dependency_overrides.pop(get_db)

    assert _candidate_by_name(body2, "NearWithLead")["classification"] == "near_qualified"
    assert body2["candidate_summary"]["near_qualified"] == 1
    assert body2["candidate_summary"]["company_qualified"] == 0


# ---------------------------------------------------------------------------
# 13-14. funnel still correct + read-only idempotency
# ---------------------------------------------------------------------------


def test_funnel_unchanged_and_results_read_only(persistence_db):
    run = _create_run(persistence_db, completed=True)
    query = _create_query(persistence_db, run.run_id)
    _create_source(persistence_db, query.query_id, fetch_status=FetchStatus.SUCCESS)
    _create_source(persistence_db, query.query_id, fetch_status=FetchStatus.SUCCESS)
    _create_source(persistence_db, query.query_id)

    qualified = _create_candidate(persistence_db, run.run_id, name="Alpha")
    near = _create_candidate(persistence_db, run.run_id, name="Beta")
    _persist_qualification(
        persistence_db, qualified.candidate_id, ALL_PASS, overall=QualificationStatus.PASS
    )
    near_results = dict(ALL_PASS)
    near_results[QualificationCriterion.US_PRESENCE] = QualificationStatus.INSUFFICIENT_EVIDENCE
    _persist_qualification(
        persistence_db,
        near.candidate_id,
        near_results,
        overall=QualificationStatus.INSUFFICIENT_EVIDENCE,
    )

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        first = _get_results(client, run.run_id)
        second = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    body = first.json()

    # The Phase 10 funnel contract is unchanged.
    assert body["funnel"] == {
        "sources_discovered": 3,
        "sources_researched": 2,
        "candidates_extracted": 2,
        "candidates_evaluated": 2,
        "financial_pass": 2,
        "tech_pass": 2,
        "geography_pass": 1,
        "company_qualified": 1,
    }
    assert body["candidate_summary"]["company_qualified"] == 1
    assert body["candidate_summary"]["near_qualified"] == 1
    assert body["candidate_summary"]["analyzed_total"] == 2

    # Reading results never mutates persistence.
    assert len(RunRepository(persistence_db).list_recent(limit=100)) == 1
    assert len(CompanyRepository(persistence_db).list_candidates()) == 2
    assert len(SourceRepository(persistence_db).list_by_run(run.run_id)) == 3
    assert len(LeadRepository(persistence_db).list_by_run(run.run_id)) == 0