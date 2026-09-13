"""Phase 2 persistence tests — every test runs against an isolated SQLite file."""

import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import (
    ActivityEventType,
    CandidateStatus,
    EvidenceType,
    FetchStatus,
    QualificationCriterion,
    QualificationStatus,
    RunPhase,
    RunStatus,
    VerificationStatus,
)
from app.db.base import Base
from app.db.session import get_db
from app.db.orm.source import SourceRecord
from app.main import app
from app.models.activity import ActivityEvent
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.contact import Contact
from app.models.evidence import Evidence
from app.models.lead import QualifiedLead
from app.models.qualification import CriterionResult, QualificationResult
from app.models.run import DiscoveryRun, SearchQuery
from app.models.source import Source
from app.models import common
from app.repositories.activity_repository import ActivityRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.query_repository import QueryRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository
from api_helpers import authed_client


@pytest.fixture()
def engine(tmp_path):
    url = f"sqlite:///{(tmp_path / 'phase2.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    def _enable_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


def make_run(target: int = 10) -> DiscoveryRun:
    return DiscoveryRun(target_lead_count=target)


def make_candidate(run_id, name="Acme Corp") -> CompanyCandidate:
    return CompanyCandidate(run_id=run_id, company_name=name)


# ---------------------------------------------------------------------------
# Run persistence + progress
# ---------------------------------------------------------------------------


def test_run_persist_and_retrieve(db):
    created = RunRepository(db).create(make_run(target=7))

    loaded = RunRepository(db).get(created.run_id)

    assert loaded is not None
    assert loaded.run_id == created.run_id
    assert loaded.status == RunStatus.PENDING
    assert loaded.target_lead_count == 7
    assert loaded.qualified_lead_count == 0
    assert loaded.started_at is not None
    assert loaded.completed_at is None


def test_run_progress_update(db):
    run_repo = RunRepository(db)
    run = run_repo.create(make_run(target=5))

    updated = run_repo.update_progress(
        run.run_id,
        qualified_lead_count=3,
        status=RunStatus.COMPLETED,
        completed_at=datetime.datetime.now(datetime.timezone.utc),
    )

    assert updated.qualified_lead_count == 3
    assert updated.status == RunStatus.COMPLETED
    assert updated.completed_at is not None

    reloaded = run_repo.get(run.run_id)
    assert reloaded.qualified_lead_count == 3
    assert reloaded.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# Search query association
# ---------------------------------------------------------------------------


def test_queries_associated_with_run(db):
    run = RunRepository(db).create(make_run())
    query_repo = QueryRepository(db)

    query = SearchQuery(run_id=run.run_id, query_text="africa saas funding", strategy="funding_variant", provider="duckduckgo")
    query_repo.create(query)

    queries = query_repo.list_by_run(run.run_id)
    assert len(queries) == 1
    assert queries[0].query_id == query.query_id
    assert queries[0].run_id == run.run_id
    assert queries[0].query_text == "africa saas funding"
    assert queries[0].provider == "duckduckgo"


def test_orphan_query_without_run_fails(db):
    with pytest.raises(Exception):
        QueryRepository(db).create(SearchQuery(run_id=uuid4(), query_text="x"))


# ---------------------------------------------------------------------------
# Sources + URL uniqueness
# ---------------------------------------------------------------------------


def test_source_persist_and_retrieve(db):
    source_repo = SourceRepository(db)
    source = Source(
        url="https://example.com/article",
        title="Example",
        snippet="snippet",
        provider="duckduckgo",
    )
    persisted = source_repo.create(source)

    loaded = source_repo.get(persisted.source_id)
    assert loaded.url == source.url
    assert loaded.title == "Example"
    assert loaded.provider == "duckduckgo"
    assert loaded.normalized_url is None
    assert loaded.fetch_status is None


def test_duplicate_normalized_url_returns_existing(db):
    source_repo = SourceRepository(db)
    first = source_repo.create(
        Source(
            url="https://example.com/a/",
            normalized_url="https://example.com/a",
            title="A",
            provider="duckduckgo",
        )
    )
    second = source_repo.create(
        Source(
            url="https://example.com/a?utm_source=x",
            normalized_url="https://example.com/a",
            title="A-ish",
            provider="duckduckgo",
        )
    )

    assert second.source_id == first.source_id

    count = db.scalar(select(func.count()).select_from(SourceRecord))
    assert count == 1


# ---------------------------------------------------------------------------
# Candidate/source relationship
# ---------------------------------------------------------------------------


def test_candidate_sources_relationship(db):
    run = RunRepository(db).create(make_run())
    company_repo = CompanyRepository(db)
    source_repo = SourceRepository(db)

    candidate = company_repo.create_candidate(make_candidate(run.run_id, "Finco"))
    s1 = source_repo.create(Source(url="https://finco.example/1", title="S1", provider="p"))
    s2 = source_repo.create(Source(url="https://finco.example/2", title="S2", provider="p"))

    updated = company_repo.attach_sources(candidate.candidate_id, [s1.source_id, s2.source_id])
    assert set(updated.discovery_source_ids) == {s1.source_id, s2.source_id}

    sources = company_repo.list_sources(candidate.candidate_id)
    assert {s.url for s in sources} == {"https://finco.example/1", "https://finco.example/2"}

    reloaded = company_repo.get_candidate(candidate.candidate_id)
    assert set(reloaded.discovery_source_ids) == {s1.source_id, s2.source_id}


