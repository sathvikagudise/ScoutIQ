"""Activity feed event for the future live agent-execution UI."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import ActivityEventType, RunPhase
from app.models.common import new_id, utcnow


class ActivityEvent(BaseModel):
    """One event in a run's activity feed."""

    event_id: UUID = Field(default_factory=new_id)
    run_id: UUID
    timestamp: datetime = Field(default_factory=utcnow)
    phase: RunPhase
    event_type: ActivityEventType
    message: str
    related_candidate_id: Optional[UUID] = None
    related_source_id: Optional[UUID] = None