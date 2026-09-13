"""Persistence operations for ContactEnrichment records."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import ContactReadiness
from app.db.mappers import enrichment_to_record, record_to_enrichment
from app.db.orm.contact_enrichment import ContactEnrichmentRecord
from app.models.common import utcnow
from app.models.contact_enrichment import ContactEnrichment


class ContactEnrichmentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_candidate(self, candidate_id: UUID) -> Optional[ContactEnrichment]:
        record = self.db.get(ContactEnrichmentRecord, candidate_id)
        return record_to_enrichment(record) if record else None

    def save(self, enrichment: ContactEnrichment) -> ContactEnrichment:
        """Replace the single enrichment row for the candidate (idempotent)."""
        existing = self.db.get(ContactEnrichmentRecord, enrichment.candidate_id)
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
        self.db.add(enrichment_to_record(enrichment))
        self.db.commit()
        return self.get_by_candidate(enrichment.candidate_id)

    def capture_channels(
        self,
        candidate_id: UUID,
        *,
        contact_page_url: Optional[str] = None,
        linkedin_url: Optional[str] = None,
    ) -> Optional[ContactEnrichment]:
        """Record discovered contact channels for a candidate (idempotent).

        Only URLs the pipeline actually discovered (never guessed/constructed)
        may be passed here; the repository simply persists them. Prior channel
        values are preserved as complementary discovery accrues.
        """
        record = self.db.get(ContactEnrichmentRecord, candidate_id)
        if record is None:
            record = ContactEnrichmentRecord(
                candidate_id=candidate_id,
                readiness=ContactReadiness.NO_CONTACT_FOUND,
                named_contact_count=0,
                public_email_count=0,
                contact_page_url=contact_page_url,
                linkedin_url=linkedin_url,
                updated_at=utcnow(),
            )
            self.db.add(record)
            self.db.commit()
            return self.get_by_candidate(candidate_id)
        if contact_page_url is not None:
            record.contact_page_url = contact_page_url
        if linkedin_url is not None:
            record.linkedin_url = linkedin_url
        record.updated_at = utcnow()
        self.db.commit()
        return self.get_by_candidate(candidate_id)