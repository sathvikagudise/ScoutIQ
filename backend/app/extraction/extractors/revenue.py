"""Revenue amount extraction — only money figures explicitly tied to revenue wording."""

from __future__ import annotations

import re
from typing import Optional

from app.core.enums import EvidenceType
from app.extraction.extractors.funding import currency_factor, money_text, normalize_money
from app.extraction.models import ExtractedClaim
from app.extraction.support import CURRENCY_PATTERN, corpus, snippet
from app.research.models import ResearchResult

_LOOKBACK = 70
_LOOKAHEAD = 70

# Amount followed by a revenue mention.
_REVENUE_BACKWARD = re.compile(
    rf"(?P<cur>{CURRENCY_PATTERN})\s*"
    rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<unit>billion|bn|b|million|m|thousand|k)?"
    rf"[^.\n]{{0,{_LOOKAHEAD}}}\b(?:annual\s+)?revenue\b",
    re.I,
)

# Revenue mention followed by an amount.
_REVENUE_FORWARD = re.compile(
    rf"\b(?:annual\s+)?revenue\b[^.\n]{{0,{_LOOKAHEAD}}}"
    rf"(?P<cur>{CURRENCY_PATTERN})\s*"
    rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<unit>billion|bn|b|million|m|thousand|k)?",
    re.I,
)

def _claim_from_match(
    research: ResearchResult,
    source_title: Optional[str],
    match: re.Match[str],
    currency: object,
    amount_text: str,
    unit: Optional[str],
    direction: str,
) -> Optional[ExtractedClaim]:
    normalized = normalize_money(amount_text, unit, currency)
    if normalized is None:
        return None
    text = corpus(research)
    span = text[match.start() : match.end() + 20].lower()
    if any(word in span for word in "valuation gmv transaction".split()):
        return None
    if "projected to reach" in text[max(0, match.start() - 15) : match.end() + 20]:
        return None
    factor = currency_factor(currency)
    return ExtractedClaim(
        claim_type=EvidenceType.REVENUE,
        field="revenue_amount_usd",
        value=money_text(amount_text, unit, currency=currency, converted_usd=normalized),
        normalized_value=normalized,
        context=f"revenue mention {direction} ({snippet(text, match.start())})",
        source_url=research.final_url or research.source_url,
        source_title=source_title,
        confidence=0.5 if (factor is not None and factor != 1.0) else 0.6,
    )


def extract_revenue(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """A revenue claim only when a money figure is explicitly revenue-worded.

    Purposefully *not* extracted from valuations, GMV, transaction volumes, or
    projected-to-reach language, even when a dollar figure sits nearby.
    """
    claims: list[ExtractedClaim] = []
    text = corpus(research)

    for match in _REVENUE_FORWARD.finditer(text):
        claim = _claim_from_match(
            research, source_title, match, match.group("cur"), match.group("amount"), match.group("unit"), "after revenue"
        )
        if claim:
            claims.append(claim)

    seen_amounts = {
        claim.normalized_value
        for claim in claims
        if claim.claim_type == EvidenceType.REVENUE
    }
    for match in _REVENUE_BACKWARD.finditer(text):
        normalized = normalize_money(match.group("amount"), match.group("unit"), match.group("cur"))
        if normalized in seen_amounts:
            continue
        claim = _claim_from_match(
            research, source_title, match, match.group("cur"), match.group("amount"), match.group("unit"), "before revenue"
        )
        if claim:
            claims.append(claim)

    return claims