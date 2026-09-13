"""Visible text extraction.

Removes script/style/noscript/navigation boilerplate and comments, then
normalizes whitespace while keeping readable paragraph boundaries. The soup is
parsed on a copy so this extractor never mutates the caller's tree.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment

REMOVE_TAGS = ("script", "style", "noscript", "nav")

BLOCK_TAGS = (
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "ol", "p", "pre", "section", "table", "td",
    "th", "tr", "ul",
)

_WHITESPACE_RE = re.compile(r"[ \t\xa0]+")


def extract_visible_text(soup: BeautifulSoup) -> str:
    working = BeautifulSoup(str(soup), "html.parser")

    for tag in working.find_all(REMOVE_TAGS):
        tag.decompose()
    for node in working.find_all(string=lambda text: isinstance(text, Comment)):
        node.extract()

    for block in working.find_all(BLOCK_TAGS):
        block.append("\n")

    # get_text with a space separator unions adjacent nodes; newlines appended
    # to block elements become paragraph boundaries.
    return _normalize_lines(working.get_text(" "))


def _normalize_lines(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        collapsed = _WHITESPACE_RE.sub(" ", line).strip()
        if collapsed:
            lines.append(collapsed)
    return "\n".join(lines)