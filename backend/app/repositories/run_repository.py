"""Persistence operations for DiscoveryRun records."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.db.mappers import record_to_run, run_to_record
from app.db.orm.run import RunRecord
from app.models.run import DiscoveryRun

_UNSET = object()


class RunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, run: DiscoveryRun) -> DiscoveryRun:
        self.db.add(run_to_record(run))
        self.db.commit()
        return self.get(run.run_id)

    def get(self, run_id: UUID) -> Optional[DiscoveryRun]:
        record = self.db.get(RunRecord, run_id)
        return record_to_run(record) if record else None

    def update_status(self, run_id: UUID, status: RunStatus) -> Optional[DiscoveryRun]:
        record = self.db.get(RunRecord, run_id)
        if record is None:
            return None
        record.status = status
        self.db.commit()
        return record_to_run(record)

    def update_progress(
        self,
        run_id: UUID,
        *,
        qualified_lead_count: object = _UNSET,
        status: object = _UNSET,
        error_message: object = _UNSET,
        completed_at: object = _UNSET,
    ) -> Optional[DiscoveryRun]:
        record = self.db.get(RunRecord, run_id)
        if record is None:
            return None
        if qualified_lead_count is not _UNSET:
            record.qualified_lead_count = qualified_lead_count
        if status is not _UNSET:
            record.status = status
        if error_message is not _UNSET:
            record.error_message = error_message
        if completed_at is not _UNSET:
            record.completed_at = completed_at
        self.db.commit()
        return record_to_run(record)

    def list_recent(self, limit: int = 20) -> list[DiscoveryRun]:
        records = self.db.scalars(
            select(RunRecord).order_by(RunRecord.started_at.desc()).limit(limit)
        ).all()
        return [record_to_run(record) for record in records]

    def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DiscoveryRun]:
        records = self.db.scalars(
            select(RunRecord)
            .where(RunRecord.user_id == user_id)
            .order_by(RunRecord.started_at.desc())
            .limit(limit)
        ).all()
        return [record_to_run(record) for record in records]