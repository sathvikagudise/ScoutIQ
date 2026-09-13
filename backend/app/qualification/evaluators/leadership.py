"""Deterministic, source-backed leadership qualification evaluator (offline).

``LeadershipEvaluator`` decides whether explicit, source-backed evidence
establishes that a named individual holds a qualifying leadership position at
the candidate company:

    QualificationCriterion.LEADERSHIP  (Phase 5D)

Qualifying roles are ONLY:

- CEO
- Chief Executive Officer
- Founder
- Co-founder / Cofounder

The evaluator is a pure decision function over evidence. It never queries a
database, never fabricates a name, role, evidence ID, or source claim, and
never calls out to any external source. Absence of evidence is never PASS.

Decisions:

* ``PASS`` — explicit evidence ties a full person's name to a qualifying role
  in the same source-backed statement (e.g. "Jane Doe is the CEO of Acme.",
  "John Smith, Founder of Example Corp", "Sarah Lee, Co-founder and CEO",
  "Michael Brown serves as Chief Executive Officer."). Name and role must be
  connected and unambiguous; a bare list of the leadership team is not enough
  to attribute a specific role to a specific person.
* ``FAIL`` — explicit evidence contradicts a qualifying leadership claim for a
  named person (e.g. "Jane Doe is not the CEO.", "John Smith is a former CEO
  and no longer holds the role.", "contrary to the filing, Jane Doe never
  served as Chief Executive Officer."). We never FAIL merely because evidence
  is missing, and never FAIL a person who merely holds a non-qualifying role
  (CTO, VP, Director, Manager, employee, team member).
* ``INSUFFICIENT_EVIDENCE`` — no evidence, or evidence that does not explicitly
  establish both a full person's name AND a qualifying role with an explicit
  name-role connection (name without role, role without a full name, only
  CTO/VP/Director/Manager/employee roles, incomplete single-name identity,
  ambiguous connection, "Founder-led company" with no named person, "our
  leadership team includes Jane Doe" without an explicit role).
"""

from __future__ import annotations

import re
from typing import Iterable

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult

_CRITERION = QualificationCriterion.LEADERSHIP

# Evidence types that can carry name+leadership-role information. Evidence
# outside these types (a funding round, a domain, an email, a location) can
# never establish a qualifying leadership position.
_RELEVANT_TYPES = frozenset(
    {
        EvidenceType.CEO,
        EvidenceType.COFOUNDER,
        EvidenceType.FOUNDER,
        EvidenceType.COMPANY_DESCRIPTION,
        EvidenceType.COMPANY_NAME,
    }
)

# A full person's name: two or more consecutive capitalized tokens. Single-word
# or truncated identities (e.g. "CEO: Jane", "John") are never sufficient.
_NAME = r"[A-Z][a-z]+(?:[\s-][A-Z][a-z]+)+"

_ROLE_ALT = (
    r"(?:Chief\s+Executive\s+Officer|CEO|Co-?founder|Founder)"
)

