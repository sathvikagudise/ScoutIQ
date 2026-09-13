"""ORM: ContactEnrichment record."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ContactReadiness
from app.db.base import Base, enum_column


class ContactEnrichmentRecord(Base):
    __tablename__ = "contact_enrichments"

    candidate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_candidates.id", ondelete="CASCADE"), primary_key=True
    )
    readiness: Mapped[ContactReadiness] = mapped_column(enum_column(ContactReadiness))
    named_contact_count: Mapped[int] = mapped_column(Integer, default=0)
    public_email_count: Mapped[int] = mapped_column(Integer, default=0)
    contact_page_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)