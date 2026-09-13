"""HTML parsing helpers for research fetches.

Parsing is kept separate from extraction: this module decides whether a
``FetchRecord`` can be parsed as HTML and builds the parse tree. Extractors
(the ``extractors`` package) consume that tree.
"""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup

from app.research.models import FetchRecord

HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def content_type_is_html(content_type: Optional[str]) -> bool:
    """Whether a response content type is supported for parsing.

    A missing content type is treated leniently (attempts a best-effort
    parse); an explicit non-HTML type rejects parsing.
    """
    if content_type is None:
        return True
    media = content_type.split(";", 1)[0].strip().lower()
    return media in HTML_CONTENT_TYPES or media.endswith("/html")


def parse_html(record: FetchRecord) -> Optional[BeautifulSoup]:
    """Parse an HTML body into a BeautifulSoup tree (``None`` if no body)."""
    if not record.body:
        return None
    return BeautifulSoup(record.body, "html.parser")