def test_candidate_create_with_sources(db):
    run = RunRepository(db).create(make_run())
    source_repo = SourceRepository(db)
    company_repo = CompanyRepository(db)

    s1 = source_repo.create(Source(url="https://x.example", title="X", provider="p"))
    candidate = CompanyCandidate(
        run_id=run.run_id, company_name="X Corp", discovery_source_ids=[s1.source_id]
    )

    persisted = company_repo.create_candidate(candidate)
    assert set(persisted.discovery_source_ids) == {s1.source_id}


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_evidence_multiple_records_per_claim(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    evidence_repo = EvidenceRepository(db)

    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.FUNDING,
            claim="funding_amount_usd",
            extracted_value=1_500_000,
            source_url="https://news.example/funding-1",
        )
    )
    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.FUNDING,
            claim="funding_amount_usd",
            extracted_value=2_000_000,
            source_url="https://news.example/funding-2",
        )
    )

    records = evidence_repo.list_by_claim(candidate.candidate_id, "funding_amount_usd")
    assert len(records) == 2
    # conflicting values coexist — no unique constraint on claim
    assert {record.extracted_value for record in records} == {1_500_000, 2_000_000}


def test_evidence_list_by_candidate_and_type(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    evidence_repo = EvidenceRepository(db)
    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.LOCATION,
            claim="primary_location",
            extracted_value="Singapore",
            source_url="https://site.example/about",
        )
    )

    location = evidence_repo.list_by_candidate_and_type(candidate.candidate_id, EvidenceType.LOCATION)
    assert len(location) == 1
    assert location[0].evidence_type == EvidenceType.LOCATION


# ---------------------------------------------------------------------------
# Contacts without email
# ---------------------------------------------------------------------------


