"""Deterministic, offline CONTACT_AVAILABILITY evaluator (CONTACT dimension).

The CONTACT dimension describes what publicly evidenced contact information a
company-qualified candidate has. It NEVER drives the company qualification
decision (Funding/Revenue, Tech Platform, US Presence) and NEVER verifies email
deliverability: ``EVIDENCED_CONTACT`` means a source page explicitly attributes
that email to the named leader, not that the address has been checked via
SMTP/MX.

The evaluator is a pure decision function over derivable signals. It NEVER
touches the network and NEVER invents a name, email, or URL. The same inputs
always produce the same decision.

Decisions
---------
PASS
    At least one contact signal exists (readiness is anything other than
    ``NO_CONTACT_FOUND``): an evidence-backed named leader with an attributed
    email, a named leader without an email, an own-domain public email, or a
    discovered company contact channel (contact page URL / LinkedIn URL /
    public official-website homepage).

INSUFFICIENT_EVIDENCE
    No contact signal at all (``NO_CONTACT_FOUND``).
"""

from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from app.core.enums import ContactReadiness, QualificationCriterion, QualificationStatus
from app.models.qualification import CriterionResult

_CRITERION = QualificationCriterion.CONTACT_AVAILABILITY

# Fixed best-first readiness priority (single source of truth).
_REASON_BY_READINESS = {
    ContactReadiness.EVIDENCED_CONTACT: (
        "A named leader has an evidence-attributed email."
    ),
    ContactReadiness.NAMED_CONTACT_NO_EMAIL: (
        "A named leader is evidenced, but no email is explicitly attributed to them."
    ),
    ContactReadiness.PUBLIC_EMAIL_AVAILABLE: (
        "An own-domain public email is available but is not explicitly attributed "
        "to a named leader."
    ),
    ContactReadiness.COMPANY_CONTACT_AVAILABLE: (
        "Company contact channels are available (contact page / LinkedIn / "
        "official website)."
    ),
    ContactReadiness.NO_CONTACT_FOUND: (
        "No public contact evidence found for the candidate."
    ),
}


def derive_contact_readiness(
    *,
    named_contact_count: int = 0,
    evidenced_contact_email_count: int = 0,
    public_email_count: int = 0,
    has_contact_page_url: bool = False,
    has_linkedin_url: bool = False,
    has_own_site: bool = False,
) -> ContactReadiness:
    """Deterministic readiness label under the fixed best-first priority."""
    if evidenced_contact_email_count > 0:
        return ContactReadiness.EVIDENCED_CONTACT
    if named_contact_count > 0:
        return ContactReadiness.NAMED_CONTACT_NO_EMAIL
    if public_email_count > 0:
        return ContactReadiness.PUBLIC_EMAIL_AVAILABLE
    if has_contact_page_url or has_linkedin_url or has_own_site:
        return ContactReadiness.COMPANY_CONTACT_AVAILABLE
    return ContactReadiness.NO_CONTACT_FOUND


class ContactAvailabilityEvaluator:
    """Offline, deterministic CONTACT_AVAILABILITY evaluator (contact dimension)."""

    criterion = _CRITERION

    @staticmethod
    def evaluate(
        evidence_ids: Iterable[str | UUID] | None = None,
        *,
        named_contact_count: int = 0,
        evidenced_contact_email_count: int = 0,
        public_email_count: int = 0,
        contact_page_url: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        has_own_site: bool = False,
    ) -> CriterionResult:
        """Decide CONTACT_AVAILABILITY from derivable, persisted signals."""
        readiness = derive_contact_readiness(
            named_contact_count=named_contact_count,
            evidenced_contact_email_count=evidenced_contact_email_count,
            public_email_count=public_email_count,
            has_contact_page_url=bool(contact_page_url),
            has_linkedin_url=bool(linkedin_url),
            has_own_site=has_own_site,
        )
        status = (
            QualificationStatus.PASS
            if readiness is not ContactReadiness.NO_CONTACT_FOUND
            else QualificationStatus.INSUFFICIENT_EVIDENCE
        )
        return CriterionResult(
            criterion=_CRITERION,
            status=status,
            reasons=[_REASON_BY_READINESS[readiness]],
            evidence_ids=list(evidence_ids or []),
        )