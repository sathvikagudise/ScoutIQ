"""Link extraction: resolve relative URLs, classify internal/external, dedup.

No recursive crawling happens in this phase — links are only extracted.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.research.attrtext import attr_text
from app.research.models import ExtractedLink

IGNORED_SCHEMES = frozenset({"mailto", "tel", "javascript", "data", "ftp", "file"})


def extract_links(soup: BeautifulSoup, base_url: str) -> list[ExtractedLink]:
    base_host = (urlparse(base_url).hostname or "").lower()
    links: dict[str, ExtractedLink] = {}

    for anchor in soup.find_all("a", href=True):
        href = attr_text(anchor.get("href")).strip()
        if not href or href.startswith("#"):
            continue
        if urlparse(href).scheme.lower() in IGNORED_SCHEMES:
            continue

        resolved = urljoin(base_url, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue

        clean = resolved.split("#", 1)[0]
        if not clean or clean in links:
            continue

        is_internal = (parsed.hostname or "").lower() == base_host
        links[clean] = ExtractedLink(
            original_href=href,
            resolved_url=clean,
            anchor_text=anchor.get_text(" ", strip=True),
            is_internal=is_internal,
        )

    return list(links.values())