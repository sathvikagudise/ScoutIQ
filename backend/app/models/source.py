"""Unified web source and fetch-validation models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import FetchStatus
from app.models.common import new_id, utcnow


class Source(BaseModel):
    """A web source, whether discovered by a query or researched later."""

    source_id: UUID = Field(default_factory=new_id)
    url: str
    normalized_url: Optional[str] = None
    title: str
    snippet: Optional[str] = None
    domain: Optional[str] = None
    provider: str
    discovered_at: datetime = Field(default_factory=utcnow)
    fetch_status: Optional[FetchStatus] = None
    http_status_code: Optional[int] = None
    final_url: Optional[str] = None
    content_type: Optional[str] = None
    discovered_by_query_id: Optional[UUID] = None


class FetchValidation(BaseModel):
    """Outcome of a single HTTP validation attempt against a URL."""

    url: str
    status_code: Optional[int] = None
    final_url: str
    reachable: bool
    content_type: Optional[str] = None
    error: Optional[str] = None
    fetch_status: FetchStatus = FetchStatus.UNKNOWN_ERROR