"""Phase 5J qualified lead API endpoint tests — fully offline, deterministic.

Exercise ``POST /api/runs/{run_id}/leads`` end to end against a temp SQLite
database with the FastAPI ``TestClient``.

Contract under test:

  1. eligible (QUALIFIED + PASS) candidate generates a lead
  2. lead run_id matches the candidate's run relationship
  3. lead candidate_id matches the requested candidate
  4. lead reuses the persisted qualification_id
  5. lead references only the persisted qualification's evidence ids
  6. verified_email stays None (no verification infrastructure yet)
  7. optional profile fields stay None when no profile exists
  8. non-QUALIFIED candidate -> 409, no lead persisted
  9. run absent                              -> 404 "Run not found"
 10. candidate absent                        -> 404 "Candidate not found"
 11. candidate in another run                -> 404 "Candidate not found in run"
 12. QUALIFIED candidate without a persisted qualification -> 409, no lead
 13. persisted qualification not PASS         -> 409, no lead
 14. response order preserves request order
 15. re-generating a lead replaces (no duplicate rows)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import (
    CandidateStatus,
    ContactReadiness,
    EvidenceType,
    QualificationStatus,
)
from app.db.base import Base
from app.db.orm.company import LeadRecord
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.evidence import Evidence
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_qualify_endpoint.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase5j.db').as_posix()}",
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


def _create_run(db: Session) -> str:
    return str(make_owned_run(db).run_id)


def _create_candidate(db: Session, run_id: str) -> CompanyCandidate:
    return CompanyRepository(db).create_candidate(
        CompanyCandidate(
            run_id=run_id,
            company_name="Acme Robotics",
            official_website="https://www.acme.com",
        )
    )


def _persist_evidence(db: Session, candidate_id, *, evidence_type: EvidenceType, value: str, claim: str) -> str:
    evidence = Evidence(
        candidate_id=candidate_id,
        evidence_type=evidence_type,
        claim=claim,
        extracted_value=value,
    )
    return str(EvidenceRepository(db).create(evidence).evidence_id)


def _qualify(client: TestClient, run_id, candidate_ids):
    return client.post(
        f"/api/runs/{run_id}/qualify",
        json={"candidate_ids": candidate_ids},
    )


def _generate_leads(client: TestClient, run_id, candidate_ids):
    return client.post(
        f"/api/runs/{run_id}/leads",
        json={"candidate_ids": candidate_ids},
    )


def _count_lead_rows(db: Session, candidate_id) -> int:
    return len(
        db.scalars(
            select(LeadRecord).where(LeadRecord.candidate_id == candidate_id)
        ).all()
    )


# ---------------------------------------------------------------------------
# PASS evidence set: every locked evaluator returns PASS
# ---------------------------------------------------------------------------


def _add_pass_evidence(db: Session, candidate_id) -> None:
    _persist_evidence(
        db, candidate_id,
        evidence_type=EvidenceType.FUNDING,
        value="$2 million",
        claim="funding_amount_usd",
    )
    _persist_evidence(
        db, candidate_id,
        evidence_type=EvidenceType.PLATFORM,
        value="The company provides SaaS software for logistics teams.",
        claim="technology platform claim",
    )
    _persist_evidence(
        db, candidate_id,
        evidence_type=EvidenceType.LOCATION,
        value="The company is headquartered in London, United Kingdom.",
        claim="primary_location",
    )
    _persist_evidence(
        db, candidate_id,
        evidence_type=EvidenceType.COMPANY_DESCRIPTION,
        value="Jane Doe is the CEO of Acme.",
        claim="company description",
    )
    _persist_evidence(
        db, candidate_id,
        evidence_type=EvidenceType.CEO,
        value="Jane Doe, CEO \u2014 jane@acme.com",
        claim="ceo",
    )


def _make_qualified_candidate(db: Session, client: TestClient, run_id: str):
    """Create a candidate, qualify it via the API, and return it."""
    candidate = _create_candidate(db, run_id)
    _add_pass_evidence(db, candidate.candidate_id)
    response = _qualify(client, run_id, [str(candidate.candidate_id)])
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["overall_status"] == QualificationStatus.PASS.value
    return candidate, result


# ---------------------------------------------------------------------------
# 1-7. eligible candidate generates a properly assembled lead
# ---------------------------------------------------------------------------


def test_eligible_candidate_generates_lead(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        qualification = QualificationRepository(persistence_db).get_by_candidate(
            candidate.candidate_id
        )
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert len(body["leads"]) == 1
    lead = body["leads"][0]
    assert lead["candidate_id"] == str(candidate.candidate_id)
    assert lead["company_name"] == "Acme Robotics"
    # The candidate's own site exists but no EMAIL evidence type was persisted,
    # so the honest readiness label is COMPANY_CONTACT_AVAILABLE.
    assert lead["contact_readiness"] == ContactReadiness.COMPANY_CONTACT_AVAILABLE.value

    persisted = LeadRepository(persistence_db).get_by_candidate(candidate.candidate_id)
    assert persisted is not None
    assert persisted.lead_id is not None


def test_lead_run_id_matches_candidate_run(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    lead = response.json()["leads"][0]
    assert lead["run_id"] == run_id


def test_lead_reuses_persisted_qualification_id(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        qualification = QualificationRepository(persistence_db).get_by_candidate(
            candidate.candidate_id
        )
        assert qualification is not None
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    lead = response.json()["leads"][0]
    assert lead["qualification_id"] == str(qualification.qualification_id)


def test_lead_references_only_persisted_evidence_ids(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        qualification = QualificationRepository(persistence_db).get_by_candidate(
            candidate.candidate_id
        )
        persisted_ids = {str(e.evidence_id) for e in
                         EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)}
        qualification_evidence = {str(value) for value in qualification.evidence_ids}
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    lead = response.json()["leads"][0]
    lead_ids = set(lead["evidence_ids"])
    assert lead_ids <= persisted_ids
    assert lead_ids == qualification_evidence
    assert lead_ids


def test_lead_verified_email_is_none(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    lead = response.json()["leads"][0]
    assert lead["verified_email"] is None
    assert lead["ceo_or_cofounder_name"] is None


def test_lead_optional_fields_none_when_no_profile(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        assert CompanyRepository(persistence_db).get_profile(candidate.candidate_id) is None
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    lead = response.json()["leads"][0]
    assert lead["description"] is None
    assert lead["industry_or_sector"] is None


def test_lead_reuses_only_persisted_profile_values(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        CompanyRepository(persistence_db).save_profile(
            CompanyProfile(
                candidate_id=candidate.candidate_id,
                company_name="Acme Robotics",
                description="Warehouse automation provider.",
                industry_or_sector="logistics software",
            )
        )
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    lead = response.json()["leads"][0]
    assert lead["description"] == "Warehouse automation provider."
    assert lead["industry_or_sector"] == "logistics software"


# ---------------------------------------------------------------------------
# 8. non-QUALIFIED candidate
# ---------------------------------------------------------------------------


def test_non_qualified_candidate_rejected_no_lead(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 409
    assert response.json()["detail"] == "Candidate not qualified"
    assert _count_lead_rows(persistence_db, candidate.candidate_id) == 0


# ---------------------------------------------------------------------------
# 9-11. validation failures
# ---------------------------------------------------------------------------


def test_run_not_found_returns_404(persistence_db):
    _override_db(app, persistence_db)
    try:
        response = _generate_leads(authed_client(app, persistence_db), str(uuid4()), [str(uuid4())])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_candidate_not_found_returns_404(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        response = _generate_leads(authed_client(app, persistence_db), run_id, [str(uuid4())])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"


def test_candidate_in_another_run_returns_404(persistence_db):
    run_id = _create_run(persistence_db)
    other_run = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, other_run)

    _override_db(app, persistence_db)
    try:
        response = _generate_leads(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found in run"


# ---------------------------------------------------------------------------
# 12. QUALIFIED status without a persisted qualification
# ---------------------------------------------------------------------------


def test_qualified_without_persisted_qualification_no_lead(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    CompanyRepository(persistence_db).set_candidate_status(
        candidate.candidate_id, CandidateStatus.QUALIFIED
    )

    _override_db(app, persistence_db)
    try:
        response = _generate_leads(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 409
    assert response.json()["detail"] == "Qualification not found"
    assert _count_lead_rows(persistence_db, candidate.candidate_id) == 0


# ---------------------------------------------------------------------------
# 13. persisted qualification not PASS
# ---------------------------------------------------------------------------


def test_persisted_qualification_not_pass_no_lead(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_evidence(
        persistence_db, candidate.candidate_id,
        evidence_type=EvidenceType.FUNDING,
        value="$700K",
        claim="funding_amount_usd",
    )

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _qualify(client, run_id, [str(candidate.candidate_id)])
        assert response.status_code == 200
        assert response.json()["results"][0]["overall_status"] == QualificationStatus.FAIL.value

        # Force a discrepancy: QUALIFIED status but persisted decision is FAIL.
        CompanyRepository(persistence_db).set_candidate_status(
            candidate.candidate_id, CandidateStatus.QUALIFIED
        )
        leads_response = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert leads_response.status_code == 409
    assert leads_response.json()["detail"] == "Candidate qualification is not PASS"
    assert _count_lead_rows(persistence_db, candidate.candidate_id) == 0


# ---------------------------------------------------------------------------
# 14. multiple candidates preserve the requested order
# ---------------------------------------------------------------------------


def test_multiple_candidates_preserve_request_order(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        first, _ = _make_qualified_candidate(persistence_db, client, run_id)
        second, _ = _make_qualified_candidate(persistence_db, client, run_id)

        requested = [str(second.candidate_id), str(first.candidate_id)]
        response = _generate_leads(client, run_id, requested)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert [lead["candidate_id"] for lead in response.json()["leads"]] == requested


# ---------------------------------------------------------------------------
# 15. re-generating replaces, never duplicates
# ---------------------------------------------------------------------------


def test_regeneration_replaces_without_duplicates(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        candidate, _ = _make_qualified_candidate(persistence_db, client, run_id)
        first = _generate_leads(client, run_id, [str(candidate.candidate_id)])
        second = _generate_leads(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["leads"][0]["candidate_id"] == str(candidate.candidate_id)
    assert second.json()["leads"][0]["candidate_id"] == str(candidate.candidate_id)
    assert _count_lead_rows(persistence_db, candidate.candidate_id) == 1