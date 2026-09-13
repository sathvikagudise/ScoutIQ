"""Leadership name extraction — explicitly titled, publicly stated roles only."""

from __future__ import annotations

import re

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.extraction.support import corpus, snippet
from app.research.models import ResearchResult

_PEOPLE_RE = re.compile(
    # Right-anchored on the role marker: the person's name is the (up to) two
    # capitalized tokens immediately before the role. Capitalized phrases are
    # often glued to leading brand/label text by corpus flattening ("Delta
    # Software Robert Chen, Founder"); anchoring on the role keeps the name
    # to "Robert Chen" instead of greedily swallowing "Delta Software".
    r"\b(?:(?:[A-Z][a-zA-Z'’\-]+\.?)\s+)?([A-Z][a-zA-Z'’\-]+\.?)\s+([A-Z][a-zA-Z'’\-]+)"
    r"\s*(?:,\s*|\s+—\s*|\s+–\s*|\s+-\s*)"
    r"(Chief Executive Officer|CEO|Co-Founder|Co-founder|CoFounder|Founding CEO|"
    r"Founder & CEO|CEO & Founder|Founder)\b"
)

_ROLE_TYPE: dict[str, EvidenceType] = {
    "chief executive officer": EvidenceType.CEO,
    "ceo": EvidenceType.CEO,
    "founding ceo": EvidenceType.CEO,
    "ceo & founder": EvidenceType.CEO,
    "co-founder": EvidenceType.COFOUNDER,
    "cofounder": EvidenceType.COFOUNDER,
    "founder": EvidenceType.FOUNDER,
    "founder & ceo": EvidenceType.FOUNDER,
    "founding founder": EvidenceType.FOUNDER,
}

_FIELD_BY_TYPE = {
    EvidenceType.CEO: "ceo",
    EvidenceType.COFOUNDER: "cofounder",
    EvidenceType.FOUNDER: "founder",
}

# Words that mark a capitalized phrase as an organization or fund rather than a
# person (e.g. "Category Capital Strategy, Founder"). Such phrases must never
# become a leader contact.
_ORG_WORDS = frozenset(
    "capital group ventures strategy fund funds partners labs media studios "
    "holdings advisory investment accelerators incubators llc inc ltd gmbh co "
    "corp company companies startup startups platform"
    .split()
)


def _plausible_person_name(name: str) -> bool:
    tokens = re.findall(r"[A-Za-z]+", name)
    return not any(token.lower() in _ORG_WORDS for token in tokens)


def _classify_role(role: str) -> EvidenceType:
    lowered = role.lower().strip()
    if lowered.startswith("co-founder") or lowered.startswith("cofounder"):
        return EvidenceType.COFOUNDER
    if "founder" in lowered and "ceo" not in lowered:
        return EvidenceType.FOUNDER
    if lowered in ("chief executive officer", "ceo", "founding ceo", "ceo & founder"):
        return EvidenceType.CEO
    # Covers "founder & ceo": person is the founder.
    if "founder" in lowered:
        return EvidenceType.FOUNDER
    return EvidenceType.CEO


def extract_people(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """One leadership claim per explicit "Name, Role" mention.

    Only the explicitly stated role is recorded. The same person appearing in
    multiple places is deduplicated; ambition and inference never add a role.
    """
    claims: list[ExtractedClaim] = []
    seen: set[tuple[EvidenceType, str]] = set()
    source_url = research.final_url or research.source_url
    text = corpus(research)

    for match in _PEOPLE_RE.finditer(text):
        name = " ".join(" ".join(match.groups()[:2]).split())
        if not _plausible_person_name(name):
            continue
        role = _classify_role(match.group(3))
        key = (role, name.lower())
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            ExtractedClaim(
                claim_type=role,
                field=_FIELD_BY_TYPE[role],
                value=f"{name}, {match.group(3)}",
                normalized_value=match.group(3),
                context=f"text match ({snippet(text, match.start())})",
                source_url=source_url,
                source_title=source_title,
                confidence=0.7,
            )
        )
    return claims