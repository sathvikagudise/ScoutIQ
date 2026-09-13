"""Run lifecycle and search-attempt models (agent memory groundwork)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import RunPhase, RunStatus
from app.models.common import new_id, utcnow


class DiscoveryRun(BaseModel):
    """One autonomous execution, representing the full future agent lifecycle."""

    run_id: UUID = Field(default_factory=new_id)
    user_id: Optional[UUID] = None
    status: RunStatus = RunStatus.PENDING
    target_lead_count: int = Field(default=10, ge=0)
    qualified_lead_count: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None
    current_phase: Optional[RunPhase] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchQuery(BaseModel):
    """A recorded search attempt, for future agent memory/adaptive strategies."""

    query_id: UUID = Field(default_factory=new_id)
    run_id: UUID
    query_text: str
    strategy: Optional[str] = None
    provider: Optional[str] = None
    executed_at: datetime = Field(default_factory=utcnow)
    result_count: int = Field(default=0, ge=0)
    error: Optional[str] = None