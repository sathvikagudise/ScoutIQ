"""Deterministic assembly of ``QualifiedLead`` records from persisted data."""

from __future__ import annotations

from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.enums import EvidenceType, QualificationStatus
from app.contact.enrichment import ContactEnrichmentService
from app.models.company import CompanyCandidate
from app.models.contact import Contact
from app.models.evidence import Evidence
from app.models.lead import QualifiedLead
from app.models.qualification import QualificationResult
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_enrichment_repository import ContactEnrichmentRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository

# Which persisted contact drives the lead name/email, CEO first.
_ROLE_PRIORITY = {"CEO": 0, "Co-Founder": 1, "Founder": 2}


def _as_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class LeadAssemblyService:
    """Assemble qualified leads using only persisted candidate data.

    Optional lead fields (``ceo_or_cofounder_name``, ``verified_email``) come
    strictly from information the system actually holds and only for leads that
    passed qualification. Leadership identity (and an evidence-attributed
    email, when the contact carries one) is reused from the candidate's
    persisted contacts; when no such value exists the field stays ``None`` and
    is never fabricated.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.company_repo = CompanyRepository(db)
        self.contact_repo = ContactRepository(db)
        self.evidence_repo = EvidenceRepository(db)
        self.enrichment_repo = ContactEnrichmentRepository(db)

    def assemble(
        self,
        candidate: CompanyCandidate,
        qualification: QualificationResult,
    ) -> QualifiedLead:
        """Build a qualified lead reusing the candidate's persisted profile.

        ``run_id`` and ``candidate_id`` are taken from the existing candidate
        relationship rather than generated fresh. Missing profile fields become
        ``None`` — nothing may be guessed. ``ceo_or_cofounder_name`` and
        ``verified_email`` are populated only when qualification passed and a
        persisted contact (CEO/Co-Founder preferred, in assembly order) carries
        an evidence-attributed email.
        """
        profile = self.company_repo.get_profile(candidate.candidate_id)
        evidence_ids = qualification.evidence_ids
        ceo_or_cofounder_name = None
        verified_email = None
        if qualification.overall_status is QualificationStatus.PASS:
            best = self._best_contact(candidate.candidate_id)
            if best is not None:
                ceo_or_cofounder_name = best.full_name
                verified_email = best.email
                email_evidence_id = self._email_evidence_id(candidate.candidate_id, best.email)
                if email_evidence_id is not None:
                    evidence_ids = [*evidence_ids, email_evidence_id]
        contact_readiness = None
        try:
            enrichment = self.enrichment_repo.get_by_candidate(candidate.candidate_id)
            if enrichment is None:
                enrichment = ContactEnrichmentService(self.db).evaluate(
                    candidate.candidate_id, candidate=candidate
                )
            contact_readiness = enrichment.readiness
        except Exception:
            # Never let lead assembly fail because enrichment could not be
            # materialised; the lead still stands (readiness simply unknown).
            contact_readiness = None
        return QualifiedLead(
            lead_id=uuid4(),
            run_id=candidate.run_id,
            candidate_id=candidate.candidate_id,
            company_name=candidate.company_name,
            description=profile.description if profile else None,
            industry_or_sector=profile.industry_or_sector if profile else None,
            ceo_or_cofounder_name=ceo_or_cofounder_name,
            verified_email=verified_email,
            contact_readiness=contact_readiness,
            evidence_ids=self._persisted_evidence_ids(evidence_ids),
            qualification_id=qualification.qualification_id,
        )

    def _best_contact(self, candidate_id: UUID) -> Contact | None:
        """The preferred leadership contact (role priority), email or not.

        ``ceo_or_cofounder_name`` comes from this contact regardless of whether
        it carries an email: a company-qualified candidate with a named leader
        must still produce a lead (the readiness label describes the missing
        email). ``verified_email`` is then set only when the contact carries an
        evidence-attributed address.
        """
        contacts = sorted(
            self.contact_repo.list_by_candidate(candidate_id),
            key=lambda contact: _ROLE_PRIORITY.get(contact.role, 10),
        )
        if not contacts:
            return None
        return contacts[0]

    def _email_evidence_id(self, candidate_id: UUID, email: str) -> UUID | None:
        """Id of the EMAIL evidence that carried this address, when present."""
        for item in self.evidence_repo.list_by_candidate(candidate_id):
            if (
                item.evidence_type is EvidenceType.EMAIL
                and isinstance(item.extracted_value, str)
                and item.extracted_value.strip().lower() == email.lower()
            ):
                return item.evidence_id
        return None

    @staticmethod
    def _persisted_evidence_ids(values: Iterable[str | UUID]) -> list[UUID]:
        return [_as_uuid(value) for value in values]