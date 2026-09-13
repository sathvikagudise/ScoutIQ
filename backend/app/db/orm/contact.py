"""ORM: Contact record."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import VerificationStatus
from app.db.base import Base, enum_column


class ContactRecord(Base):
    __tablename__ = "contacts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_candidates.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_column(VerificationStatus), default=VerificationStatus.UNVERIFIED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)