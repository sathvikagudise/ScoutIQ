"""Company description extraction from page metadata."""

from __future__ import annotations

from typing import Optional

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.research.models import ResearchResult


def extract_description(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """A single description claim: Open Graph description if present, else meta.

    Source text is never written into generated sentences; whatever is found
    is preserved verbatim as the claim value.
    """
    claims: list[ExtractedClaim] = []
    source_url = research.final_url or research.source_url

    og_desc = (research.metadata.og_description or "").strip()
    if og_desc:
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.COMPANY_DESCRIPTION,
                field="company_description",
                value=og_desc,
                normalized_value=og_desc,
                context="Open Graph description",
                source_url=source_url,
                source_title=source_title,
                confidence=0.7,
            )
        )
        return claims

    meta_desc = (research.metadata.meta_description or "").strip()
    if meta_desc:
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.COMPANY_DESCRIPTION,
                field="company_description",
                value=meta_desc,
                normalized_value=meta_desc,
                context="meta description",
                source_url=source_url,
                source_title=source_title,
                confidence=0.5,
            )
        )
        return claims

    return []