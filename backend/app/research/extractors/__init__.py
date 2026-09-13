"""Research extractors — each one is a pure, deterministic function over HTML."""

from app.research.extractors.emails import ExtractedEmail, extract_emails
from app.research.extractors.internal_pages import (
    InternalPage,
    InternalPageCategory,
    classify_internal_pages,
)
from app.research.extractors.links import ExtractedLink, extract_links
from app.research.extractors.metadata import PageMetadata, extract_metadata
from app.research.extractors.text import extract_visible_text

__all__ = [
    "ExtractedEmail",
    "extract_emails",
    "InternalPage",
    "InternalPageCategory",
    "classify_internal_pages",
    "ExtractedLink",
    "extract_links",
    "PageMetadata",
    "extract_metadata",
    "extract_visible_text",
]