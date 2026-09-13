"""ORM: Source record."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FetchStatus
from app.db.base import Base, enum_column


class SourceRecord(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    url: Mapped[str] = mapped_column(String)
    normalized_url: Mapped[Optional[str]] = mapped_column(
        String, unique=True, nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String)
    snippet: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    discovered_at: Mapped[datetime] = mapped_column(DateTime)
    fetch_status: Mapped[Optional[FetchStatus]] = mapped_column(enum_column(FetchStatus, nullable=True))
    http_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discovered_by_query_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid, ForeignKey("search_queries.id", ondelete="SET NULL"), nullable=True
    )