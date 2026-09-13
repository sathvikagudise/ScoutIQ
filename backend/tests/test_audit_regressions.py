"""Regression tests for the Phase 10 debugging audit fixes.

Covers (offline, deterministic):
  1. currency-aware funding/revenue extraction with explicit USD equivalents
     and no inference for bare, unmarked figures;
  2. junk/portal candidate identity suppression in company extraction;
  3. robustness of HTML attribute coercion (bs4 AttributeValueList);
  4. the own-site discovery hop: a candidate first seen on a third-party
     publisher page becomes anchored on its real website (via page link or via
     a quoted-brand search), and its own-domain material then closes email
     attribution honestly (EVIDENCED, never VERIFIED).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import (
    CandidateStatus,
    EvidenceType,
    FetchStatus,
    QualificationStatus,
    RunStatus,
    VerificationStatus,
)
from app.db.base import Base
from app.discovery.base import DiscoveryProvider
from app.discovery.service import DiscoveryService
from app.extraction.extractors.company import extract_company
from app.extraction.extractors.funding import extract_funding
from app.extraction.extractors.revenue import extract_revenue
from app.extraction.service import own_site_host
from app.models.discovery import DiscoveredSource
from app.orchestration.service import PipelineOrchestrator
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.research.extractors import extract_metadata
from app.research.extractors.metadata import extract_metadata as _extract_metadata_mod
from app.research.models import FetchRecord, PageMetadata, ResearchResult
from app.research.parser import parse_html
from app.research.service import ResearchService


def make_research(
    visible_text="",
    title=None,
    og_site=None,
    canonical=None,
    source_url="https://www.acme.example/",
) -> ResearchResult:
    return ResearchResult(
        source_url=source_url,
        final_url=source_url,
        fetch_status=FetchStatus.SUCCESS,
        http_status_code=200,
        content_type="text/html",
        html_extracted=True,
        metadata=PageMetadata(title=title, og_site_name=og_site, canonical_url=canonical),
        visible_text=visible_text,
    )


# ---------------------------------------------------------------------------
# Currency-aware financial extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected_usd, snippet_part",
    [
        ("raised £2 million", 2_540_000, "≈ $2,540,000"),
        ("secured € 3 million", 3_270_000, "≈ $3,270,000"),
        ("received £ 1.5M in a seed round", 1_905_000, "≈ $1,905,000"),
        ("closed EUR 2m seed funding", 2_180_000, "≈ $2,180,000"),
    ],
)
def test_funding_extracts_non_usd_with_explicit_usd_equivalent(
    phrase, expected_usd, snippet_part
):
    research = make_research(visible_text=f"Acme {phrase} to expand operations.")
    claims = extract_funding(research)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_type == EvidenceType.FUNDING
    assert claim.normalized_value == expected_usd
    assert snippet_part in claim.value, claim.value
    assert claim.confidence <= 0.5


def test_funding_does_not_invent_currency_for_bare_figure():
    research = make_research(visible_text="Acme raised 2 million in a seed round.")
    assert extract_funding(research) == []


def test_funding_usd_behavior_is_unchanged():
    research = make_research(visible_text="Acme raised $2 million in a seed round.")
    claim = extract_funding(research)[0]
    assert claim.normalized_value == 2_000_000
    assert claim.value == "$2 million"
    assert claim.confidence == 0.6


def test_revenue_currency_conversion_is_explicit():
    research = make_research(
        visible_text="Acme reported annual revenue of £3 million for 2025."
    )
    claims = extract_revenue(research)
    assert len(claims) == 1
    assert claims[0].normalized_value == 3_810_000
    assert "≈ $3,810,000" in claims[0].value


# ---------------------------------------------------------------------------
# Junk / portal candidate identity suppression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Find Investors - Get Funding For Your Dream",
        "Investor",
        "Subscribe | Conversations",
        "Compare UK business finance",
        "Government Schemes",
        "I'm a teen founder",
        "Six Aussie startups that raised $28.5 million this week",
    ],
)
def test_company_identity_rejects_portal_and_stub_titles(title):
    research = make_research(title=title)
    assert extract_company(research) == []


@pytest.mark.parametrize(
    "og_site",
    ["Funded", "Entrepreneur", "Investor", "Angel Investors Network"],
)
def test_company_identity_rejects_portal_og_site_names(og_site):
    research = make_research(title="Home", og_site=og_site)
    assert extract_company(research) == []


def test_company_identity_still_keeps_real_brand_titles():
    research = make_research(title="Noria Systems | logistics platform")
    claims = extract_company(research)
    assert len(claims) == 1
    assert claims[0].value == "Noria Systems"


# ---------------------------------------------------------------------------
# HTML attribute coercion robustness (bs4 AttributeValueList)
# ---------------------------------------------------------------------------


def test_metadata_survives_multi_valued_attributes():
    html = """
    <html><head>
    <title>Noria Systems</title>
    <meta name="description" class="a b" content="desc" />
    <meta property="og:title" rel="alternate" content="og title" />
    <link rel="canonical alternate" href="https://noria.example.com/" />
    </head><body></body></html>
    """
    soup = parse_html(
        FetchRecord(
            url="https://noria.example.com",
            fetch_status=FetchStatus.SUCCESS,
            status_code=200,
            content_type="text/html",
            final_url="https://noria.example.com",
            body=html,
        )
    )
    assert soup is not None
    metadata = extract_metadata(soup)
    assert metadata.title == "Noria Systems"
    assert metadata.meta_description == "desc"
    assert metadata.og_title == "og title"
    assert metadata.canonical_url == "https://noria.example.com/"


# ---------------------------------------------------------------------------
# Own-site discovery hop (end to end)
# ---------------------------------------------------------------------------


class FakeDiscoveryProvider(DiscoveryProvider):
    name = "fake"

    def __init__(self, results_by_query):
        self.results_by_query = results_by_query

    async def search(self, query: str, max_results: int = 5) -> list[DiscoveredSource]:
        return list(self.results_by_query.get(query, []))


class FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    async def fetch_page(self, url: str) -> FetchRecord:
        if url not in self.pages:
            return FetchRecord(
                url=url,
                fetch_status=FetchStatus.UNKNOWN_ERROR,
                error="no stub page",
            )
        return FetchRecord(
            url=url,
            fetch_status=FetchStatus.SUCCESS,
            status_code=200,
            final_url=url,
            content_type="text/html",
            body=self.pages[url],
        )


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'audit.db').as_posix()}",
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


def _create_run(db: Session):
    from app.models.run import DiscoveryRun
    from app.repositories.run_repository import RunRepository

    return RunRepository(db).create(DiscoveryRun(target_lead_count=5))


def _discovered(url: str, title: str, query: str) -> DiscoveredSource:
    return DiscoveredSource(query=query, title=title, url=url, provider="fake")


# A third-party funding-news article. Its canonical is the publisher's deep
# article URL (so own_site_host is None), it DOES link the company's real site,
# and none of the qualifying evidence can produce an email.
ARTICLE_HTML = """<!doctype html>
<html><head>
<title>Noria Systems raises $3 million to expand logistics platform</title>
<meta property="og:site_name" content="TechCrowd" />
<link rel="canonical" href="https://techcrowd.example.com/2026/09/08/noria-raises-3m" />
</head><body>
<p>Noria Systems, headquartered in Berlin, Germany, has raised $3 million in seed funding.</p>
<p>Anna Schmidt is the CEO of Noria Systems.</p>
<p><a href="https://noria.example.com">Noria Systems</a></p>
</body></html>
"""

# The company's own homepage: homepage canonical on the brand domain, logistics
# platform wording, and explicit Berlin HQ. Links reach team (contact) pages.
NORIA_HOME_HTML = """<!doctype html>
<html><head>
<title>Noria Systems | logistics platform</title>
<meta property="og:site_name" content="Noria Systems" />
<meta name="description" content="Noria Systems is a logistics platform headquartered in Berlin, Germany." />
<link rel="canonical" href="https://noria.example.com" />
</head><body>
<p>Noria Systems is a logistics platform.</p>
<p>Noria Systems is headquartered in Berlin, Germany.</p>
<p><a href="https://noria.example.com/team">Team</a></p>
<p><a href="/about">About</a></p>
<p><a href="/blog">Blog</a></p>
</body></html>
"""

NORIA_TEAM_HTML = """<!doctype html>
<html><head>
<title>Noria Systems - Team</title>
<link rel="canonical" href="https://noria.example.com/team" />
</head><body>
<p>Noria Systems team.</p>
<p>Anna Schmidt, CEO - anna@noria.example.com</p>
<p><a href="https://noria.example.com/contact">Contact</a></p>
</body></html>
"""


def _route():
    query = "noria systems logistics platform raised $3 million"
    results = {
        query: [
            _discovered(
                "https://techcrowd.example.com/2026/09/08/noria-raises-3m",
                "Noria Systems raises $3 million",
                query,
            )
        ]
    }
    pages = {
        "https://techcrowd.example.com/2026/09/08/noria-raises-3m": ARTICLE_HTML,
        "https://noria.example.com": NORIA_HOME_HTML,
        "https://noria.example.com/team": NORIA_TEAM_HTML,
        "https://noria.example.com/about": ALREADY_RESEARCHED_PLACEHOLDER,
        "https://noria.example.com/contact": ALREADY_RESEARCHED_PLACEHOLDER,
        "https://noria.example.com/blog": ALREADY_RESEARCHED_PLACEHOLDER,
    }
    return results, pages


ALREADY_RESEARCHED_PLACEHOLDER = "<html><head><title>x</title></head><body></body></html>"


def test_own_site_link_hop_anchors_candidate_and_attributes_email(persistence_db):
    """A publisher-article candidate becomes anchored on its real website via
    the article's brand-host link; own-domain team material then attributes the
    leader's email as EVIDENCED, and the candidate qualifies."""
    from app.core.enums import EvidenceType as ET

    run = _create_run(persistence_db)
    query = "noria systems logistics platform raised $3 million"
    results = {
        query: [
            _discovered(
                "https://techcrowd.example.com/2026/09/08/noria-raises-3m",
                "Noria Systems raises $3 million",
                query,
            )
        ]
    }
    pages = {
        "https://techcrowd.example.com/2026/09/08/noria-raises-3m": ARTICLE_HTML,
        "https://noria.example.com": NORIA_HOME_HTML,
        "https://noria.example.com/team": NORIA_TEAM_HTML,
    }
    discovery = DiscoveryService(FakeDiscoveryProvider(results))
    research = ResearchService(fetcher=FakeFetcher(pages))
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)

    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, list(results)))
    assert final_run.status == RunStatus.COMPLETED

    repo = CompanyRepository(persistence_db)
    candidates = [c for c in repo.list_candidates() if c.run_id == run.run_id]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.company_name == "Noria Systems"
    assert candidate.official_website == "https://noria.example.com"
    assert own_site_host(candidate) == "noria.example.com"
    assert candidate.status == CandidateStatus.QUALIFIED

    evidence = [e for e in repo.list_sources(candidate.candidate_id) if e]
    from app.repositories.evidence_repository import EvidenceRepository

    ev_rows = EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)
    emails = {e.extracted_value for e in ev_rows if e.evidence_type is ET.EMAIL}
    assert "anna@noria.example.com" in emails, "own-domain email persisted"

    contacts = ContactRepository(persistence_db).list_by_candidate(candidate.candidate_id)
    assert contacts
    contact = contacts[0]
    assert contact.full_name == "Anna Schmidt"
    assert contact.email == "anna@noria.example.com"
    assert contact.verification_status is VerificationStatus.EVIDENCED, (
        "evidence-attributed, never fabricated as VERIFIED"
    )

    qualification = QualificationRepository(persistence_db).get_by_candidate(candidate.candidate_id)
    assert qualification is not None
    assert qualification.overall_status is QualificationStatus.PASS

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    assert len(leads) == 1
    assert leads[0].company_name == "Noria Systems"
    assert leads[0].ceo_or_cofounder_name == "Anna Schmidt"
    assert leads[0].verified_email == "anna@noria.example.com"


