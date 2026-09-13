"""ORM: Evidence record."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import EvidenceType
from app.db.base import Base, enum_column


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_candidates.id", ondelete="CASCADE"), index=True
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(enum_column(EvidenceType))
    claim: Mapped[str] = mapped_column(String)
    extracted_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    source_url: Mapped[str] = mapped_column(String)
    source_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime)
    supporting_context: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )