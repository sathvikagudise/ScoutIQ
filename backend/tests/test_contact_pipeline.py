"""Phase 5L contact pipeline tests - fully offline, deterministic.

Exercise ``ContactAssemblyService`` and ``POST /api/runs/{run_id}/contacts``
against a temp SQLite database with the FastAPI ``TestClient``.

Contract under test:

  1. a contact is created only from persisted name+role evidence (CEO,
     Co-Founder, Founder claims persisted by the people extractor)
  2. full_name comes straight from the evidence value, never from an email
  3. role comes from the evidence type, never from company context
  4. email stays None: visible emails carry no person attribution by contract
  5. verification_status stays UNVERIFIED, never auto-upgraded
  6. evidence_ids reference only the evidence actually used, never fabricated
  7. the current Contact ORM does not persist evidence_ids (round-trip drops it)
  8. repeated processing is idempotent by ``(candidate_id, full_name, role)``
  9. same person + same role across sources deduplicates to one contact
 10. run/candidate ownership validation (404s) like the qualification endpoint
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.contact.service import ContactAssemblyService
from app.core.enums import EvidenceType, VerificationStatus
from app.db.base import Base
from app.db.orm.contact import ContactRecord
from app.db.session import get_db
from app.main import app
from app.models.company import CompanyCandidate
from app.models.contact import Contact
from app.models.evidence import Evidence
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run

# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_lead_endpoint.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase5l.db').as_posix()}",
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
        CompanyCandidate(run_id=run_id, company_name="Acme Robotics")
    )


def _persist_evidence(
    db: Session,
    candidate_id,
    *,
    evidence_type: EvidenceType,
    claim: str,
    value: object,
) -> str:
    evidence = EvidenceRepository(db).create(
        Evidence(
            candidate_id=candidate_id,
            evidence_type=evidence_type,
            claim=claim,
            extracted_value=value,
        )
    )
    return str(evidence.evidence_id)


def _persist_leader_name(db: Session, candidate_id, *, evidence_type: EvidenceType, name: str) -> str:
    claim = {
        EvidenceType.CEO: "ceo",
        EvidenceType.COFOUNDER: "cofounder",
        EvidenceType.FOUNDER: "founder",
    }[evidence_type]
    return _persist_evidence(
        db, candidate_id, evidence_type=evidence_type, claim=claim, value=name
    )


def _generate_contacts(client: TestClient, run_id, candidate_ids):
    return client.post(
        f"/api/runs/{run_id}/contacts",
        json={"candidate_ids": candidate_ids},
    )


def _count_contact_rows(db: Session, candidate_id) -> int:
    return len(
        db.scalars(
            select(ContactRecord).where(ContactRecord.candidate_id == candidate_id)
        ).all()
    )


# ---------------------------------------------------------------------------
# 1-3. one contact per persisted named leader
# ---------------------------------------------------------------------------


def test_contact_created_from_ceo_evidence(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    evidence_id = _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contacts = response.json()["contacts"]
    assert len(contacts) == 1
    contact = contacts[0]
    assert contact["full_name"] == "Jane Smith"
    assert contact["role"] == "CEO"
    assert contact["email"] is None
    assert contact["verification_status"] == VerificationStatus.UNVERIFIED.value
    assert contact["evidence_ids"] == [evidence_id]

    persisted = ContactRepository(persistence_db).get(UUID(contacts[0]["contact_id"]))
    assert persisted is not None
    assert persisted.full_name == "Jane Smith"
    assert persisted.role == "CEO"


def test_contact_created_from_cofounder_evidence(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.COFOUNDER,
        name="Sarah Lee",
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact = response.json()["contacts"][0]
    assert contact["full_name"] == "Sarah Lee"
    assert contact["role"] == "Co-Founder"


def test_contact_created_from_founder_evidence(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.FOUNDER,
        name="Michael Brown",
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact = response.json()["contacts"][0]
    assert contact["full_name"] == "Michael Brown"
    assert contact["role"] == "Founder"


def test_multiple_leaders_produce_multiple_contacts(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.COFOUNDER, name="Sarah Lee"
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contacts = response.json()["contacts"]
    assert {contact["full_name"] for contact in contacts} == {"Jane Smith", "Sarah Lee"}
    assert {contact["role"] for contact in contacts} == {"CEO", "Co-Founder"}


# ---------------------------------------------------------------------------
# 4. email never attached without person attribution
# ---------------------------------------------------------------------------


def test_contact_has_no_email_without_attribution(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    _persist_evidence(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.EMAIL,
        claim="email",
        value="jane@acme.com",
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact = response.json()["contacts"][0]
    assert contact["email"] is None


def test_no_contact_from_email_alone(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_evidence(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.EMAIL,
        claim="email",
        value="jane@acme.com",
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json()["contacts"] == []
    assert _count_contact_rows(persistence_db, candidate.candidate_id) == 0


# ---------------------------------------------------------------------------
# 6-7. evidence gating: only structured person claims produce contacts
# ---------------------------------------------------------------------------


def test_no_contact_from_sentence_value_claim(persistence_db):
    """Qualification-style evidence ("Jane Doe, CEO - jane@acme.com") is not a
    bare full name and must never produce a contact."""
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_evidence(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.CEO,
        claim="ceo",
        value="Jane Doe, CEO \u2014 jane@acme.com",
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json()["contacts"] == []


def test_no_contact_from_non_people_claim(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_evidence(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.COMPANY_DESCRIPTION,
        claim="company description",
        value="Jane Smith runs Acme Robotics.",
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json()["contacts"] == []


def test_no_contact_from_incomplete_name(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane"
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json()["contacts"] == []


# ---------------------------------------------------------------------------
# 8-9. idempotency: duplicate-free (candidate_id, full_name, role)
# ---------------------------------------------------------------------------


def test_same_person_same_role_across_sources_deduplicates(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert len(response.json()["contacts"]) == 1
    assert _count_contact_rows(persistence_db, candidate.candidate_id) == 1


def test_regeneration_is_idempotent(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        first = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
        second = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["contacts"][0]["contact_id"] == first.json()["contacts"][0]["contact_id"]
    assert _count_contact_rows(persistence_db, candidate.candidate_id) == 1


def test_existing_contact_reused_not_duplicated(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    pre_existing = ContactRepository(persistence_db).create(
        Contact(candidate_id=candidate.candidate_id, full_name="Jane Smith", role="CEO")
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact = response.json()["contacts"][0]
    assert contact["contact_id"] == str(pre_existing.contact_id)
    assert _count_contact_rows(persistence_db, candidate.candidate_id) == 1


# ---------------------------------------------------------------------------
# 5. verification stays UNVERIFIED; evidence ids are real, never fabricated
# ---------------------------------------------------------------------------


def test_evidence_ids_reference_only_used_evidence(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    used_id = _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    unrelated_id = _persist_evidence(
        persistence_db,
        candidate.candidate_id,
        evidence_type=EvidenceType.LOCATION,
        claim="primary_location",
        value="London",
    )

    service = ContactAssemblyService(persistence_db)
    contacts = service.assemble(candidate.candidate_id)

    assert len(contacts) == 1
    assert contacts[0].evidence_ids == [UUID(used_id)]
    assert UUID(unrelated_id) not in contacts[0].evidence_ids


def test_existing_contact_verification_never_upgraded(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )
    ContactRepository(persistence_db).create(
        Contact(candidate_id=candidate.candidate_id, full_name="Jane Smith", role="CEO")
    )
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    contact = response.json()["contacts"][0]
    assert contact["verification_status"] == VerificationStatus.UNVERIFIED.value
    persisted = ContactRepository(persistence_db).get(UUID(contact["contact_id"]))
    assert persisted.verification_status == VerificationStatus.UNVERIFIED


def test_evidence_ids_not_persisted_by_orm(persistence_db):
    """Documented Phase 5I limitation: the Contact ORM has no evidence_ids
    column, so a DB round-trip drops the linkage."""
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _persist_leader_name(
        persistence_db, candidate.candidate_id, evidence_type=EvidenceType.CEO, name="Jane Smith"
    )

    contact = Contact(
        candidate_id=candidate.candidate_id,
        full_name="Jane Smith",
        role="CEO",
        email=None,
        evidence_ids=[uuid4()],
    )
    persisted = ContactRepository(persistence_db).create(contact)
    reloaded = ContactRepository(persistence_db).get(persisted.contact_id)

    assert reloaded.evidence_ids == []


# ---------------------------------------------------------------------------
# 10. endpoint run/candidate ownership validation
# ---------------------------------------------------------------------------


def test_endpoint_run_not_found(persistence_db):
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, uuid4(), [str(uuid4())])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_endpoint_candidate_not_found(persistence_db):
    run_id = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(uuid4())])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"


def test_endpoint_candidate_in_another_run(persistence_db):
    run_id = _create_run(persistence_db)
    other_run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, other_run_id)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found in run"


def test_requests_without_leader_evidence_still_validate_ownership(persistence_db):
    run_id = _create_run(persistence_db)
    candidate = _create_candidate(persistence_db, run_id)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = _generate_contacts(client, run_id, [str(candidate.candidate_id)])
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json()["contacts"] == []