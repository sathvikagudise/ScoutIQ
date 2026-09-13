"""Phase 5O run results endpoint tests - fully offline, deterministic.

Exercise ``GET /api/runs/{run_id}/results`` against a temp SQLite database with
the FastAPI ``TestClient``.

Contract under test:

  1. an existing run returns its persisted run + leads + contacts output
  2. an unknown run id -> 404 "Run not found"
  3. an empty completed run returns valid empty output
  4. returned leads exactly match the persisted lead data
  5. persisted None fields remain None (never inferred)
  6. returned collection ordering is deterministic (leads and contacts)
  7. reading results twice never mutates persistence
  8. run completion fields are returned accurately (status, lead count, completed_at)
  9. only contacts belonging to the run's own candidates are returned
 10. contact email and verification_status are returned exactly as persisted
 11. no person/email attribution is fabricated
 12. contact evidence_ids follow the persistence contract only (no fabricated
     round-trip)
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import RunStatus, VerificationStatus
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate
from app.models.contact import Contact
from app.models.lead import QualifiedLead
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_run_completion_endpoint.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase5o.db').as_posix()}",
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


def _create_run(db: Session, completed: bool = False) -> DiscoveryRun:
    return make_owned_run(db, completed=completed)


def _create_candidate(db: Session, run_id: UUID) -> CompanyCandidate:
    return CompanyRepository(db).create_candidate(
        CompanyCandidate(run_id=run_id, company_name="Acme Robotics")
    )


def _persist_lead(
    db: Session, run_id: UUID, candidate: CompanyCandidate, *, created_at=None
) -> QualifiedLead:
    return LeadRepository(db).create(
        QualifiedLead(
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
            description=candidate.company_name,
            industry_or_sector="Robotics",
            created_at=created_at or datetime.datetime.now(datetime.timezone.utc),
        )
    )


def _persist_contact(
    db: Session,
    candidate: CompanyCandidate,
    *,
    email=None,
    role=None,
    verification_status=VerificationStatus.UNVERIFIED,
    created_at=None,
) -> Contact:
    return ContactRepository(db).create(
        Contact(
            candidate_id=candidate.candidate_id,
            full_name="Jane Smith",
            role=role,
            email=email,
            verification_status=verification_status,
            created_at=created_at or datetime.datetime.now(datetime.timezone.utc),
        )
    )


def _get_results(client: TestClient, run_id):
    return client.get(f"/api/runs/{run_id}/results")


def _db_snapshot(db: Session, run_id: UUID) -> dict:
    run = RunRepository(db).get(run_id)
    return {
        "status": run.status,
        "qualified_lead_count": run.qualified_lead_count,
        "completed_at": run.completed_at,
        "lead_ids": sorted(
            str(lead.lead_id) for lead in LeadRepository(db).list_by_run(run_id)
        ),
        "contact_ids": sorted(
            str(contact.contact_id)
            for candidate in CompanyRepository(db).list_candidates()
            if candidate.run_id == run_id
            for contact in ContactRepository(db).list_by_candidate(candidate.candidate_id)
        ),
    }


# ---------------------------------------------------------------------------
# 1-3. baseline retrieval
# ---------------------------------------------------------------------------


def test_existing_run_returns_persisted_output(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    _persist_lead(persistence_db, run.run_id, candidate)
    _persist_contact(persistence_db, candidate)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_id"] == str(run.run_id)
    assert body["run"]["status"] == RunStatus.COMPLETED.value
    assert len(body["leads"]) == 1
    assert len(body["contacts"]) == 1
    assert body["contacts"][0]["candidate_id"] == str(candidate.candidate_id)


def test_missing_run_returns_404(persistence_db):
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, uuid4())
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_empty_completed_run_returns_valid_empty_output(persistence_db):
    run = _create_run(persistence_db, completed=True)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == RunStatus.COMPLETED.value
    assert body["leads"] == []
    assert body["contacts"] == []


# ---------------------------------------------------------------------------
# 4-5. exact persisted lead data; None stays None
# ---------------------------------------------------------------------------


def test_returned_leads_exactly_match_persisted(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    lead = _persist_lead(persistence_db, run.run_id, candidate)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    lead_json = response.json()["leads"][0]
    assert lead_json["lead_id"] == str(lead.lead_id)
    assert lead_json["candidate_id"] == str(lead.candidate_id)
    assert lead_json["company_name"] == lead.company_name
    assert lead_json["description"] == lead.description
    assert lead_json["industry_or_sector"] == lead.industry_or_sector
    assert lead_json["run_id"] == str(run.run_id)


def test_persisted_none_fields_stay_none(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    lead = LeadRepository(persistence_db).create(
        QualifiedLead(
            run_id=run.run_id,
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
            description=None,
            industry_or_sector=None,
            ceo_or_cofounder_name=None,
            verified_email=None,
        )
    )
    assert lead.description is None
    assert lead.verified_email is None

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    lead_json = response.json()["leads"][0]
    assert lead_json["description"] is None
    assert lead_json["industry_or_sector"] is None
    assert lead_json["ceo_or_cofounder_name"] is None
    assert lead_json["verified_email"] is None
    # Legacy leads predate contact enrichment; the field round-trips as None.
    assert lead_json["contact_readiness"] is None


# ---------------------------------------------------------------------------
# 6. deterministic ordering
# ---------------------------------------------------------------------------


def test_lead_ordering_is_deterministic(persistence_db):
    run = _create_run(persistence_db, completed=True)
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    candidate_a = _create_candidate(persistence_db, run.run_id)
    candidate_b = _create_candidate(persistence_db, run.run_id)
    candidate_c = _create_candidate(persistence_db, run.run_id)
    lead_a = _persist_lead(
        persistence_db, run.run_id, candidate_a, created_at=base + datetime.timedelta(minutes=3)
    )
    lead_b = _persist_lead(
        persistence_db, run.run_id, candidate_b, created_at=base + datetime.timedelta(minutes=1)
    )
    lead_c = _persist_lead(
        persistence_db, run.run_id, candidate_c, created_at=base + datetime.timedelta(minutes=2)
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    ids = [lead["lead_id"] for lead in response.json()["leads"]]
    assert ids == [str(lead_b.lead_id), str(lead_c.lead_id), str(lead_a.lead_id)]


def test_contact_ordering_is_deterministic(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    base = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    contact_a = _persist_contact(
        persistence_db, candidate, created_at=base + datetime.timedelta(minutes=5)
    )
    contact_b = _persist_contact(
        persistence_db, candidate, created_at=base + datetime.timedelta(minutes=1)
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    ids = [contact["contact_id"] for contact in response.json()["contacts"]]
    assert ids == [str(contact_b.contact_id), str(contact_a.contact_id)]


# ---------------------------------------------------------------------------
# 7. read-only guarantee
# ---------------------------------------------------------------------------


def test_repeated_read_does_not_mutate_persistence(persistence_db):
    run = _create_run(persistence_db, completed=False)
    candidate = _create_candidate(persistence_db, run.run_id)
    _persist_lead(persistence_db, run.run_id, candidate)
    _persist_contact(persistence_db, candidate)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        completed = client.post(f"/api/runs/{run.run_id}/complete")
        assert completed.status_code == 200
        first = _get_results(client, run.run_id)
        second = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    snapshot = _db_snapshot(persistence_db, run.run_id)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert snapshot["status"] == RunStatus.COMPLETED
    assert snapshot["qualified_lead_count"] == 1
    assert snapshot["completed_at"] is not None
    assert len(snapshot["lead_ids"]) == 1
    assert len(snapshot["contact_ids"]) == 1


# ---------------------------------------------------------------------------
# 8. completion fields returned accurately
# ---------------------------------------------------------------------------


def test_completion_fields_returned_accurately(persistence_db):
    run = _create_run(persistence_db, completed=False)
    candidate = _create_candidate(persistence_db, run.run_id)
    _persist_lead(persistence_db, run.run_id, candidate)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        completed = client.post(f"/api/runs/{run.run_id}/complete")
        assert completed.status_code == 200
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == RunStatus.COMPLETED.value
    assert body["run"]["qualified_lead_count"] == 1
    assert body["run"]["completed_at"] is not None


# ---------------------------------------------------------------------------
# 9-12. contacts: run scoping, exact persisted fields, no fabrication
# ---------------------------------------------------------------------------


def test_only_contacts_of_run_candidates_returned(persistence_db):
    run = _create_run(persistence_db, completed=True)
    other_run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    foreign_candidate = _create_candidate(persistence_db, other_run.run_id)
    own_contact = _persist_contact(persistence_db, candidate, role="CEO")
    foreign_contact = _persist_contact(persistence_db, foreign_candidate, role="CTO")
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    ids = [contact["contact_id"] for contact in response.json()["contacts"]]
    assert str(own_contact.contact_id) in ids
    assert str(foreign_contact.contact_id) not in ids


def test_contact_email_and_status_returned_as_persisted(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    contact = _persist_contact(
        persistence_db, candidate, role="CEO", email="jane@acme.com"
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact_json = response.json()["contacts"][0]
    assert contact_json["full_name"] == "Jane Smith"
    assert contact_json["role"] == "CEO"
    assert contact_json["email"] == "jane@acme.com"
    assert contact_json["verification_status"] == VerificationStatus.UNVERIFIED.value
    assert contact_json["contact_id"] == str(contact.contact_id)


def test_no_attribution_fabricated(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    _persist_contact(persistence_db, candidate, role="CEO", email=None)
    lead = LeadRepository(persistence_db).create(
        QualifiedLead(
            run_id=run.run_id,
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
        )
    )
    assert lead.ceo_or_cofounder_name is None
    assert lead.verified_email is None
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    contact_json = body["contacts"][0]
    lead_json = body["leads"][0]
    assert contact_json["email"] is None
    assert contact_json["verification_status"] == VerificationStatus.UNVERIFIED.value
    assert lead_json["ceo_or_cofounder_name"] is None
    assert lead_json["verified_email"] is None


def test_contact_evidence_ids_follow_persistence_contract(persistence_db):
    run = _create_run(persistence_db, completed=True)
    candidate = _create_candidate(persistence_db, run.run_id)
    contact = ContactRepository(persistence_db).create(
        Contact(
            candidate_id=candidate.candidate_id,
            full_name="Jane Smith",
            role="CEO",
            email=None,
            evidence_ids=[uuid4()],
        )
    )
    reloaded = ContactRepository(persistence_db).get(contact.contact_id)
    assert reloaded.evidence_ids == []
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _get_results(client, run.run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact_json = response.json()["contacts"][0]
    assert contact_json["evidence_ids"] == []