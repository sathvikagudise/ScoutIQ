"""Phase 3 research engine tests — fully offline (no live internet)."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.research.fetcher as fetcher_mod
import app.main as main_mod
from app.core.enums import FetchStatus, VerificationStatus
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.source import Source
from app.repositories.source_repository import SourceRepository
from app.research.extractors.internal_pages import classify_internal_pages
from app.research.extractors.links import extract_links
from app.research.fetcher import UrlFetcher
from app.research.models import FetchRecord, InternalPageCategory, PageMetadata, ResearchResult
from app.research.parser import content_type_is_html
from app.research.service import ResearchService
from app.research.extractors.emails import extract_emails
from app.research.extractors.metadata import extract_metadata
from app.research.extractors.text import extract_visible_text
from fakes import FakeAsyncClient, FakeResponse

SAMPLE_HTML = """
<html>
<head>
  <title>Acme Robotics | AI Automation</title>
  <meta name="description" content="Acme Robotics builds warehouse automation.">
  <meta property="og:title" content="Acme Robotics">
  <meta property="og:description" content="Warehouse automation, made simple.">
  <meta property="og:site_name" content="Acme">
  <link rel="canonical" href="https://www.acme.example/">
</head>
<body>
  <nav>
    <a href="/about">About</a>
    <a href="/team">Team</a>
    <a href="/contact-us">Contact</a>
  </nav>
  <script>var secret = "not text";</script>
  <style>.hidden { display: none; }</style>
  <p>Acme Robotics is a    warehouse automation company founded in 2020.</p>
  <p>Reach us at hi@acme.example or sales@acme.example.</p>
  <a href="/press/releases">Press</a>
  <a href="blog/">Blog</a>
  <a href="https://external.example/">External partner</a>
  <a href="mailto:ceo@acme.example">Email our CEO</a>
  <a href="/about#mission">About (mission)</a>
  <a href="/about#mission">About (dedup)</a>
