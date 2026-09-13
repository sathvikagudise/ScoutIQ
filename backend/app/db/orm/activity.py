"""ORM: Activity event record."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActivityEventType, RunPhase
from app.db.base import Base, enum_column


class ActivityRecord(Base):
    __tablename__ = "activity_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    phase: Mapped[RunPhase] = mapped_column(enum_column(RunPhase))
    event_type: Mapped[ActivityEventType] = mapped_column(enum_column(ActivityEventType))
    message: Mapped[str] = mapped_column(String)
    related_candidate_id: Mapped[Optional[UUID]] = mapped_column(Uuid, nullable=True)
    related_source_id: Mapped[Optional[UUID]] = mapped_column(Uuid, nullable=True)

    run: Mapped["RunRecord"] = relationship(back_populates="activities")