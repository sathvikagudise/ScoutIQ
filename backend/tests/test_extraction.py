"""Phase 4 candidate extraction & evidence collection tests — fully offline."""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import app.main as main_mod
from app.core.enums import EvidenceType, FetchStatus, VerificationStatus
from app.db.base import Base
from app.db.session import get_db
from app.extraction.extractors import run_all_extractors
from app.extraction.extractors.company import extract_company
from app.extraction.extractors.contact import extract_contact_details
from app.extraction.extractors.description import extract_description
from app.extraction.extractors.funding import extract_funding
from app.extraction.extractors.geography import extract_geography
from app.extraction.extractors.people import extract_people
from app.extraction.service import claim_is_candidate_scoped
from app.models.company import CompanyCandidate
from app.extraction.extractors.platform import extract_platform
from app.extraction.extractors.revenue import extract_revenue
from app.extraction.extractors.sector import extract_sector
from app.extraction.extractors.website import extract_website
from app.extraction.service import CandidateExtractionService
from app.main import app
from app.models.run import DiscoveryRun
from app.models.source import Source
from app.repositories.company_repository import CompanyRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository
from api_helpers import authed_client
from app.research.models import ExtractedEmail, PageMetadata, ResearchResult


def run(coro):
    return asyncio.run(coro)


def make_research(
    visible_text="",
    title=None,
    og_site=None,
    og_title=None,
    og_desc=None,
    meta_desc=None,
    canonical=None,
    emails=(),
    source_url="https://www.acme.example/",
    content_type="text/html",
) -> ResearchResult:
    return ResearchResult(
        source_url=source_url,
        final_url=source_url,
        fetch_status=FetchStatus.SUCCESS,
        http_status_code=200,
        content_type=content_type,
        html_extracted=True,
        metadata=PageMetadata(
            title=title,
            og_title=og_title,
            og_description=og_desc,
            meta_description=meta_desc,
            canonical_url=canonical,
            og_site_name=og_site,
        ),
        visible_text=visible_text,
        emails=[
            ExtractedEmail(email=email, context="contact section", verification_status=VerificationStatus.UNVERIFIED)
            for email in emails
        ],
    )


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase4.db').as_posix()}",
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


# ---------------------------------------------------------------------------
# Company name
# ---------------------------------------------------------------------------


def test_company_name_prefers_og_site_name():
    research = make_research(
        title="Acme Robotics | Warehouse Automation",
        og_site="Acme Robotics",
    )
    claims = extract_company(research)
    assert len(claims) == 1
    assert claims[0].claim_type == EvidenceType.COMPANY_NAME
    assert claims[0].value == "Acme Robotics"
    assert claims[0].confidence == 0.8


def test_company_name_falls_back_to_cleaned_title():
    research = make_research(title="Acme Robotics | Warehouse Automation")
    claims = extract_company(research)
    assert len(claims) == 1
    assert claims[0].value == "Acme Robotics"


def test_company_name_generic_titles_produce_no_claim():
    research = make_research(title="Home | Welcome")
    assert extract_company(research) == []
    generic = make_research(title="Official Website", og_site="Official Website")
    assert extract_company(generic) == []


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


def test_description_prefers_og_over_meta():
    research = make_research(og_desc="Warehouse automation, made simple.", meta_desc="The meta description.")
    claims = extract_description(research)
    assert len(claims) == 1
    assert claims[0].value == "Warehouse automation, made simple."
    assert claims[0].claim_type == EvidenceType.COMPANY_DESCRIPTION


def test_description_falls_back_to_meta():
    research = make_research(meta_desc="The meta description.")
    claims = extract_description(research)
    assert len(claims) == 1
    assert claims[0].value == "The meta description."


def test_description_absent_when_no_metadata():
    assert extract_description(make_research(visible_text="nothing here")) == []


# ---------------------------------------------------------------------------
# Sector
# ---------------------------------------------------------------------------


def test_sector_controlled_vocabulary_hits():
    research = make_research(visible_text="Acme is an enterprise software company that is also a fintech.")
    claims = extract_sector(research)
    values = {claim.value for claim in claims}
    assert values == {"enterprise software", "fintech"}
    assert all(claim.claim_type == EvidenceType.INDUSTRY for claim in claims)


def test_sector_dedups_same_term():
    research = make_research(visible_text="saas saas saas saas")
    claims = extract_sector(research)
    assert len(claims) == 1
    assert claims[0].value == "saas"


