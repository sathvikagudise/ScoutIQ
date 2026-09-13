"""Phase 4 candidate extraction service — claims, identity, evidence, profile."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import EvidenceType
from app.extraction.extractors import run_all_extractors
from app.extraction.identity import find_existing_candidate
from app.extraction.models import ExtractedClaim, ExtractionResult
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.evidence import Evidence
from app.models.run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.run_repository import RunRepository
from app.research.models import ResearchResult

_PROFILE_FIELDS = (
    "company_description",
    "industry_or_sector",
    "primary_location",
    "funding_amount_usd",
    "revenue_amount_usd",
)

# Money and location claims report their parseable value in
# ``normalized_value`` (whole USD figure / plain place name); the profile never
# stores the base-verb phrasing ("headquartered in Berlin") as a location.
_MONEY_FIELDS = {"funding_amount_usd", "revenue_amount_usd"}
_LOCATION_FIELDS = {"primary_location"}
_NORMALIZED_FIELDS = _MONEY_FIELDS | _LOCATION_FIELDS

# Claim types that only count for this candidate when the claim text ties the
# observation back to the candidate itself. Cross-source listings (crunches,
# news round-ups, aggregator/market pages) routinely describe OTHER companies'
# funding rounds, platforms, locations, and leadership in the same page, so a
# bare claim from that context is never treated as the candidate's own.
_SCOPED_CLAIM_TYPES = {
    EvidenceType.FUNDING,
    EvidenceType.REVENUE,
    EvidenceType.LOCATION,
    EvidenceType.US_PRESENCE,
    EvidenceType.PLATFORM,
    EvidenceType.CEO,
    EvidenceType.COFOUNDER,
    EvidenceType.FOUNDER,
}

# Leadership claims need a person+role; only own-site pages (team/about/contact)
# may state them without re-naming the candidate. External leadership claims
# must name the candidate in the claim text.
_LEADERSHIP_CLAIM_TYPES = {EvidenceType.CEO, EvidenceType.COFOUNDER, EvidenceType.FOUNDER}

# Words too generic to discriminate whose claim an observation is.
_GENERIC_NAME_TOKENS = frozenset(
    {
        "software", "technologies", "technology", "solutions", "systems",
        "platform", "group", "holdings", "limited", "company", "companies",
        "startup", "startups", "capital", "ventures", "incorporation",
        "funding", "revenue", "location", "website", "industry", "candidate",
        "evidence", "contact", "signals", "signal",
    }
)

# First-person nominals that establish a page is speaking about itself. Rarer
# on third-party listings than a company name; kept deliberately narrow so
# aggregate "London startup raised $3m" round-ups are NOT retained.
_FIRST_PERSON_MARKERS = ("we ", "our ", "us ", "the company")

# A leadership line can name the leader's affiliation explicitly ("CEO of
# X"). Affiliations that clearly point at some OTHER organization mean the
# person is not the candidate's leader even on a same-site page (a publisher's
# article, for example). Self-referential phrasings are not foreign.
_AFFILIATION_RE = re.compile(
    r"\b(?:ceo|chief\s+executive\s+officer|cto|founder|co-?founder|president|"
    r"managing\s+director)\s+(?:of|at)\s+([a-z@][a-z0-9 &.'-]{2,40})",
    re.IGNORECASE,
)
_SELF_MENTION_ORGS = {"the company", "our company", "the startup", "the firm"}


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower() if host else None


def _normalized_host(host: str | None) -> str | None:
    """''``www.`` prefix so acme.example.com == www.acme.example.com."""
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def own_site_host(candidate: CompanyCandidate) -> str | None:
    """The candidate's own-site host, or None when no identity-homepage is known.

    A canonical pointing at a *homepage* (empty or ``/`` path) is the company's
    own site; a canonical with a deep path (an article, a post, a listing) is
    someone else's page about the company and does NOT count as the company's
    site. The gate matters: attributed emails may only be trusted as the
    leader's personal work address when they sit on the candidate's own domain.
    """
    site = candidate.official_website
    if not site:
        return None
    parsed = urlparse(site)
    path = parsed.path or ""
    if path not in ("", "/"):
        return None
    return _normalized_host(parsed.hostname)


def _significant_name_tokens(name: str | None) -> list[str]:
    """Discriminative tokens of a company name (len>=5, not filler words)."""
    if not name:
        return []
    tokens: list[str] = []
    for token in name.lower().split():
        cleaned = "".join(ch for ch in token if ch.isalnum())
        if len(cleaned) >= 5 and cleaned not in _GENERIC_NAME_TOKENS:
            if cleaned not in tokens:
                tokens.append(cleaned)
    return tokens


def _claim_text(claim: ExtractedClaim) -> str:
    return " ".join(
        f"{claim.context or ''} {claim.source_title or ''}".lower().split()
    )


def _claims_foreign_affiliation(candidate: CompanyCandidate, text: str) -> bool:
    """True when the text ties a leadership role to some other organization."""
    match = _AFFILIATION_RE.search(text)
    if not match:
        return False
    org = match.group(1).strip().rstrip(".")
    if not org or org.lower() in _SELF_MENTION_ORGS:
        return False
    name = (candidate.company_name or "").lower().strip()
    if name and name in org.lower():
        return False
    return not any(token in org.lower() for token in _significant_name_tokens(name))


def claim_is_candidate_scoped(
    candidate: CompanyCandidate, claim: ExtractedClaim, current_page_url: str | None = None
) -> bool:
    """Whether a claim's text ties the observation back to the candidate.

    Claims of types that decide qualification (money, platform, location, and
    leadership) survive only when their text names the candidate, uses a
    first-person voice (the page speaking about itself), or — for leadership —
    comes from the candidate's own site. Claims extracted from benign third-
    party context (round-ups, category menus, other companies) are dropped
    before they can tip any criterion.
    """
    if claim.claim_type not in _SCOPED_CLAIM_TYPES:
        return True

    text = _claim_text(claim)
    name = (candidate.company_name or "").lower().strip()
    named = bool(name) and (
        name in text or any(token in text for token in _significant_name_tokens(name))
    )

    if claim.claim_type in _LEADERSHIP_CLAIM_TYPES:
        same_site = bool(candidate.official_website) and _hostname(
            claim.source_url
        ) == _hostname(candidate.official_website)
        if same_site and _claims_foreign_affiliation(candidate, text):
            return False
        return named or same_site

    return named or any(marker in text for marker in _FIRST_PERSON_MARKERS)


def _single_consistent_value(claims: list[ExtractedClaim], field: str):
    """A field's value only when every source agrees on exactly one value.

    Money claims report the parsed USD figure (``normalized_value``) and
    location claims the plain place name so the magnitude/place survives; all
    other fields use the extracted value itself.
    """
    attribute = "normalized_value" if field in _NORMALIZED_FIELDS else "value"
    values = [getattr(claim, attribute, None) for claim in claims if claim.field == field]
    values = [value for value in values if value is not None]
    unique: list = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else None


class CandidateExtractionService:
    """Extract claims from a researched page, then persist candidate + evidence."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.company_repo = CompanyRepository(db)
        self.evidence_repo = EvidenceRepository(db)
        self.run_repo = RunRepository(db)

    def extract_claims(
        self, research: ResearchResult, source_title: str | None = None
    ) -> list[ExtractedClaim]:
        return run_all_extractors(research, source_title=source_title)

    def _ensure_run(self, run_id: Optional[UUID]) -> UUID:
        if run_id is not None:
            return run_id
        run = self.run_repo.create(DiscoveryRun(target_lead_count=0))
        return run.run_id

    def extract_and_persist(
        self,
        research: ResearchResult,
        *,
        run_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        source_title: str | None = None,
    ) -> ExtractionResult:
        source_url = research.final_url or research.source_url
        claims = self.extract_claims(research, source_title=source_title)

        company_claims = [claim for claim in claims if claim.field == "company_name"]
        if not company_claims:
            return ExtractionResult(
                source_url=source_url,
                source_id=source_id,
                run_id=run_id,
                claims=claims,
                skipped_reason="no reliable company identity extracted",
            )

        company_claim = company_claims[0]
        website_claims = [claim for claim in claims if claim.field == "official_website"]
        website_value = website_claims[0].value if website_claims else None

        run_id = self._ensure_run(run_id)

        existing = find_existing_candidate(
            self.company_repo.list_candidates(),
            company_name=company_claim.value,
            website=website_value,
        )
        if existing is not None:
            candidate = existing
            created_candidate = False
        else:
            candidate = CompanyCandidate(
                run_id=run_id,
                company_name=company_claim.value,
                official_website=website_value,
            )
            candidate = self.company_repo.create_candidate(candidate)
            created_candidate = True
            if source_id is not None:
                self.company_repo.attach_sources(candidate.candidate_id, [source_id])

        evidence_ids: list[UUID] = []
        kept_claims: list[ExtractedClaim] = []
        for claim in claims:
            if not claim_is_candidate_scoped(candidate, claim):
                continue
            kept_claims.append(claim)
            evidence = Evidence(
                candidate_id=candidate.candidate_id,
                evidence_type=claim.claim_type,
                claim=claim.field,
                extracted_value=claim.value,
                source_url=claim.source_url,
                source_title=claim.source_title,
                supporting_context=claim.context,
                confidence=claim.confidence,
                extracted_at=claim.extracted_at,
            )
            evidence_ids.append(self.evidence_repo.create(evidence).evidence_id)

        profile = self._build_profile(candidate, kept_claims, evidence_ids)
        saved_profile = self.company_repo.save_profile(profile)

        return ExtractionResult(
            source_url=source_url,
            source_id=source_id,
            run_id=run_id,
            candidate=candidate,
            profile=saved_profile,
            claims=kept_claims,
            evidence_ids=evidence_ids,
            created_candidate=created_candidate,
        )

    def _build_profile(
        self, candidate: CompanyCandidate, claims: list[ExtractedClaim], evidence_ids: list[UUID]
    ) -> CompanyProfile:
        merged_evidence = list(dict.fromkeys(evidence_ids))
        existing = self.company_repo.get_profile(candidate.candidate_id)
        if existing is not None:
            merged_evidence = list(dict.fromkeys([*existing.evidence_ids, *evidence_ids]))

        values = {
            field: _single_consistent_value(claims, field)
            for field in _PROFILE_FIELDS
        }
        description = values["company_description"]
        sector = existing.industry_or_sector if existing and values["industry_or_sector"] is None and existing.industry_or_sector else values["industry_or_sector"]
        location = existing.primary_location if existing and values["primary_location"] is None and existing.primary_location else values["primary_location"]

        return CompanyProfile(
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
            official_website=candidate.official_website,
            description=description,
            industry_or_sector=sector,
            primary_location=location,
            funding_amount_usd=values["funding_amount_usd"],
            revenue_amount_usd=values["revenue_amount_usd"],
            evidence_ids=merged_evidence,
        )