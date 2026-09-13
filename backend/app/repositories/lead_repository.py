"""Persistence operations for QualifiedLead records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mappers import lead_to_record, record_to_lead
from app.db.orm.company import LeadRecord
from app.models.lead import QualifiedLead


class LeadRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, lead: QualifiedLead) -> QualifiedLead:
        self.db.add(lead_to_record(lead))
        self.db.commit()
        return self.get(lead.lead_id)

    def get(self, lead_id: UUID) -> QualifiedLead | None:
        record = self.db.get(LeadRecord, lead_id)
        return record_to_lead(record) if record else None

    def list_by_run(self, run_id: UUID) -> list[QualifiedLead]:
        records = self.db.scalars(
            select(LeadRecord)
            .where(LeadRecord.run_id == run_id)
            .order_by(LeadRecord.created_at.asc())
        ).all()
        return [record_to_lead(record) for record in records]

    def get_by_candidate(self, candidate_id: UUID) -> QualifiedLead | None:
        record = self.db.scalar(
            select(LeadRecord).where(LeadRecord.candidate_id == candidate_id)
        )
        return record_to_lead(record) if record else None

    def list_by_candidate(self, candidate_id: UUID) -> list[QualifiedLead]:
        records = self.db.scalars(
            select(LeadRecord)
            .where(LeadRecord.candidate_id == candidate_id)
            .order_by(LeadRecord.created_at.asc())
        ).all()
        return [record_to_lead(record) for record in records]

    def replace_for_candidate(self, lead: QualifiedLead) -> QualifiedLead:
        """Persist a qualified lead, replacing any prior lead for the candidate.

        Re-generating a lead for the same candidate replaces it rather than
        accumulating stale lead rows.
        """
        existing = self.db.scalars(
            select(LeadRecord).where(LeadRecord.candidate_id == lead.candidate_id)
        ).all()
        for record in existing:
            self.db.delete(record)
        self.db.flush()

        self.db.add(lead_to_record(lead))
        self.db.commit()
        return self.get(lead.lead_id)