def test_sector_unguarded_terms_not_claimed():
    research = make_research(visible_text="Acme makes high quality widgets with software inside.")
    assert extract_sector(research) == []


# ---------------------------------------------------------------------------
# Website
# ---------------------------------------------------------------------------


def test_website_from_canonical_only():
    research = make_research(title="Acme", canonical="https://www.acme.example/")
    claims = extract_website(research)
    assert len(claims) == 1
    assert claims[0].value == "https://www.acme.example/"
    assert claims[0].claim_type == EvidenceType.OFFICIAL_WEBSITE


def test_website_absent_without_canonical():
    assert extract_website(make_research(title="Acme")) == []


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------


def test_geography_explicit_wording_only():
    research = make_research(
        visible_text="Acme is headquartered in San Francisco and has an office based in Berlin, Germany."
    )
    claims = extract_geography(research)
    values = set(claim.value for claim in claims)
    assert values == {"headquartered in San Francisco", "based in Berlin"}
    assert {claim.normalized_value for claim in claims} == {"San Francisco", "Berlin"}


def test_geography_no_tld_inference():
    research = make_research(visible_text="Visit acme.uk for details.", title="Acme")
    assert extract_geography(research) == []


def test_geography_dash_based_phrasing_extracted():
    """Live gap: coverage articles typically say 'Bengaluru-based' / 'Surat-based'
    rather than 'based in Bengaluru', and the evaluator already recognizes the
    '-based' form — so the extractor must also emit it."""
    research = make_research(
        visible_text="SaaS startup Bengaluru-based Apptile raises $2.5 million in seed funding."
    )
    claims = extract_geography(research)
    assert len(claims) == 1
    assert claims[0].value == "Bengaluru-based"
    assert claims[0].normalized_value == "Bengaluru"


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("raised $2M", 2_000_000),
        ("raised $1.5 million", 1_500_000),
        ("secured USD 3 million", 3_000_000),
        ("closed a $3.2m round", 3_200_000),
        ("received an additional $5M", 5_000_000),
    ],
)
def test_funding_normalizes_amounts(phrase, expected):
    research = make_research(visible_text=f"Acme {phrase} to expand.")
    claims = extract_funding(research)
    assert len(claims) == 1
    assert claims[0].claim_type == EvidenceType.FUNDING
    assert claims[0].field == "funding_amount_usd"
    assert claims[0].normalized_value == expected


def test_funding_unsupported_amount_ignored():
    research = make_research(visible_text="Acme charges $5 per delivery.")
    assert extract_funding(research) == []


def test_funding_skipped_adjacent_to_revenue():
    research = make_research(
        visible_text="Acme raised $2M last year and reported annual revenue of $5M this year."
    )
    claims = extract_funding(research)
    assert len(claims) == 1
    assert claims[0].normalized_value == 2_000_000


def test_funding_multiple_rounds_kept_separate():
    research = make_research(
        visible_text="Acme raised $2 million in a Series A, then secured $5 million in a Series B."
    )
    claims = extract_funding(research)
    assert {claim.normalized_value for claim in claims} == {2_000_000, 5_000_000}


def test_funding_inr_crore_normalized_to_usd():
    """Live gap: SUIND's ₹20.5 crore (~$2.4M) pre-seed was unreadable because
    INR and Indian numbering (crore/lakh) were not explicit recognized units."""
    research = make_research(visible_text="SUIND secures ₹20.5 crore in pre-seed funding.")
    claims = extract_funding(research)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.normalized_value == 2_460_000
    assert "$2,460,000" in claim.value
    assert claim.claim_type == EvidenceType.FUNDING


def test_funding_inr_rs_lakh_outside_range_still_read():
    research = make_research(visible_text="SeedBox raised Rs 12 lakh in angel funding.")
    claims = extract_funding(research)
    assert len(claims) == 1
    assert claims[0].normalized_value == 14_400


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------


def test_revenue_forward_wording():
    research = make_research(visible_text="Acme reported annual revenue of $2 million for 2024.")
    claims = extract_revenue(research)
    assert len(claims) == 1
    assert claims[0].claim_type == EvidenceType.REVENUE
    assert claims[0].normalized_value == 2_000_000


def test_revenue_backward_wording():
    research = make_research(visible_text="Acme generated $1.2 million in revenue last year.")
    claims = extract_revenue(research)
    assert len(claims) == 1
    assert claims[0].normalized_value == 1_200_000


