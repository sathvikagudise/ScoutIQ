"""Persistence operations for SearchQuery records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mappers import query_to_record, record_to_query
from app.db.orm.run import QueryRecord
from app.models.run import SearchQuery


class QueryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, query: SearchQuery) -> SearchQuery:
        self.db.add(query_to_record(query))
        self.db.commit()
        return self.get(query.query_id)

    def get(self, query_id: UUID) -> SearchQuery | None:
        record = self.db.get(QueryRecord, query_id)
        return record_to_query(record) if record else None

    def list_by_run(self, run_id: UUID) -> list[SearchQuery]:
        records = self.db.scalars(
            select(QueryRecord)
            .where(QueryRecord.run_id == run_id)
            .order_by(QueryRecord.executed_at.asc())
        ).all()
        return [record_to_query(record) for record in records]