"""Qualification decision models (contract only — rules come in a later phase)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import QualificationCriterion, QualificationStatus
from app.models.common import new_id, utcnow


class CriterionResult(BaseModel):
    """Decision for one independent qualification criterion."""

    criterion: QualificationCriterion
    status: QualificationStatus = QualificationStatus.NOT_EVALUATED
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str | UUID] = Field(default_factory=list)


class QualificationResult(BaseModel):
    """Full qualification decision for a candidate.

    Partial evidence is representable: individual criteria can be
    ``INSUFFICIENT_EVIDENCE`` while the overall status remains
    ``NOT_EVALUATED``. A result must never silently become PASS.
    """

    qualification_id: UUID = Field(default_factory=new_id)
    candidate_id: str | UUID
    criteria: list[CriterionResult] = Field(default_factory=list)
    overall_status: QualificationStatus = QualificationStatus.NOT_EVALUATED
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str | UUID] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=utcnow)