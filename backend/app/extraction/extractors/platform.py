"""Platform signal extraction — a page about building, not just using, a platform."""

from __future__ import annotations

import re

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.extraction.support import corpus, snippet
from app.research.models import ResearchResult

_PLATFORM_QUALIFIERS = {
    "software",
    "technology",
    "tech",
    "saas",
    "digital",
    "marketplace",
    "infrastructure",
    "data",
    "ai",
    "ml",
    "analytics",
    "cloud",
    "logistics",
    "fintech",
    "edtech",
    "healthtech",
    "developer",
    "b2b",
}

# A qualified claim like "SaaS platform", "technology platform", etc.
_QUALIFIED_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9-]*)\s+platform\b")

# A standalone "platform for/to/that" clause, e.g. "a platform for logistics".
_STANDALONE_RE = re.compile(r"\bplatform\b\s+(?:for|to|that)\b", re.I)


def extract_platform(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """Each descriptive platform signal becomes one claim (deduplicated).

    A bare word "platform" is *not* a signal on its own — the company must be
    described as building a qualified platform (a "SaaS platform") or as "a
    platform for/to/that ..." something. Generic website copy never qualifies.
    """
    claims: list[ExtractedClaim] = []
    seen: set[str] = set()
    source_url = research.final_url or research.source_url
    text = corpus(research)

    for match in _QUALIFIED_RE.finditer(text):
        qualifier = match.group(1).lower()
        if qualifier not in _PLATFORM_QUALIFIERS:
            continue
        key = f"{qualifier} platform"
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.PLATFORM,
                field="platform",
                value=match.group(0),
                normalized_value=key,
                context=f"text match ({snippet(text, match.start())})",
                source_url=source_url,
                source_title=source_title,
                confidence=0.6,
            )
        )

    for match in _STANDALONE_RE.finditer(text):
        if "platform" in seen:
            continue
        seen.add("platform")
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.PLATFORM,
                field="platform",
                value=match.group(0).lower(),
                normalized_value="platform",
                context=f"text match ({snippet(text, match.start())})",
                source_url=source_url,
                source_title=source_title,
                confidence=0.5,
            )
        )

    return claims