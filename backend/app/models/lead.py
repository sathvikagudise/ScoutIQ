"""Qualified lead model — the future TVB-facing output."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import ContactReadiness
from app.models.common import new_id, utcnow


class QualifiedLead(BaseModel):
    """A fully qualified lead.

    ``verified_email`` is optional by design: the system must never invent a
    value, and a lead can exist while verification is still pending.
    ``contact_readiness`` (when present) is the persisted contact-enrichment
    label for the candidate; legacy/company-qualified-without-enrichment leads
    leave it ``None``.
    """

    lead_id: UUID = Field(default_factory=new_id)
    run_id: UUID = Field(default_factory=new_id)
    candidate_id: UUID
    company_name: str
    description: Optional[str] = None
    industry_or_sector: Optional[str] = None
    ceo_or_cofounder_name: Optional[str] = None
    verified_email: Optional[str] = None
    contact_readiness: Optional[ContactReadiness] = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    qualification_id: Optional[UUID] = None
    created_at: datetime = Field(default_factory=utcnow)