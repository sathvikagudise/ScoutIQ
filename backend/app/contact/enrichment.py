"""Phase 5E contact enrichment — persisted contact-readiness per candidate.

``ContactEnrichmentService`` derives one deterministic ``ContactReadiness`` per
company candidate from state the system already holds (persisted contacts,
evidence-attributed contact emails, own-domain public email evidence, discovered
contact channels), and persists it together with the backing counts and any
channel URLs the research pipeline actually discovered.

Readiness NEVER implies email deliverability: ``EVIDENCED_CONTACT`` is a source
page explicitly attributing that email to the named leader. Nothing is ever
guessed here — no name inference, no email construction, no URL fabrication.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import EvidenceType
from app.extraction.service import own_site_host
from app.models.company import CompanyCandidate
from app.models.contact_enrichment import ContactEnrichment
from app.qualification.evaluators.contact_availability import derive_contact_readiness
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_enrichment_repository import ContactEnrichmentRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.research.models import InternalPageCategory, ResearchResult


def _normalized_host(value: str) -> str:
    host = (value or "").strip().strip(".").lower()
    return host[4:] if host.startswith("www.") else host


def _hostname(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower() if host else None


def _email_host(email: str) -> str:
    host = (email or "").split("@", 1)[-1].split(":", 1)[0].strip(".")
    return _normalized_host(host)


class ContactEnrichmentService:
    """Derive, capture, and persist contact-readiness for company candidates."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.company_repo = CompanyRepository(db)
        self.contact_repo = ContactRepository(db)
        self.evidence_repo = EvidenceRepository(db)
        self.enrichment_repo = ContactEnrichmentRepository(db)

    def evaluate(
        self,
        candidate_id: UUID,
        candidate: CompanyCandidate | None = None,
    ) -> ContactEnrichment:
        """Derive and persist exactly one readiness row for the candidate.

        ``evaluate`` is idempotent (one row per candidate) and completely
        offline: it reads ONLY persisted contacts, persisted EMAIL evidence,
        and any channels the pipeline already captured. Public emails count
        only when they sit on the candidate's own-site domain.
        """
        candidate = candidate or self.company_repo.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"candidate {candidate_id} not found")

        contacts = self.contact_repo.list_by_candidate(candidate.candidate_id)
        named_contact_count = len(contacts)
        evidenced_contact_email_count = sum(1 for contact in contacts if contact.email)

        own_host = own_site_host(candidate)
        public_email_count = 0
        if own_host is not None:
            for item in self.evidence_repo.list_by_candidate(candidate.candidate_id):
                if item.evidence_type is not EvidenceType.EMAIL:
                    continue
                value = item.extracted_value
                if not isinstance(value, str) or not value.strip():
                    continue
                if _email_host(value) == own_host:
                    public_email_count += 1

        existing = self.enrichment_repo.get_by_candidate(candidate.candidate_id)
        contact_page_url = existing.contact_page_url if existing else None
        linkedin_url = existing.linkedin_url if existing else None

        readiness = derive_contact_readiness(
            named_contact_count=named_contact_count,
            evidenced_contact_email_count=evidenced_contact_email_count,
            public_email_count=public_email_count,
            has_contact_page_url=bool(contact_page_url),
            has_linkedin_url=bool(linkedin_url),
            has_own_site=own_host is not None,
        )
        return self.enrichment_repo.save(
            ContactEnrichment(
                candidate_id=candidate.candidate_id,
                readiness=readiness,
                named_contact_count=named_contact_count,
                public_email_count=public_email_count,
                contact_page_url=contact_page_url,
                linkedin_url=linkedin_url,
            )
        )

    def capture_channels(
        self,
        candidate: CompanyCandidate | None,
        research: ResearchResult,
    ) -> Optional[ContactEnrichment]:
        """Persist contact channels genuinely discovered on the candidate's own site.

        Only pages sitting on the candidate's own-site domain may contribute
        channels: a publisher article (deep canonical, no own host) never
        yields a company contact page or LinkedIn URL here. Discovered values
        are persisted as-is; none are ever constructed.
        """
        if candidate is None or candidate.candidate_id is None:
            return None
        own_host = own_site_host(candidate)
        if own_host is None:
            return None
        page_host = _normalized_host(
            _hostname(research.final_url or research.source_url)
        )
        if not page_host or page_host != own_host:
            return None

        contact_page_url = None
        for page in research.relevant_internal_pages:
            if page.category is InternalPageCategory.CONTACT:
                contact_page_url = page.url
                break

        linkedin_url = None
        for link in research.links:
            host = _normalized_host(_hostname(link.resolved_url))
            if host != "linkedin.com":
                continue
            path = urlparse(link.resolved_url).path or ""
            if path.startswith("/company/"):
                linkedin_url = link.resolved_url.split("?")[0]
                break

        if contact_page_url is None and linkedin_url is None:
            return None
        return self.enrichment_repo.capture_channels(
            candidate.candidate_id,
            contact_page_url=contact_page_url,
            linkedin_url=linkedin_url,
        )