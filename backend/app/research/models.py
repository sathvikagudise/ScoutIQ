"""Phase 3 research contracts — structured page-fetch and extraction output.

These models describe *what was observed and extracted* from a single web
page. They never assert that an extracted value is true:

    EXTRACTION != VERIFICATION

An extracted email carries ``VerificationStatus.UNVERIFIED`` and extracted
metadata is always optional — nothing is fabricated.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import FetchStatus, VerificationStatus
from app.models.common import utcnow


class InternalPageCategory(StrEnum):
    """Deterministic classification of a potentially useful internal page."""

    ABOUT = "about"
    TEAM = "team"
    LEADERSHIP = "leadership"
    FOUNDERS = "founders"
    CONTACT = "contact"
    COMPANY = "company"
    PRESS_NEWS = "press_news"
    BLOG = "blog"


class FetchRecord(BaseModel):
    """Outcome of fetching a single URL, including its (bounded) body."""

    url: str
    fetch_status: FetchStatus
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    content_type: Optional[str] = None
    error: Optional[str] = None
    body: Optional[str] = None


class PageMetadata(BaseModel):
    """Optional page-level metadata. Absent values stay ``None``."""

    title: Optional[str] = None
    meta_description: Optional[str] = None
    canonical_url: Optional[str] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_site_name: Optional[str] = None


class ExtractedLink(BaseModel):
    """A hyperlink found on the page."""

    original_href: str
    resolved_url: str
    anchor_text: str = ""
    is_internal: bool = False


class ExtractedEmail(BaseModel):
    """A publicly visible email found on the page — never a verified one."""

    email: str
    context: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class InternalPage(BaseModel):
    """An internal page likely worth visiting during future research."""

    url: str
    anchor_text: str = ""
    category: InternalPageCategory


class ResearchResult(BaseModel):
    """Structured output of researching one URL.

    ``html_extracted`` is ``False`` (with an ``extraction_skip_reason``) when
    the fetch failed or the response was not HTML.
    """

    source_url: str
    final_url: Optional[str] = None
    fetch_status: Optional[FetchStatus] = None
    http_status_code: Optional[int] = None
    content_type: Optional[str] = None
    html_extracted: bool = False
    extraction_skip_reason: Optional[str] = None
    metadata: PageMetadata = Field(default_factory=PageMetadata)
    visible_text: Optional[str] = None
    links: list[ExtractedLink] = Field(default_factory=list)
    emails: list[ExtractedEmail] = Field(default_factory=list)
    relevant_internal_pages: list[InternalPage] = Field(default_factory=list)
    researched_at: datetime = Field(default_factory=utcnow)
    error: Optional[str] = None