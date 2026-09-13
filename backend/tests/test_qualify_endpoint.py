"""Phase 5H qualification API endpoint tests -- fully offline, deterministic.

Exercise ``POST /api/runs/{run_id}/qualify`` end to end against a temp SQLite
database with the FastAPI ``TestClient``.

Contract under test:

  1. run absent                                   -> 404 "Run not found"
  2. candidate absent                             -> 404 "Candidate not found"
  3. candidate in another run                     -> 404 "Candidate not found in run"
  4. evidence loaded from persisted repository
  5. locked QualificationService avoids fabricated evidence
  6. results persisted via QualificationRepository
  7. candidate status updated deterministically
  8. response order preserves request order
  9. re-qualification replaces (no duplicate rows)
 10. never QUALIFIED unless overall overall status is PASS
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import CandidateStatus, EvidenceType, QualificationStatus
from app.db.base import Base
from app.db.orm.qualification import QualificationRecord
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate
from app.models.evidence import Evidence
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_extraction.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase5h.db').as_posix()}",
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


# ---------------------------------------------------------------------------
# 1. PASS candidate
# ---------------------------------------------------------------------------


def test_pass_candidate_is_persisted_and_qualified(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _add_pass_evidence(persistence_db, candidate.candidate_id)

    _override_db(app, persistence_db)
    try:
        response = _qualify(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["candidate_id"] == str(candidate.candidate_id)
    assert result["overall_status"] == QualificationStatus.PASS.value

    persisted = QualificationRepository(persistence_db).get_by_candidate(candidate.candidate_id)
    assert persisted is not None
    assert persisted.overall_status == QualificationStatus.PASS

    status = CompanyRepository(persistence_db).get_candidate(candidate.candidate_id).status
    assert status == CandidateStatus.QUALIFIED


# ---------------------------------------------------------------------------
# 2. FAIL candidate
# ---------------------------------------------------------------------------


def test_fail_candidate_is_persisted_and_rejected(persistence_db):
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
        response = _qualify(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["overall_status"] == QualificationStatus.FAIL.value

    persisted = QualificationRepository(persistence_db).get_by_candidate(candidate.candidate_id)
    assert persisted is not None
    assert persisted.overall_status == QualificationStatus.FAIL

    status = CompanyRepository(persistence_db).get_candidate(candidate.candidate_id).status
    assert status == CandidateStatus.REJECTED
    assert status != CandidateStatus.QUALIFIED


# ---------------------------------------------------------------------------
# 3. INSUFFICIENT_EVIDENCE candidate
# ---------------------------------------------------------------------------


def test_insufficient_evidence_candidate_is_partially_verified(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)

    _override_db(app, persistence_db)
    try:
        response = _qualify(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["overall_status"] == QualificationStatus.INSUFFICIENT_EVIDENCE.value

    persisted = QualificationRepository(persistence_db).get_by_candidate(candidate.candidate_id)
    assert persisted is not None
    assert persisted.overall_status == QualificationStatus.INSUFFICIENT_EVIDENCE

    status = CompanyRepository(persistence_db).get_candidate(candidate.candidate_id).status
    assert status == CandidateStatus.PARTIALLY_VERIFIED
    assert status != CandidateStatus.QUALIFIED


# ---------------------------------------------------------------------------
# 4-6. validation failures
# ---------------------------------------------------------------------------


def test_run_not_found_returns_404(persistence_db):
    _override_db(app, persistence_db)
    try:
        response = _qualify(authed_client(app, persistence_db), str(uuid4()), [str(uuid4())])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_candidate_not_found_returns_404(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        response = _qualify(authed_client(app, persistence_db), run_id, [str(uuid4())])
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
        response = _qualify(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found in run"


# ---------------------------------------------------------------------------
# 7. evidence comes from the persisted repository (no fabricated evidence)
# ---------------------------------------------------------------------------


def test_evidence_loaded_from_persisted_repository(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _add_pass_evidence(persistence_db, candidate.candidate_id)

    persisted_evidence = EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)
    persisted_ids = {str(e.evidence_id) for e in persisted_evidence}
    assert len(persisted_ids) == 5

    _override_db(app, persistence_db)
    try:
        response = _qualify(authed_client(app, persistence_db), run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)

    # The decision references ONLY the persisted evidence rows, never fabricated ids.
    result = response.json()["results"][0]
    assert result["overall_status"] == QualificationStatus.PASS.value
    assert set(result["evidence_ids"]) <= persisted_ids
    assert set(result["evidence_ids"])


# ---------------------------------------------------------------------------
# 8. multiple candidates preserve the requested order
# ---------------------------------------------------------------------------


def test_multiple_candidates_preserve_request_order(persistence_db):
    run_id = _create_run(persistence_db)
    first = _create_candidate(persistence_db, run_id)
    second = _create_candidate(persistence_db, run_id)
    _add_pass_evidence(persistence_db, first.candidate_id)
    _add_pass_evidence(persistence_db, second.candidate_id)

    requested = [str(second.candidate_id), str(first.candidate_id)]

    _override_db(app, persistence_db)
    try:
        response = _qualify(authed_client(app, persistence_db), run_id, requested)
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert [result["candidate_id"] for result in response.json()["results"]] == requested


# ---------------------------------------------------------------------------
# 9. re-qualifying replaces, never duplicates
# ---------------------------------------------------------------------------


def test_requalification_replaces_without_duplicates(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _add_pass_evidence(persistence_db, candidate.candidate_id)

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        first = _qualify(client, run_id, [str(candidate.candidate_id)])
        second = _qualify(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["results"][0]["overall_status"] == QualificationStatus.PASS.value
    assert second.json()["results"][0]["overall_status"] == QualificationStatus.PASS.value

    rows = persistence_db.scalars(
        select(QualificationRecord).where(
            QualificationRecord.candidate_id == candidate.candidate_id
        )
    ).all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 10. never QUALIFIED unless overall status is PASS
# ---------------------------------------------------------------------------


def test_never_qualified_without_overall_pass(persistence_db):
    run_id = _create_run(persistence_db)
    failed = _create_candidate(persistence_db, run_id)
    partially = _create_candidate(persistence_db, run_id)
    _persist_evidence(
        persistence_db, failed.candidate_id,
        evidence_type=EvidenceType.FUNDING,
        value="$700K",
        claim="funding_amount_usd",
    )

    _override_db(app, persistence_db)
    try:
        response = _qualify(
            authed_client(app, persistence_db),
            run_id,
            [str(failed.candidate_id), str(partially.candidate_id)],
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    results = {result["candidate_id"]: result for result in response.json()["results"]}
    assert results[str(failed.candidate_id)]["overall_status"] != QualificationStatus.PASS.value
    assert results[str(partially.candidate_id)]["overall_status"] != QualificationStatus.PASS.value
    assert all(
        CompanyRepository(persistence_db).get_candidate(candidate_id).status
        != CandidateStatus.QUALIFIED
        for candidate_id in (failed.candidate_id, partially.candidate_id)
    )