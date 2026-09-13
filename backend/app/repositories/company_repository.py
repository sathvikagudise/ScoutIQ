"""Persistence operations for company candidates, profiles, and associations."""

from __future__ import annotations

import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import CandidateStatus
from app.db.mappers import (
    candidate_to_record,
    profile_to_record,
    record_to_candidate,
    record_to_profile,
    record_to_source,
)
from app.db.orm.company import CompanyCandidateRecord, CompanyProfileRecord
from app.db.orm.source import SourceRecord
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.source import Source


def _as_uuid(value: str | UUID) -> UUID:
    """Accept either a UUID or a UUID string at repository boundaries."""
    return value if isinstance(value, UUID) else UUID(str(value))


class CompanyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_candidate(self, candidate: CompanyCandidate) -> CompanyCandidate:
        record = candidate_to_record(candidate)
        self.db.add(record)
        self.db.flush()
        if candidate.discovery_source_ids:
            sources = self.db.scalars(
                select(SourceRecord).where(SourceRecord.id.in_(candidate.discovery_source_ids))
            ).all()
            record.sources.extend(sources)
        self.db.commit()
        return self.get_candidate(candidate.candidate_id)

    def get_candidate(self, candidate_id: str | UUID) -> Optional[CompanyCandidate]:
        candidate_id = _as_uuid(candidate_id)
        record = self.db.scalar(
            select(CompanyCandidateRecord)
            .where(CompanyCandidateRecord.id == candidate_id)
            .options(selectinload(CompanyCandidateRecord.sources))
        )
        return record_to_candidate(record) if record else None

    def update_candidate(self, candidate: CompanyCandidate) -> Optional[CompanyCandidate]:
        record = self.db.get(CompanyCandidateRecord, candidate.candidate_id)
        if record is None:
            return None
        record.company_name = candidate.company_name
        record.official_website = candidate.official_website
        record.status = candidate.status
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        return self.get_candidate(candidate.candidate_id)

    def set_candidate_status(
        self, candidate_id: str | UUID, status: CandidateStatus
    ) -> Optional[CompanyCandidate]:
        candidate_id = _as_uuid(candidate_id)
        record = self.db.get(CompanyCandidateRecord, candidate_id)
        if record is None:
            return None
        record.status = status
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        return self.get_candidate(candidate_id)

    def attach_sources(self, candidate_id: str | UUID, source_ids: list[UUID]) -> Optional[CompanyCandidate]:
        candidate_id = _as_uuid(candidate_id)
        record = self.db.scalar(
            select(CompanyCandidateRecord)
            .where(CompanyCandidateRecord.id == candidate_id)
            .options(selectinload(CompanyCandidateRecord.sources))
        )
        if record is None:
            return None
        existing = {source.id for source in record.sources}
        sources = self.db.scalars(
            select(SourceRecord).where(SourceRecord.id.in_(source_ids))
        ).all()
        for source in sources:
            if source.id not in existing:
                record.sources.append(source)
        record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        return self.get_candidate(candidate_id)

    def list_sources(self, candidate_id: str | UUID) -> list[Source]:
        candidate_id = _as_uuid(candidate_id)
        record = self.db.scalar(
            select(CompanyCandidateRecord)
            .where(CompanyCandidateRecord.id == candidate_id)
            .options(selectinload(CompanyCandidateRecord.sources))
        )
        if record is None:
            return []
        return [record_to_source(source) for source in record.sources]

    def list_candidates(self) -> list[CompanyCandidate]:
        """All candidates, newest first, with their linked sources loaded."""
        records = self.db.scalars(
            select(CompanyCandidateRecord)
            .options(selectinload(CompanyCandidateRecord.sources))
            .order_by(CompanyCandidateRecord.created_at.desc())
        ).all()
        return [record_to_candidate(record) for record in records]

    def save_profile(self, profile: CompanyProfile) -> CompanyProfile:
        record = self.db.scalar(
            select(CompanyProfileRecord).where(
                CompanyProfileRecord.candidate_id == profile.candidate_id
            )
        )
        if record is None:
            record = profile_to_record(profile)
            self.db.add(record)
        else:
            record.company_name = profile.company_name or record.company_name
            record.official_website = profile.official_website or record.official_website
            record.description = profile.description or record.description
            record.industry_or_sector = profile.industry_or_sector or record.industry_or_sector
            record.primary_location = profile.primary_location or record.primary_location
            record.funding_amount_usd = profile.funding_amount_usd or record.funding_amount_usd
            record.revenue_amount_usd = profile.revenue_amount_usd or record.revenue_amount_usd
            record.evidence_ids = [str(value) for value in profile.evidence_ids]
            record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        return self.get_profile(profile.candidate_id)

    def get_profile(self, candidate_id: str | UUID) -> Optional[CompanyProfile]:
        candidate_id = _as_uuid(candidate_id)
        record = self.db.scalar(
            select(CompanyProfileRecord).where(
                CompanyProfileRecord.candidate_id == candidate_id
            )
        )
        return record_to_profile(record) if record else None