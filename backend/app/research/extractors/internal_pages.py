"""Deterministic classification of potentially useful internal pages.

Pure keyword/path heuristics over the page's internal links — no AI, no
external APIs, no site-specific hardcoding. Categories resolve in a fixed
priority order so results are reproducible.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.research.models import ExtractedLink, InternalPage, InternalPageCategory

# Priority order matters: the first matching category wins.
_PATH_RULES: tuple[tuple[frozenset[str], InternalPageCategory], ...] = (
    (frozenset({"founder", "founders"}), InternalPageCategory.FOUNDERS),
    (frozenset({"leadership"}), InternalPageCategory.LEADERSHIP),
    (frozenset({"team", "our-team", "ourteam"}), InternalPageCategory.TEAM),
    (frozenset({"contact", "contact-us", "contactus", "contacts"}), InternalPageCategory.CONTACT),
    (
        frozenset({
            "press", "press-room", "pressroom", "press-release", "press-releases",
            "newsroom", "media", "media-center", "mediacentre", "in-the-news",
        }),
        InternalPageCategory.PRESS_NEWS,
    ),
    (frozenset({"news"}), InternalPageCategory.PRESS_NEWS),
    (frozenset({"blog", "blogs"}), InternalPageCategory.BLOG),
    (frozenset({"about", "about-us", "aboutus"}), InternalPageCategory.ABOUT),
    (frozenset({"company"}), InternalPageCategory.COMPANY),
)

_ANCHOR_WORDS: tuple[tuple[frozenset[str], InternalPageCategory], ...] = (
    (frozenset({"founder", "founders"}), InternalPageCategory.FOUNDERS),
    (frozenset({"leadership", "leaders"}), InternalPageCategory.LEADERSHIP),
    (frozenset({"team"}), InternalPageCategory.TEAM),
    (frozenset({"contact", "contact-us"}), InternalPageCategory.CONTACT),
    (
        frozenset({"press", "press-releases", "newsroom", "media", "in-the-news", "news"}),
        InternalPageCategory.PRESS_NEWS,
    ),
    (frozenset({"blog"}), InternalPageCategory.BLOG),
    (frozenset({"about", "about-us", "who-we-are"}), InternalPageCategory.ABOUT),
    (frozenset({"company"}), InternalPageCategory.COMPANY),
)


def classify_internal_pages(links: list[ExtractedLink]) -> list[InternalPage]:
    pages: dict[str, InternalPage] = {}

    for link in links:
        if not link.is_internal:
            continue
        category = _classify(link)
        if category is None:
            continue
        pages.setdefault(
            link.resolved_url,
            InternalPage(url=link.resolved_url, anchor_text=link.anchor_text, category=category),
        )

    return [pages[key] for key in sorted(pages)]


def _classify(link: ExtractedLink) -> InternalPageCategory | None:
    path = urlparse(link.resolved_url).path.lower()
    segments = {segment for segment in path.split("/") if segment}

    for signals, category in _PATH_RULES:
        if segments & signals or any(f"/{signal}" in path for signal in signals):
            return category

    words = set(link.anchor_text.lower().split())
    for signals, category in _ANCHOR_WORDS:
        if words & signals:
            return category

    return None