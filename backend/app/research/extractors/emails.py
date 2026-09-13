"""Public email extraction — discovery only, never verification.

Emails are collected from visible text and ``mailto:`` links, normalized,
deduplicated, and syntax-checked. Every result is explicitly
``VerificationStatus.UNVERIFIED``: nothing is guessed, inferred from domains,
or attributed to a person/role.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.core.enums import VerificationStatus
from app.research.attrtext import attr_text
from app.research.models import ExtractedEmail

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

_CONTEXT_RADIUS = 45


def extract_emails(soup: BeautifulSoup) -> list[ExtractedEmail]:
    full_text = soup.get_text(" ")
    found: dict[str, str | None] = {}

    for match in EMAIL_RE.finditer(full_text):
        email = _normalize_email(match.group(0))
        if email and _is_plausible(email) and email not in found:
            found[email] = _snippet(full_text, match.start())

    for anchor in soup.find_all("a", href=True):
        href = attr_text(anchor.get("href")).strip()
        if not href.lower().startswith("mailto:"):
            continue
        target = href[7:].split("?", 1)[0].replace(" ", "").strip()
        email = _normalize_email(target)
        if email and _is_plausible(email) and email not in found:
            found[email] = anchor.get_text(" ", strip=True) or None

    def _entry(item: tuple[str, str | None]) -> ExtractedEmail:
        email, context = item
        return ExtractedEmail(
            email=email,
            context=context,
            verification_status=VerificationStatus.UNVERIFIED,
        )

    return [_entry(item) for item in sorted(found.items())]


def _normalize_email(raw: str) -> str | None:
    email = raw.strip().rstrip(".").lower()
    if not EMAIL_RE.fullmatch(email):
        return None
    return email


def _is_plausible(email: str) -> bool:
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    if ".." in email or email.startswith(".") or email.endswith("."):
        return False
    if urlparse(f"//{domain}").hostname is None:
        return False
    return True


def _snippet(text: str, index: int) -> str | None:
    start = max(0, index - _CONTEXT_RADIUS)
    end = index + _CONTEXT_RADIUS
    return " ".join(text[start:end].split()) or None