def test_revenue_valuation_not_claimed():
    research = make_research(visible_text="Acme reached a $2M valuation after its latest round.")
    claims = extract_revenue(research)
    assert claims == []


def test_revenue_gmv_not_claimed():
    research = make_research(visible_text="Gross merchandise volume hit $5M across the network.")
    assert extract_revenue(research) == []


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


def test_platform_qualified_signal():
    research = make_research(visible_text="Acme builds a SaaS platform managing warehouses.")
    claims = extract_platform(research)
    assert len(claims) == 1
    assert claims[0].claim_type == EvidenceType.PLATFORM
    assert claims[0].normalized_value == "saas platform"


def test_platform_standalone_clause():
    research = make_research(visible_text="Acme is a platform for cross-border logistics.")
    claims = extract_platform(research)
    assert len(claims) == 1
    assert claims[0].normalized_value == "platform"


def test_platform_generic_copy_not_a_signal():
    research = make_research(visible_text="Acme uses the best platform and latest tools on the market.")
    assert extract_platform(research) == []


def test_platform_developer_qualifier():
    research = make_research(visible_text="Acme ships a developer platform used by engineering teams.")
    claims = extract_platform(research)
    assert claims[0].claim_type == EvidenceType.PLATFORM
    assert claims[0].normalized_value == "developer platform"


def test_platform_b2b_qualifier():
    research = make_research(visible_text="Acme operates a b2b platform for supply-chain teams.")
    claims = extract_platform(research)
    assert claims[0].claim_type == EvidenceType.PLATFORM
    assert claims[0].normalized_value == "b2b platform"


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role_text", "expected_type", "expected_field"),
    [
        ("Jane Smith, CEO", EvidenceType.CEO, "ceo"),
        ("John Doe, Co-Founder", EvidenceType.COFOUNDER, "cofounder"),
        ("Jay Patel, Co-founder", EvidenceType.COFOUNDER, "cofounder"),
        ("Noah Lee, Founder", EvidenceType.FOUNDER, "founder"),
        ("Mia Chen, Founder & CEO", EvidenceType.FOUNDER, "founder"),
        ("Sam Ortiz, CEO & Founder", EvidenceType.CEO, "ceo"),
    ],
)
def test_people_explicit_roles(role_text, expected_type, expected_field):
    research = make_research(visible_text=f"Meet {role_text}. They run everyday operations.")
    claims = extract_people(research)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_type == expected_type
    assert claim.field == expected_field
    assert isinstance(claim.value, str) and " " in claim.value


def test_people_dedup_same_person():
    research = make_research(
        visible_text="Jane Smith, CEO. Contact Jane Smith by email. Jane Smith, CEO again."
    )
    claims = extract_people(research)
    assert len(claims) == 1
    assert claims[0].value.rsplit(", ", 1)[0].split() == ["Jane", "Smith"]


def test_people_no_role_no_claim():
    research = make_research(visible_text="We spoke with Alex Carter at the summit about logistics.")
    assert extract_people(research) == []


# ---------------------------------------------------------------------------
# Contact details
# ---------------------------------------------------------------------------


def test_emails_bound_to_claims():
    research = make_research(emails=("hello@acme.example", "support@acme.example"))
    claims = extract_contact_details(research)
    assert len(claims) == 2
    for claim in claims:
        assert claim.claim_type == EvidenceType.EMAIL
        assert claim.field == "email"
        assert claim.value in ("hello@acme.example", "support@acme.example")


def test_emails_never_attributed_to_a_person():
    research = make_research(visible_text="Email CEO Jane Smith at jane@acme.example.", emails=("jane@acme.example",))
    claims = extract_contact_details(research)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.value == "jane@acme.example"
    assert claim.context != "jane@acme.example"
    # Nothing in the claim claims the email belongs to a named person.


# ---------------------------------------------------------------------------
# Service: end-to-end persistence
# ---------------------------------------------------------------------------


def _sample_research() -> ResearchResult:
    return make_research(
        title="Acme Robotics | Warehouse Automation",
        og_site="Acme Robotics",
        og_desc="Acme Robotics builds warehouse automation.",
        canonical="https://www.acme.example/",
        visible_text=(
            "Acme Robotics builds a SaaS platform managing warehouse automation. "
            "The company raised $2 million in a Series A round. "
            "Acme is headquartered in San Francisco. "
            "Jane Smith, CEO, founded the company in 2019."
        ),
        emails=("hello@acme.example",),
    )


