"""Deterministic extractors: one researched page -> source-backed claims."""

from __future__ import annotations

from app.extraction.extractors.company import extract_company
from app.extraction.extractors.contact import extract_contact_details
from app.extraction.extractors.description import extract_description
from app.extraction.extractors.funding import extract_funding
from app.extraction.extractors.geography import extract_geography
from app.extraction.extractors.people import extract_people
from app.extraction.extractors.platform import extract_platform
from app.extraction.extractors.revenue import extract_revenue
from app.extraction.extractors.sector import extract_sector
from app.extraction.extractors.website import extract_website
from app.extraction.models import ExtractedClaim
from app.research.models import ResearchResult

ALL_EXTRACTORS = (
    extract_company,
    extract_description,
    extract_sector,
    extract_website,
    extract_geography,
    extract_funding,
    extract_revenue,
    extract_platform,
    extract_people,
    extract_contact_details,
)


def run_all_extractors(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """Run every extractor over one research result, preserving order."""
    claims: list[ExtractedClaim] = []
    for extractor in ALL_EXTRACTORS:
        claims.extend(extractor(research, source_title=source_title))
    return claims