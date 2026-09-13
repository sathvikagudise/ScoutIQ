"""Discovery orchestration: multi-query search, URL normalization, dedup."""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.discovery.base import DiscoveryProvider
from app.models.discovery import (
    DEFAULT_MAX_RESULTS_PER_QUERY,
    DiscoveryResponse,
    DiscoveredSource,
)

logger = logging.getLogger(__name__)

# Query params that carry tracking/attribution noise, not meaning.
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "source",
        "s",
    }
)


def normalize_url(url: str) -> str:
    """Normalize a URL so equivalent URLs collapse to a single dedup key.

    Lowercases scheme/host, strips fragments and trailing slashes, removes
    default ports and tracking params, and sorts remaining query params.
    """
    cleaned = url.strip()
    parsed = urlsplit(cleaned)
    if not parsed.scheme or not parsed.netloc:
        return cleaned

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    try:
        if parsed.port in (80, 443):
            hostname = parsed.hostname or netloc
            netloc = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    except ValueError:  # malformed port — leave netloc as-is
        pass

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    params.sort()
    query = urlencode(params)

    return urlunsplit((scheme, netloc, path, query, ""))


def domain_of(url: str) -> str | None:
    """Extract a normalized hostname from a URL, if present."""
    parsed = urlsplit(url.strip())
    if not parsed.netloc:
        return None
    host = (parsed.hostname or parsed.netloc).lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host or None


def _restamp_sources(results: list[DiscoveredSource]) -> list[DiscoveredSource]:
    """Attach normalized URL + domain metadata without mutating inputs."""
    enriched: list[DiscoveredSource] = []
    for result in results:
        try:
            normalized = normalize_url(result.url)
        except ValueError:
            normalized = result.url.strip()
        enriched.append(
            result.model_copy(
                update={"normalized_url": normalized, "domain": domain_of(result.url)}
            )
        )
    return enriched


def deduplicate(results: list[DiscoveredSource]) -> tuple[list[DiscoveredSource], int]:
    """Drop results whose normalized URL was already seen.

    Returns the unique, order-preserving list (enriched with normalized URL and
    domain metadata) and the number of duplicates removed. The first query that
    discovered a URL owns the result.
    """
    seen: set[str] = set()
    unique: list[DiscoveredSource] = []
    removed = 0

    for result in results:
        key = normalize_url(result.url)
        if key in seen:
            removed += 1
            logger.debug("Duplicate removed: %s", result.url)
            continue
        seen.add(key)
        unique.append(result)

    return _restamp_sources(unique), removed


class DiscoveryService:
    """Runs discovery across one or more queries using a pluggable provider."""

    def __init__(self, provider: DiscoveryProvider) -> None:
        self.provider = provider

    async def discover(
        self,
        queries: list[str],
        max_results_per_query: int = DEFAULT_MAX_RESULTS_PER_QUERY,
    ) -> DiscoveryResponse:
        if not queries:
            raise ValueError("queries must not be empty")

        logger.info("Discovery started with %d queries", len(queries))
        collected: list[DiscoveredSource] = []
        errors: list[str] = []

        for raw_query in queries:
            query = raw_query.strip()
            if not query:
                errors.append("Empty query ignored")
                continue
            try:
                results = await self.provider.search(query, max_results_per_query)
                collected.extend(results)
                logger.info("Query %r yielded %d results", query, len(results))
            except Exception as exc:  # one failed query must not sink the run
                logger.warning("Discovery failed for query %r: %s", query, exc)
                errors.append(f"Query {query!r} failed: {exc}")

        unique, removed = deduplicate(collected)
        logger.info(
            "Discovery finished: %d collected, %d unique (removed %d)",
            len(collected),
            len(unique),
            removed,
        )

        return DiscoveryResponse(
            results=unique,
            total_results=len(collected),
            deduplicated_count=len(unique),
            provider=self.provider.name,
            errors=errors,
        )