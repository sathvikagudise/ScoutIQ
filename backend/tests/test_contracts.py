"""Phase 1 core data contract tests (fully offline)."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fakes import FakeAsyncClient, FakeResponse
from pydantic import ValidationError

import app.research.fetcher as fetcher_mod
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
from app.discovery.base import DiscoveryProvider
from app.discovery.service import DiscoveryService
from app.main import app
from app.models.activity import ActivityEvent
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.contact import Contact
from app.models.discovery import DiscoveredSource
from app.models.evidence import Evidence
from app.models.lead import QualifiedLead
from app.models.qualification import CriterionResult, QualificationResult
from app.models.run import DiscoveryRun, SearchQuery
from app.models.source import FetchValidation, Source
from app.research.fetcher import UrlFetcher


def run(coro):
    return asyncio.run(coro)


class FakeProvider(DiscoveryProvider):
    name = "fake"

    async def search(self, query, max_results=5):
        return [
            DiscoveredSource(query=query, title="Result", url="https://Example.com/a/", provider=self.name)
        ]


class FakeFetcher:
    """Stands in for UrlFetcher in endpoint tests."""

    async def validate(self, urls, max_urls=10):
        return [
            FetchValidation(
                url=url,
                status_code=200,
                final_url=url,
                reachable=True,
                content_type="text/html; charset=utf-8",
            )
            for url in urls[:max_urls]
        ]


client = TestClient(app)


# ---------------------------------------------------------------------------
# Model instantiation
# ---------------------------------------------------------------------------


def test_major_models_instantiate():
    run_model = DiscoveryRun(target_lead_count=5)
    candidate = CompanyCandidate(run_id=run_model.run_id, company_name="Acme Corp")
    source = Source(url="https://example.com", title="Title", provider="duckduckgo")
    profile = CompanyProfile(candidate_id=candidate.candidate_id, company_name="Acme Corp")
    evidence = Evidence(
        candidate_id=candidate.candidate_id,
        evidence_type=EvidenceType.FUNDING,
        claim="funding_amount_usd",
        extracted_value=2_500_000,
        source_url="https://example.com/evidence",
    )
    contact = Contact(candidate_id=candidate.candidate_id, full_name="Jane Doe", role="CEO")
    qualification = QualificationResult(candidate_id=candidate.candidate_id)
    lead = QualifiedLead(candidate_id=candidate.candidate_id, company_name="Acme Corp")
    event = ActivityEvent(
        run_id=run_model.run_id,
        phase=RunPhase.DISCOVERY,
        event_type=ActivityEventType.RUN_STARTED,
        message="Discovery run started",
    )

    ids = [
        run_model.run_id,
        source.source_id,
        candidate.candidate_id,
        profile.profile_id,
        evidence.evidence_id,
        contact.contact_id,
        qualification.qualification_id,
        lead.lead_id,
        event.event_id,
    ]
    assert all(isinstance(item, UUID) for item in ids)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_run_defaults():
    run_model = DiscoveryRun()
    assert run_model.status == RunStatus.PENDING
    assert run_model.started_at is not None
    assert run_model.completed_at is None
    assert run_model.qualified_lead_count == 0
    assert run_model.current_phase is None
    assert run_model.error_message is None
    assert run_model.metadata == {}


def test_source_defaults():
    source = Source(url="https://example.com", title="T", provider="p")
    assert source.discovered_at is not None
    assert source.fetch_status is None
    assert source.normalized_url is None


def test_discovered_source_inherits_source_contract():
    discovered = DiscoveredSource(url="https://x.io/a/", title="A", query="q", provider="p")
    assert isinstance(discovered, Source)
    dumped = discovered.model_dump()
    assert "source_id" in dumped
    assert "normalized_url" in dumped
    assert "domain" in dumped
    assert dumped["query"] == "q"


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


def test_invalid_run_status_rejected():
    with pytest.raises(ValidationError):
        DiscoveryRun(status="definitely_running")


def test_invalid_fetch_status_on_source_rejected():
    with pytest.raises(ValidationError):
        Source(url="https://e.com", title="t", provider="p", fetch_status="loading")


def test_invalid_candidate_status_rejected():
    with pytest.raises(ValidationError):
        CompanyCandidate(run_id=uuid4(), company_name="Acme", status="maybe")


# ---------------------------------------------------------------------------
# Optional fields remain None (no invented values)
# ---------------------------------------------------------------------------


def test_candidate_unknown_data_is_none():
    candidate = CompanyCandidate(run_id=uuid4(), company_name="Acme")
    assert candidate.official_website is None
    assert candidate.discovery_source_ids == []
    assert candidate.status == CandidateStatus.DISCOVERED


def test_profile_unknown_financials_are_none():
    candidate = CompanyCandidate(run_id=uuid4(), company_name="Acme")
    profile = CompanyProfile(candidate_id=candidate.candidate_id)
    assert profile.funding_amount_usd is None
    assert profile.revenue_amount_usd is None
    assert profile.description is None


def test_qualified_lead_email_is_optional():
    lead = QualifiedLead(candidate_id=uuid4(), company_name="Acme")
    assert lead.verified_email is None
    assert lead.ceo_or_cofounder_name is None


# ---------------------------------------------------------------------------
# Evidence integrity
# ---------------------------------------------------------------------------


def test_evidence_source_url_is_optional():
    """Evidence can exist as a lightweight domain object without a source URL.

    A source URL is provenance metadata required at the persistence boundary,
    not universally required for every in-memory Evidence instance (qualification
    evaluators construct evidence offline).
    """
    evidence = Evidence(
        candidate_id=uuid4(),
        evidence_type=EvidenceType.FUNDING,
        claim="funding_amount_usd",
        extracted_value=1_000_000,
    )
    assert evidence.source_url == ""


def test_evidence_accepts_unknown_extracted_value():
    evidence = Evidence(
        candidate_id=uuid4(),
        evidence_type=EvidenceType.REVENUE,
        claim="revenue_amount_usd",
        source_url="https://example.com/evidence",
    )
    assert evidence.extracted_value is None
    assert evidence.source_url == "https://example.com/evidence"


def test_evidence_confidence_bounds():
    with pytest.raises(ValidationError):
        Evidence(
            candidate_id=uuid4(),
            evidence_type=EvidenceType.CEO,
            claim="ceo_name",
            source_url="https://example.com/evidence",
            confidence=1.5,
        )


# ---------------------------------------------------------------------------
# Contact safety
# ---------------------------------------------------------------------------


def test_contact_can_exist_without_email():
    contact = Contact(candidate_id=uuid4(), full_name="Jane Doe")
    assert contact.email is None
    assert contact.role is None
    assert contact.verification_status == VerificationStatus.UNVERIFIED


# ---------------------------------------------------------------------------
# Qualification structure
# ---------------------------------------------------------------------------


def test_qualification_represents_insufficient_evidence_without_pass():
    qualification = QualificationResult(
        candidate_id=uuid4(),
        criteria=[
            CriterionResult(
                criterion=QualificationCriterion.FUNDING_OR_REVENUE,
                status=QualificationStatus.INSUFFICIENT_EVIDENCE,
                reasons=["No public funding or revenue figures found"],
            ),
            CriterionResult(
                criterion=QualificationCriterion.US_PRESENCE,
                status=QualificationStatus.NOT_EVALUATED,
            ),
        ],
    )
    assert qualification.overall_status == QualificationStatus.NOT_EVALUATED
    assert qualification.criteria[0].status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert qualification.overall_status != QualificationStatus.PASS


# ---------------------------------------------------------------------------
# Fetch status classification (real-world outcomes)
# ---------------------------------------------------------------------------


def test_fetch_classification_of_http_outcomes(monkeypatch):
    fake = FakeAsyncClient()
    fake.route("https://ok.example", response=FakeResponse(status_code=200))
    fake.route("https://blocked.example", response=FakeResponse(status_code=403))
    fake.route("https://limited.example", response=FakeResponse(status_code=429))
    fake.route("https://broken.example", response=FakeResponse(status_code=500))
    fake.route("https://missing.example", response=FakeResponse(status_code=404))
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    validations = run(
        UrlFetcher().validate(
            [
                "https://ok.example",
                "https://blocked.example",
                "https://limited.example",
                "https://broken.example",
                "https://missing.example",
            ]
        )
    )
    by_url = {item.url: item for item in validations}

    assert by_url["https://ok.example"].fetch_status == FetchStatus.SUCCESS
    assert by_url["https://ok.example"].reachable is True
    assert by_url["https://blocked.example"].fetch_status == FetchStatus.ACCESS_BLOCKED
    assert by_url["https://blocked.example"].reachable is False
    assert by_url["https://limited.example"].fetch_status == FetchStatus.RATE_LIMITED
    assert by_url["https://limited.example"].reachable is False
    assert by_url["https://broken.example"].fetch_status == FetchStatus.SERVER_ERROR
    assert by_url["https://broken.example"].reachable is False
    assert by_url["https://missing.example"].fetch_status == FetchStatus.NOT_FOUND
    assert by_url["https://missing.example"].reachable is False


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_models_serialize_cleanly():
    run_model = DiscoveryRun()
    parsed = json.loads(run_model.model_dump_json())
    assert parsed["run_id"]
    assert parsed["started_at"]
    assert parsed["status"] == "pending"

    evidence = Evidence(
        candidate_id=uuid4(),
        evidence_type=EvidenceType.LOCATION,
        claim="primary_location",
        extracted_value="Singapore",
        source_url="https://example.com/evidence",
    )
    parsed = json.loads(evidence.model_dump_json())
    assert parsed["evidence_type"] == "location"
    assert parsed["source_url"] == "https://example.com/evidence"


# ---------------------------------------------------------------------------
# Discovery service enrichment + API surface
# ---------------------------------------------------------------------------


def test_discovery_sources_enriched_with_metadata():
    service = DiscoveryService(FakeProvider())
    response = run(service.discover(["some query"], max_results_per_query=5))

    assert response.provider == "fake"
    assert response.total_results == 1
    source = response.results[0]
    assert source.normalized_url == "https://example.com/a"
    assert source.domain == "example.com"


def test_discovery_endpoints_preserve_phase0_behavior(monkeypatch):
    import app.main as main_mod

    class StubProvider(DiscoveryProvider):
        name = "stub"

        async def search(self, query, max_results=5):
            return [
                DiscoveredSource(query=query, title="A", url="https://example.com/a", provider=self.name)
            ]

    monkeypatch.setattr(main_mod, "discovery_service", DiscoveryService(StubProvider()))
    monkeypatch.setattr(main_mod, "url_fetcher", FakeFetcher())

    search = client.post("/api/discovery/search", json={"queries": ["q"], "max_results_per_query": 3})
    assert search.status_code == 200
    assert search.json()["provider"] == "stub"
    assert search.json()["deduplicated_count"] == 1
    assert search.json()["results"][0]["url"] == "https://example.com/a"

    response = client.post(
        "/api/discovery/validate",
        json={"queries": ["q"], "max_urls_to_validate": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stub"
    assert body["deduplicated_count"] == 1
    assert body["validations"][0]["validation"]["reachable"] is True
    assert body["validations"][0]["source"]["normalized_url"] == "https://example.com/a"


def test_contracts_endpoint():
    response = client.get("/api/system/contracts")
    assert response.status_code == 200
    body = response.json()
    assert "DiscoveryRun" in body["models"]
    assert "Evidence" in body["models"]
    assert "QualifiedLead" in body["models"]
    assert body["enums"]["FetchStatus"] == [
        "success",
        "access_blocked",
        "rate_limited",
        "server_error",
        "not_found",
        "timeout",
        "network_error",
        "unknown_error",
    ]
    assert "pending" in body["enums"]["RunStatus"]