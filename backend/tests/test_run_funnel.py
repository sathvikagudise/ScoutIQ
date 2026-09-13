"""Phase 10 run funnel tests — fully offline, deterministic.

Exercise the run-scoped funnel and contact-readiness breakdown exposed by
``GET /api/runs/{run_id}/results`` against a temp SQLite database.

Contract under test:

  1. an empty/completed run returns a zero funnel + zero breakdown
  2. every funnel count is derived from persisted state only (queries×sources,
     candidates, qualification criteria/results, leads)
  3. criterion pass counts are per-criterion over evaluated candidates and may
     overlap; ``company_qualified`` requires ALL THREE company criteria to pass
  4. candidates with no persisted qualification are never counted as evaluated
  5. qualification rows from OTHER runs never leak into this run's counts
  6. the contact breakdown counts persisted leads by readiness, and legacy
     leads (readiness None) report only as ``not_enriched``
  7. a company-qualified lead with no contact data stays a lead with None
     name/email and never receives a fabricated readiness
  8. reading results repeatedly is idempotent and never mutates persistence
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
from app.models.company import CompanyCandidate
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

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_run_results_endpoint.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase10.db').as_posix()}",
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
    db: Session,
    query_id: UUID,
    *,
    fetch_status: FetchStatus | None = None,
    url: str | None = None,
) -> Source:
    source = SourceRepository(db).create(
        Source(
            url=url or f"https://example.com/source-{uuid4().hex}",
            normalized_url=url or f"https://example.com/norm-{uuid4().hex}",
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


def _create_candidate(db: Session, run_id: UUID, *, name: str = "Acme Robotics") -> CompanyCandidate:
    return CompanyRepository(db).create_candidate(
        CompanyCandidate(run_id=run_id, company_name=name)
    )


def _persist_qualification(
    db: Session,
    candidate_id,
    results: list[tuple[QualificationCriterion, QualificationStatus]],
):
    overall = QualificationStatus.PASS if all(
        status == QualificationStatus.PASS for _, status in results
    ) else QualificationStatus.INSUFFICIENT_EVIDENCE
    if QualificationStatus.FAIL in {status for _, status in results}:
        overall = QualificationStatus.FAIL
    return QualificationRepository(db).save(
        QualificationResult(
            candidate_id=candidate_id,
            criteria=[
                CriterionResult(criterion=criterion, status=status)
                for criterion, status in results
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


# ---------------------------------------------------------------------------
# 1. empty run
# ---------------------------------------------------------------------------


def test_empty_completed_run_all_funnel_counts_zero(persistence_db):
    run = _create_run(persistence_db, completed=True)
    _override_db(app, persistence_db)
    try:
        response = _get_results(authed_client(app, persistence_db), run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["leads"] == []
    assert body["contacts"] == []
    assert body["funnel"] == {
        "sources_discovered": 0,
        "sources_researched": 0,
        "candidates_extracted": 0,
        "candidates_evaluated": 0,
        "financial_pass": 0,
        "tech_pass": 0,
        "geography_pass": 0,
        "company_qualified": 0,
    }
    assert body["contact_breakdown"] == {
        "evidenced_contact": 0,
        "named_contact_no_email": 0,
        "public_email_available": 0,
        "company_contact_available": 0,
        "no_contact_found": 0,
        "not_enriched": 0,
    }


# ---------------------------------------------------------------------------
# 2-3. funnel counts from persisted state, with overlapping criteria
# ---------------------------------------------------------------------------


def test_funnel_counts_derive_from_persisted_state(persistence_db):
    run = _create_run(persistence_db, completed=True)
    query = _create_query(persistence_db, run.run_id)
    _create_source(
        persistence_db, query.query_id, fetch_status=FetchStatus.SUCCESS
    )
    _create_source(
        persistence_db, query.query_id, fetch_status=FetchStatus.SUCCESS
    )
    _create_source(persistence_db, query.query_id, fetch_status=FetchStatus.NOT_FOUND)
    _create_source(persistence_db, query.query_id)

    candidate_pass = _create_candidate(persistence_db, run.run_id, name="Alpha")
    candidate_partial = _create_candidate(persistence_db, run.run_id, name="Beta")
    _create_candidate(persistence_db, run.run_id, name="Gamma")

    _persist_qualification(
        persistence_db,
        candidate_pass.candidate_id,
        [
            (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
            (QualificationCriterion.TECH_PLATFORM, QualificationStatus.PASS),
            (QualificationCriterion.US_PRESENCE, QualificationStatus.PASS),
        ],
    )
    _persist_qualification(
        persistence_db,
        candidate_partial.candidate_id,
        [
            (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
            (QualificationCriterion.TECH_PLATFORM, QualificationStatus.PASS),
            (QualificationCriterion.US_PRESENCE, QualificationStatus.INSUFFICIENT_EVIDENCE),
        ],
    )

    _override_db(app, persistence_db)
    try:
        response = _get_results(authed_client(app, persistence_db), run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    funnel = response.json()["funnel"]
    assert funnel["sources_discovered"] == 4
    assert funnel["sources_researched"] == 2
    assert funnel["candidates_extracted"] == 3
    assert funnel["candidates_evaluated"] == 2
    # Criterion passes are per-criterion and overlap: Alpha + Beta both pass
    # funding and tech, only Alpha passes geography.
    assert funnel["financial_pass"] == 2
    assert funnel["tech_pass"] == 2
    assert funnel["geography_pass"] == 1
    # Only Alpha passed ALL THREE company criteria.
    assert funnel["company_qualified"] == 1


def test_partial_criteria_do_not_auto_qualify(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id)
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        [
            (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
            (QualificationCriterion.TECH_PLATFORM, QualificationStatus.PASS),
            (QualificationCriterion.US_PRESENCE, QualificationStatus.INSUFFICIENT_EVIDENCE),
        ],
    )
    _override_db(app, persistence_db)
    try:
        response = _get_results(authed_client(app, persistence_db), run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    funnel = response.json()["funnel"]
    assert funnel["financial_pass"] == 1
    assert funnel["tech_pass"] == 1
    assert funnel["geography_pass"] == 0
    assert funnel["company_qualified"] == 0


# ---------------------------------------------------------------------------
# 4-5. run scoping and unevaluated candidates
# ---------------------------------------------------------------------------


def test_other_runs_and_unevaluated_candidates_do_not_leak(persistence_db):
    run = _create_run(persistence_db)
    other_run = _create_run(persistence_db)

    own_candidate = _create_candidate(persistence_db, run.run_id, name="Own")
    foreign_candidate = _create_candidate(persistence_db, other_run.run_id, name="Foreign")
    unevaluated = _create_candidate(persistence_db, run.run_id, name="NoQual")

    _persist_qualification(
        persistence_db,
        own_candidate.candidate_id,
        [
            (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
            (QualificationCriterion.TECH_PLATFORM, QualificationStatus.INSUFFICIENT_EVIDENCE),
            (QualificationCriterion.US_PRESENCE, QualificationStatus.INSUFFICIENT_EVIDENCE),
        ],
    )
    _persist_qualification(
        persistence_db,
        foreign_candidate.candidate_id,
        [
            (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
            (QualificationCriterion.TECH_PLATFORM, QualificationStatus.PASS),
            (QualificationCriterion.US_PRESENCE, QualificationStatus.PASS),
        ],
    )

    _override_db(app, persistence_db)
    try:
        response = _get_results(authed_client(app, persistence_db), run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    funnel = response.json()["funnel"]
    assert funnel["candidates_extracted"] == 2
    assert funnel["candidates_evaluated"] == 1
    assert funnel["company_qualified"] == 0
    assert funnel["financial_pass"] == 1


# ---------------------------------------------------------------------------
# 6-7. contact readiness breakdown and the no-contact qualified lead contract
# ---------------------------------------------------------------------------


def test_contact_breakdown_counts_by_readiness_and_legacy_not_enriched(persistence_db):
    run = _create_run(persistence_db, completed=True)
    with_readiness = {
        ContactReadiness.EVIDENCED_CONTACT: "A",
        ContactReadiness.NAMED_CONTACT_NO_EMAIL: "B",
        ContactReadiness.PUBLIC_EMAIL_AVAILABLE: "C",
        ContactReadiness.COMPANY_CONTACT_AVAILABLE: "D",
        ContactReadiness.NO_CONTACT_FOUND: "E",
    }
    candidates = {}
    for readiness, name in with_readiness.items():
        candidate = _create_candidate(persistence_db, run.run_id, name=name)
        _persist_qualification(
            persistence_db,
            candidate.candidate_id,
            [
                (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
                (QualificationCriterion.TECH_PLATFORM, QualificationStatus.PASS),
                (QualificationCriterion.US_PRESENCE, QualificationStatus.PASS),
            ],
        )
        candidates[name] = candidate
    for name, candidate in candidates.items():
        _persist_lead(
            persistence_db,
            run.run_id,
            candidate,
            readiness=next(
                readiness for readiness, n in with_readiness.items() if n == name
            ),
        )
    legacy = _create_candidate(persistence_db, run.run_id, name="Legacy")
    _persist_lead(persistence_db, run.run_id, legacy)

    _override_db(app, persistence_db)
    try:
        response = _get_results(authed_client(app, persistence_db), run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["contact_breakdown"] == {
        "evidenced_contact": 1,
        "named_contact_no_email": 1,
        "public_email_available": 1,
        "company_contact_available": 1,
        "no_contact_found": 1,
        "not_enriched": 1,
    }


def test_company_qualified_without_contact_data_stays_a_lead(persistence_db):
    run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run.run_id)
    _persist_qualification(
        persistence_db,
        candidate.candidate_id,
        [
            (QualificationCriterion.FUNDING_OR_REVENUE, QualificationStatus.PASS),
            (QualificationCriterion.TECH_PLATFORM, QualificationStatus.PASS),
            (QualificationCriterion.US_PRESENCE, QualificationStatus.PASS),
        ],
    )
    # The candidate is company-qualified, but no contact was ever assembled:
    # the lead carries no name, no email, and a legacy NULL readiness.
    lead = _persist_lead(persistence_db, run.run_id, candidate)
    assert lead.ceo_or_cofounder_name is None
    assert lead.verified_email is None

    _override_db(app, persistence_db)
    try:
        response = _get_results(authed_client(app, persistence_db), run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["funnel"]["company_qualified"] == 1
    assert body["contact_breakdown"] == {
        "evidenced_contact": 0,
        "named_contact_no_email": 0,
        "public_email_available": 0,
        "company_contact_available": 0,
        "no_contact_found": 0,
        "not_enriched": 1,
    }
    lead_json = body["leads"][0]
    assert lead_json["ceo_or_cofounder_name"] is None
    assert lead_json["verified_email"] is None
    assert lead_json["contact_readiness"] is None


# ---------------------------------------------------------------------------
# 8. idempotent read
# ---------------------------------------------------------------------------


def test_repeated_read_is_identical_and_none_mutating(persistence_db):
    run = _create_run(persistence_db)
    query = _create_query(persistence_db, run.run_id)
    _create_source(persistence_db, query.query_id, fetch_status=FetchStatus.SUCCESS)
    candidate = _create_candidate(persistence_db, run.run_id)
    lead = _persist_lead(
        persistence_db, run.run_id, candidate, readiness=ContactReadiness.NO_CONTACT_FOUND
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

    # The only lead/qualification/source rows persisted remain, untouched.
    assert len(LeadRepository(persistence_db).list_by_run(run.run_id)) == 1
    assert LeadRepository(persistence_db).get_by_candidate(candidate.candidate_id) is not None
    assert len(SourceRepository(persistence_db).list_by_run(run.run_id)) == 1