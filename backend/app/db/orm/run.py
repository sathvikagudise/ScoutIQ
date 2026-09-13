"""ORM: DiscoveryRun and SearchQuery records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RunPhase, RunStatus
from app.db.base import Base, enum_column


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(Uuid, nullable=True, index=True)
    status: Mapped[RunStatus] = mapped_column(enum_column(RunStatus), default=RunStatus.PENDING)
    target_lead_count: Mapped[int] = mapped_column(Integer, default=10)
    qualified_lead_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_phase: Mapped[Optional[RunPhase]] = mapped_column(enum_column(RunPhase, nullable=True))
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    queries: Mapped[list[QueryRecord]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["CompanyCandidateRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    activities: Mapped[list["ActivityRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    leads: Mapped[list["LeadRecord"]] = relationship(back_populates="run")


class QueryRecord(Base):
    __tablename__ = "search_queries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    query_text: Mapped[str] = mapped_column(String)
    strategy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    run: Mapped[RunRecord] = relationship(back_populates="queries")