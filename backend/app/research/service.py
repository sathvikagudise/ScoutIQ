"""ResearchService — orchestrates the page-to-structured-material pipeline.

    Fetch → classify → validate content type → parse HTML →
    metadata / text / links / emails / internal pages → ResearchResult

The fetcher is injected so tests can stub the HTTP layer entirely.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.core.enums import FetchStatus
from app.repositories.source_repository import SourceRepository
from app.research.extractors import (
    classify_internal_pages,
    extract_emails,
    extract_links,
    extract_metadata,
    extract_visible_text,
)
from app.research.fetcher import UrlFetcher
from app.research.models import FetchRecord, ResearchResult
from app.research.parser import content_type_is_html, parse_html


class ResearchService:
    def __init__(self, fetcher: UrlFetcher | None = None) -> None:
        self.fetcher = fetcher or UrlFetcher()

    async def research_url(self, url: str) -> ResearchResult:
        """Fetch, parse, and extract structured material from one URL."""
        record = await self.fetcher.fetch_page(url)

        if record.fetch_status != FetchStatus.SUCCESS:
            return ResearchResult(
                source_url=url,
                final_url=record.final_url,
                fetch_status=record.fetch_status,
                http_status_code=record.status_code,
                content_type=record.content_type,
                html_extracted=False,
                extraction_skip_reason=record.error or f"fetch classified as {record.fetch_status.value}",
                error=record.error,
            )

        return self._extract(record)

    async def research_source(
        self, source_id: UUID, repository: SourceRepository
    ) -> Optional[ResearchResult]:
        """Research a persisted source and update its stored fetch metadata.

        Returns ``None`` when the source does not exist.
        """
        source = repository.get(source_id)
        if source is None:
            return None

        result = await self.research_url(source.url)
        repository.update_validation(
            source_id,
            fetch_status=result.fetch_status or FetchStatus.UNKNOWN_ERROR,
            http_status_code=result.http_status_code,
            final_url=result.final_url,
            content_type=result.content_type,
        )
        return result

    def _extract(self, record: FetchRecord) -> ResearchResult:
        base = ResearchResult(
            source_url=record.url,
            final_url=record.final_url,
            fetch_status=record.fetch_status,
            http_status_code=record.status_code,
            content_type=record.content_type,
            error=record.error,
        )

        if not content_type_is_html(record.content_type):
            base.html_extracted = False
            base.extraction_skip_reason = (
                f"unsupported content type '{record.content_type}'; HTML extraction skipped"
            )
            return base

        soup = parse_html(record)
        if soup is None:
            base.html_extracted = False
            base.extraction_skip_reason = "empty or unparsable HTML body"
            return base

        page_url = record.final_url or record.url
        metadata = extract_metadata(soup)
        links = extract_links(soup, page_url)
        emails = extract_emails(soup)
        internal_pages = classify_internal_pages(links)
        visible_text = extract_visible_text(soup)

        return base.model_copy(
            update={
                "html_extracted": True,
                "extraction_skip_reason": None,
                "metadata": metadata,
                "visible_text": visible_text,
                "links": links,
                "emails": emails,
                "relevant_internal_pages": internal_pages,
            }
        )