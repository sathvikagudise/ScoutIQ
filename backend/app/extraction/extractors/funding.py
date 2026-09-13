"""Funding amount extraction — only money figures tied to raising/investment wording."""

from __future__ import annotations

import re
from typing import Optional

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.extraction.support import (
    CURRENCY_PATTERN,
    corpus,
    currency_factor,
    normalize_money,
    snippet,
)
from app.research.models import ResearchResult

# Magnitude words recognized after a money figure, mirrored in the unit
# alternation of every money regex below (USD/GBP/EUR and Indian numbering
# "crore"/"lakh" are all explicit, never inferred).
_MONEY_UNIT_ALT = r"billion|bn|b|million|m|thousand|k|crore|lakh|lac"

_MONEY_RE = re.compile(
    rf"(?P<cur>{CURRENCY_PATTERN})\s*(\d[\d,]*(?:\.\d+)?)\s*({_MONEY_UNIT_ALT})?",
    re.I,
)

# A USD figure in a parenthetical frequently follows a non-USD amount, e.g.
# "raised €3.1 million ($3.6 million) in a seed round" -> the $3.6 million
# figure carries an explicit unit AND an explicit USD marker.
_USD_EQUIV_RE = re.compile(
    r"\(\s*(?:US\$|\$|\bUSD\b)\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(billion|bn|b|million|m|thousand|k)?\s*\)",
    re.I,
)

_FUNDING_WINDOW_WORDS = (
    "raised",
    "raises",
    "raising",
    "secured",
    "secures",
    "closed",
    "closes",
    "received",
    "obtained",
    "announced",
    "seed",
    "round",
    "funding",
    "financing",
    "investment",
    "investors",
    "series",
)


def money_text(
    amount_text: str,
    unit: Optional[str],
    currency: object = "$",
    converted_usd: Optional[int] = None,
) -> str:
    """A canonical explicit money string that keeps its magnitude wording.

    Short units keep their original case ("2M", "3.2m", "5K"); long units keep
    the word ("2 million", "3 billion"). USD figures carry the dollar sign
    directly so the persisted value is readable by the qualification layer.
    Non-USD figures keep their original currency wording and append the
    explicit converted USD equivalent ("€ 3 million (≈ $3,270,000)") so no
    unit conversion is ever hidden.
    """
    amount = amount_text.replace(",", "")
    is_usd = currency_factor(currency) == 1.0
    short = unit is not None and unit.lower() in ("m", "b", "k")
    unit_word = unit or ""
    if is_usd:
        gap = "" if not unit_word or short else " "
        base = f"${amount}{gap}{unit_word}"
    else:
        gap = "" if short else " "
        base = f"{currency} {amount}{gap}{unit_word}".strip()
    if is_usd or converted_usd is None:
        return base
    return f"{base} (≈ ${converted_usd:,})"

# A raising verb immediately before the money figure. Mirrors the headline-verb
# vocabulary (which includes simple present forms like "secures"/"raises").
_FUNDING_VERB_RE = re.compile(
    rf"\b(?:raised|raises|raising|secured|secures|securing|closed|closes|"
    rf"received|receiving|obtained|announced|announcing)\b(?:\s+\w+){{0,3}}\s*"
    rf"(?P<cur>{CURRENCY_PATTERN})\s*"
    rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<unit>{_MONEY_UNIT_ALT})?",
    re.I,
)

# A round/offer noun explicitly connected to the money figure.
_ROUND_RE = re.compile(
    rf"\b(?:seed|series|round|funding|financing|investment)\b(?:\s+\w+){{0,2}}\s+"
    rf"(?:of|for|worth|totaling|:)\s*(?P<cur>{CURRENCY_PATTERN})\s*"
    rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*"
    rf"(?P<unit>{_MONEY_UNIT_ALT})?",
    re.I,
)


def _claim_for(
    research: ResearchResult,
    source_title: Optional[str],
    start: int,
    currency: object,
    amount_text: str,
    unit: Optional[str],
    label: str,
    confidence: float = 0.6,
) -> Optional[ExtractedClaim]:
    normalized = normalize_money(amount_text, unit, currency)
    if normalized is None:
        return None
    text = corpus(research)
    # Only refuse a funding read when the SAME figure is revenue/valuation phrasing
    # directly attached (e.g. "$2M in revenue", "a $5M valuation").
    tail = text[start : start + 30].lower()
    if "revenue" in tail or "valuation" in tail:
        return None
    factor = currency_factor(currency)
    non_usd = factor is not None and factor != 1.0
    return ExtractedClaim(
        claim_type=EvidenceType.FUNDING,
        field="funding_amount_usd",
        value=money_text(amount_text, unit, currency=currency, converted_usd=normalized),
        normalized_value=normalized,
        context=f"funding signal {label} ({snippet(text, start)})",
        source_url=research.final_url or research.source_url,
        source_title=source_title,
        confidence=0.5 if non_usd else confidence,
    )


def extract_funding(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """Funding claims for each money figure tied to raising/round wording.

    Only figures with an explicit unit (K/M/B etc.) qualify; sums are reported
    individually and are never added together.
    """
    claims: list[ExtractedClaim] = []
    text = corpus(research)
    source_url = research.final_url or research.source_url
    # Claim end position per normalized value, used to recognise that a USD
    # parenthetical explains the *same* round that a non-USD figure just stated
    # ("raised €3.1 million ($3.6 million)") rather than a second round.
    claim_end_by_value: dict[int, int] = {}

    for match in _FUNDING_VERB_RE.finditer(text):
        claim = _claim_for(
            research,
            source_title,
            match.start(),
            match.group("cur"),
            match.group("amount"),
            match.group("unit"),
            "verb",
        )
        if claim:
            claims.append(claim)
            claim_end_by_value[claim.normalized_value] = match.end()

    for match in _ROUND_RE.finditer(text):
        skip_verbs = any(
            claim.normalized_value
            == normalize_money(match.group("amount"), match.group("unit"), match.group("cur"))
            for claim in claims
            if claim.claim_type == EvidenceType.FUNDING
            and claim.source_url == source_url
        )
        if skip_verbs:
            continue
        claim = _claim_for(
            research,
            source_title,
            match.start(),
            match.group("cur"),
            match.group("amount"),
            match.group("unit"),
            "round",
        )
        if claim:
            claims.append(claim)
            claim_end_by_value[claim.normalized_value] = match.end()

    claimed = {
        claim.normalized_value
        for claim in claims
        if claim.claim_type == EvidenceType.FUNDING
    }
    for match in _USD_EQUIV_RE.finditer(text):
        normalized = normalize_money(match.group(1), match.group(2), "$")
        if normalized is None or normalized in claimed:
            continue
        window = text[max(0, match.start() - 150) : match.end() + 30].lower()
        if not any(word in window for word in _FUNDING_WINDOW_WORDS):
            continue
        if "valuation" in window:
            continue
        explained = next(
            (
                value
                for value, end in claim_end_by_value.items()
                if 0 <= match.start() - end <= 80
            ),
            None,
        )
        if explained is not None:
            claims[:] = [
                claim
                for claim in claims
                if claim.claim_type is not EvidenceType.FUNDING
                or claim.normalized_value != explained
            ]
            claimed.discard(explained)
            claim_end_by_value.pop(explained, None)
        claim = _claim_for(
            research,
            source_title,
            match.start(),
            "$",
            match.group(1),
            match.group(2),
            "usd-equivalent parenthetical",
            confidence=0.5,
        )
        if claim:
            claimed.add(normalized)
            claims.append(claim)

    return claims