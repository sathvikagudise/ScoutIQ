"""Persistence operations for QualificationResult records."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.mappers import qualification_to_components, record_to_qualification
from app.db.orm.qualification import QualificationRecord
from app.models.qualification import QualificationResult


class QualificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, result: QualificationResult) -> QualificationResult:
        """Persist a qualification result (and its criterion results).

        Re-evaluating a candidate replaces the previous result rather than
        accumulating stale qualification rows.
        """
        existing = self.db.scalar(
            select(QualificationRecord).where(
                QualificationRecord.candidate_id == result.candidate_id
            )
        )
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()

        record, criteria = qualification_to_components(result)
        record.criteria.extend(criteria)
        self.db.add(record)
        self.db.commit()
        return self.get_by_candidate(result.candidate_id)

    def get(self, qualification_id: UUID) -> Optional[QualificationResult]:
        record = self.db.scalar(
            select(QualificationRecord)
            .where(QualificationRecord.id == qualification_id)
            .options(selectinload(QualificationRecord.criteria))
        )
        if record is None:
            return None
        criteria = sorted(record.criteria, key=lambda item: item.criterion.value)
        return record_to_qualification(record, criteria)

    def get_by_candidate(self, candidate_id: UUID) -> Optional[QualificationResult]:
        record = self.db.scalar(
            select(QualificationRecord)
            .where(QualificationRecord.candidate_id == candidate_id)
            .options(selectinload(QualificationRecord.criteria))
        )
        if record is None:
            return None
        criteria = sorted(record.criteria, key=lambda item: item.criterion.value)
        return record_to_qualification(record, criteria)