def test_contact_without_email(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    contact_repo = ContactRepository(db)

    contact = Contact(candidate_id=candidate.candidate_id, full_name="Jane Doe", role="CEO")
    persisted = contact_repo.create(contact)

    loaded = contact_repo.get(persisted.contact_id)
    assert loaded.full_name == "Jane Doe"
    assert loaded.role == "CEO"
    assert loaded.email is None
    assert loaded.verification_status == VerificationStatus.UNVERIFIED


def test_contact_update(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    contact_repo = ContactRepository(db)
    contact = contact_repo.create(Contact(candidate_id=candidate.candidate_id, full_name="Jane Doe"))

    updated = contact_repo.update(
        contact.model_copy(
            update={"email": "jane@example.com", "verification_status": VerificationStatus.EVIDENCED}
        )
    )

    assert updated.email == "jane@example.com"
    assert updated.verification_status == VerificationStatus.EVIDENCED


# ---------------------------------------------------------------------------
# Enum round trips
# ---------------------------------------------------------------------------


def test_enum_round_trip(db):
    run_repo = RunRepository(db)
    source_repo = SourceRepository(db)
    company_repo = CompanyRepository(db)

    run = run_repo.create(make_run())
    failed = run_repo.update_status(run.run_id, RunStatus.FAILED)
    assert failed.status == RunStatus.FAILED
    assert run_repo.get(run.run_id).status == RunStatus.FAILED

    source = source_repo.create(
        Source(
            url="https://limited.example",
            normalized_url="https://limited.example",
            title="L",
            provider="p",
            fetch_status=FetchStatus.RATE_LIMITED,
            http_status_code=429,
        )
    )
    loaded_source = source_repo.get(source.source_id)
    assert loaded_source.fetch_status == FetchStatus.RATE_LIMITED
    assert loaded_source.http_status_code == 429

    candidate = company_repo.create_candidate(
        CompanyCandidate(run_id=run.run_id, company_name="Acme")
    )
    company_repo.set_candidate_status(candidate.candidate_id, CandidateStatus.QUALIFIED)
    assert company_repo.get_candidate(candidate.candidate_id).status == CandidateStatus.QUALIFIED


# ---------------------------------------------------------------------------
# Qualification persistence
# ---------------------------------------------------------------------------


def test_qualification_persists_insufficient_evidence(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    qual_repo = QualificationRepository(db)

    result = QualificationResult(
        candidate_id=candidate.candidate_id,
        criteria=[
            CriterionResult(
                criterion=QualificationCriterion.FUNDING_OR_REVENUE,
                status=QualificationStatus.INSUFFICIENT_EVIDENCE,
                reasons=["No public funding figures"],
            ),
            CriterionResult(
                criterion=QualificationCriterion.US_PRESENCE,
                status=QualificationStatus.NOT_EVALUATED,
            ),
        ],
    )
    saved = qual_repo.save(result)
    assert saved.overall_status == QualificationStatus.NOT_EVALUATED

    loaded = qual_repo.get_by_candidate(candidate.candidate_id)
    assert loaded is not None
    assert len(loaded.criteria) == 2
    funding = next(
        c for c in loaded.criteria if c.criterion == QualificationCriterion.FUNDING_OR_REVENUE
    )
    assert funding.status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert funding.reasons == ["No public funding figures"]
    assert not any(c.status == QualificationStatus.PASS for c in loaded.criteria)


# ---------------------------------------------------------------------------
# Company profile
# ---------------------------------------------------------------------------


def test_profile_persist_unknown_fields_null(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    company_repo = CompanyRepository(db)

    profile = CompanyProfile(
        candidate_id=candidate.candidate_id,
        company_name="Acme",
        funding_amount_usd=2_000_000,
    )
    saved = company_repo.save_profile(profile)

    assert saved.funding_amount_usd == 2_000_000
    assert saved.revenue_amount_usd is None
    assert saved.primary_location is None

    loaded = company_repo.get_profile(candidate.candidate_id)
    assert loaded.company_name == "Acme"
    assert loaded.funding_amount_usd == 2_000_000


# ---------------------------------------------------------------------------
# Qualified leads
# ---------------------------------------------------------------------------


def test_lead_list_by_run(db):
    run = RunRepository(db).create(make_run())
    candidate = CompanyRepository(db).create_candidate(make_candidate(run.run_id))
    lead_repo = LeadRepository(db)

    lead = lead_repo.create(
        QualifiedLead(run_id=run.run_id, candidate_id=candidate.candidate_id, company_name="Acme")
    )

    leads = lead_repo.list_by_run(run.run_id)
    assert len(leads) == 1
    assert leads[0].lead_id == lead.lead_id
    assert leads[0].verified_email is None


# ---------------------------------------------------------------------------
# Activity ordering
# ---------------------------------------------------------------------------


def test_activity_events_chronological(db):
    run = RunRepository(db).create(make_run())
    activity_repo = ActivityRepository(db)

    base = common.utcnow()
    for i in range(3):
        activity_repo.create(
            ActivityEvent(
                run_id=run.run_id,
                timestamp=base - datetime.timedelta(minutes=3 - i),
                phase=RunPhase.DISCOVERY,
                event_type=ActivityEventType.QUERY_EXECUTED,
                message=f"query {i}",
            )
        )

    events = activity_repo.list_by_run_chronological(run.run_id)
    assert [event.message for event in events] == ["query 0", "query 1", "query 2"]
    assert events[0].phase == RunPhase.DISCOVERY
    assert events[0].event_type == ActivityEventType.QUERY_EXECUTED


def test_activity_events_empty_for_unknown_run(db):
    assert ActivityRepository(db).list_by_run_chronological(uuid4()) == []


# ---------------------------------------------------------------------------
# API endpoints (isolated DB via dependency override)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(db):
    yield authed_client(app, db)
    app.dependency_overrides.pop(get_db)


def test_post_run_endpoint(client):
    response = client.post("/api/runs", json={"target_lead_count": 12})
    assert response.status_code == 201
    body = response.json()
    assert body["target_lead_count"] == 12
    assert body["status"] == "pending"
    assert body["run_id"]


def test_get_run_endpoint(client):
    created = client.post("/api/runs", json={"target_lead_count": 3}).json()
    response = client.get(f"/api/runs/{created['run_id']}")
    assert response.status_code == 200
    assert response.json()["target_lead_count"] == 3


def test_list_runs_endpoint(client):
    client.post("/api/runs", json={"target_lead_count": 1})
    client.post("/api/runs", json={"target_lead_count": 2})
    response = client.get("/api/runs")
    assert response.status_code == 200
    bodies = response.json()
    assert len(bodies) == 2
    assert {item["target_lead_count"] for item in bodies} == {1, 2}


def test_get_unknown_run_404(client):
    assert client.get(f"/api/runs/{uuid4()}").status_code == 404


def test_run_activity_endpoint(client, db):
    run_id = client.post("/api/runs", json={}).json()["run_id"]
    ActivityRepository(db).create(
        ActivityEvent(
            run_id=run_id,
            phase=RunPhase.DISCOVERY,
            event_type=ActivityEventType.RUN_STARTED,
            message="Discovery run started",
        )
    )
    response = client.get(f"/api/runs/{run_id}/activity")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["event_type"] == "run_started"


# ---------------------------------------------------------------------------
# Isolation: dev database must not be touched
# ---------------------------------------------------------------------------

from guard_helpers import dev_db_fingerprint


def test_developer_database_not_created(dev_db_start_state):
    """The offline test run must never create or modify the developer's
    ``backend/scoutiq.db`` — whether or not one already exists from live API
    use. Comparing the live fingerprint against the session-start snapshot
    proves this suite leaves the dev database untouched."""
    assert dev_db_fingerprint() == dev_db_start_state