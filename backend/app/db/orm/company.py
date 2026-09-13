"""ORM: Company candidate, profile, and qualified lead records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Table, Uuid, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CandidateStatus, ContactReadiness
from app.db.base import Base, enum_column

company_candidate_sources = Table(
    "company_candidate_sources",
    Base.metadata,
    Column(
        "candidate_id",
        Uuid,
        ForeignKey("company_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_id", Uuid, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    ),
)


class CompanyCandidateRecord(Base):
    __tablename__ = "company_candidates"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String)
    official_website: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[CandidateStatus] = mapped_column(
        enum_column(CandidateStatus), default=CandidateStatus.DISCOVERED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    run: Mapped["RunRecord"] = relationship(back_populates="candidates")
    sources: Mapped[list["SourceRecord"]] = relationship(secondary=company_candidate_sources)
    profile: Mapped[Optional["CompanyProfileRecord"]] = relationship(
        back_populates="candidate", uselist=False, cascade="all, delete-orphan"
    )


class CompanyProfileRecord(Base):
    __tablename__ = "company_profiles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_candidates.id", ondelete="CASCADE"), unique=True
    )
    company_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    official_website: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    industry_or_sector: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    primary_location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    funding_amount_usd: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revenue_amount_usd: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    candidate: Mapped[CompanyCandidateRecord] = relationship(back_populates="profile")


class LeadRecord(Base):
    __tablename__ = "leads"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("company_candidates.id", ondelete="CASCADE"), index=True
    )
    company_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    industry_or_sector: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ceo_or_cofounder_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact_readiness: Mapped[Optional[ContactReadiness]] = mapped_column(
        enum_column(ContactReadiness, nullable=True), nullable=True
    )
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    qualification_id: Mapped[Optional[UUID]] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    run: Mapped["RunRecord"] = relationship(back_populates="leads")