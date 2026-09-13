"""Support helpers for qualification support (stdlib-only, offline, deterministic).

These helpers locate *explicit financial figures* inside persisted evidence.
They never estimate, infer, project, or fabricate values — and they never
combine independent revenue/funding figures into a single total.
"""

from __future__ import annotations

import re
from typing import Optional, Union

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence

# ---------------------------------------------------------------------------
# Money parsing (mirroring storage conventions from Phase 4 extraction)
# ---------------------------------------------------------------------------

# Matches ``$2 million`` / ``USD 3 million`` / ``$2,000,000`` / ``2M`` / ``4 million``.
_MONEY_TEXT_RE = re.compile(
    r"(?:US\$|\$|\bUSD\b)\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*"
    r"(billion|bn|b|million|m|thousand|k)?",
    re.I,
)

_SCALE: dict[str, int] = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
}


def normalize_money(text: str) -> Optional[int]:
    """Whole USD when the text is an explicit, confidently-readable money figure.

    Returns ``None`` whenever any doubt remains (no dollar sign, no explicit
    unit, or an unparseable figure) — a ``None`` is always treated as
    insufficient evidence, never as zero.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        return None
    match = _MONEY_TEXT_RE.search(text.strip())
    if match is None:
        return None
    number_text, unit = match.group(1), (match.group(2) or "").lower()
    try:
        amount = float(number_text.replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None
    scale = _SCALE.get(unit)
    if unit and scale is None:
        return None
    return int(round(amount * (scale or 1)))


def is_qualifying_metric(evidence: Evidence) -> bool:
    """True only for explicitly financial evidence (revenue or funding).

    Valuation, platform, location, contact, and generic evidence never
    qualify. Nothing is inferred from a bare money figure alone.
    """
    return evidence.evidence_type in (EvidenceType.FUNDING, EvidenceType.REVENUE)
