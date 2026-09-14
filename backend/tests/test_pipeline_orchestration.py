"""Phase 5P pipeline orchestration tests - fully offline, deterministic.

Exercise ``PipelineOrchestrator`` (and ``POST /api/runs/{run_id}/execute``) with
a fake discovery provider + fake fetcher, against a temp SQLite database.

Ground truth established in discovery:
  * the funding/revenue extractors now persist explicit, unit-bearing USD
    figures (``value='$2 million'``) that the financial evaluator can read, the
    people extractor persists the explicit "Name, Role" connection, and the
    description extractor preserves attribution phrasing.
  * a research->extraction page that names a leader, announces in-range
    funding, and carries an EXPLICITLY attributed personal email (the ACME
    fixture: "Jane Doe, CEO - jane@example.com") qualifies PASS and produces
    exactly one lead and one evidence-backed contact.
  * a research->extraction page that funds, leads, and platforms but carries NO
    attributed personal email STILL PASSES the three company criteria (email
    attribution is no longer a company gate). The candidate produces a lead and
    the contact dimension honestly reports the gap as a named leader with no
    evidence-attributed email (NAMED_CONTACT_NO_EMAIL).
  * a candidate whose persisted evidence is readable AND explicitly attributes
    a personal email on its own-site domain (``"Alice Smith, CEO -
    alice@atlas.example.com"``) qualifies PASS and produces exactly one lead
    and one evidence-backed contact.

Contract under test:
  1. unknown run id -> orchestrator returns None / endpoint 404 "Run not found"
  2. empty queries -> 422 validation
  3. execute runs the full pipeline and persists queries + deduped sources
  4. leader evidence in researched pages assembles contacts
  5. only qualified (PASS) run candidates produce leads; count is exact
  6. a pure-extraction candidate stays INSUFFICIENT_EVIDENCE with no lead
  7. a pre-evidenced candidate is re-qualified PASS and linked into its lead
  8. unexpected research errors mark the run FAILED (with error_message)
  9. a discovery provider error on one query is soft; healthy queries continue
 10. non-HTML sources are skipped without failing the run
 11. re-running is idempotent (no duplicate leads/contacts/sources)
 12. run scoping: another run's execution never touches this run's output
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.contact.service import ContactAssemblyService
from app.core.enums import (
    CandidateStatus,
    ContactReadiness,
    EvidenceType,
    FetchStatus,
    QualificationCriterion,
    QualificationStatus,
    RunStatus,
)
from app.db.base import Base
from app.db.session import get_db
from app.discovery.base import DiscoveryProvider
from app.discovery.service import DiscoveryService
from app.extraction.service import own_site_host
from app.main import app
from app.models.company import CompanyCandidate
from app.models.discovery import DiscoveredSource
from app.models.evidence import Evidence
from app.models.run import DiscoveryRun
from app.orchestration.service import PipelineOrchestrator
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.query_repository import QueryRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run
from app.repositories.source_repository import SourceRepository
from app.research.models import FetchRecord
from app.research.service import ResearchService

# ---------------------------------------------------------------------------
# Offline doubles
# ---------------------------------------------------------------------------

ACME_HTML = """<!doctype html>
<html><head>
<title>Acme Software - home page</title>
<meta property="og:site_name" content="Acme Software" />
<meta property="og:description" content="Jane Doe, CEO - jane@acme.example.com. Acme Software is a software company headquartered in London, England." />
<meta name="description" content="Acme Software is a software company headquartered in London, England." />
<link rel="canonical" href="https://acme.example.com" />
</head><body>
<p>Jane Doe, CEO - jane@acme.example.com</p>
<p>Acme Software is a software company headquartered in London, England.</p>
<p>Acme recently raised $2 million in seed funding.</p>
</body></html>
"""

GAMMA_HTML = """<!doctype html>
<html><head>
<title>Gamma Analytics - home page</title>
<meta property="og:site_name" content="Gamma Analytics" />
<meta property="og:description" content="Gamma Analytics is a data analytics company headquartered in Dublin, Ireland." />
<meta name="description" content="Gamma Analytics is a data analytics company headquartered in Dublin, Ireland." />
<link rel="canonical" href="https://gamma.example.com" />
</head><body>
<p>Gamma Analytics is a data analytics company headquartered in Dublin, Ireland.</p>
</body></html>
"""

# A funded, non-US, software-platform company with an explicit leader but NO
# email anywhere on the page: the honest EMAIL_ATTRIBUTION boundary.
BETA_HTML = """<!doctype html>
<html><head>
<title>Beta Robotics | Warehouse Automation</title>
<meta property="og:site_name" content="Beta Robotics" />
<meta property="og:description" content="Beta Robotics builds a SaaS platform headquartered in Berlin, Germany." />
<link rel="canonical" href="https://beta.example.com" />
</head><body>
<p>Beta Robotics builds a SaaS platform headquartered in Berlin, Germany.</p>
<p>Jane Smith is the CEO of Beta Robotics.</p>
<p>Beta recently raised $4 million in a Series A round.</p>
</body></html>
"""

# A US, funded, software-platform homepage with NO leader email of its own:
# the funding/platform/location signals are all here, but the attributed
# personal email only exists on the /team page, so qualification can only
# PASS after the internal-pages follow-up actually happens.
DELTA_HOME_HTML = """<!doctype html>
<html><head>
<title>Delta Software - home page</title>
<meta property="og:site_name" content="Delta Software" />
<meta property="og:description" content="Delta Software is a saas platform headquartered in London, England." />
<link rel="canonical" href="https://delta.example.com" />
</head><body>
<p>Delta Software is a saas platform headquartered in London, England.</p>
<p>Delta recently raised $2 million in seed funding.</p>
<a href="https://delta.example.com/team">Team</a>
<a href="https://delta.example.com/about">About</a>
<a href="https://delta.example.com/contact">Contact</a>
<a href="https://delta.example.com/blog">Blog</a>
</body></html>
"""

DELTA_TEAM_HTML = """<!doctype html>
<html><head>
<title>Team | Delta Software</title>
<meta property="og:site_name" content="Delta Software" />
</head><body>
<p>Robert Chen, Founder - robert@delta.example.com</p>
</body></html>
"""

DELTA_ABOUT_HTML = """<!doctype html>
<html><head>
<title>About | Delta Software</title>
<meta property="og:site_name" content="Delta Software" />
</head><body>
<p>Delta Software is the SaaS platform for small warehouses in London, England.</p>
</body></html>
"""

DELTA_CONTACT_HTML = """<!doctype html>
<html><head>
<title>Contact | Delta Software</title>
<meta property="og:site_name" content="Delta Software" />
</head><body>
<p>Reach Delta Software at hello@delta.example.com.</p>
</body></html>
"""

DELTA_BLOG_HTML = """<!doctype html>
<html><head>
<title>Blog | Delta Software</title>
<meta property="og:site_name" content="Delta Software" />
</head><body><p>Delta's engineering blog.</p></body></html>
"""


class FakeDiscoveryProvider(DiscoveryProvider):
    name = "fake"

    def __init__(self, results_by_query: dict[str, list[DiscoveredSource]], raising: set[str] | None = None):
        self.results_by_query = results_by_query
        self.raising = raising or set()

    async def search(self, query: str, max_results: int = 5) -> list[DiscoveredSource]:
        if query in self.raising:
            raise RuntimeError(f"provider failed for {query!r}")
        return list(self.results_by_query.get(query, []))


class FakeFetcher:
    def __init__(self, pages: dict[str, str], raising: set[str] | None = None):
        self.pages = pages
        self.raising = raising or set()

    async def fetch_page(self, url: str) -> FetchRecord:
        if url in self.raising:
            raise RuntimeError(f"fetch failed for {url}")
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


def _discovered(url: str, title: str, query: str) -> DiscoveredSource:
    return DiscoveredSource(query=query, title=title, url=url, provider="fake")


def _delta_route() -> tuple[dict, dict]:
    query = "delta software company"
    results = {query: [_discovered("https://delta.example.com", "Delta Software", query)]}
    pages = {
        "https://delta.example.com": DELTA_HOME_HTML,
        "https://delta.example.com/team": DELTA_TEAM_HTML,
        "https://delta.example.com/about": DELTA_ABOUT_HTML,
        "https://delta.example.com/contact": DELTA_CONTACT_HTML,
        "https://delta.example.com/blog": DELTA_BLOG_HTML,
    }
    return results, pages


class RecordingFetcher(FakeFetcher):
    """FakeFetcher that records the URLs it was asked to fetch."""

    def __init__(self, pages: dict[str, str], raising: set[str] | None = None):
        super().__init__(pages, raising)
        self.fetched: list[str] = []

    async def fetch_page(self, url: str) -> FetchRecord:
        self.fetched.append(url)
        return await super().fetch_page(url)


def _make_orchestrator(
    db: Session,
    results_by_query: dict[str, list[DiscoveredSource]],
    pages: dict[str, str],
    *,
    provider_raising: set[str] | None = None,
    fetcher_raising: set[str] | None = None,
) -> PipelineOrchestrator:
    discovery = DiscoveryService(FakeDiscoveryProvider(results_by_query, provider_raising))
    research = ResearchService(fetcher=FakeFetcher(pages, fetcher_raising))
    return PipelineOrchestrator(db, discovery, research)


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror test_contact_pipeline.py conventions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase5p.db').as_posix()}",
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


def _create_run(db: Session) -> DiscoveryRun:
    return make_owned_run(db)


def _acme_route() -> tuple[dict, dict]:
    query = "acme software company"
    results = {query: [_discovered("https://acme.example.com", "Acme Software", query)]}
    pages = {"https://acme.example.com": ACME_HTML}
    return results, pages


def _beta_route() -> tuple[dict, dict]:
    query = "beta robotics company"
    results = {query: [_discovered("https://beta.example.com", "Beta Robotics", query)]}
    pages = {"https://beta.example.com": BETA_HTML}
    return results, pages


def _seed_qualified_candidate(db: Session, run_id: UUID) -> CompanyCandidate:
    """A run candidate whose persisted evidence qualifies PASS (financial + all criteria).

    The candidate carries an own-site domain (root homepage) and its evidence
    attributes a leadership email on that same domain, so EMAIL_ATTRIBUTION
    legitimately passes under the own-site gate.
    """
    candidate = CompanyRepository(db).create_candidate(
        CompanyCandidate(
            run_id=run_id,
            company_name="Atlas Robotics",
            official_website="https://atlas.example.com",
        )
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
                "Atlas Robotics is a software company headquartered in Berlin. "
                "Alice Smith, CEO - alice@atlas.example.com"
            ),
        )
    )
    evidence_repo.create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.CEO,
            claim="ceo",
            extracted_value="Alice Smith",
        )
    )
    return candidate


def _run_candidates(db: Session, run_id: UUID) -> list:
    return [
        candidate
        for candidate in CompanyRepository(db).list_candidates()
        if candidate.run_id == run_id
    ]


def _run_contacts(db: Session, run_id: UUID) -> list:
    contacts: list = []
    for candidate in _run_candidates(db, run_id):
        contacts.extend(
            ContactRepository(db).list_by_candidate(candidate.candidate_id)
        )
    return contacts


def _override_db(app_obj, persistence_db):
    def override_get_db():
        yield persistence_db

    app_obj.dependency_overrides[get_db] = override_get_db


# ---------------------------------------------------------------------------
# 1-3. run validation and request validation
# ---------------------------------------------------------------------------


def test_orchestrator_unknown_run_id_returns_none(persistence_db):
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    outcome = asyncio.run(orchestrator.execute(uuid4(), ["acme software company"]))
    assert outcome is None


def test_execute_endpoint_missing_run_returns_404(persistence_db):
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = client.post(
            f"/api/runs/{uuid4()}/execute", json={"queries": ["acme software company"]}
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_execute_endpoint_rejects_empty_queries(persistence_db):
    run = _create_run(persistence_db)
    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = client.post(f"/api/runs/{run.run_id}/execute", json={"queries": []})
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 422


def test_execute_endpoint_returns_run_results_json(monkeypatch, persistence_db):
    """The full execute path must serialize as RunResults (not 500).

    Regression for a bug where the async handler returned the un-awaited
    ``get_run_results`` coroutine, which failed FastAPI response validation
    with a 500 even though the run itself completed.
    """
    import app.main as main_module

    run = _create_run(persistence_db)
    results, pages = _acme_route()
    discovery_service = DiscoveryService(FakeDiscoveryProvider(results))
    research_service = ResearchService(fetcher=FakeFetcher(pages))
    monkeypatch.setattr(main_module, "discovery_service", discovery_service)
    monkeypatch.setattr(main_module, "research_service", research_service)

    _override_db(app, persistence_db)
    try:
        client = authed_client(app, persistence_db)
        response = client.post(
            f"/api/runs/{run.run_id}/execute",
            json={"queries": ["acme software company"], "max_results_per_query": 2},
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "run",
        "funnel",
        "contact_breakdown",
        "candidate_summary",
        "candidates",
        "leads",
        "contacts",
    }
    assert body["run"]["run_id"] == str(run.run_id)
    assert body["run"]["status"] == "completed"
    assert body["run"]["qualified_lead_count"] == 1
    assert [lead["company_name"] for lead in body["leads"]] == ["Acme Software"]
    assert len(body["contacts"]) == 1
    assert body["contacts"][0]["full_name"] == "Jane Doe"
    assert body["contacts"][0]["email"] == "jane@acme.example.com"
    assert body["contacts"][0]["verification_status"] == "evidenced"
    assert body["leads"][0]["verified_email"] == "jane@acme.example.com"
    assert body["funnel"]["company_qualified"] == 1
    assert body["contact_breakdown"]["evidenced_contact"] == 1
    assert body["leads"][0]["ceo_or_cofounder_name"] == "Jane Doe"
    assert body["candidate_summary"]["company_qualified"] == 1
    assert body["candidate_summary"]["near_qualified"] == 0
    assert body["candidate_summary"]["analyzed_total"] >= 1
    classifications = {item["classification"] for item in body["candidates"]}
    assert "company_qualified" in classifications


# ---------------------------------------------------------------------------
# 3-4. full pipeline success + persisted queries/sources + contacts
# ---------------------------------------------------------------------------


def test_execute_completes_run_and_persists_queries_and_sources(persistence_db):
    run = _create_run(persistence_db)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    assert final_run is not None
    assert final_run.status == RunStatus.COMPLETED
    assert final_run.completed_at is not None
    assert final_run.error_message is None

    queries = QueryRepository(persistence_db).list_by_run(run.run_id)
    assert len(queries) == 1
    assert queries[0].query_text == "acme software company"
    assert queries[0].provider == "fake"
    assert queries[0].result_count == 1

    sources = SourceRepository(persistence_db).list_by_run(run.run_id)
    assert len(sources) == 1
    assert sources[0].url == "https://acme.example.com"
    assert sources[0].normalized_url is not None


def test_execute_assembles_contacts_from_leader_evidence(persistence_db):
    run = _create_run(persistence_db)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    contacts = _run_contacts(persistence_db, run.run_id)
    assert [contact.full_name for contact in contacts] == ["Jane Doe"]
    assert [contact.role for contact in contacts] == ["CEO"]


def test_execute_follows_internal_pages_to_close_email_attribution(persistence_db):
    run = _create_run(persistence_db)
    results, pages = _delta_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, ["delta software company"]))

    candidates = {
        candidate.company_name: candidate
        for candidate in _run_candidates(persistence_db, run.run_id)
    }
    assert "Delta Software" in candidates
    candidate = CompanyRepository(persistence_db).get_candidate(
        candidates["Delta Software"].candidate_id
    )
    assert candidate.status == CandidateStatus.QUALIFIED

    evidence = EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)
    team_urls = [
        item.source_url for item in evidence if item.source_url == "https://delta.example.com/team"
    ]
    assert team_urls, "evidence from the followed /team page must be persisted"
    assert any(item.evidence_type.value == "email" for item in evidence)

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    delta_leads = [lead for lead in leads if lead.company_name == "Delta Software"]
    assert len(delta_leads) == 1
    assert delta_leads[0].ceo_or_cofounder_name == "Robert Chen"
    assert delta_leads[0].verified_email == "robert@delta.example.com"

    contacts = _run_contacts(persistence_db, run.run_id)
    assert (contacts[0].full_name, contacts[0].role, contacts[0].email) == (
        "Robert Chen",
        "Founder",
        "robert@delta.example.com",
    )


def test_execute_internal_page_followup_is_capped_and_skips_blog(persistence_db):
    run = _create_run(persistence_db)
    results, pages = _delta_route()
    fetcher = RecordingFetcher(pages)
    discovery = DiscoveryService(FakeDiscoveryProvider(results))
    research = ResearchService(fetcher=fetcher)
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, ["delta software company"]))

    assert fetcher.fetched[0] == "https://delta.example.com"
    followed = [url for url in fetcher.fetched if url != "https://delta.example.com"]
    assert set(followed) == {
        "https://delta.example.com/team",
        "https://delta.example.com/about",
        "https://delta.example.com/contact",
    }
    assert "https://delta.example.com/blog" not in fetcher.fetched


def test_execute_internal_page_fetch_failure_is_isolated(persistence_db):
    """A broken internal page must not sink the run (failure isolation)."""
    run = _create_run(persistence_db)
    results, pages = _delta_route()
    orchestrator = _make_orchestrator(
        persistence_db, results, pages, fetcher_raising={"https://delta.example.com/team"}
    )
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, ["delta software company"]))

    assert final_run is not None
    assert final_run.status == RunStatus.COMPLETED
    assert final_run.error_message is None


# ---------------------------------------------------------------------------
# 5-7. leads: only PASS candidates produce them (exact count + linkage)
# ---------------------------------------------------------------------------


def test_execute_only_qualified_candidates_produce_leads(persistence_db):
    run = _create_run(persistence_db)
    atlas = _seed_qualified_candidate(persistence_db, run.run_id)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    candidates = {candidate.company_name: candidate for candidate in _run_candidates(persistence_db, run.run_id)}
    assert "Acme Software" in candidates
    assert "Atlas Robotics" in candidates

    atlas_fresh = CompanyRepository(persistence_db).get_candidate(atlas.candidate_id)
    assert atlas_fresh.status == CandidateStatus.QUALIFIED

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    assert len(leads) == 2
    assert {lead.company_name for lead in leads} == {"Atlas Robotics", "Acme Software"}
    assert [lead.company_name for lead in leads if lead.candidate_id == atlas.candidate_id] == ["Atlas Robotics"]

    assert final_run.qualified_lead_count == 2


def test_execute_company_qualified_leader_without_email_still_leads(persistence_db):
    """Hybrid boundary: a company that funds, platforms, and is non-US is
    COMPANY-QUALIFIED on its three locked criteria and MUST produce a lead even
    though no email is attributed anywhere. The contact dimension honestly
    reports the gap (company contact channel available via own site, but no
    named leader or email found). The run still completes.
    """
    run = _create_run(persistence_db)
    results, pages = _beta_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, ["beta robotics company"]))

    beta = next(
        candidate
        for candidate in _run_candidates(persistence_db, run.run_id)
        if candidate.company_name == "Beta Robotics"
    )
    beta_fresh = CompanyRepository(persistence_db).get_candidate(beta.candidate_id)
    assert beta_fresh.status == CandidateStatus.QUALIFIED

    qualification = QualificationRepository(persistence_db).get_by_candidate(beta.candidate_id)
    assert qualification is not None
    assert qualification.overall_status == QualificationStatus.PASS
    # Company criteria now exclude email attribution entirely.
    assert {
        r.criterion for r in qualification.criteria
    } == {
        QualificationCriterion.FUNDING_OR_REVENUE,
        QualificationCriterion.TECH_PLATFORM,
        QualificationCriterion.US_PRESENCE,
    }

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    assert len(leads) == 1
    lead = LeadRepository(persistence_db).get_by_candidate(beta.candidate_id)
    assert lead is not None
    assert lead.verified_email is None
    # No named leader or email was extracted; the company's own site exists so
    # readiness is COMPANY_CONTACT_AVAILABLE (the honest minimum for a
    # company-qualified candidate with a homepage but no contact evidence).
    assert lead.contact_readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE


def test_execute_requalifies_pre_evidenced_candidate_and_links_lead(persistence_db):
    run = _create_run(persistence_db)
    atlas = _seed_qualified_candidate(persistence_db, run.run_id)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    qualification = QualificationRepository(persistence_db).get_by_candidate(atlas.candidate_id)
    assert qualification is not None
    assert qualification.overall_status == QualificationStatus.PASS

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    atlas_leads = [lead for lead in leads if lead.candidate_id == atlas.candidate_id]
    assert len(atlas_leads) == 1
    assert atlas_leads[0].qualification_id == qualification.qualification_id
    assert atlas_leads[0].ceo_or_cofounder_name == "Alice Smith"
    assert atlas_leads[0].verified_email == "alice@atlas.example.com"


# ---------------------------------------------------------------------------
# 8-10. failure isolation
# ---------------------------------------------------------------------------


def test_execute_unexpected_research_error_marks_run_failed(persistence_db):
    run = _create_run(persistence_db)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(
        persistence_db,
        results,
        pages,
        fetcher_raising={"https://acme.example.com"},
    )
    import asyncio

    with pytest.raises(RuntimeError):
        asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    failed = RunRepository(persistence_db).get(run.run_id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_message == "fetch failed for https://acme.example.com"


def test_execute_cancelled_does_not_leave_run_running(persistence_db):
    """A cancelled handler must still persist FAILED (never stuck RUNNING).

    asyncio.CancelledError is a BaseException (Python 3.8+), so the generic
    ``except Exception`` handler cannot catch it. Without a dedicated handler
    the run is left RUNNING forever after a client disconnect / server
    shutdown cancels the request.
    """
    run = _create_run(persistence_db)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)

    async def _raise_cancelled(
        resolved_queries, run_id, max_results_per_query, query_strategies
    ):
        raise asyncio.CancelledError()

    orchestrator._discover_and_persist = _raise_cancelled

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    failed = RunRepository(persistence_db).get(run.run_id)
    assert failed.status == RunStatus.FAILED
    assert failed.status is not RunStatus.RUNNING
    assert failed.error_message == "Run cancelled while executing"


def test_execute_db_poisoned_session_still_marks_failed(persistence_db):
    """A mid-pipeline database error must never block the FAILED write.

    On PostgreSQL any failed statement aborts the enclosing transaction and
    every later statement on that session fails until rollback. The orchestrator
    must persist the terminal FAILED state through a fresh session, otherwise a
    run whose pipeline hit a database error is left RUNNING forever.
    """
    run = _create_run(persistence_db)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)

    async def _poison_and_raise(
        resolved_queries, run_id, max_results_per_query, query_strategies
    ):
        from sqlalchemy import text

        # Poison the shared session: this statement fails on every backend and
        # (on PostgreSQL) aborts the current transaction, leaving the session
        # unusable for any further write — including a FAILED update. The DB
        # error itself is then surfaced as the ordinary pipeline failure below.
        with pytest.raises(Exception):
            orchestrator.db.execute(
                text("INSERT INTO this_table_does_not_exist (id) VALUES (1)")
            )
        raise RuntimeError("poisoned transaction")

    orchestrator._discover_and_persist = _poison_and_raise

    with pytest.raises(RuntimeError, match="poisoned transaction"):
        asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    failed = RunRepository(persistence_db).get(run.run_id)
    assert failed.status is RunStatus.FAILED
    assert failed.status is not RunStatus.RUNNING
    assert failed.error_message == "poisoned transaction"


def test_execute_soft_discovery_error_still_completes(persistence_db):
    run = _create_run(persistence_db)
    query = "acme software company"
    results = {query: [_discovered("https://acme.example.com", "Acme Software", query)]}
    pages = {"https://acme.example.com": ACME_HTML}
    discovery = DiscoveryService(
        FakeDiscoveryProvider(results, raising={"broken query"})
    )
    research = ResearchService(fetcher=FakeFetcher(pages))
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, ["acme software company", "broken query"]))

    assert final_run is not None
    assert final_run.status == RunStatus.COMPLETED
    sources = SourceRepository(persistence_db).list_by_run(run.run_id)
    assert len(sources) == 1
    assert len(_run_candidates(persistence_db, run.run_id)) == 1


def test_execute_skips_non_html_sources(persistence_db):
    run = _create_run(persistence_db)

    class PdfFetcher(FakeFetcher):
        async def fetch_page(self, url: str) -> FetchRecord:
            return FetchRecord(
                url=url,
                fetch_status=FetchStatus.SUCCESS,
                status_code=200,
                final_url=url,
                content_type="application/pdf",
                error=None,
            )

    query = "acme software company"
    results = {query: [_discovered("https://acme.example.com", "Acme Software", query)]}
    pages = {}
    discovery = DiscoveryService(FakeDiscoveryProvider(results))
    research = ResearchService(fetcher=PdfFetcher(pages))
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, [query]))

    assert final_run is not None
    assert final_run.status == RunStatus.COMPLETED
    assert _run_candidates(persistence_db, run.run_id) == []
    assert LeadRepository(persistence_db).list_by_run(run.run_id) == []


# ---------------------------------------------------------------------------
# 11-12. idempotency and run scoping
# ---------------------------------------------------------------------------


def test_execute_rerun_is_idempotent(persistence_db):
    run = _create_run(persistence_db)
    atlas = _seed_qualified_candidate(persistence_db, run.run_id)
    results, pages = _acme_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))
    asyncio.run(orchestrator.execute(run.run_id, ["acme software company"]))

    assert len(LeadRepository(persistence_db).list_by_run(run.run_id)) == 2
    assert len(LeadRepository(persistence_db).list_by_candidate(atlas.candidate_id)) == 1
    assert len(_run_contacts(persistence_db, run.run_id)) == 2  # Acme + Atlas leaders

    sources = SourceRepository(persistence_db).list_by_run(run.run_id)
    assert len(sources) == 1

    final_run = RunRepository(persistence_db).get(run.run_id)
    assert final_run.status == RunStatus.COMPLETED
    assert final_run.qualified_lead_count == 2


def test_execute_keeps_cross_run_isolation(persistence_db):
    run_a = _create_run(persistence_db)
    run_b = _create_run(persistence_db)
    results, pages = _acme_route()

    query_b = "gamma analytics company"
    results_b = {query_b: [_discovered("https://gamma.example.com", "Gamma Analytics", query_b)]}
    pages_b = {"https://gamma.example.com": GAMMA_HTML}

    orchestrator = _make_orchestrator(persistence_db, results, pages)
    orchestrator_b = _make_orchestrator(persistence_db, results_b, pages_b)
    import asyncio

    asyncio.run(orchestrator.execute(run_a.run_id, ["acme software company"]))
    asyncio.run(orchestrator_b.execute(run_b.run_id, [query_b]))

    names_a = {c.company_name for c in _run_candidates(persistence_db, run_a.run_id)}
    names_b = {c.company_name for c in _run_candidates(persistence_db, run_b.run_id)}
    assert names_a == {"Acme Software"}
    assert names_b == {"Gamma Analytics"}
    assert not (names_a & names_b)

    # Acme's page carries an explicitly attributed email, so run A produces one
    # lead; Gamma's page has no funding/email, so run B produces none.
    assert {lead.company_name for lead in LeadRepository(persistence_db).list_by_run(run_a.run_id)} == {"Acme Software"}
    assert {lead.company_name for lead in LeadRepository(persistence_db).list_by_run(run_b.run_id)} == set()

    assert {s.url for s in SourceRepository(persistence_db).list_by_run(run_a.run_id)} == {"https://acme.example.com"}
    assert {s.url for s in SourceRepository(persistence_db).list_by_run(run_b.run_id)} == {"https://gamma.example.com"}


# ---------------------------------------------------------------------------
# 13-14. foreign-claim scoping on round-up/press pages + own-site follow-up
# ---------------------------------------------------------------------------

# A publisher round-up reminiscent of the live "Which UK" case: one page on a
# news/aggregator site describing OTHER companies' rounds, platforms, HQ, and
# leadership. None of it belongs to the candidate the pipeline builds from the
# page, so scoped claims must be dropped before qualification.
PRESS_ROUNDUP_HTML = """<!doctype html>
<html><head>
<title>10 Which UK tech startups that raised millions this month</title>
<meta property="og:site_name" content="Tech Funding News" />
<meta property="og:description" content="The UK has seen notable funding rounds lately." />
<link rel="canonical" href="https://wires.example.com/stories/which-uk-roundup" />
</head><body>
<nav><a href="/category/edtech">Edtech</a><a href="/category/fintech">Fintech</a>\
<a href="/category/saas">SaaS</a></nav>
<p>London-based Autone raised $17 million to build its AI platform.</p>
<p>Auquan is headquartered in London, England and raised $4.5 million recently.</p>
<p>Fintech startup Ralio just raised $2.5 million for its marketplace.</p>
<p>The round was led by Dr. David Redfern, CEO of Datable Ltd, an investor in the deal.</p>
</body></html>
"""


def _press_roundup_route() -> tuple[dict, dict]:
    query = "saas platform raised $3 million united kingdom"
    results = {
        query: [_discovered("https://wires.example.com/stories/which-uk-roundup", "Which UK roundup", query)]
    }
    pages = {"https://wires.example.com/stories/which-uk-roundup": PRESS_ROUNDUP_HTML}
    return results, pages


# The Cloud Retail / RTIH shape from live run faf37bfd: a publisher (here
# "RetailWire Hub") article about a funded London SaaS company. The canonical
# URL is the DEEP article path on the publisher's domain, so the candidate's
# official website is the article itself — never the company's own site. The
# page also carries the publisher's editorial contact attributed to a
# "Founder" role. No email may be trusted here: the only host in play is the
# publisher's, and the own-site gate must close.
PUBLISHER_ARTICLE_HTML = """<!doctype html>
<html><head>
<title>Cloud Retail raises $3 million to power UK takeaway brands</title>
<meta property="og:site_name" content="RetailWire Hub" />
<meta name="description" content="Cloud Retail raises $3 million." />
<link rel="canonical" href="https://retailwirehub.example.com/home/2025/4/24/cloud-retail-raises-3m" />
</head><body>
<p>Cloud Retail, the platform helping UK takeaway brands go online, has raised $3 million.</p>
<p>Cloud Retail is headquartered in London, England.</p>
<p>Marat Bolatov is the CEO of Cloud Retail.</p>
<p>Scott Thompson, Founder - scott.thompson@retailwirehub.example.com</p>
</body></html>
"""


def _publisher_article_route() -> tuple[dict, dict]:
    query = "cloud retail platform raised $3 million united kingdom"
    results = {
        query: [_discovered(
            "https://retailwirehub.example.com/home/2025/4/24/cloud-retail-raises-3m",
            "Cloud Retail raises $3 million",
            query,
        )]
    }
    pages = {
        "https://retailwirehub.example.com/home/2025/4/24/cloud-retail-raises-3m": PUBLISHER_ARTICLE_HTML
    }
    return results, pages


def test_execute_publisher_article_email_never_passes_attribution(persistence_db):
    """A publisher-article email is never the leader's work email.

    The candidate genuinely funds ($3M), platforms (SaaS), and is London-based,
    and the article explicitly emails a "Founder" — but that address lives on
    the PUBLISHER's domain and the candidate has no own site (its canonical is
    a deep article URL). EMAIL_ATTRIBUTION must reject the attribution and the
    candidate must stay unqualified with no contact email and no lead.
    """
    run = _create_run(persistence_db)
    results, pages = _publisher_article_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, list(results)))

    assert final_run.status == RunStatus.COMPLETED
    candidates = _run_candidates(persistence_db, run.run_id)
    assert candidates, "the article must still produce a candidate identity"

    for candidate in candidates:
        fresh = CompanyRepository(persistence_db).get_candidate(candidate.candidate_id)
        assert fresh.official_website == (
            "https://retailwirehub.example.com/home/2025/4/24/cloud-retail-raises-3m"
        )
        assert own_site_host(fresh) is None, "a deep canonical is never the own site"
        assert fresh.status != CandidateStatus.QUALIFIED
        contacts = ContactRepository(persistence_db).list_by_candidate(fresh.candidate_id)
        assert contacts, "the named founder still produces a contact"
        assert all(contact.email is None for contact in contacts)

    assert LeadRepository(persistence_db).list_by_run(run.run_id) == []


def test_execute_ignores_other_companys_claims_on_roundup_page(persistence_db):
    """Foreign claims on a single third-party page never enter the candidate.

    The page names other companies' funding/platform/HQ/leadership; the only
    candidate identity comes from the page itself. Scoped evidence must be
    empty, so the run reliably holds at INSUFFICIENT_EVIDENCE with no lead.
    """
    run = _create_run(persistence_db)
    results, pages = _press_roundup_route()
    orchestrator = _make_orchestrator(persistence_db, results, pages)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, list(results)))

    assert final_run.status == RunStatus.COMPLETED
    candidates = _run_candidates(persistence_db, run.run_id)
    assert candidates, "the page must still produce a candidate identity"
    scoped = {
        EvidenceType.FUNDING,
        EvidenceType.REVENUE,
        EvidenceType.LOCATION,
        EvidenceType.US_PRESENCE,
        EvidenceType.PLATFORM,
        EvidenceType.CEO,
        EvidenceType.COFOUNDER,
        EvidenceType.FOUNDER,
    }
    for candidate in candidates:
        evidence = EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)
        claim_types = {item.evidence_type for item in evidence}
        assert claim_types.isdisjoint(scoped)
    assert LeadRepository(persistence_db).list_by_run(run.run_id) == []


# A press-release page whose canonical URL is the company's own site: the
# brand-new candidate's website is identified from the canonical, and the
# orchestrator then fetches the company's own homepage so self-published
# evidence (including the attributed leader email) grounds qualification.
DELTA_PRESS_HTML = """<!doctype html>
<html><head>
<title>Delta Software closes seed round</title>
<meta property="og:site_name" content="Press Wire" />
<link rel="canonical" href="https://delta.example.com" />
</head><body>
<p>Delta Software is a saas platform headquartered in London, England.</p>
<p>Delta recently raised $2 million in seed funding.</p>
<p>Robert Chen, Founder at Delta Software - robert@delta.example.com</p>
</body></html>
"""


def test_execute_fetches_own_site_when_canonical_points_to_company_site(persistence_db):
    """A press-identified candidate's website is fetched (and evidence merged)."""
    run = _create_run(persistence_db)
    query = "delta software company"
    results = {query: [_discovered("https://press.example.com/stories/delta", "Delta Software seed", query)]}
    pages = {
        "https://press.example.com/stories/delta": DELTA_PRESS_HTML,
        "https://delta.example.com": DELTA_HOME_HTML,
    }
    fetcher = RecordingFetcher(pages)
    discovery = DiscoveryService(FakeDiscoveryProvider(results))
    research = ResearchService(fetcher=fetcher)
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)
    import asyncio

    asyncio.run(orchestrator.execute(run.run_id, [query]))

    assert "https://delta.example.com" in fetcher.fetched
    candidates = {
        candidate.company_name: candidate
        for candidate in _run_candidates(persistence_db, run.run_id)
    }
    names = [name for name in candidates if "delta" in name.lower()]
    assert names, candidates
    candidate = CompanyRepository(persistence_db).get_candidate(
        candidates[names[0]].candidate_id
    )
    evidence = EvidenceRepository(persistence_db).list_by_candidate(candidate.candidate_id)
    assert any(item.source_url == "https://delta.example.com" for item in evidence)
    assert candidate.status == CandidateStatus.QUALIFIED

    leads = LeadRepository(persistence_db).list_by_run(run.run_id)
    delta_leads = [lead for lead in leads if "delta" in lead.company_name.lower()]
    assert len(delta_leads) == 1
    assert delta_leads[0].verified_email == "robert@delta.example.com"