</body>
</html>
"""


def run(coro):
    return asyncio.run(coro)


def success_record(url="https://www.acme.example/", body=SAMPLE_HTML, content_type="text/html"):
    return FetchRecord(
        url=url,
        fetch_status=FetchStatus.SUCCESS,
        status_code=200,
        final_url=url,
        content_type=content_type,
        body=body,
    )


class StubFetcher:
    def __init__(self, record: FetchRecord):
        self.record = record

    async def fetch_page(self, url: str) -> FetchRecord:
        return self.record


# ---------------------------------------------------------------------------
# Fetch classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, FetchStatus.SUCCESS),
        (302, FetchStatus.SUCCESS),
        (401, FetchStatus.ACCESS_BLOCKED),
        (403, FetchStatus.ACCESS_BLOCKED),
        (429, FetchStatus.RATE_LIMITED),
        (404, FetchStatus.NOT_FOUND),
        (410, FetchStatus.NOT_FOUND),
        (500, FetchStatus.SERVER_ERROR),
        (502, FetchStatus.SERVER_ERROR),
    ],
)
def test_fetch_classifies_http_statuses(monkeypatch, status_code, expected):
    fake = FakeAsyncClient()
    fake.route("https://page.example", response=FakeResponse(status_code=status_code, text="<p>hi</p>"))
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    record = run(UrlFetcher().fetch_page("https://page.example"))
    assert record.fetch_status == expected
    assert record.status_code == status_code
    assert record.final_url == "https://example.com/final"
    assert record.error is None


def test_fetch_timeout_classified_timeout(monkeypatch):
    fake = FakeAsyncClient()
    fake.route("https://slow.example", error=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    record = run(UrlFetcher().fetch_page("https://slow.example"))
    assert record.fetch_status == FetchStatus.TIMEOUT
    assert record.error is not None
    assert record.body is None


def test_fetch_connection_error_classified_network(monkeypatch):
    fake = FakeAsyncClient()
    fake.route("https://dead.example", error=httpx.ConnectError("dns failed"))
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    record = run(UrlFetcher().fetch_page("https://dead.example"))
    assert record.fetch_status == FetchStatus.NETWORK_ERROR
    assert record.error is not None


def test_fetch_respects_max_response_bytes(monkeypatch):
    fake = FakeAsyncClient()
    fake.route("https://big.example", response=FakeResponse(text="x" * 5000))
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    record = run(UrlFetcher(max_response_bytes=1024).fetch_page("https://big.example"))
    assert record.fetch_status == FetchStatus.SUCCESS
    assert record.body is None
    assert "exceeded" in record.error


# ---------------------------------------------------------------------------
# Content type handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/html", True),
        ("text/html; charset=utf-8", True),
        ("application/xhtml+xml", True),
        ("application/pdf", False),
        ("image/png", False),
        ("application/json", False),
    ],
)
def test_content_type_is_html(content_type, expected):
    assert content_type_is_html(content_type) is expected


def test_content_type_missing_is_lenient():
    assert content_type_is_html(None) is True


def test_non_html_content_is_skipped():
    record = success_record(content_type="application/pdf", body="%PDF-1.4 ...")
    result = run(ResearchService(StubFetcher(record)).research_url("https://www.acme.example/"))
    assert result.html_extracted is False
    assert result.fetch_status == FetchStatus.SUCCESS
    assert result.content_type == "application/pdf"
    assert "unsupported content type" in result.extraction_skip_reason
    assert result.metadata == PageMetadata()
    assert result.links == []
    assert result.emails == []
    assert result.visible_text is None


def test_html_is_parsed():
    record = success_record()
    result = run(ResearchService(StubFetcher(record)).research_url(record.url))
    assert result.html_extracted is True
    assert result.extraction_skip_reason is None
    assert result.visible_text


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

HTML_METADATA = """
<html><head>
<title>  Title Here  </title>
<meta name="description" content="A meta description">
<meta property="og:site_name" content="OGSite">
<meta name="og:title" content="OG Title">
<meta property="og:description" content="OG Description">
<link rel="canonical" href="https://www.acme.example/">
</head><body><p>Body</p></body></html>
"""


def test_metadata_extraction():
    soup = BeautifulSoup(HTML_METADATA, "html.parser")
    metadata = extract_metadata(soup)
    assert metadata.title == "Title Here"
    assert metadata.meta_description == "A meta description"
    assert metadata.og_site_name == "OGSite"
    assert metadata.og_title == "OG Title"
    assert metadata.og_description == "OG Description"
    assert metadata.canonical_url == "https://www.acme.example/"


def test_metadata_absent_fields_stay_none():
    soup = BeautifulSoup("<html><body><p>x</p></body></html>", "html.parser")
    assert extract_metadata(soup) == PageMetadata()


def test_metadata_extraction_with_multivalued_meta_attribute():
    """A ``class`` attribute on a ``<meta>`` tag must not crash extraction.

    bs4 represents multi-valued attributes as its ``AttributeValueList`` (a
    ``list[str]``), which has no ``.strip()``; the extractor must coerce it to
    a clean string at the boundary. Regression for the live pipeline failure
    ``'AttributeValueList' object has no attribute 'strip'``.
    """
    html = """
    <html><head>
    <meta class="optimize-bg" name="description" content="Description with class">
    <meta class="lazy" property="og:title" content="OG Title With Class">
    </head><body></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    metadata = extract_metadata(soup)
    assert metadata.meta_description == "Description with class"
    assert metadata.og_title == "OG Title With Class"
    assert metadata.title is None


# ---------------------------------------------------------------------------
# Visible text extraction
# ---------------------------------------------------------------------------


def test_visible_text_removes_script_style_and_normalizes():
    html = """
    <html><body>
      <script>var x = 1;</script>
      <style>.a{color:red}</style>
      <noscript>JS required</noscript>
      <p>  First   paragraph. </p>
      <p>Second paragraph.</p>
    </body></html>
    """
    text = extract_visible_text(BeautifulSoup(html, "html.parser"))
    assert "var x" not in text
    assert ".a{color:red}" not in text
    assert "JS required" not in text
    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert "  First   paragraph" not in text
    assert "First paragraph.\nSecond paragraph." in text


def test_visible_text_removes_nav_boilerplate():
    html = """
    <html><body>
      <nav><a href="/x">Home</a><a href="/y">Pricing</a></nav>
      <p>Real content.</p>
    </body></html>
    """
    text = extract_visible_text(BeautifulSoup(html, "html.parser"))
    assert "Pricing" not in text
    assert "Real content." in text


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------


