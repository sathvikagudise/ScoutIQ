"""Persistence operations for ActivityEvent records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mappers import activity_to_record, record_to_activity
from app.db.orm.activity import ActivityRecord
from app.models.activity import ActivityEvent


class ActivityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, event: ActivityEvent) -> ActivityEvent:
        self.db.add(activity_to_record(event))
        self.db.commit()
        return self.get(event.event_id)

    def get(self, event_id: UUID) -> ActivityEvent | None:
        record = self.db.get(ActivityRecord, event_id)
        return record_to_activity(record) if record else None

    def list_by_run_chronological(self, run_id: UUID) -> list[ActivityEvent]:
        """Events for a run, oldest first (id breaks timestamp ties)."""
        records = self.db.scalars(
            select(ActivityRecord)
            .where(ActivityRecord.run_id == run_id)
            .order_by(ActivityRecord.timestamp.asc(), ActivityRecord.id.asc())
        ).all()
        return [record_to_activity(record) for record in records]