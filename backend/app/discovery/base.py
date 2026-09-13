"""Discovery provider abstraction.

The rest of the application talks to ``DiscoveryProvider`` only. Swapping the
underlying search mechanism (e.g. DuckDuckGo -> Bing -> self-hosted crawler)
never requires touching the service, models, or API layer.
"""

from abc import ABC, abstractmethod

from app.models.discovery import DEFAULT_MAX_RESULTS_PER_QUERY, DiscoveredSource


class DiscoveryProvider(ABC):
    """Interface every discovery provider must implement."""

    name: str = "unknown"

    @abstractmethod
    async def search(
        self, query: str, max_results: int = DEFAULT_MAX_RESULTS_PER_QUERY
    ) -> list[DiscoveredSource]:
        """Discover web sources for a single query."""