def test_link_resolution_classification_and_dedup():
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    links = extract_links(soup, "https://www.acme.example/")

    by_url = {link.resolved_url: link for link in links}

    assert by_url["https://www.acme.example/about"].is_internal is True
    assert by_url["https://www.acme.example/team"].is_internal is True
    assert by_url["https://www.acme.example/contact-us"].is_internal is True
    assert by_url["https://www.acme.example/press/releases"].is_internal is True
    # relative with no leading slash resolves against the directory of the page
    assert by_url["https://www.acme.example/blog/"].original_href == "blog/"
    external = by_url["https://external.example/"]
    assert external.is_internal is False
    assert external.anchor_text == "External partner"
    # fragment-only same-page anchors are dropped but fragment-stripped dupes kept once
    assert [link for link in links if "mission" in link.resolved_url] == []


# ---------------------------------------------------------------------------
# Email extraction
# ---------------------------------------------------------------------------


def test_email_extraction_visits_text_and_mailto():
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    emails = extract_emails(soup)

    by_email = {item.email: item for item in emails}
    assert "hi@acme.example" in by_email
    assert "sales@acme.example" in by_email
    assert "ceo@acme.example" in by_email
    assert [item.email for item in emails] == sorted(by_email)


def test_emails_are_normalized_deduplicated_never_verified():
    html = """
    <p>HI@Acme.Example and hi@acme.example</p>
    <a href="mailto:HELLO@acme.example">mail</a>
    """
    emails = extract_emails(BeautifulSoup(html, "html.parser"))
    emails_set = {item.email for item in emails}
    assert emails_set == {"hi@acme.example", "hello@acme.example"}
    assert all(
        item.verification_status == VerificationStatus.UNVERIFIED for item in emails
    )


def test_email_extraction_ignores_invalid_addresses():
    html = """
    <p>contact@localhost not-invalid-looking? let's try 123@nosuchdomain.x and a..b@example.com</p>
    """
    emails = extract_emails(BeautifulSoup(html, "html.parser"))
    assert emails == []


# ---------------------------------------------------------------------------
# Internal page classification
# ---------------------------------------------------------------------------


def test_internal_page_classifier_categories():
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    links = extract_links(soup, "https://www.acme.example/")
    pages = classify_internal_pages(links)

    by_category = {page.category: page.url for page in pages}
    assert by_category[InternalPageCategory.ABOUT] == "https://www.acme.example/about"
    assert by_category[InternalPageCategory.TEAM] == "https://www.acme.example/team"
    assert by_category[InternalPageCategory.CONTACT] == "https://www.acme.example/contact-us"
    assert by_category[InternalPageCategory.PRESS_NEWS] == "https://www.acme.example/press/releases"
    assert by_category[InternalPageCategory.BLOG] == "https://www.acme.example/blog/"
    assert all(
        page.category
        in (
            InternalPageCategory.ABOUT,
            InternalPageCategory.TEAM,
            InternalPageCategory.CONTACT,
            InternalPageCategory.PRESS_NEWS,
            InternalPageCategory.BLOG,
        )
        for page in pages
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/about", InternalPageCategory.ABOUT),
        ("/about-us", InternalPageCategory.ABOUT),
        ("/team", InternalPageCategory.TEAM),
        ("/leadership", InternalPageCategory.LEADERSHIP),
        ("/founders", InternalPageCategory.FOUNDERS),
        ("/contact", InternalPageCategory.CONTACT),
        ("/company", InternalPageCategory.COMPANY),
        ("/press", InternalPageCategory.PRESS_NEWS),
        ("/news", InternalPageCategory.PRESS_NEWS),
        ("/blog", InternalPageCategory.BLOG),
        ("/products", None),
    ],
)
def test_internal_page_classifier_heuristics(path, expected):
    record = success_record()
    soup = BeautifulSoup(f'<html><body><a href="{path}">link</a></body></html>', "html.parser")
    links = extract_links(soup, record.final_url)
    pages = classify_internal_pages(links)
    if expected is None:
        assert pages == []
    else:
        assert len(pages) == 1
        assert pages[0].category == expected


# ---------------------------------------------------------------------------
# Research service pipeline
# ---------------------------------------------------------------------------


def test_research_service_full_pipeline():
    service = ResearchService(StubFetcher(success_record()))
    result = run(service.research_url("https://www.acme.example/"))

    assert result.source_url == "https://www.acme.example/"
    assert result.fetch_status == FetchStatus.SUCCESS
    assert result.http_status_code == 200
    assert result.content_type == "text/html"
    assert result.html_extracted is True
    assert result.metadata.title == "Acme Robotics | AI Automation"
    assert result.metadata.meta_description == "Acme Robotics builds warehouse automation."
    assert result.metadata.og_site_name == "Acme"
    assert "warehouse automation company" in result.visible_text
    assert "var secret" not in result.visible_text
    assert len(result.links) >= 6
    assert {item.email for item in result.emails} == {
        "hi@acme.example",
        "sales@acme.example",
        "ceo@acme.example",
    }
    assert any(page.category == InternalPageCategory.ABOUT for page in result.relevant_internal_pages)
    assert result.error is None


