"""Contact-enrichment model — the contact readiness of a company candidate.

Computed ONLY from persisted, evidenced data. Nothing is guessed: no name
inference, no email construction, no URL fabrication. Channel URLs
(``contact_page_url``, ``linkedin_url``) are populated only with URLs the
research/extraction pipeline actually discovered; the counts come from
persisted contact and evidence rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import ContactReadiness
from app.models.common import utcnow


class ContactEnrichment(BaseModel):
    """One row of contact-readiness state per company candidate."""

    candidate_id: UUID
    readiness: ContactReadiness = ContactReadiness.NO_CONTACT_FOUND
    named_contact_count: int = 0
    public_email_count: int = 0
    contact_page_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)