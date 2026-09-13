"""Phase 10 strategy generation tests - fully offline, deterministic.

Exercise the deterministic discovery-strategy generator and the orchestrator's
strategy persistence (``SearchQuery.strategy``), covering:

  1. generation is deterministic and reproducible across calls
  2. generated queries are unique and each carries a strategy label
  3. explicit queries persist a caller-provided strategy label
  4. ``execute(queries=None)`` generates strategies and persists them
  5. the execute endpoint records generated strategies when asked to
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.discovery.base import DiscoveryProvider
from app.discovery.service import DiscoveryService
from app.discovery.strategies import generate_strategies
from app.main import app
from app.models.discovery import DiscoveredSource
from app.models.run import DiscoveryRun
from app.orchestration.service import PipelineOrchestrator
from app.repositories.query_repository import QueryRepository
from app.repositories.run_repository import RunRepository
from api_helpers import authed_client, make_owned_run
from app.research.service import ResearchService

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase10_strategies.db').as_posix()}",
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


def _create_run(db: Session) -> DiscoveryRun:
    return make_owned_run(db, target_lead_count=3)


class EmptyDiscoveryProvider(DiscoveryProvider):
    name = "fake-empty"

    async def search(self, query: str, max_results: int = 5) -> list[DiscoveredSource]:
        return []


class EmptyFetcher:
    async def fetch_page(self, url: str):
        raise AssertionError("No source should be researched in these tests")


# ---------------------------------------------------------------------------
# 1-2. generator determinism + uniqueness
# ---------------------------------------------------------------------------


def test_generate_strategies_is_deterministic_and_unique():
    first = generate_strategies()
    second = generate_strategies()
    assert first == second
    assert first
    texts = [text for text, _ in first]
    assert len(set(texts)) == len(texts)
    labels = [label for _, label in first]
    assert all(labels)
    assert all(text.strip() == text for text in texts)


def test_generate_strategies_carries_platform_and_geography_labels():
    strategies = generate_strategies()
    labels = {label for _, label in strategies}
    for label in labels:
        assert label.startswith("platform:")
        assert ";geo:" in label


def test_generate_strategies_queries_carry_entity_cue():
    texts = [text for text, _ in generate_strategies()]
    assert texts, "generator must produce queries"
    assert all("company" in text for text in texts)


def test_generate_strategies_spans_evidence_oriented_regions():
    """Discovery must combine a funding shape, a platform concept, and a non-US
    geography across the early-stage SaaS markets, not just the UK."""
    strategies = generate_strategies()
    geo_labels = {label for _, label in strategies}
    assert len(strategies) == 22
    assert any(label.endswith(";geo:uk") for label in geo_labels)
    assert any(label.endswith(";geo:india") for label in geo_labels)
    assert any(label.endswith(";geo:de") for label in geo_labels)
    assert any(label.endswith(";geo:br") for label in geo_labels)
    assert any("funding:seed_2m" in label for label in geo_labels)
    assert any("funding:seed_5m" in label for label in geo_labels)
    assert any("platform:marketplace" in label for label in geo_labels)


# ---------------------------------------------------------------------------
# 3-4. orchestrator strategy persistence
# ---------------------------------------------------------------------------


def test_execute_with_explicit_query_strategy_persists_label(persistence_db):
    run = _create_run(persistence_db)
    discovery = DiscoveryService(EmptyDiscoveryProvider())
    research = ResearchService(fetcher=EmptyFetcher())
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)
    import asyncio

    final_run = asyncio.run(
        orchestrator.execute(
            run.run_id,
            ["saas platform raised $2 million united states"],
            query_strategies={"saas platform raised $2 million united states": "platform:saas;funding:seed_2m;geo:us"},
        )
    )

    assert final_run is not None
    queries = QueryRepository(persistence_db).list_by_run(final_run.run_id)
    assert len(queries) == 1
    assert queries[0].strategy == "platform:saas;funding:seed_2m;geo:us"


def test_execute_without_queries_generates_and_persists_strategies(persistence_db):
    run = _create_run(persistence_db)
    discovery = DiscoveryService(EmptyDiscoveryProvider())
    research = ResearchService(fetcher=EmptyFetcher())
    orchestrator = PipelineOrchestrator(persistence_db, discovery, research)
    import asyncio

    final_run = asyncio.run(orchestrator.execute(run.run_id, queries=None))

    assert final_run is not None
    assert final_run.status.value == "completed"

    expected = dict(generate_strategies())
    queries = QueryRepository(persistence_db).list_by_run(final_run.run_id)
    assert len(queries) == len(expected)
    by_text = {query.query_text: query.strategy for query in queries}
    assert by_text == expected
    assert all(query.provider == "fake-empty" for query in queries)


# ---------------------------------------------------------------------------
# 5. endpoint records generated strategies when asked to
# ---------------------------------------------------------------------------


def test_execute_endpoint_generate_queries_flag(persistence_db, monkeypatch):
    import app.main as main_module

    _override_db(app, persistence_db)
    discovery = DiscoveryService(EmptyDiscoveryProvider())
    research = ResearchService(fetcher=EmptyFetcher())
    monkeypatch.setattr(main_module, "discovery_service", discovery)
    monkeypatch.setattr(main_module, "research_service", research)
    try:
        client = authed_client(app, persistence_db)
        run = _create_run(persistence_db)
        response = client.post(
            f"/api/runs/{run.run_id}/execute",
            json={"generate_queries": True, "max_results_per_query": 2},
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "completed"
    queries = QueryRepository(persistence_db).list_by_run(UUID(body["run"]["run_id"]))
    assert len(queries) == len(generate_strategies())
    assert all(query.strategy for query in queries)


def test_execute_endpoint_rejects_empty_queries_without_generate(persistence_db, monkeypatch):
    import app.main as main_module

    _override_db(app, persistence_db)
    monkeypatch.setattr(
        main_module, "discovery_service", DiscoveryService(EmptyDiscoveryProvider())
    )
    monkeypatch.setattr(main_module, "research_service", ResearchService(fetcher=EmptyFetcher()))
    try:
        client = authed_client(app, persistence_db)
        run = _create_run(persistence_db)
        response = client.post(
            f"/api/runs/{run.run_id}/execute",
            json={"queries": []},
        )
    finally:
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 422
    assert response.json()["detail"] == "queries must not be empty"