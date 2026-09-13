"""ORM: Qualification result and criterion records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import QualificationCriterion, QualificationStatus
from app.db.base import Base, enum_column


class QualificationRecord(Base):
    __tablename__ = "qualification_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_candidates.id", ondelete="CASCADE"), index=True
    )
    overall_status: Mapped[QualificationStatus] = mapped_column(
        enum_column(QualificationStatus), default=QualificationStatus.NOT_EVALUATED
    )
    reasons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime)

    criteria: Mapped[list[CriterionRecord]] = relationship(
        back_populates="qualification", cascade="all, delete-orphan"
    )


class CriterionRecord(Base):
    __tablename__ = "qualification_criteria"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    qualification_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("qualification_results.id", ondelete="CASCADE"), index=True
    )
    criterion: Mapped[QualificationCriterion] = mapped_column(enum_column(QualificationCriterion))
    status: Mapped[QualificationStatus] = mapped_column(enum_column(QualificationStatus))
    reasons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)

    qualification: Mapped[QualificationRecord] = relationship(back_populates="criteria")