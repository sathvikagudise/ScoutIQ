"""Tests for the ScoutIQ Phase 0 web discovery proof of concept."""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from fakes import FakeAsyncClient, FakeResponse
from pydantic import ValidationError

import app.research.fetcher as fetcher_mod
from app.discovery.base import DiscoveryProvider
from app.discovery.service import DiscoveryService, deduplicate, normalize_url
from app.main import app
from app.models.discovery import (
    DEFAULT_MAX_RESULTS_PER_QUERY,
    DiscoveredSource,
    DiscoveryRequest,
)
from app.models.source import FetchValidation
from app.research.fetcher import UrlFetcher

QUERY_A = "Southeast Asia fintech platform startup funding"
QUERY_B = "Africa SaaS platform startup seed funding"


def run(coro):
    return asyncio.run(coro)


def source(url, query=QUERY_A, title="Example", provider="fake") -> DiscoveredSource:
    return DiscoveredSource(
        query=query,
        title=title,
        url=url,
        snippet="snippet text",
        provider=provider,
        discovered_at=datetime.now(timezone.utc),
    )


class FakeProvider(DiscoveryProvider):
    """In-memory provider used to test the abstraction without live internet."""

    name = "fake"

    def __init__(self, results_by_query=None, failures=()):
        self.results_by_query = results_by_query or {}
        self.failures = set(failures)
        self.calls = []

    async def search(self, query, max_results=DEFAULT_MAX_RESULTS_PER_QUERY):
        self.calls.append(query)
        if query in self.failures:
            raise RuntimeError("provider exploded")
        return self.results_by_query.get(query, [])[:max_results]


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


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def test_normalize_url_lowercases_scheme_and_host():
    assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert normalize_url("https://example.com/path/") == "https://example.com/path"
    assert normalize_url("https://example.com/path/#frag") == "https://example.com/path"


def test_normalize_url_drops_tracking_params_and_sorts_remaining():
    noisy = "https://example.com/page?utm_source=x&id=5&fbclid=abc"
    clean = "https://example.com/page?id=5"
    assert normalize_url(noisy) == clean
    assert normalize_url(clean) == clean


def test_normalize_url_removes_default_port():
    assert normalize_url("https://example.com:443/x") == "https://example.com/x"


def test_normalize_url_returns_scheme_less_urls_unchanged():
    assert normalize_url("example.com/path") == "example.com/path"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_deduplicate_removes_equivalent_urls_across_queries():
    results = [
        source("https://example.com/a/", query=QUERY_A),
        source("https://example.com/b", query=QUERY_B),
        source("https://example.com/a", query=QUERY_B),
    ]
    unique, removed = deduplicate(results)
    assert len(unique) == 2
    assert removed == 1
    # First query that discovered the URL owns the result.
    assert unique[0].query == QUERY_A


def test_deduplicate_ignores_tracking_params_and_fragments():
    results = [
        source("https://example.com/p?id=1&utm_campaign=x"),
        source("https://example.com/p?id=1#section"),
    ]
    unique, removed = deduplicate(results)
    assert len(unique) == 1
    assert removed == 1


# ---------------------------------------------------------------------------
# DiscoveryService + provider abstraction
# ---------------------------------------------------------------------------


def test_service_uses_provider_abstraction():
    provider = FakeProvider({QUERY_A: [source("https://example.com/a", query=QUERY_A)]})
    service = DiscoveryService(provider)

    response = run(service.discover([QUERY_A]))

    assert provider.calls == [QUERY_A]
    assert response.provider == "fake"
    assert response.total_results == 1
    assert response.deduplicated_count == 1
    assert response.results[0].provider == "fake"
    assert response.results[0].query == QUERY_A
    assert response.errors == []


def test_service_deduplicates_across_queries():
    provider = FakeProvider(
        {
            QUERY_A: [source("https://example.com/same", query=QUERY_A)],
            QUERY_B: [source("https://example.com/same/", query=QUERY_B), source("https://example.com/other", query=QUERY_B)],
        }
    )
    service = DiscoveryService(provider)

    response = run(service.discover([QUERY_A, QUERY_B]))

    assert response.total_results == 3
    assert response.deduplicated_count == 2  # three raw, one duplicate removed


