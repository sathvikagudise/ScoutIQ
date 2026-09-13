"""Company candidate and profile models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import CandidateStatus
from app.models.common import new_id, utcnow


class CompanyCandidate(BaseModel):
    """A discovered company that has not yet been qualified."""

    candidate_id: UUID = Field(default_factory=new_id)
    run_id: UUID
    company_name: str
    official_website: Optional[str] = None
    discovery_source_ids: list[UUID] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.DISCOVERED
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CompanyProfile(BaseModel):
    """Accumulated, unadjudicated company information.

    Represents what has been *collected* — it is not a qualification decision.
    Unknown values stay ``None``; nothing may be guessed.
    """

    profile_id: UUID = Field(default_factory=new_id)
    candidate_id: UUID
    company_name: Optional[str] = None
    official_website: Optional[str] = None
    description: Optional[str] = None
    industry_or_sector: Optional[str] = None
    primary_location: Optional[str] = None
    funding_amount_usd: Optional[int] = None
    revenue_amount_usd: Optional[int] = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)