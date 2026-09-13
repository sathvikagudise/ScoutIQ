"""Deterministic, offline EMAIL_ATTRIBUTION qualification evaluator.

``EmailAttributionEvaluator`` / :func:`evaluate_email_attribution` decide
whether explicit, source-backed evidence ties the following to ONE AND THE SAME
person:

* a full person's name (first + last, e.g. "Jane Doe");
* a qualifying leadership role for that same person (CEO, Chief Executive
  Officer, Founder, Co-founder, Cofounder);
* a concrete, personalized email address that is EXPLICITLY attributed to that
  same person (e.g. "Jane Doe can be reached at jane@example.com", "Jane Doe
  (CEO) — jane@example.com").

The evaluator is a pure decision function over evidence. It NEVER queries a
database or API, NEVER calls an LLM, NEVER touches the network, and NEVER makes
up evidence IDs, names, roles, emails, or source claims. The same input always
produces the same output spoiled.

Emails are NOT deliverability-verified here: verification of an address is out
of scope for this criterion. We only qualify whether the email is explicitly
attributed to the same qualifying person. We never infer an email from a name
pattern (first.last@, first@, firstinitiallast@, ...) without an explicit
attribution, and we never infer attribution from a local-part that merely
resembles the name.

Decisions
---------
PASS
    Explicit source-backed evidence links the SAME person's full name, a
    qualifying role, and an explicit personalized email attribution to one
    another (for example "Jane Doe is the CEO of Acme and can be reached at
    jane@example.com." or "Jane Doe, CEO — jane@example.com").

FAIL
    Explicit source-backed evidence CONTRADICTS the attribution: the email is
    explicitly attributed to a DIFFERENT person, or an explicit statement
    contradicts the same-person email attribution (e.g. "jane@example.com is
    the email of someone else." / "contrary to the filing, this email does not
    belong to Jane Doe."). FAIL is only ever reached from an explicit
    contradiction, never from missing evidence.

INSUFFICIENT_EVIDENCE
    Everything else: no evidence at all; missing/empty extracted values; no
    email; an email without an attributed person; a person without an email; a
    person without a full name; a person without a qualifying role; a
    qualifying person + role but no explicit email; a generic / shared mailbox
    (contact@, info@, hello@, support@, sales@, team@, careers@, ...); an email
    whose attribution to the named person is not explicit (e.g. only a
    name-resembling local-part); an email attributed to a different person; or
    evidence whose email is ambiguous. Absence is never PASS, and we never
    fabricate evidence IDs or invent an email.

The same person must carry the name, the role, and the explicit email
attribution together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from app.core.enums import (
    EvidenceType,
    QualificationCriterion,
    QualificationStatus,
)
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult

_CRITERION = QualificationCriterion.EMAIL_ATTRIBUTION

_EVALUATOR_NAME = "EmailAttributionEvaluator"

# Evidence types that can plausibly carry a person's name, a leadership role,
# and an explicit email attribution. Evidence outside these sets can never
# establish same-person email attribution.
_RELEVANT_TYPES = frozenset(
    {
        EvidenceType.EMAIL,
        EvidenceType.CEO,
        EvidenceType.COFOUNDER,
        EvidenceType.FOUNDER,
        EvidenceType.COMPANY_DESCRIPTION,
        EvidenceType.COMPANY_NAME,
    }
)

# A full person's name: two or more consecutive capitalized tokens, with the
# final token a title-cased word rather than an all-caps role acronym. This
# avoids mistaking role phrases like "CEO of Acme" for a person name.
_NAME_RE = r"[A-Z][a-z]+(?:[ -][A-Z][a-z]+)+"

# A concrete, explicit email address.
_EMAIL_RE = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"

# Qualifying leadership roles this criterion recognises (FinTech leader is
# covered by LEADERSHIP; here we only need role qualification for the email
# attribution's same-person check).
_ROLE_RE = (
    r"(?:CEO|Chief\s+Executive\s+Officer|Co-?founder|Cofounder|Founder)"
)

# Generic / shared mailboxes that can never be attributed to a single person.
_GENERIC_MAILBOX_LOCAL_PARTS = frozenset(
    {
        "contact", "info", "hello", "support", "sales", "team", "careers",
        "admin", "office", "hr", "press", "pr", "media", "marketing",
        "inquiries", "enquiries", "billing", "jobs", "recruiting", "investors",
        "outreach", "business", "general", "accounts", "test", "noreply",
        "no-reply", "donotreply", "do-not-reply", "mail", "contactus",
        "info2", "sales2", "support2",
    }
)

_ROLE_RE_RE = re.compile(rf"\b{_ROLE_RE}\b", re.IGNORECASE)
_EMAIL_FINDER = re.compile(rf"\b({_EMAIL_RE})\b")

# Explicit same-person attribution patterns. The email must be explicitly tied
# to the SAME person who carries the qualifying role and the full name.
#
#   "Jane Doe, CEO — jane@example.com"
#   "Jane Doe is the CEO of Acme and can be reached at jane@example.com."
#   "Jane Doe (CEO). Reach her at jane@example.com."
#   "Jane Doe's email is jane@example.com."
_ATTRIBUTION_PATTERNS = (
    re.compile(
        rf"{_NAME_RE}\s*,\s*(?:the\s+)?{_ROLE_RE}\s*(?:[-—–:]\s*)*{_EMAIL_RE}",
    ),
    re.compile(
        rf"{_NAME_RE}\s+(?:is|was|serves\s+as|served\s+as|currently\s+serves\s+as|has\s+served\s+as)\s+(?:the\s+)?{_ROLE_RE}\b(?:.{{0,140}}?)\b{_EMAIL_RE}\b",
    ),
    re.compile(
        rf"{_NAME_RE}\s*\(\s*(?:the\s+)?{_ROLE_RE}\s*\)\s*(?:.{{0,80}}?)\b{_EMAIL_RE}\b",
    ),
    re.compile(
        rf"{_NAME_RE}['’]s\s+email\s+is\s+{_EMAIL_RE}",
    ),
    re.compile(
        rf"(?:reach|contact|email)\b(?:.{{0,30}}?)\b{_NAME_RE}\b(?:.{{0,80}}?)\b{_EMAIL_RE}\b",
        re.IGNORECASE,
    ),
)

# Explicit contradiction of the same-person email attribution. FAIL requires an
# explicit statement that the email belongs to a different person or otherwise
# contradicts the attribution.
_CONTRADICTION_PATTERNS = (
    re.compile(
        rf"{_EMAIL_RE}\s+(?:is|was)\s+(?:the\s+)?email\s+of\s+(?:a\s+)?different\s+person",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_EMAIL_RE}\s+(?:is|was)\s+(?:the\s+)?email\s+of\s+.*?\b(?:not|other than)\s+{_NAME_RE}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"contrary\s+to\b(?:.{0,80}?)\b{_EMAIL_RE}\b(?:.{0,80}?)\bdoes\s+not\s+belong\s+to\b(?:.{0,40}?)\b{_NAME_RE}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_EMAIL_RE}\s+(?:belongs?|is\s+attributed)\s+to\b(?:.{0,40}?)\b(?!{_NAME_RE}\b)[A-Z][a-z]+\s+[A-Z][a-z]+",
        re.IGNORECASE,
    ),
)


def _coerce_evidence(evidence: Iterable[Evidence] | Evidence) -> list[Evidence]:
    """Normalize single or multi-item evidence inputs to a plain list."""
    if evidence is None:
        return []
    if isinstance(evidence, Evidence):
        return [evidence]

    flattened: list[Evidence] = []
    for item in evidence:
        if isinstance(item, Evidence):
            flattened.append(item)
        elif isinstance(item, tuple):
            flattened.extend(_coerce_evidence(item))
        else:
            continue
    return flattened


def _texts(evidence: Iterable[Evidence] | Evidence) -> list[tuple[Evidence, str]]:
    """Yield ``(evidence, text)`` pairs that are usable for this criterion."""
    usable: list[tuple[Evidence, str]] = []
    for item in _coerce_evidence(evidence):
        if item.evidence_type not in _RELEVANT_TYPES:
            continue
        value = item.extracted_value
        if not isinstance(value, str) or not value.strip():
            continue
        usable.append((item, value.strip()))
    return usable


def _iter_emails(text: str) -> list[str]:
    return [m.group(1) for m in _EMAIL_FINDER.finditer(text)]


def _email_host(email: str) -> str:
    host = email.split("@", 1)[1].split(":", 1)[0].strip(".")
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _normalized_host(value: str) -> str:
    host = value.strip().strip(".").lower()
    return host[4:] if host.startswith("www.") else host


def _is_generic(email: str) -> bool:
    local = email.split("@", 1)[0].lower().lstrip("+")
    return local in _GENERIC_MAILBOX_LOCAL_PARTS


def _looks_name_like_local_part(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return bool(re.fullmatch(r"[a-z]+(?:[._-][a-z]+)+", local))


@dataclass(frozen=True)
class AttributedEmail:
    """A name↔role↔email triple explicitly attributed by evidence text.

    ``role`` is ``None`` when the matched attribution phrase ties only the
    person's name to the email (e.g. "Jane Doe's email is jane@example.com").
    """

    name: str
    role: Optional[str]
    email: str


def _first_email(text: str) -> Optional[str]:
    match = _EMAIL_FINDER.search(text)
    return match.group(1) if match else None


def _name_from_segment(text: str) -> Optional[str]:
    """The person's name in an attribution segment, anchored on the role.

    Returns the (up to) two capitalized tokens immediately before the role in
    the segment — the same right-anchoring the people extractor uses — so
    flattened page text like "Delta Software Robert Chen, Founder" resolves to
    "Robert Chen" rather than the greedy token run. Falls back to the first
    plain name match for attribution phrases without a role marker (e.g.
    "Jane Doe's email is jane@example.com").
    """
    role_match = _ROLE_RE_RE.search(text)
    if role_match:
        head = text[: role_match.start()]
        tokens = re.findall(r"[A-Z][a-zA-Z'’\-]+", head)
        if len(tokens) >= 2:
            return " ".join(tokens[-2:])
        if tokens:
            return tokens[-1]
    match = re.search(_NAME_RE, text)
    return match.group(0) if match else None


def _first_role(text: str) -> Optional[str]:
    match = _ROLE_RE_RE.search(text)
    return match.group(0) if match else None


def find_attributed_emails(
    evidence: Iterable[Evidence] | Evidence,
    company_hosts: Iterable[str] | None = None,
) -> list[AttributedEmail]:
    """Deterministically recover every explicitly attributed email triple.

    Uses exactly the same explicit-attribution phrase patterns as
    :func:`evaluate_email_attribution` (single source of truth): an email is
    only linked to a person when the persisted source text explicitly ties it
    to that person's name (and, when present in the phrase, their role).
    Generic shared mailboxes are never returned, and no email is ever inferred
    from a name, a pattern, or a resemblance.

    When ``company_hosts`` is provided, only emails whose host is in that set
    are returned: an attributed address is only treated as the leader's own
    work email when it sits on the candidate's own-site domain.
    """
    allowed: set[str] | None = None
    if company_hosts is not None:
        allowed = {
            _normalized_host(host) for host in company_hosts if host
        }

    usable = _texts(evidence)
    combined = " ".join(text for _, text in usable)
    if not combined.strip():
        return []

    results: list[AttributedEmail] = []
    seen: set[tuple[str, str]] = set()
    for pattern in _ATTRIBUTION_PATTERNS:
        for match in pattern.finditer(combined):
            segment = combined[match.start() : match.end()]
            email = _first_email(segment)
            if email is None or _is_generic(email):
                continue
            if allowed is not None and _email_host(email) not in allowed:
                continue
            name = _name_from_segment(segment)
            if not name:
                continue
            role = _first_role(segment)
            key = (name.lower(), email.lower())
            if key in seen:
                continue
            seen.add(key)
            results.append(AttributedEmail(name=name, role=role, email=email))
    return results


def evaluate_email_attribution(
    evidence: Iterable[Evidence] | Evidence,
    company_hosts: Iterable[str] | None = None,
) -> CriterionResult:
    """Decide EMAIL_ATTRIBUTION for the supplied evidence.

    When ``company_hosts`` is provided, an attribution only counts when its
    email sits on one of those hosts (the candidate's own-site domain): an
    explicitly attributed address on a third-party page is never treated as the
    leader's own personal work email.
    """

    allowed: set[str] | None = None
    if company_hosts is not None:
        allowed = {
            _normalized_host(host) for host in company_hosts if host
        }

    usable = _texts(evidence)
    evidence_ids = [item.evidence_id for item, _ in usable]

    if not usable:
        return CriterionResult(
            criterion=_CRITERION,
            status=QualificationStatus.INSUFFICIENT_EVIDENCE,
            reasons=["No relevant evidence supplied for EMAIL_ATTRIBUTION."],
            evidence_ids=[],
        )

    combined = " ".join(text for _, text in usable)
    emails = _iter_emails(combined)
    names = re.findall(_NAME_RE, combined)
    roles = re.findall(rf"{_ROLE_RE}", combined, re.IGNORECASE)

    # Explicit contradiction wins over everything.
    if any(pattern.search(combined) for pattern in _CONTRADICTION_PATTERNS):
        return CriterionResult(
            criterion=_CRITERION,
            status=QualificationStatus.FAIL,
            reasons=["Evidence explicitly contradicts the same-person email attribution."],
            evidence_ids=evidence_ids,
        )

    if not names or not roles or not emails:
        missing: list[str] = []
        if not names:
            missing.append("full person's name")
        if not roles:
            missing.append("qualifying role")
        if not emails:
            missing.append("explicit personal email")
        return CriterionResult(
            criterion=_CRITERION,
            status=QualificationStatus.INSUFFICIENT_EVIDENCE,
            reasons=[f"Missing for EMAIL_ATTRIBUTION: {', '.join(missing)}."],
            evidence_ids=evidence_ids,
        )

    # Explicit attribution of a non-generic personal email PASSes even when the
    # candidate also surfaced a generic/shared mailbox elsewhere (e.g. a company
    # contact page with info@) or a name-resembling local part — the existence
    # of an unrelated mailbox cannot unsay an explicit same-person attribution.
    for pattern in _ATTRIBUTION_PATTERNS:
        for match in pattern.finditer(combined):
            segment_email = _first_email(combined[match.start() : match.end()])
            if segment_email is None or _is_generic(segment_email):
                continue
            if allowed is not None and _email_host(segment_email) not in allowed:
                continue
            if _looks_name_like_local_part(segment_email) and not re.search(
                rf"{_NAME_RE}['’]s\s+email\s+is\s+{re.escape(segment_email)}|{_NAME_RE}\s*,\s*(?:the\s+)?{_ROLE_RE}\s*(?:[-—–:]\s*)*{re.escape(segment_email)}|{_NAME_RE}\s+(?:can\s+be\s+reached|reach(?:ed)?|contact(?:ed)?|email\s+is|e-mail\s+is)\b(?:.{{0,40}}?)\b{re.escape(segment_email)}\b",
                combined,
            ):
                continue
            return CriterionResult(
                criterion=_CRITERION,
                status=QualificationStatus.PASS,
                reasons=["The same person has a full name, a qualifying role, and an explicitly attributed personal email."],
                evidence_ids=evidence_ids,
            )

    # No explicitly attributed personal email: generic mailboxes, name-like
    # local parts without an explicit attribution, or nothing at all.
    if any(_is_generic(email) for email in emails):
        return CriterionResult(
            criterion=_CRITERION,
            status=QualificationStatus.INSUFFICIENT_EVIDENCE,
            reasons=["Generic or shared mailbox cannot be attributed to a single person."],
            evidence_ids=evidence_ids,
        )

    if any(_looks_name_like_local_part(email) for email in emails):
        return CriterionResult(
            criterion=_CRITERION,
            status=QualificationStatus.INSUFFICIENT_EVIDENCE,
            reasons=["Evidence names a person and role but does not explicitly attribute a non-generic personal email to that same person."],
            evidence_ids=evidence_ids,
        )

    return CriterionResult(
        criterion=_CRITERION,
        status=QualificationStatus.INSUFFICIENT_EVIDENCE,
        reasons=["Evidence names a person and role but does not explicitly attribute a non-generic personal email to that same person."],
        evidence_ids=evidence_ids,
    )


class EmailAttributionEvaluator:
    """Offline, deterministic EMAIL_ATTRIBUTION qualification evaluator."""

    criterion = _CRITERION

    @staticmethod
    def evaluate(
        evidence: Iterable[Evidence],
        company_hosts: Iterable[str] | None = None,
    ) -> CriterionResult:
        return evaluate_email_attribution(evidence, company_hosts=company_hosts)
