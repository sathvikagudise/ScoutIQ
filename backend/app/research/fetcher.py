"""Lightweight HTTP layer — URL validation (Phase 0) and page fetching (Phase 3)."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.enums import FetchStatus
from app.models.source import FetchValidation
from app.research.models import FetchRecord

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "TVBFundRadar/0.3 (web research proof of concept)"
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000


def classify_fetch_status(status_code: int) -> FetchStatus:
    """Map an HTTP status code to a meaningful fetch outcome."""
    if 200 <= status_code < 400:
        return FetchStatus.SUCCESS
    if status_code in (401, 403):
        return FetchStatus.ACCESS_BLOCKED
    if status_code == 429:
        return FetchStatus.RATE_LIMITED
    if status_code in (404, 410):
        return FetchStatus.NOT_FOUND
    if status_code >= 500:
        return FetchStatus.SERVER_ERROR
    return FetchStatus.UNKNOWN_ERROR


def _to_failure(url: str, message: str, fetch_status: FetchStatus) -> FetchValidation:
    return FetchValidation(
        url=url,
        status_code=None,
        final_url=url,
        reachable=False,
        error=message,
        fetch_status=fetch_status,
    )


class UrlFetcher:
    """Validates that discovered URLs can be fetched and fetches page bodies."""

    def __init__(
        self,
        timeout: float = 8.0,
        follow_redirects: bool = True,
        headers: dict[str, str] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.headers = headers or {"User-Agent": DEFAULT_USER_AGENT}
        self.max_response_bytes = max_response_bytes

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=self.follow_redirects,
            headers=self.headers,
        )

    async def fetch(self, url: str) -> FetchValidation:
        """Validate a single URL using a dedicated client."""
        results = await self.validate([url], max_urls=1)
        return results[0]

    async def validate(self, urls: list[str], max_urls: int = 10) -> list[FetchValidation]:
        """Validate up to ``max_urls`` URLs concurrently.

        Individual failures return ``reachable=False`` instead of raising.
        """
        sample = list(dict.fromkeys(urls))[:max_urls]
        logger.info("URL validation started for %d URLs (sampling %d)", len(urls), len(sample))

        async with self._client() as client:
            validations = await asyncio.gather(*(self._fetch_with(client, url) for url in sample))

        return list(validations)

    async def fetch_page(self, url: str) -> FetchRecord:
        """Fetch one page and return a classified, size-bounded result.

        Never raises: every failure is converted into a ``FetchRecord`` with a
        meaningful ``FetchStatus`` and error message, keeping a research run
        isolated from any single broken URL.
        """
        try:
            async with self._client() as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            logger.warning("Page %s timed out: %s", url, exc)
            return _to_failure_record(url, f"timeout: {exc}", FetchStatus.TIMEOUT)
        except httpx.RequestError as exc:
            logger.warning("Page %s request failed: %s", url, exc)
            return _to_failure_record(url, f"request error: {type(exc).__name__}", FetchStatus.NETWORK_ERROR)
        except Exception as exc:  # defensive: never crash a research operation
            logger.exception("Unexpected error fetching page %s", url)
            return _to_failure_record(url, f"unexpected error: {exc}", FetchStatus.UNKNOWN_ERROR)

        fetch_status = classify_fetch_status(response.status_code)
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        logger.info(
            "Page %s fetched status=%s (%s) content-type=%s",
            url, response.status_code, fetch_status.value, content_type,
        )

        body = response.text
        if len(body.encode("utf-8", errors="ignore")) > self.max_response_bytes:
            return FetchRecord(
                url=url,
                fetch_status=fetch_status,
                status_code=response.status_code,
                final_url=final_url,
                content_type=content_type,
                error=f"response exceeded {self.max_response_bytes} bytes; extraction skipped",
            )

        return FetchRecord(
            url=url,
            fetch_status=fetch_status,
            status_code=response.status_code,
            final_url=final_url,
            content_type=content_type,
            body=body,
        )

    @staticmethod
    async def _fetch_with(client: httpx.AsyncClient, url: str) -> FetchValidation:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            logger.warning("URL %s timed out: %s", url, exc)
            return _to_failure(url, f"timeout: {exc}", FetchStatus.TIMEOUT)
        except httpx.RequestError as exc:
            logger.warning("URL %s request failed: %s", url, exc)
            return _to_failure(url, f"request error: {type(exc).__name__}: {exc}", FetchStatus.NETWORK_ERROR)
        except Exception as exc:  # defensive: never crash a discovery run
            logger.exception("Unexpected error fetching %s", url)
            return _to_failure(url, f"unexpected error: {exc}", FetchStatus.UNKNOWN_ERROR)

        fetch_status = classify_fetch_status(response.status_code)
        reachable = fetch_status == FetchStatus.SUCCESS
        logger.info("URL %s reachable=%s status=%s (%s)", url, reachable, response.status_code, fetch_status.value)
        return FetchValidation(
            url=url,
            status_code=response.status_code,
            final_url=str(response.url),
            reachable=reachable,
            content_type=response.headers.get("content-type"),
            fetch_status=fetch_status,
        )


def _to_failure_record(url: str, message: str, fetch_status: FetchStatus) -> FetchRecord:
    return FetchRecord(url=url, fetch_status=fetch_status, error=message)