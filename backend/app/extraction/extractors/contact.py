"""Contact detail extraction — emails shown on the page, never attributed."""

from __future__ import annotations

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.research.models import ResearchResult


def extract_contact_details(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """One claim per visible email address.

    Emails carry no person attribution: a name next to an email is *not*
    evidence that the email belongs to that person. Verification status stays
    UNVERIFIED by construction.
    """
    claims: list[ExtractedClaim] = []
    source_url = research.final_url or research.source_url

    for email in research.emails:
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.EMAIL,
                field="email",
                value=email.email,
                normalized_value=email.email,
                context=email.context or "email visible on page",
                source_url=source_url,
                source_title=source_title,
            )
        )
    return claims