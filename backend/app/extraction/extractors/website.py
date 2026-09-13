"""Official website extraction from canonical URL metadata."""

from __future__ import annotations

from typing import Optional

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.research.models import ResearchResult


def extract_website(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """A canonical URL is strong evidence of the official website.

    Absent a canonical URL nothing is emitted; the final_url is *not* used as
    an official-website claim because a redirected landing page is weaker
    evidence.
    """
    canonical = (research.metadata.canonical_url or "").strip()
    if not canonical:
        return []
    return [
        ExtractedClaim(
            claim_type=EvidenceType.OFFICIAL_WEBSITE,
            field="official_website",
            value=canonical,
            normalized_value=canonical,
            context="canonical URL",
            source_url=research.final_url or research.source_url,
            source_title=source_title,
            confidence=0.7,
        )
    ]