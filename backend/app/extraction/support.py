"""Shared helpers for Phase 4 extractors (deterministic, stdlib-only)."""

from __future__ import annotations

import re
from typing import Optional

from app.research.models import ResearchResult

# Explicit currency markers recognized in funding/revenue claims. A bare figure
# with no currency marker is NEVER converted (no inference). Conversion rates
# are fixed, documented, deterministic approximations (2025-average FX) so the
# same source text always yields the same USD equivalent.
CURRENCY_PATTERN = (
    r"(?:US\$|\$|\bUSD\b|€|\bEUR\b|£|\bGBP\b|₹|\bINR\b|\bRs\.?\b)"
)

_FX_RATES = {
    "$": 1.0,
    "us$": 1.0,
    "usd": 1.0,
    "€": 1.09,  # EUR -> USD
    "eur": 1.09,
    "£": 1.27,  # GBP -> USD
    "gbp": 1.27,
    "₹": 0.012,  # INR -> USD (2025-average ~83 INR/USD)
    "inr": 0.012,
    "rs": 0.012,
    "rs.": 0.012,
}


def currency_factor(currency: object) -> float | None:
    """Deterministic USD multiplier for an explicit currency marker."""
    if currency is None:
        return None
    return _FX_RATES.get(str(currency).strip().lower())


def corpus(research: ResearchResult) -> str:
    """A single searchable string combining visible text and page metadata."""
    pieces = [
        research.visible_text or "",
        research.metadata.title or "",
        research.metadata.og_title or "",
        research.metadata.og_description or "",
        research.metadata.meta_description or "",
    ]
    return "\n".join(piece for piece in pieces if piece)


def snippet(text: str, start: int, radius: int = 90) -> str:
    """A whitespace-trimmed window of surrounding text for context traces."""
    window = text[max(0, start - radius) : start + radius]
    return " ".join(window.split())


def normalize_money(
    number_text: str, unit: Optional[str], currency: object = "$"
) -> Optional[int]:
    """Parse a money figure into whole USD. Returns None on any doubt.

    ``currency`` must be the explicit marker captured from the source text
    ("$", "€", "£", "USD", …); a bare figure with no marker must be passed as
    ``None`` and yields ``None`` (no inference). Non-USD figures are converted
    with the documented deterministic rate table.
    """
    try:
        amount = float(number_text.replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None
    scale = {
        "k": 1_000,
        "thousand": 1_000,
        "lakh": 100_000,
        "lac": 100_000,
        "m": 1_000_000,
        "million": 1_000_000,
        "crore": 10_000_000,
        "b": 1_000_000_000,
        "bn": 1_000_000_000,
        "billion": 1_000_000_000,
    }.get((unit or "").lower())
    if scale is None:
        return None
    factor = currency_factor(currency)
    if factor is None:
        return None
    return int(round(amount * scale * factor))


_URL_CLEANER = re.compile(r"(?:https?://)?(?:www\.)?([^/?#]+).*", re.I)


def normalize_website(url: str) -> Optional[str]:
    """Reduce a URL to a comparable hostname (lowercase, no www)."""
    match = _URL_CLEANER.match((url or "").strip())
    if not match:
        return None
    host = match.group(1).lower()
    return host or None


_GENERIC_SUFFIXES = (
    " inc",
    " inc.",
    " llc",
    " llc.",
    " ltd",
    " ltd.",
    " limited",
    " corp",
    " corp.",
    " corporation",
    " co",
    " co.",
    " group",
    " gmbh",
    " pvt",
    " pvt.",
    " pty",
    " pty.",
    " sa",
)


def normalize_company_name(name: str) -> str:
    """Fold company name to a comparable key (lowercase, punctuation stripped, legal suffix removed)."""
    cleaned = (name or "").strip().lower().replace(",", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    removed = True
    while removed:
        removed = False
        for suffix in _GENERIC_SUFFIXES:
            suffix_key = suffix.strip()
            if cleaned.endswith(suffix_key) and " " + suffix_key in " " + cleaned:
                cleaned = cleaned[: -len(suffix_key)].strip()
                removed = True
    return cleaned