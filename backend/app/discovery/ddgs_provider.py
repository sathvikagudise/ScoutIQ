"""Zero-API-key discovery provider backed by DuckDuckGo search (``ddgs``)."""

import asyncio
import logging

from app.discovery.base import DiscoveryProvider
from app.models.discovery import DEFAULT_MAX_RESULTS_PER_QUERY, DiscoveredSource

logger = logging.getLogger(__name__)


class DDGSProvider(DiscoveryProvider):
    """Discovery provider using DuckDuckGo's HTML/instant-answer search."""

    name = "duckduckgo"

    async def search(
        self, query: str, max_results: int = DEFAULT_MAX_RESULTS_PER_QUERY
    ) -> list[DiscoveredSource]:
        # ``ddgs`` is synchronous; offload to a thread so the event loop stays free.
        return await asyncio.to_thread(self._search_sync, query, max_results)

    @staticmethod
    def _search_sync(query: str, max_results: int) -> list[DiscoveredSource]:
        # Lazy import keeps the backend importable even if this provider is broken.
        from ddgs import DDGS

        sources: list[DiscoveredSource] = []

        with DDGS() as ddgs:
            raw_results = ddgs.text(query, max_results=max_results) or []
            for item in raw_results:
                url = (item.get("href") or "").strip()
                if not url:
                    continue
                title = (item.get("title") or "").strip()
                snippet = (item.get("body") or "").strip() or None
                sources.append(
                    DiscoveredSource(
                        query=query,
                        title=title or url,
                        url=url,
                        snippet=snippet,
                        provider=DDGSProvider.name,
                    )
                )

        logger.info("DDGS provider returned %d results for %r", len(sources), query)
        return sources