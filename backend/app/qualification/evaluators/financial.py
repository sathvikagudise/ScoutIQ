"""Deterministic, source-backed financial qualification evaluator (CS-style, offline).

``FinancialEvaluator`` consumes a candidate's *persisted evidence*
(``Evidence`` records from Phase 4) and returns one criterion result:

    pass   -- at least one explicit revenue or funding figure falls in USD
              range (early-accessible, either metric — never both).

The evaluator is a pure decision function over evidence. It is deliberately
decoupled from persistence so it can be verified deterministically offline:
the evaluator is handed evidence, and it never queries the database.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult
from app.qualification.support import normalize_money

_USD_MIN: int = 1_000_000
_USD_MAX: int = 5_000_000

_CHOICE_LABEL = {
    EvidenceType.FUNDING: "funding",
    EvidenceType.REVENUE: "revenue",
}

_UNSUPPORTED_CLAIMS = {
    "valuation_amount_usd",
    "gmv_amount_usd",
    "total_payments_volume_usd",
    "aum_amount_usd",
    "market_size_usd",
}


def _is_supported_claim(item: Evidence) -> bool:
    """Known unsupported claim names are never treated as qualifying funding/revenue evidence."""
    claim = item.claim.strip().lower() if isinstance(item.claim, str) else ""
    return claim not in _UNSUPPORTED_CLAIMS


def _evidence_values(evidence: Iterator[Evidence]) -> Iterator[tuple[EvidenceType, int]]:
    """(metric, whole-USD value) pairs for evidence with a deterministically
    readable, explicitly-attributable revenue/funding figure."""
    for item in evidence:
        if item.evidence_type not in (EvidenceType.FUNDING, EvidenceType.REVENUE):
            continue
        value = normalize_money(item.extracted_value)
        if value is None:
            continue
        yield item.evidence_type, value


def evaluate_financial(evidence: Iterable[Evidence]) -> CriterionResult:
    """Qualify the candidate's funding or revenue evidence (independent).

    :param evidence: all persisted evidence for the candidate.
    :returns: a ``CriterionResult`` for ``FUNDING_OR_REVENUE``.
    """
    result = CriterionResult(
        criterion=QualificationCriterion.FUNDING_OR_REVENUE,
        status=QualificationStatus.NOT_EVALUATED,
    )

    evidence_list = list(evidence)
    usable: list[tuple[EvidenceType, int, Evidence]] = []
    reasons: list[str] = []

    for item in evidence_list:
        if item.evidence_type not in (EvidenceType.FUNDING, EvidenceType.REVENUE):
            continue
        if not _is_supported_claim(item):
            continue
        amount = normalize_money(item.extracted_value)
        if amount is None:
            reasons.append(
                f"financial yardstick unreadable for {item.evidence_type.value} "
                f"evidence ({item.claim!r}); no value fabricated"
            )
            continue
        usable.append((item.evidence_type, amount, item))

    if not usable:
        reasons.append("no readable revenue or funding figure in evidence")
        result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
        result.reasons = reasons
        return result

    # Independent, early-accessible pass: ANY explicit figure within range.
    for metric, amount, item in usable:
        metric_label = _CHOICE_LABEL[metric]
        if _USD_MIN <= amount <= _USD_MAX:
            reasons.append(
                f"{metric_label} figure {_format_usd(amount)} is within "
                f"{_format_usd(_USD_MIN)}-{_format_usd(_USD_MAX)} (evidence "
                f"{item.claim!r})"
            )
            result.status = QualificationStatus.PASS
            result.reasons = reasons
            result.evidence_ids = [item.evidence_id]
            return result

    # No figure in range, but at least one explicit figure exists.
    figures = ", ".join(
        f"{_CHOICE_LABEL[metric]}={_format_usd(amount)}" for metric, amount, _ in usable
    )
    reasons.append(f"explicit financial evidence exists but no figure is in range: {figures}")
    result.status = QualificationStatus.FAIL
    result.reasons = reasons
    result.evidence_ids = [item.evidence_id for _, _, item in usable]
    return result


def _format_usd(amount: int) -> str:
    """Format a whole USD figure as ``$1,000,000`` (no cents, no rounding)."""
    return f"${amount:,}"


class FinancialEvaluator:
    """Object interface for the Phase 5A financial qualification evaluator.

    Thin delegation over :func:`evaluate_financial` so the evaluator remains
    importable and callable as ``FinancialEvaluator().evaluate(evidence)``
    without duplicating the qualification logic.
    """

    def evaluate(self, evidence: Iterable[Evidence]) -> CriterionResult:
        return evaluate_financial(evidence)
