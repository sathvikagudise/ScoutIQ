"""Contact model for future CEO/co-founder research.

A person must be representable before any email is known. Emails are never
guessed; unknown details remain ``None``. Verification is a separate concern.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import VerificationStatus
from app.models.common import new_id, utcnow


class Contact(BaseModel):
    """A person associated with a company candidate."""

    contact_id: UUID = Field(default_factory=new_id)
    candidate_id: UUID
    full_name: str
    role: Optional[str] = None
    email: Optional[str] = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    created_at: datetime = Field(default_factory=utcnow)