def test_research_service_fetch_failure_isolated():
    record = FetchRecord(url="https://blocked.example", fetch_status=FetchStatus.ACCESS_BLOCKED, status_code=403)
    result = run(ResearchService(StubFetcher(record)).research_url("https://blocked.example"))
    assert result.html_extracted is False
    assert result.fetch_status == FetchStatus.ACCESS_BLOCKED
    assert result.http_status_code == 403
    assert result.visible_text is None
    assert result.links == []
    assert result.emails == []


def test_research_url_with_empty_body():
    record = success_record(body="")
    result = run(ResearchService(StubFetcher(record)).research_url(record.url))
    assert result.html_extracted is False
    assert "empty or unparsable" in result.extraction_skip_reason


# ---------------------------------------------------------------------------
# Persistence integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'research.db').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def test_research_source_updates_fetch_metadata(persistence_db):
    record = success_record()
    service = ResearchService(StubFetcher(record))
    repo = SourceRepository(persistence_db)

    source = repo.create(
        Source(
            url="https://www.acme.example/",
            normalized_url="https://www.acme.example",
            title="Acme",
            provider="duckduckgo",
        )
    )

    result = run(service.research_source(source.source_id, repo))
    assert result is not None
    assert result.fetch_status == FetchStatus.SUCCESS

    updated = repo.get(source.source_id)
    assert updated.fetch_status == FetchStatus.SUCCESS
    assert updated.http_status_code == 200
    assert updated.final_url == "https://www.acme.example/"
    assert updated.content_type == "text/html"


def test_research_unknown_source_returns_none(persistence_db):
    service = ResearchService(StubFetcher(success_record()))
    assert run(service.research_source(uuid4(), SourceRepository(persistence_db))) is None


def test_research_source_failed_fetch_updates_metadata(persistence_db):
    record = FetchRecord(url="https://blocked.example", fetch_status=FetchStatus.ACCESS_BLOCKED, status_code=403)
    service = ResearchService(StubFetcher(record))
    repo = SourceRepository(persistence_db)
    source = repo.create(
        Source(url="https://blocked.example", title="Blocked", provider="duckduckgo")
    )

    result = run(service.research_source(source.source_id, repo))
    assert result.fetch_status == FetchStatus.ACCESS_BLOCKED

    updated = repo.get(source.source_id)
    assert updated.fetch_status == FetchStatus.ACCESS_BLOCKED
    assert updated.http_status_code == 403


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class FakeResearchService:
    def __init__(self, result=None):
        self.result = result or ResearchResult(source_url="https://www.acme.example/", html_extracted=True)

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


def test_research_url_endpoint(monkeypatch):
    monkeypatch.setattr(main_mod, "research_service", FakeResearchService())
    response = TestClient(app).post("/api/research/url", json={"url": "https://www.acme.example/"})
    assert response.status_code == 200
    body = response.json()
    assert body["source_url"] == "https://www.acme.example/"
    assert body["html_extracted"] is True
    assert body["fetch_status"] is None


def test_research_source_endpoint_updates_db(monkeypatch, persistence_db):
    repo = SourceRepository(persistence_db)
    source = repo.create(
        Source(url="https://www.acme.example/", title="Acme", provider="duckduckgo")
    )

    result = ResearchResult(
        source_url=source.url,
        final_url="https://www.acme.example/",
        fetch_status=FetchStatus.SUCCESS,
        http_status_code=200,
        content_type="text/html",
        html_extracted=True,
        metadata=PageMetadata(title="Acme"),
    )
    monkeypatch.setattr(main_mod, "research_service", FakeResearchService(result))

    def override_get_db():
        yield persistence_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(f"/api/research/source/{source.source_id}")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    assert response.json()["html_extracted"] is True

    updated = repo.get(source.source_id)
    assert updated.fetch_status == FetchStatus.SUCCESS
    assert updated.http_status_code == 200


def test_research_source_endpoint_404(monkeypatch, persistence_db):
    monkeypatch.setattr(main_mod, "research_service", FakeResearchService())

    def override_get_db():
        yield persistence_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(f"/api/research/source/{uuid4()}")
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 404


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