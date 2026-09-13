"""Persistence operations for Evidence records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EvidenceType
from app.db.mappers import evidence_to_record, record_to_evidence
from app.db.orm.evidence import EvidenceRecord
from app.models.evidence import Evidence


class EvidenceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, evidence: Evidence) -> Evidence:
        self.db.add(evidence_to_record(evidence))
        self.db.commit()
        return self.get(evidence.evidence_id)

    def get(self, evidence_id: UUID) -> Evidence | None:
        record = self.db.get(EvidenceRecord, evidence_id)
        return record_to_evidence(record) if record else None

    def list_by_candidate(self, candidate_id: UUID) -> list[Evidence]:
        records = self.db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.candidate_id == candidate_id)
            .order_by(EvidenceRecord.extracted_at.asc())
        ).all()
        return [record_to_evidence(record) for record in records]

    def list_by_candidate_and_type(
        self, candidate_id: UUID, evidence_type: EvidenceType
    ) -> list[Evidence]:
        records = self.db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.candidate_id == candidate_id,
                EvidenceRecord.evidence_type == evidence_type,
            )
        ).all()
        return [record_to_evidence(record) for record in records]

    def list_by_claim(self, candidate_id: UUID, claim: str) -> list[Evidence]:
        """All evidence records for one claim — multiple rows are allowed by design."""
        records = self.db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.candidate_id == candidate_id,
                EvidenceRecord.claim == claim,
            )
        ).all()
        return [record_to_evidence(record) for record in records]