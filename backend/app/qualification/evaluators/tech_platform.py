"""Deterministic, source-backed tech-platform qualification evaluator (offline).

``TechPlatformEvaluator`` decides whether explicit, source-backed evidence
establishes that the candidate's company operates a qualifying *technology-related
platform* as its actual product or business:

    QualificationCriterion.TECH_PLATFORM  (Phase 5B)

Qualifying technology concepts (software, SaaS, cloud, marketplace, data
platform, infrastructure, developer platform) qualify only when they are framed
as what the company actually provides, builds, operates, or sells. A bare
"platform" — or a vague "leading platform", "growth platform", "business
platform", "digital platform" — never qualifies on its own.

The evaluator is a pure decision function over evidence. It never queries a
database, never fabricates an extracted value, never invents an evidence ID,
and never calls any external source, so it can be verified deterministically
offline.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Optional

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult

_CRITERION = QualificationCriterion.TECH_PLATFORM

# Evidence types whose extracted text is an actual product/business statement
# about the company. A raw figure or a person's email cannot establish that the
# company operates a tech platform.
_RELEVANT_TYPES = frozenset(
    {
        EvidenceType.PLATFORM,
        EvidenceType.COMPANY_DESCRIPTION,
        EvidenceType.COMPANY_NAME,
        EvidenceType.INDUSTRY,
        EvidenceType.OFFICIAL_WEBSITE,
    }
)

# Qualifying tech concepts framed as what the company actually provides, builds,
# operates, or sells. A bare "platform" (or "digital platform", "leading
# platform", "business platform") is deliberately absent.
_QUALIFYING_PATTERNS = (
    re.compile(
        r"\b(?:operates?|runs?|builds?|provides?|offers?|sells?|develops?|"
        r"maintains?)\s+(?:a\s+)?(?:software|saas|cloud|marketplace|data\s+"
        r"platform|developer\s+platform|developer\s+infrastructure|infrastructure)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bis\s+(?:a\s+)?(?:software|saas|cloud|marketplace|data\s+platform|"
        r"developer\s+platform)\s+(?:company|platform|provider|business)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:software|saas|cloud|marketplace|data\s+platform|developer\s+"
        r"platform|developer\s+infrastructure)\s+"
        r"(?:product|company|platform|provider|services?|solution|business)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:saas|software)\s+(?:company|provider|platform|product|service|solution|business|inc)\b", re.IGNORECASE),
    re.compile(r"\b(?:cloud|software|saas)\s+(?:infrastructure|platform|product|service|solution)\b", re.IGNORECASE),
    re.compile(r"\bdata\s+platform\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+platform\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+infrastructure\b", re.IGNORECASE),
    re.compile(r"\bcloud\s+(?:platform|software|infrastructure|services?)\b", re.IGNORECASE),
    re.compile(r"\b(?:B2B\s+|online\s+)?marketplace\b", re.IGNORECASE),
    re.compile(r"\bsoftware-as-a-service\b", re.IGNORECASE),
    re.compile(
        r"\b(?:ai|ml|artificial\s+intelligence|machine\s+learning)\s+"
        r"(?:platform|infrastructure|engine)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\ban?\s+ai\s+(?:company|platform|infrastructure)\b", re.IGNORECASE),
    re.compile(r"\b(?:analytics|data\s+engineering|data\s+infrastructure)\s+platform\b", re.IGNORECASE),
    # Vertical platform concepts the pipeline recognizes as platform businesses:
    # logistics/HR/climate/fintech/health/education technology platforms.
    re.compile(
        r"\b(?:logistics|hr|human\s+resources|climate|fintech|health(?:care)?|"
        r"education|edtech|martech|proptech|legaltech|retail)\s+"
        r"(?:tech(?:nology)?\s+)?(?:platform|software|saas|infrastructure)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bb2b\s+(?:software\s+)?(?:platform|saas)\b",
        re.IGNORECASE,
    ),
)

# Explicit statements that the company does NOT operate a qualifying tech
# platform. These are the ONLY grounds for FAIL; absence of evidence is never
# FAIL.
_NEGATIVE_PATTERNS = (
    re.compile(
        r"\bno\s+(?:software|saas|cloud|digital|tech(?:nology)?|marketplace|platform)"
        r"(?:\s+or\s+(?:software|saas|cloud|digital|tech(?:nology)?|marketplace|platform))*"
        r"\s*(?:product|platform|business|company|operations?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:does\s+not|doesn't|do\s+not|don't)\s+(?:operate|run|build|provide|"
        r"offer|maintain|have)\s+(?:a\s+)?(?:software|saas|cloud|technology|tech|"
        r"digital|marketplace|data)\s*(?:platform|product)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:does\s+not|doesn't|do\s+not|don't)\s+(?:offer|sell|provide|build|operate|run|have)"
        r"\s+(?:any\s+)?(?:software|saas|technology|tech|digital|cloud|marketplace|data)"
        r"\s*(?:product|platform|service|business)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwithout\s+(?:a\s+)?(?:software|digital|cloud|technology|tech)\s+"
        r"(?:platform|product)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:not|never)\s+(?:operates?|runs?|builds?|provides?|offers?)\s+"
        r"(?:a\s+)?(?:tech(?:nology)?|software|digital|cloud)\s+platform\b",
        re.IGNORECASE,
    ),
    re.compile(r"\boffline\s+(?:only|business|operations?|company|services?)\b", re.IGNORECASE),
    re.compile(r"\bphysical(?:-|\s+)?only\b", re.IGNORECASE),
    re.compile(
        r"\bexclusively\s+(?:\w+\s+){0,3}(?:offline|physical)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bno\s+digital\s+(?:product|platform)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+involved\s+with\s+technology\b", re.IGNORECASE),
    re.compile(r"\bno\s+tech(?:nology)?\s+(?:product|platform|component)\b", re.IGNORECASE),
)

_IRRELEVANT_TECH_PATTERNS = (
    re.compile(
        r"\b(?:values?|likes?|supports?|interests?\s+in)\s+(?:saas|software|cloud|technology)\b"
        r".*?\b(?:never|not)\s+(?:offer(?:s)?|sell(?:s)?|provide(?:s)?|build(?:s)?|operate(?:s)?|run(?:s)?)"
        r"\s+(?:any\s+)?(?:product|platform)\b",
        re.IGNORECASE,
    ),
)


def _evidence_texts(evidence: Iterable[Evidence]) -> Iterator[tuple[Evidence, str]]:
    """``(evidence, text)`` pairs with a usable, non-empty extracted value."""
    for item in evidence:
        value = item.extracted_value
        if not isinstance(value, str) or not value.strip():
            continue
        yield item, value.strip()


def evaluate_tech_platform(evidence: Iterable[Evidence]) -> CriterionResult:
    """Qualify whether the company operates a qualifying tech-related platform.

    :param evidence: all persisted evidence for the candidate.
    :returns: a ``CriterionResult`` for ``TECH_PLATFORM``.
    """
    result = CriterionResult(criterion=_CRITERION, status=QualificationStatus.NOT_EVALUATED)

    qualifying: list[tuple[Evidence, str]] = []
    negative: list[tuple[Evidence, str]] = []
    reasons: list[str] = []

    for item, text in _evidence_texts(evidence):
        if item.evidence_type not in _RELEVANT_TYPES:
            continue
        if any(pattern.search(text) for pattern in _IRRELEVANT_TECH_PATTERNS):
            continue
        if any(pattern.search(text) for pattern in _NEGATIVE_PATTERNS):
            negative.append((item, text))
        elif any(pattern.search(text) for pattern in _QUALIFYING_PATTERNS):
            qualifying.append((item, text))

    if qualifying and not negative:
        reasons = [
            f"explicit product/business evidence of a qualifying tech platform "
            f"({_concept(text)}): {text!r}"
            for _, text in qualifying
        ]
        result.status = QualificationStatus.PASS
        result.reasons = reasons
        result.evidence_ids = [item.evidence_id for item, _ in qualifying]
        return result

    if negative and not qualifying:
        reasons = [
            f"explicit evidence that the company does not operate a qualifying "
            f"tech-related platform: {text!r}"
            for _, text in negative
        ]
        result.status = QualificationStatus.FAIL
        result.reasons = reasons
        result.evidence_ids = [item.evidence_id for item, _ in negative]
        return result

    if qualifying and negative:
        reasons = [
            "conflicting evidence: statements describing a qualifying tech "
            "platform appear together with explicit statements that no such "
            "platform exists"
        ]
        result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
        result.reasons = reasons
        result.evidence_ids = [item.evidence_id for item, _ in [*qualifying, *negative]]
        return result

    result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
    result.reasons = [
        "insufficient evidence to establish that the company operates a "
        "qualifying tech-related platform; bare or vague 'platform' references "
        "or unconnected technology wording do not qualify on their own"
    ]
    result.evidence_ids = [item.evidence_id for item, _ in [*qualifying, *negative]]
    return result


def _concept(text: str) -> str:
    """Short name of the first qualifying tech concept found in ``text``."""
    for pattern in _QUALIFYING_PATTERNS:
        match = pattern.search(text)
        if match:
            example = str(match.group(0))
            for token in ("software", "saas", "cloud", "marketplace", "data platform",
                          "developer platform", "developer infrastructure",
                          "logistics platform", "hr platform", "fintech platform",
                          "infrastructure", "platform"):
                if token in example.lower():
                    return token
    return "tech platform"


class TechPlatformEvaluator:
    """Object interface for the Phase 5B tech-platform evaluator.

    Thin delegation over :func:`evaluate_tech_platform` so the evaluator is
    importable and callable as ``TechPlatformEvaluator().evaluate(evidence)``
    without duplicating the qualification logic.
    """

    def evaluate(self, evidence: Iterable[Evidence]) -> CriterionResult:
        return evaluate_tech_platform(evidence)