def test_service_skips_when_no_company_identity(persistence_db):
    research = make_research(visible_text="A page about robots with no company identity.")
    result = CandidateExtractionService(persistence_db).extract_and_persist(research)

    assert result.skipped_reason == "no reliable company identity extracted"
    assert result.candidate is None
    assert result.profile is None
    assert CompanyRepository(persistence_db).list_candidates() == []


def test_service_persists_candidate_evidence_and_profile(persistence_db):
    run_id = RunRepository(persistence_db).create(DiscoveryRun(target_lead_count=5)).run_id
    research = _sample_research()

    result = CandidateExtractionService(persistence_db).extract_and_persist(research, run_id=run_id)

    assert result.created_candidate is True
    assert result.candidate is not None
    assert result.candidate.run_id == run_id
    assert result.candidate.company_name == "Acme Robotics"
    assert result.candidate.official_website == "https://www.acme.example/"

    evidence = EvidenceRepository(persistence_db).list_by_candidate(result.candidate.candidate_id)
    assert len(evidence) == len(result.claims)
    for claim, rec in zip(result.claims, evidence):
        assert rec.claim == claim.field
        assert rec.extracted_value == claim.value
    claim_fields = {claim.field for claim in result.claims}
    assert {"company_name", "official_website"} <= claim_fields

    funding = [
        claim for claim in result.claims
        if claim.claim_type == EvidenceType.FUNDING
    ]
    assert len(funding) == 1
    assert funding[0].normalized_value == 2_000_000

    profile = result.profile
    assert profile is not None
    assert profile.funding_amount_usd == 2_000_000
    assert profile.primary_location == "San Francisco"
    assert profile.revenue_amount_usd is None
    assert profile.evidence_ids == result.evidence_ids


def test_service_conflicting_funding_leaves_profile_unset(persistence_db):
    run_id = RunRepository(persistence_db).create(DiscoveryRun()).run_id
    research = make_research(
        title="Acme | Logistics",
        og_site="Acme",
        visible_text=(
            "Acme raised $2 million in a Series A, then secured $5 million in a Series B. "
            "The company is based in Austin."
        ),
    )

    result = CandidateExtractionService(persistence_db).extract_and_persist(research, run_id=run_id)

    funding_claims = [c for c in result.claims if c.claim_type == EvidenceType.FUNDING]
    assert len(funding_claims) == 2
    assert {c.normalized_value for c in funding_claims} == {2_000_000, 5_000_000}
    assert result.profile.funding_amount_usd is None
    assert result.profile.primary_location == "Austin"


def test_service_reuses_candidate_by_website(persistence_db):
    run_id = RunRepository(persistence_db).create(DiscoveryRun()).run_id
    service = CandidateExtractionService(persistence_db)

    first = make_research(title="Acme | Home", og_site="Acme", canonical="https://www.acme.example/")
    second = make_research(
        title="Acme Robotics | Automation",
        og_site="Acme Robotics",
        canonical="https://www.acme.example/",
        visible_text="Acme Robotics is headquartered in Boston.",
    )

    r1 = service.extract_and_persist(first, run_id=run_id)
    r2 = service.extract_and_persist(second, run_id=run_id)

    assert r1.created_candidate is True
    assert r2.created_candidate is False
    assert r1.candidate.candidate_id == r2.candidate.candidate_id
    assert r2.candidate.company_name == "Acme"

    evidence = EvidenceRepository(persistence_db).list_by_candidate(r1.candidate.candidate_id)
    assert len(evidence) == len(r1.claims) + len(r2.claims)

    profile = CompanyRepository(persistence_db).get_profile(r1.candidate.candidate_id)
    assert profile.evidence_ids == r1.evidence_ids + r2.evidence_ids


def test_service_does_not_force_merge_distinct_companies(persistence_db):
    run_id = RunRepository(persistence_db).create(DiscoveryRun()).run_id
    service = CandidateExtractionService(persistence_db)

    r1 = service.extract_and_persist(make_research(title="Alpha Co | Home", og_site="Alpha Co"), run_id=run_id)
    r2 = service.extract_and_persist(make_research(title="Beta Shop | Home", og_site="Beta Shop"), run_id=run_id)

    assert r1.created_candidate is True
    assert r2.created_candidate is True
    assert r1.candidate.candidate_id != r2.candidate.candidate_id


