"""Metadata extraction: title, description, canonical, Open Graph fields.

All fields are optional — absent values stay ``None``. Nothing is guessed or
fabricated.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.research.attrtext import attr_text
from app.research.models import PageMetadata


def _rel_contains(value) -> bool:
    values = value if isinstance(value, list) else [value]
    return any(str(item).lower() == "canonical" for item in values)


def extract_metadata(soup: BeautifulSoup) -> PageMetadata:
    title = soup.title.get_text(strip=True) if soup.title else None

    meta_description = None
    canonical_url = None
    og_title = None
    og_description = None
    og_site_name = None

    for tag in soup.find_all("meta"):
        attrs = {key.lower(): (attr_text(value) or "").strip() for key, value in tag.attrs.items()}
        if attrs.get("charset"):
            continue
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content")
        if content is None:
            continue
        if name in ("description", "twitter:description") and meta_description is None:
            meta_description = content
        elif name == "og:title" and og_title is None:
            og_title = content
        elif name == "og:description" and og_description is None:
            og_description = content
        elif name == "og:site_name" and og_site_name is None:
            og_site_name = content

    canonical = soup.find("link", rel=_rel_contains)
    if canonical is not None:
        canonical_url = attr_text(canonical.get("href")).strip() or None

    return PageMetadata(
        title=title or None,
        meta_description=meta_description or None,
        canonical_url=canonical_url,
        og_title=og_title or None,
        og_description=og_description or None,
        og_site_name=og_site_name or None,
    )