# Explicit name-role connections. Each requires a full name immediately tied to
# a qualifying role by a possessive/equative/appositive structure. These are
# the ONLY constructs that produce a PASS; we never infer a role from a title,
# a bare mention, or surrounding context.
_POSITIVE_PATTERNS = (
    re.compile(
        rf"\b{_NAME}\s+(?:is|was|serves\s+as|served\s+as|has\s+served\s+as|"
        rf"currently\s+serves\s+as|is\s+currently)\s+(?:a\s+|an\s+|the\s+)?"
        rf"{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s+(?:is|was|serves\s+as|served\s+as|has\s+served\s+as|"
        rf"currently\s+serves\s+as|is\s+currently)\s+(?:a\s+|an\s+|the\s+)?"
        rf"{_ROLE_ALT}\s+of\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s*,\s*(?:the\s+)?{_ROLE_ALT}\b(?!\s*[A-Z])",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s*,\s*(?:co-?founder|founder|CEO)\s+"
        rf"(?:and\s+(?:co-?founder|founder|CEO)\s+)*of\b",
        re.IGNORECASE,
    ),
    # "John Smith, co-founder and CEO of Example Corp"
    re.compile(
        rf"\b{_NAME}\s*,\s*(?:the\s+)?{_ROLE_ALT}\s+and\s+{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
)

# Explicit contradictions of a qualifying leadership claim. Failure requires an
# unambiguous negation attached to a named person and a qualifying role. Bare
# non-qualifying roles (CTO/VP/Director/Manager) never FAIL.
_NEGATIVE_PATTERNS = (
    re.compile(
        rf"\b{_NAME}\s+(?:is|was|has\s+been)\s+not\s+(?:a\s+|an\s+|the\s+)?"
        rf"{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s+(?:is|was|has\s+been)\s+(?:a\s+|an\s+|the\s+)?former\s+"
        rf"{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s+never\s+(?:served\s+as|was)\s+(?:a\s+|an\s+|the\s+)?"
        rf"{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s+no\s+longer\s+(?:serves\s+as|holds|is)\s+(?:a\s+|an\s+|the\s+)?"
        rf"{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_NAME}\s+(?:stepped\s+down|resigned|was\s+removed)\s+(?:as|from)\s+"
        rf"(?:a\s+|an\s+|the\s+)?{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bcontrary\s+to\b.{0,80}\b{_NAME}\b.{0,80}\bnever\s+"
        rf"(?:served\s+as|was)\s+(?:a\s+|an\s+|the\s+)?{_ROLE_ALT}\b",
        re.IGNORECASE,
    ),
)


def _evidence_texts(evidence: Iterable[Evidence]) -> list[tuple[Evidence, str]]:
    """Return ``(evidence, text)`` pairs whose type is relevant and value usable."""
    usable: list[tuple[Evidence, str]] = []
    for item in evidence:
        if item.evidence_type not in _RELEVANT_TYPES:
            continue
        value = item.extracted_value
        if not isinstance(value, str) or not value.strip():
            continue
        usable.append((item, value.strip()))
    return usable


def _matches(text: str, patterns: tuple[re.Pattern, ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def evaluate_leadership(evidence: Iterable[Evidence]) -> CriterionResult:
    """Qualify the candidate's leadership evidence (independent criterion).

    :param evidence: all persisted evidence for the candidate.
    :returns: a ``CriterionResult`` for ``LEADERSHIP``.
    """
    result = CriterionResult(
        criterion=_CRITERION,
        status=QualificationStatus.NOT_EVALUATED,
    )

    usable = _evidence_texts(evidence)
    if not usable:
        result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
        result.reasons = [
            "no readable leadership evidence; nothing to qualify "
            "(evidence is missing, empty, or outside relevant types)"
        ]
        return result

    passage = []
    negative = []

    for item, text in usable:
        if _matches(text, _NEGATIVE_PATTERNS):
            negative.append((item, text))
        elif _matches(text, _POSITIVE_PATTERNS):
            passage.append((item, text))

    # An explicit contradiction wins: a named person explicitly denied (or no
    # longer holding) a qualifying role never PASSes on a conflicting positive.
    if negative and passage:
        result.status = QualificationStatus.FAIL
        result.reasons = [
            f"conflicting leadership evidence: an explicit statement denies a "
            f"qualifying role ({text!r}, evidence {item.evidence_id}) while "
            f"another claims it ({ptext!r}, evidence {pitem.evidence_id})"
            for (item, text), (pitem, ptext) in zip(negative, passage)
        ]
        result.evidence_ids = [
            item.evidence_id for item, _ in (negative + passage)
        ]
        return result

    if negative:
        result.status = QualificationStatus.FAIL
        result.reasons = [
            f"explicit evidence contradicts a qualifying leadership role for a "
            f"named person ({text!r}, evidence {item.evidence_id})"
            for item, text in negative
        ]
        result.evidence_ids = [item.evidence_id for item, _ in negative]
        return result

    if passage:
        result.status = QualificationStatus.PASS
        result.reasons = [
            f"explicit source-backed evidence ties a full person's name to a "
            f"qualifying leadership role ({text!r}, evidence {item.evidence_id})"
            for item, text in passage
        ]
        result.evidence_ids = [item.evidence_id for item, _ in passage]
        return result

    result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
    result.reasons = [
        "leadership evidence is insufficient: no source-backed statement "
        "explicitly connects a full person's name to a qualifying role "
        "(CEO / Chief Executive Officer / Founder / Co-founder); missing, "
        "incomplete, or non-qualifying evidence never qualifies"
    ]
    result.evidence_ids = [item.evidence_id for item, _ in usable]
    return result


class LeadershipEvaluator:
    """Object interface for the Phase 5D leadership evaluator.

    Thin delegation over :func:`evaluate_leadership` so the evaluator is
    importable and callable as ``LeadershipEvaluator().evaluate(evidence)``
    without duplicating the qualification logic.
    """

    def evaluate(self, evidence: Iterable[Evidence]) -> CriterionResult:
        return evaluate_leadership(evidence)