def test_service_query_failure_does_not_abort_run():
    provider = FakeProvider(
        {QUERY_A: [source("https://example.com/a", query=QUERY_A)]}, failures={QUERY_B}
    )
    service = DiscoveryService(provider)

    response = run(service.discover([QUERY_A, QUERY_B]))

    assert response.total_results == 1
    assert response.deduplicated_count == 1
    assert len(response.errors) == 1
    assert QUERY_B in response.errors[0]


def test_service_rejects_empty_query_lists():
    service = DiscoveryService(FakeProvider({}))
    with pytest.raises(ValueError):
        run(service.discover([]))


def test_service_ignores_blank_entries_but_reports_them():
    service = DiscoveryService(FakeProvider({}))
    response = run(service.discover(["  "]))
    assert response.total_results == 0
    assert response.errors


def test_discovery_request_model_rejects_empty_queries():
    with pytest.raises(ValidationError):
        DiscoveryRequest(queries=[], max_results_per_query=3)


# ---------------------------------------------------------------------------
# HTTP fetch validation
# ---------------------------------------------------------------------------


def test_validate_handles_failures_and_successes(monkeypatch):
    fake = FakeAsyncClient()
    fake.route(
        "https://ok.example",
        response=FakeResponse(status_code=200, final_url="https://ok.example/home"),
    )
    fake.route("https://dead.example", error=httpx.ConnectError("boom"))
    fake.route("https://slow.example", error=httpx.TimeoutException("timed out"))

    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    validations = run(
        UrlFetcher().validate(
            ["https://ok.example", "https://dead.example", "https://slow.example"]
        )
    )
    by_url = {item.url: item for item in validations}

    assert by_url["https://ok.example"].reachable is True
    assert by_url["https://ok.example"].final_url == "https://ok.example/home"
    assert by_url["https://ok.example"].status_code == 200

    assert by_url["https://dead.example"].reachable is False
    assert by_url["https://dead.example"].error

    assert by_url["https://slow.example"].reachable is False
    assert "timeout" in (by_url["https://slow.example"].error or "")


def test_validate_respects_max_urls(monkeypatch):
    fake = FakeAsyncClient()
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    validations = run(
        UrlFetcher().validate(
            [f"https://example.com/{i}" for i in range(20)], max_urls=3
        )
    )
    assert len(validations) == 3


def test_fetch_never_raises_on_unreachable_host(monkeypatch):
    fake = FakeAsyncClient()
    fake.route("https://dead.example", error=httpx.ConnectError("no route"))
    monkeypatch.setattr(fetcher_mod.httpx, "AsyncClient", lambda **kw: fake)

    validation = run(UrlFetcher().fetch("https://dead.example"))
    assert validation.reachable is False
    assert validation.error


# ---------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


client = TestClient(app)


def test_health_endpoint(monkeypatch):
    if True:  # keep behavior obvious; health does not hit the provider
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_search_endpoint_rejects_empty_queries():
    response = client.post("/api/discovery/search", json={"queries": []})
    assert response.status_code == 422


def test_search_endpoint_uses_mocked_provider(monkeypatch):
    import app.main as main_mod

    provider = FakeProvider({QUERY_A: [source("https://example.com/a", query=QUERY_A)]})
    monkeypatch.setattr(main_mod, "discovery_service", DiscoveryService(provider))

    response = client.post(
        "/api/discovery/search",
        json={"queries": [QUERY_A], "max_results_per_query": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "fake"
    assert body["total_results"] == 1
    assert body["deduplicated_count"] == 1
    assert body["results"][0]["url"] == "https://example.com/a"


def test_validate_endpoint_returns_validations(monkeypatch):
    import app.main as main_mod

    provider = FakeProvider({QUERY_A: [source("https://example.com/a", query=QUERY_A)]})
    monkeypatch.setattr(main_mod, "discovery_service", DiscoveryService(provider))
    monkeypatch.setattr(main_mod, "url_fetcher", FakeFetcher())

    response = client.post(
        "/api/discovery/validate",
        json={"queries": [QUERY_A], "max_urls_to_validate": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["validations"]) == 1
    assert body["validations"][0]["validation"]["reachable"] is True
    assert body["validations"][0]["source"]["url"] == "https://example.com/a"