"""Persistence operations for Source records."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import FetchStatus
from app.db.mappers import record_to_source, source_to_record
from app.db.orm.run import QueryRecord
from app.db.orm.source import SourceRecord
from app.models.source import Source


class SourceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, source: Source) -> Source:
        """Persist a source. Duplicate normalized URLs return the existing row."""
        record = source_to_record(source)
        try:
            self.db.add(record)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if source.normalized_url:
                existing = self.get_by_normalized_url(source.normalized_url)
                if existing:
                    return existing
            raise
        return record_to_source(record)

    def get(self, source_id: UUID) -> Optional[Source]:
        record = self.db.get(SourceRecord, source_id)
        return record_to_source(record) if record else None

    def get_by_normalized_url(self, normalized_url: str) -> Optional[Source]:
        record = self.db.scalar(
            select(SourceRecord).where(SourceRecord.normalized_url == normalized_url)
        )
        return record_to_source(record) if record else None

    def get_by_url(self, url: str) -> Optional[Source]:
        record = self.db.scalar(select(SourceRecord).where(SourceRecord.url == url))
        return record_to_source(record) if record else None

    def list_by_query(self, query_id: UUID) -> list[Source]:
        records = self.db.scalars(
            select(SourceRecord).where(SourceRecord.discovered_by_query_id == query_id)
        ).all()
        return [record_to_source(record) for record in records]

    def list_by_run(self, run_id: UUID) -> list[Source]:
        records = self.db.scalars(
            select(SourceRecord)
            .join(QueryRecord, QueryRecord.id == SourceRecord.discovered_by_query_id)
            .where(QueryRecord.run_id == run_id)
        ).all()
        return [record_to_source(record) for record in records]

    def update_validation(
        self,
        source_id: UUID,
        *,
        fetch_status: FetchStatus,
        http_status_code: Optional[int] = None,
        final_url: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[Source]:
        record = self.db.get(SourceRecord, source_id)
        if record is None:
            return None
        record.fetch_status = fetch_status
        record.http_status_code = http_status_code
        record.final_url = final_url
        record.content_type = content_type
        self.db.commit()
        return record_to_source(record)