"""Phase 5N run completion endpoint tests - fully offline, deterministic.

Exercise ``POST /api/runs/{run_id}/complete`` against a temp SQLite database
with the FastAPI ``TestClient``.

Contract under test:

  1. completion sets status == COMPLETED, completed_at, and the exact counted
     number of persisted lead rows for the run
  2. the count is derived from ``LeadRepository.list_by_run``, never from
     request input or a prior run value
  3. a run with zero persisted leads still completes (count == 0)
  4. an unknown run id -> 404 "Run not found"
  5. completion is idempotent: double completion never creates, deletes, or
     duplicates leads and recomputes the same final state
  6. re-completing after the persisted lead set changes recomputes the count
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import RunStatus
from app.db.base import Base
from app.db.orm.company import LeadRecord
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate
from app.models.lead import QualifiedLead
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_lead_endpoint.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase5n.db').as_posix()}",
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


def _create_run(db: Session) -> UUID:
    return make_owned_run(db).run_id


def _create_candidate(db: Session, run_id: UUID) -> CompanyCandidate:
    return CompanyRepository(db).create_candidate(
        CompanyCandidate(run_id=run_id, company_name="Acme Robotics")
    )


def _persist_lead(db: Session, run_id: UUID, candidate: CompanyCandidate) -> QualifiedLead:
    return LeadRepository(db).create(
        QualifiedLead(
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
        )
    )


def _complete(client: TestClient, run_id):
    return client.post(f"/api/runs/{run_id}/complete")


def _count_lead_rows(db: Session, run_id: UUID) -> int:
    return len(
        db.scalars(select(LeadRecord).where(LeadRecord.run_id == run_id)).all()
    )


# ---------------------------------------------------------------------------
# 1-2. successful completion with correct persisted lead count
# ---------------------------------------------------------------------------


def test_successful_completion_sets_final_state(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_lead(persistence_db, run_id, candidate)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _complete(client, run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == RunStatus.COMPLETED.value
    assert body["qualified_lead_count"] == 1
    assert body["completed_at"] is not None

    persisted = RunRepository(persistence_db).get(run_id)
    assert persisted.status == RunStatus.COMPLETED
    assert persisted.qualified_lead_count == 1
    assert persisted.completed_at is not None


def test_completion_count_matches_multiple_persisted_leads(persistence_db):
    run_id = _create_run(persistence_db)
    candidate_a = _create_candidate(persistence_db, run_id)
    candidate_b = _create_candidate(persistence_db, run_id)
    candidate_c = _create_candidate(persistence_db, run_id)
    _persist_lead(persistence_db, run_id, candidate_a)
    _persist_lead(persistence_db, run_id, candidate_b)
    _persist_lead(persistence_db, run_id, candidate_c)
    assert _count_lead_rows(persistence_db, run_id) == 3

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _complete(client, run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["qualified_lead_count"] == 3
    assert _count_lead_rows(persistence_db, run_id) == 3


# ---------------------------------------------------------------------------
# 3. zero-lead completion
# ---------------------------------------------------------------------------


def test_zero_leads_still_completes(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _complete(client, run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == RunStatus.COMPLETED.value
    assert body["qualified_lead_count"] == 0
    assert body["completed_at"] is not None


# ---------------------------------------------------------------------------
# 4. missing run
# ---------------------------------------------------------------------------


def test_completion_returns_404_for_unknown_run(persistence_db):
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _complete(client, str(uuid4()))
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


# ---------------------------------------------------------------------------
# 5. idempotent double completion
# ---------------------------------------------------------------------------


def test_double_completion_is_idempotent(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_lead(persistence_db, run_id, candidate)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        first = _complete(client, run_id)
        second = _complete(client, run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == RunStatus.COMPLETED.value
    assert second.json()["qualified_lead_count"] == 1
    assert _count_lead_rows(persistence_db, run_id) == 1


# ---------------------------------------------------------------------------
# 6. recompute from persisted lead rows
# ---------------------------------------------------------------------------


def test_completion_recomputes_count_when_leads_change(persistence_db):
    run_id = _create_run(persistence_db)
    candidate_a = _create_candidate(persistence_db, run_id)
    candidate_b = _create_candidate(persistence_db, run_id)
    _persist_lead(persistence_db, run_id, candidate_a)

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        first = _complete(client, run_id)
        assert first.status_code == 200
        assert first.json()["qualified_lead_count"] == 1

        _persist_lead(persistence_db, run_id, candidate_b)
        second = _complete(client, run_id)
    finally:
        app.dependency_overrides.pop(get_db)

    assert second.status_code == 200
    assert second.json()["status"] == RunStatus.COMPLETED.value
    assert second.json()["qualified_lead_count"] == 2
    persisted = RunRepository(persistence_db).get(run_id)
    assert persisted.qualified_lead_count == 2