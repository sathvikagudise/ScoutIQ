"""Controlled sector/industry vocabulary extraction from page text."""

from __future__ import annotations

import re

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.extraction.support import corpus, snippet
from app.research.models import ResearchResult

# canonical sector -> (detection terms). Multi-word terms are checked first so
# a phrase like "enterprise software" never degrades into "software" alone.
_SECTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("enterprise software", ("enterprise software",)),
    ("developer tools", ("developer tools",)),
    ("logistics technology", ("logistics technology", "logistics tech")),
    ("healthtech", ("healthtech", "health tech")),
    ("edtech", ("edtech", "education technology")),
    ("fintech", ("fintech", "financial technology")),
    ("cleantech", ("cleantech", "clean tech", "climate technology")),
    ("marketplace", ("marketplace",)),
    ("ai software", ("ai software",)),
    ("saas", ("saas",)),
)

_TERMS: list[str] = sorted(
    (term for _, terms in _SECTORS for term in terms),
    key=len,
    reverse=True,
)
_TERM_RE = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in _TERMS) + r")\b", re.I)

_CANONICAL_BY_TERM = {term: canonical for canonical, terms in _SECTORS for term in terms}


def extract_sector(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """Each controlled vocabulary hit becomes one sector claim (deduplicated).

    Only exact phrases from the controlled vocabulary count; a page that
    merely *mentions* an industry is still reported, since the mention is a
    real observable, but nothing is inferred beyond the phrase itself.
    """
    claims: list[ExtractedClaim] = []
    seen: set[str] = set()
    source_url = research.final_url or research.source_url
    text = corpus(research)

    for match in _TERM_RE.finditer(text):
        term = match.group(0).lower()
        canonical = _CANONICAL_BY_TERM.get(term, term)
        if canonical in seen:
            continue
        seen.add(canonical)
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.INDUSTRY,
                field="industry_or_sector",
                value=canonical,
                normalized_value=canonical,
                context=f"text match: {term} ({snippet(text, match.start())})",
                source_url=source_url,
                source_title=source_title,
                confidence=0.6,
            )
        )
    return claims