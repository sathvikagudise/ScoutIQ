"""Phase 4 extraction contracts.

Extraction turns one 'researched' page into source-backed, individually
traceable claims (:class:`ExtractedClaim`) and an :class:`ExtractionResult`
that describes what was persisted. Like every phase before it:

    EXTRACTION != VERIFICATION != QUALIFICATION

A claim states that *some value appeared in a real source*. It never asserts
the value is true, and nothing is ever fabricated or guessed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import EvidenceType
from app.models.common import new_id, utcnow
from app.models.company import CompanyCandidate, CompanyProfile


class ExtractedClaim(BaseModel):
    """One source-backed observation about a company, ready for persistence."""

    claim_id: UUID = Field(default_factory=new_id)
    claim_type: EvidenceType
    field: str
    value: Optional[Any] = None
    normalized_value: Optional[Any] = None
    context: Optional[str] = None
    source_url: str
    source_title: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    extracted_at: datetime = Field(default_factory=utcnow)


class ExtractionResult(BaseModel):
    """Outcome of extracting (and persisting) a single researched page."""

    source_url: str
    source_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    candidate: Optional[CompanyCandidate] = None
    profile: Optional[CompanyProfile] = None
    claims: list[ExtractedClaim] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    created_candidate: bool = False
    skipped_reason: Optional[str] = None