def test_own_site_search_hop_used_when_article_has_no_site_link(persistence_db):
    """When the article carries no brand-host link, a quoted-brand search
    locates the company's own site and the same honest path completes."""
    run = _create_run(persistence_db)
    query = "noria systems raised $3 million"
    no_link_article = ARTICLE_HTML.replace(
        '<p><a href="https://noria.example.com">Noria Systems</a></p>', ""
    )
    results = {
        query: [
            _discovered(
                "https://techcrowd.example.com/2026/09/08/noria-raises-3m",
                "Noria Systems raises $3 million",
                query,
            )
        ],
        '"Noria Systems"': [
            _discovered("https://noria.example.com", "Noria Systems", '"Noria Systems"')
        ],
    }
    pages = {
        "https://techcrowd.example.com/2026/09/08/noria-raises-3m": no_link_article,
        "https://noria.example.com": NORIA_HOME_HTML,
        "https://noria.example.com/team": NORIA_TEAM_HTML,
    }
    discovery = DiscoveryService(FakeDiscoveryProvider(results))
    research = ResearchService(fetcher=FakeFetcher(pages))
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)

    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, list(results)))
    assert final_run.status == RunStatus.COMPLETED

    repo = CompanyRepository(persistence_db)
    candidates = [c for c in repo.list_candidates() if c.run_id == run.run_id]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.official_website == "https://noria.example.com"
    assert own_site_host(candidate) == "noria.example.com"

    contacts = ContactRepository(persistence_db).list_by_candidate(candidate.candidate_id)
    assert contacts and contacts[0].email == "anna@noria.example.com"

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    assert len(leads) == 1