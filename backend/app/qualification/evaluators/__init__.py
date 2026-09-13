"""Deterministic, source-backed tech-platform qualification evaluator (offline).

``TechPlatformEvaluator`` decides whether explicit evidence establishes that the
candidate operates a qualifying technology-related platform — i.e. one of:
software, SaaS, cloud, marketplace, data platform, infrastructure, or a
developer platform — as the company's actual product or business.

The evaluator is a pure decision function over evidence. It never queries a
database, never fabricates values or evidence IDs, and never calls out to any
external source. Absence of qualifying evidence is never treated as PASS.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.core.enums import QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult

_CRITERION = QualificationCriterion.TECH_PLATFORM

# Explicit qualifying technology concepts. A concept only qualifies when it is
# stated about the company's actual product or business — bare "platform",
# "digital platform", "leading platform", etc. are deliberately excluded.
_QUALIFYING_PATTERNS = (
    re.compile(r"\bsaas\b", re.IGNORECASE),
    re.compile(r"\bsoftware\b", re.IGNORECASE),
    re.compile(r"\bcloud\b", re.IGNORECASE),
    re.compile(r"\bmarketplace\b", re.IGNORECASE),
    re.compile(r"\bdata\s+platform\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+platform\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+infrastructure\b", re.IGNORECASE),
    re.compile(r"\bapi\s+(?:platform|management)\b", re.IGNORECASE),
    re.compile(r"\binfrastructure\s+platform\b", re.IGNORECASE),
    re.compile(r"\b(?:iaas|paas|platform\s+as\s+a\s+service)\b", re.IGNORECASE),
    re.compile(r"\b(?:technology|software|cloud|developer|data|api)\s+infrastructure\b", re.IGNORECASE),
)

# Explicit statements that the company does NOT operate a qualifying tech
# platform. These are the only grounds for FAIL; absence of evidence is not.
_NEGATIVE_PATTERNS = (
    re.compile(r"\bno\s+(?:software|saas|cloud|marketplace|platform|technology|digital)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+a\s+(?:software|technology|digital|platform|cloud)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:does\s+not|doesn'?t|will\s+not)\s+"
        r"(?:operate|run|build|provide|offer|have|maintain)\s+"
        r"(?:a\s+)?(?:software|technology|digital|platform|cloud|marketplace)",
        re.IGNORECASE,
    ),
    re.compile(r"\bwithout\s+(?:a\s+)?(?:software|technology|digital|platform|cloud|marketplace)\b", re.IGNORECASE),
    re.compile(r"\b(?:exclusively|only)\s+(?:physical|offline)\b", re.IGNORECASE),
    re.compile(r"\boffline\s+(?:only|services|business)\b", re.IGNORECASE),
    re.compile(r"\bphysical\s+manufacturing\b", re.IGNORECASE),
    re.compile(r"\bnot\s+a\s+tech(?:nology)?\s+platform\b", re.IGNORECASE),
)


def _evidence_texts(evidence: Iterable[Evidence]) -> list[tuple[Evidence, str]]:
    """Usable (evidence, text) pairs; skips missing/empty extracted values."""
    usable: list[tuple[Evidence, str]] = []
    for item in evidence:
        value = item.extracted_value
        if not isinstance(value, str) or not value.strip():
            continue
        usable.append((item, value.strip()))
    return usable


def evaluate_tech_platform(evidence: Iterable[Evidence]) -> CriterionResult:
    """Qualify the candidate's technology-platform evidence (independent).

    :param evidence: all persisted evidence for the candidate.
    :returns: a ``CriterionResult`` for ``TECH_PLATFORM``.
    """
    result = CriterionResult(
        criterion=_CRITERION,
        status=QualificationStatus.NOT_EVALUATED,
    )

    usable = _evidence_texts(evidence)
    if not usable:
        result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
        result.reasons = ["no readable technology-platform evidence; nothing to qualify"]
        return result

    qualifying: list[tuple[Evidence, str]] = []
    negative: list[tuple[Evidence, str]] = []

    for item, text in usable:
        if any(pattern.search(text) for pattern in _NEGATIVE_PATTERNS):
            negative.append((item, text))
        elif any(pattern.search(text) for pattern in _QUALIFYING_PATTERNS):
            qualifying.append((item, text))

    # Both an explicit qualification and an explicit negation is a conflict:
    # the criterion cannot be cleanly established, so it stays undetermined.
    if qualifying and negative:
        result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
        result.reasons = [
            "conflicting evidence: some claims describe a qualifying technology "
            "platform while others state the company does not operate one"
        ]
        result.evidence_ids = [item.evidence_id for item, _ in (qualifying + negative)]
        return result

    if qualifying:
        result.status = QualificationStatus.PASS
        result.reasons = [
            f"explicit evidence establishes the company operates a qualifying "
            f"technology platform ({text!r})"
            for _, text in qualifying
        ]
        result.evidence_ids = [item.evidence_id for item, _ in qualifying]
        return result

    if negative:
        result.status = QualificationStatus.FAIL
        result.reasons = [
            f"explicit evidence establishes the company does not operate a qualifying "
            f"technology platform ({text!r})"
            for _, text in negative
        ]
        result.evidence_ids = [item.evidence_id for item, _ in negative]
        return result

    result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
    result.reasons = [
        "technology-platform evidence is too vague or unconnected to the "
        "company's product or business to qualify"
    ]
    result.evidence_ids = [item.evidence_id for item, _ in usable]
    return result


class TechPlatformEvaluator:
    """Object interface for the Phase 5B tech-platform evaluator.

    Thin delegation over :func:`evaluate_tech_platform` so the evaluator is
    importable and callable as ``TechPlatformEvaluator().evaluate(evidence)``
    without duplicating the qualification logic.
    """

    def evaluate(self, evidence: Iterable[Evidence]) -> CriterionResult:
        return evaluate_tech_platform(evidence)