def test_service_attaches_source_to_candidate(persistence_db):
    source = SourceRepository(persistence_db).create(
        Source(url="https://www.acme.example/", title="Acme", provider="duckduckgo")
    )
    run_id = RunRepository(persistence_db).create(DiscoveryRun()).run_id
    research = make_research(title="Acme | Home", og_site="Acme", canonical="https://www.acme.example/")

    result = CandidateExtractionService(persistence_db).extract_and_persist(
        research, run_id=run_id, source_id=source.source_id
    )

    linked = CompanyRepository(persistence_db).list_sources(result.candidate.candidate_id)
    assert [s.source_id for s in linked] == [source.source_id]


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class FakeResearchService:
    def __init__(self, result):
        self.result = result

    async def research_url(self, url):
        return self.result

    async def research_source(self, source_id, repository):
        repository.update_validation(
            source_id,
            fetch_status=self.result.fetch_status or FetchStatus.SUCCESS,
            http_status_code=self.result.http_status_code,
            final_url=self.result.final_url,
            content_type=self.result.content_type,
        )
        return self.result


def _override_db(app_obj, persistence_db):
    def override_get_db():
        yield persistence_db

    app_obj.dependency_overrides[get_db] = override_get_db


def test_from_research_endpoint_persists(persistence_db):
    research = _sample_research()
    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).post(
            "/api/extraction/from-research",
            json={"research": research.model_dump(mode="json")},
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["company_name"] == "Acme Robotics"
    assert body["created_candidate"] is True
    assert body["run_id"] is not None
    assert body["profile"] is not None

    candidates = CompanyRepository(persistence_db).list_candidates()
    assert len(candidates) == 1


def test_research_endpoint_extracts_persisted_source(monkeypatch, persistence_db):
    source = SourceRepository(persistence_db).create(
        Source(url="https://www.acme.example/", title="Acme", provider="duckduckgo")
    )
    result = _sample_research()
    monkeypatch.setattr(main_mod, "research_service", FakeResearchService(result))
    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).post(
            f"/api/extraction/research",
            json={"source_id": str(source.source_id)},
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["company_name"] == "Acme Robotics"
    assert body["created_candidate"] is True

    linked = CompanyRepository(persistence_db).list_sources(body["candidate"]["candidate_id"])
    assert [s.source_id for s in linked] == [source.source_id]


def test_research_endpoint_unknown_source_404(monkeypatch, persistence_db):
    monkeypatch.setattr(main_mod, "research_service", FakeResearchService(_sample_research()))
    _override_db(app, persistence_db)
    try:
        response = authed_client(app, persistence_db).post(
            "/api/extraction/research",
            json={"source_id": str(uuid4())},
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404


def test_from_research_endpoint_reuses_candidate_across_calls(persistence_db):
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        payload = {"research": make_research(
            title="Acme | Home", og_site="Acme", canonical="https://www.acme.example/"
        ).model_dump(mode="json")}
        first = client.post("/api/extraction/from-research", json=payload)
        second = client.post("/api/extraction/from-research", json=payload)
    finally:
        app.dependency_overrides.pop(get_db)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["candidate"]["candidate_id"] == second.json()["candidate"]["candidate_id"]
    assert first.json()["created_candidate"] is True
    assert second.json()["created_candidate"] is False


# ---------------------------------------------------------------------------
# Phase 10 regressions — each test reproduces a bug observed in live runs
# ---------------------------------------------------------------------------


def test_funding_persists_explicit_usd_figure_with_unit():
    """Live bug: money figures were persisted as bare digits ("1.44"), so the
    qualification layer (which requires an explicit $/unit) never read them."""
    research = make_research(visible_text="Acme raised $1.44 million in seed funding.")
    claims = extract_funding(research)
    assert len(claims) == 1
    assert claims[0].value == "$1.44 million"
    assert claims[0].normalized_value == 1_440_000


def test_funding_persists_short_unit_figure():
    research = make_research(visible_text="Acme raised $2M to expand.")
    claims = extract_funding(research)
    assert [claim.value for claim in claims] == ["$2M"]


def test_funding_usd_equivalent_parenthetical_captured():
    """Live bug: EUR/GBP rounds written as "€3.1 million ($3.6 million)" left
    the in-range USD equivalent invisible to the evaluator."""
    research = make_research(
        visible_text="Zalos raised €3.1 million ($3.6 million) in a seed round to expand."
    )
    claims = extract_funding(research)
    assert [claim.normalized_value for claim in claims] == [3_600_000]
    assert claims[0].value == "$3.6 million"


def test_revenue_persists_explicit_usd_figure_with_unit():
    research = make_research(visible_text="Acme reported annual revenue of $2 million for 2024.")
    claims = extract_revenue(research)
    assert claims[0].value == "$2 million"
    assert claims[0].normalized_value == 2_000_000


def test_company_name_from_funding_headline():
    """Live bug: publisher pages (og:site_name = the outlet) became candidates."""
    research = make_research(title="Tower Raises €5.5 Million to Build Enterprise AI")
    claims = extract_company(research)
    assert len(claims) == 1
    assert claims[0].value == "Tower"
    assert claims[0].claim_type == EvidenceType.COMPANY_NAME


def test_company_name_from_funding_headline_ignores_geo_prefix():
    research = make_research(title="London-Based Dragonfly Raises £3 Million in Seed Funding")
    claims = extract_company(research)
    assert [claim.value for claim in claims] == ["Dragonfly"]


def test_company_name_from_funding_headline_skips_leading_category_words():
    """Live bug: "SaaS Startup <X> Raises ..." headlines were skipped because the
    leading category word cut the brand read short, so real funded companies
    (Apptile, TreZix) never became candidates."""
    cases = [
        "SaaS Startup TreZix Raises $2 Mn in Seed Funding",
        "The SaaS Platform Hugo Raises $5 Million to Scale",
        "Indian SaaS Startup Apptile Raises $2.5 Million in Seed Funding",
        "Software Company Wealthfy Secures $3 Million Pre-Series A",
    ]
    for title, expected in zip(cases, ["TreZix", "Hugo", "Apptile", "Wealthfy"]):
        claims = extract_company(make_research(title=title))
        assert [claim.value for claim in claims] == [expected], title


def test_company_name_from_funding_headline_category_words_only_skipped():
    """A headline that is nothing but category words still yields no identity —
    the page is skipped, never guessed."""
    research = make_research(title="The SaaS Startup Company Secures $4 Million in Funding")
    assert extract_company(research) == []


def test_company_name_from_funding_headline_lowercase_opener_still_skipped_when_geo_lead():
    research = make_research(title="Singapore-based SaaS startup Paddle Raises $2 Million")
    claims = extract_company(research)
    assert [claim.value for claim in claims] == ["Paddle"]


def test_company_name_publisher_listing_headline_skipped():
    """A funding headline that only names a directory/list must yield no claim
    rather than falling back to the publisher's site name."""
    research = make_research(
        title="Top 10 SaaS Startups That Raised $5M in 2024",
        og_site="EU-Startups",
    )
    assert extract_company(research) == []


def test_company_name_prefers_og_site_when_no_funding_headline():
    research = make_research(title="Acme Robotics | Warehouse Automation", og_site="Acme Robotics")
    claims = extract_company(research)
    assert [claim.value for claim in claims] == ["Acme Robotics"]


def test_company_name_marketing_title_without_og_site_skipped():
    """Pages whose only identity is a marketing phrase (no og:site_name) must
    not become junk candidates."""
    research = make_research(
        title="The Customer Service AI Platform for Modern Support Teams"
    )
    assert extract_company(research) == []


def test_company_name_list_headline_skipped():
    research = make_research(
        title="10+ Best AI Recruiting Software for 2026: Expert Reviews + Pricing"
    )
    assert extract_company(research) == []


def test_company_name_editorial_title_uses_suffix_brand():
    """A how-to/editorial main title is not a company, but a brand visible in
    the title suffix still is (e.g. "What is Machine Learning? | IBM")."""
    research = make_research(title="What is Machine Learning? | IBM")
    claims = extract_company(research)
    assert [claim.value for claim in claims] == ["IBM"]


def test_company_name_plain_brand_title_still_extracted():
    research = make_research(title="Acme Robotics | Warehouse Automation")
    claims = extract_company(research)
    assert [claim.value for claim in claims] == ["Acme Robotics"]


def test_people_value_keeps_explicit_role():
    """Live bug: people were persisted as a bare name; the leadership evaluator
    needs the explicit "Name, Role" connection."""
    research = make_research(visible_text="Jane Smith, CEO. She runs operations.")
    claims = extract_people(research)
    assert len(claims) == 1
    assert claims[0].value == "Jane Smith, CEO"
    assert claims[0].normalized_value == "CEO"


def test_people_rejects_organization_shaped_name():
    """Live bug: a fund listing ("Category Capital Strategy, Founder") became a
    leadership contact."""
    research = make_research(
        visible_text="Category Capital Strategy, Founder & CEO, invests in seed rounds."
    )
    assert extract_people(research) == []


def test_profile_uses_plain_location_not_base_phrase():
    research = make_research(
        title="Acme | Home",
        og_site="Acme",
        visible_text="Acme is headquartered in Berlin, Germany.",
    )
    from app.extraction.service import _single_consistent_value

    claims = extract_geography(research)
    assert _single_consistent_value(claims, "primary_location") == "Berlin"


# ---------------------------------------------------------------------------
# Claim scoping: foreign-company claims never enter the candidate
# ---------------------------------------------------------------------------


def _scoped_claim(claim_type, text, url="https://press.example.com/x", context=None):
    from app.extraction.models import ExtractedClaim

    return ExtractedClaim(
        claim_type=claim_type,
        field=claim_type.value,
        value=text,
        normalized_value=text,
        source_url=url,
        context=context or text,
    )


def _delta_candidate():
    return CompanyCandidate(
        run_id=uuid4(),
        company_name="Delta Software",
        official_website="https://delta.example.com",
    )


def test_scoped_funding_claim_must_name_candidate_or_speak_first_person():
    candidate = _delta_candidate()
    foreign = _scoped_claim(
        EvidenceType.FUNDING,
        "$17 million",
        context="funding signal verb (London-based Autone raised $17 million recently)",
    )
    assert claim_is_candidate_scoped(candidate, foreign) is False

    named = _scoped_claim(
        EvidenceType.FUNDING,
        "$2 million",
        context="funding signal verb (Delta Software raised $2 million in seed funding)",
    )
    assert claim_is_candidate_scoped(candidate, named) is True

    first_person = _scoped_claim(
        EvidenceType.FUNDING,
        "$2 million",
        context="funding signal verb (We raised $2 million in seed funding)",
    )
    assert claim_is_candidate_scoped(candidate, first_person) is True


def test_scoped_location_claim_drops_other_companys_hq():
    candidate = _delta_candidate()
    foreign = _scoped_claim(
        EvidenceType.LOCATION,
        "headquartered in London",
        context="text match (Auquan is headquartered in London, England)",
    )
    assert claim_is_candidate_scoped(candidate, foreign) is False


def test_scoped_leadership_drops_foreign_affiliation_even_linked_to_own_site():
    candidate = _delta_candidate()
    foreign_ceo = _scoped_claim(
        EvidenceType.CEO,
        "David Redfern, CEO",
        url="https://delta.example.com/news/round-up",
        context="text match (Dr. David Redfern, CEO of Datable Ltd, an investor in the deal)",
    )
    assert claim_is_candidate_scoped(candidate, foreign_ceo) is False


def test_scoped_leadership_kept_on_own_site_team_page_without_name():
    candidate = _delta_candidate()
    team_leader = _scoped_claim(
        EvidenceType.COFOUNDER,
        "Robert Chen, Founder",
        url="https://delta.example.com/team",
        context="text match (Robert Chen, Founder - robert@delta.example.com)",
    )
    assert claim_is_candidate_scoped(candidate, team_leader) is True


def test_scoped_leadership_kept_when_claim_names_candidate():
    candidate = _delta_candidate()
    press_leader = _scoped_claim(
        EvidenceType.CEO,
        "Robert Chen, Founder",
        context="text match (Robert Chen, Founder at Delta Software - robert@delta.example.com)",
    )
    assert claim_is_candidate_scoped(candidate, press_leader) is True


# ---------------------------------------------------------------------------
# Guard: tests never create the developer's database
# ---------------------------------------------------------------------------

from guard_helpers import dev_db_fingerprint


def test_developer_database_not_created(dev_db_start_state):
    """The offline test run must never create or modify the developer's
    ``backend/tvbfundradar.db`` — whether or not one already exists from live API
    use. Comparing the live fingerprint against the session-start snapshot
    proves this suite leaves the dev database untouched."""
    assert dev_db_fingerprint() == dev_db_start_state