"""Phase 10 run diagnostics endpoint tests - fully offline, deterministic.

Exercise ``GET /api/runs/{run_id}/diagnostics`` against a temp SQLite database
with the FastAPI ``TestClient``.

Contract under test:

  1. unknown run id -> 404 "Run not found"
  2. returns the run's persisted candidates, profiles, evidence, contacts, leads
  3. per-candidate qualification is computed live (the three company criteria) and is
     NEVER persisted by this endpoint (read-only diagnostics)
  4. candidates are scoped to the run (another run's candidates never appear)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import EvidenceType
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.contact import Contact
from app.models.evidence import Evidence
from app.models.lead import QualifiedLead
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase10_diag.db').as_posix()}",
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


def _seed_candidate(db: Session, run_id) -> CompanyCandidate:
    candidate = CompanyRepository(db).create_candidate(
        CompanyCandidate(run_id=run_id, company_name="Acme Robotics")
    )
    evidence_repo = EvidenceRepository(db)
    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.FUNDING,
            claim="funding_amount_usd",
            extracted_value="$2 million",
        )
    )
    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.COMPANY_DESCRIPTION,
            claim="company_description",
            extracted_value=(
                "Acme Robotics is a software company headquartered in Berlin. "
                "Alice Smith, CEO - alice@example.com"
            ),
        )
    )
    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.CEO,
            claim="ceo",
            extracted_value="Alice Smith, CEO",
        )
    )
    CompanyRepository(db).save_profile(
        CompanyProfile(
            candidate_id=candidate.candidate_id,
            company_name="Acme Robotics",
            primary_location="Berlin",
        )
    )
    ContactRepository(db).create(
        Contact(candidate_id=candidate.candidate_id, full_name="Alice Smith", role="CEO")
    )
    return candidate


def test_diagnostics_unknown_run_404(persistence_db):
    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).get(f"/api/runs/{uuid4()}/diagnostics")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_diagnostics_empty_run(persistence_db):
    run = make_owned_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).get(f"/api/runs/{run.run_id}/diagnostics")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_id"] == str(run.run_id)
    assert body["candidates"] == []
    assert body["leads"] == []


def test_diagnostics_snapshots_candidate_funnel(persistence_db):
    run = make_owned_run(persistence_db)
    candidate = _seed_candidate(persistence_db, run.run_id)
    lead_repo = LeadRepository(persistence_db)
    lead_repo.replace_for_candidate(
        QualifiedLead(
            run_id=run.run_id,
            candidate_id=candidate.candidate_id,
            company_name="Acme Robotics",
        )
    )

    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).get(f"/api/runs/{run.run_id}/diagnostics")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()

    assert len(body["candidates"]) == 1
    item = body["candidates"][0]
    assert item["candidate"]["company_name"] == "Acme Robotics"
    assert item["profile"] is not None
    assert item["profile"]["primary_location"] == "Berlin"
    assert {evidence["evidence_type"] for evidence in item["evidence"]} == {
        EvidenceType.FUNDING.value,
        EvidenceType.COMPANY_DESCRIPTION.value,
        EvidenceType.CEO.value,
    }
    assert item["contacts"][0]["full_name"] == "Alice Smith"

    qual = item["qualification"]
    assert qual["candidate_id"] == str(candidate.candidate_id)
    assert len(qual["criteria"]) == 3

    assert [lead["company_name"] for lead in body["leads"]] == ["Acme Robotics"]


def test_diagnostics_qualification_is_not_persisted(persistence_db):
    """Read-only guarantee: a live qualification computed by the endpoint must
    never be written to the qualification store."""
    run = make_owned_run(persistence_db)
    candidate = _seed_candidate(persistence_db, run.run_id)

    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).get(f"/api/runs/{run.run_id}/diagnostics")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert len(response.json()["candidates"]) == 1
    assert QualificationRepository(persistence_db).get_by_candidate(candidate.candidate_id) is None


def test_diagnostics_scopes_candidates_to_run(persistence_db):
    run_a = make_owned_run(persistence_db)
    run_b = make_owned_run(persistence_db)
    _seed_candidate(persistence_db, run_a.run_id)
    _seed_candidate(persistence_db, run_b.run_id)

    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).get(f"/api/runs/{run_a.run_id}/diagnostics")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["candidate"]["run_id"] == str(run_a.run_id)