"""Explicit location extraction (headquartered/based/founded in ...)."""

from __future__ import annotations

import re
from typing import Optional

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.extraction.support import corpus, snippet
from app.research.models import ResearchResult

_LOCATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bheadquartered\s+in\s+([A-Z][A-Za-z'&\u2019-]+(?:[ \t]+[A-Z][A-Za-z'&\u2019-]+){0,3})"
    ),
    re.compile(
        r"\bbased\s+in\s+([A-Z][A-Za-z'&\u2019-]+(?:[ \t]+[A-Z][A-Za-z'&\u2019-]+){0,3})"
    ),
    re.compile(
        r"\bfounded\s+in\s+([A-Z][A-Za-z'&\u2019-]+(?:[ \t]+[A-Z][A-Za-z'&\u2019-]+){0,3})"
    ),
    # "<Place>-based" ("Bengaluru-based SaaS startup Apptile raises ...") is the
    # dominant base phrasing in funding coverage; the claim keeps the exact
    # "<Place>-based" form so the US-presence evaluator can read it directly.
    re.compile(r"\b([A-Z][A-Za-z'&\u2019-]+)-based\b"),
)

_STOP_WORDS = {"the", "of", "and", "for", "at", "in", "a", "an"}


def _clean_location(raw: str) -> Optional[str]:
    words = raw.split()
    for index, word in enumerate(words):
        if word.lower() in _STOP_WORDS:
            # "Headquartered in the heart of Berlin" -> stop at the first stop word.
            return " ".join(words[:index]) or None
    return raw


def extract_geography(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """One location claim per explicit '.. in <Place>' statement.

    Location is only ever taken from explicit wording like "headquartered in
    Austin". It is never inferred from a TLD, language, or timezone; without
    such wording no claim is made. The persisted ``value`` keeps the base
    phrasing ("headquartered in Austin") so downstream qualification can read
    the explicit base statement directly; the plain place name is carried in
    ``normalized_value`` for the candidate profile.
    """
    claims: list[ExtractedClaim] = []
    source_url = research.final_url or research.source_url
    text = corpus(research)

    for pattern in _LOCATION_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).strip()
            location = _clean_location(raw)
            if not location:
                continue
            claims.append(
                ExtractedClaim(
                    claim_type=EvidenceType.LOCATION,
                    field="primary_location",
                    value=match.group(0).strip(),
                    normalized_value=location,
                    context=f"text match ({snippet(text, match.start())})",
                    source_url=source_url,
                    source_title=source_title,
                    confidence=0.6,
                )
            )
    return claims