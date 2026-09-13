"""Central ORM <-> Pydantic conversion for every persisted entity.

Keeping this in one module prevents duplicated ad-hoc conversion across
repositories. Enums round-trip through their stored values; UUID string lists
stored in JSON columns are converted back to ``UUID`` objects.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from app.core.enums import (
    CandidateStatus,
    ContactReadiness,
    EvidenceType,
    FetchStatus,
    QualificationCriterion,
    QualificationStatus,
    RunPhase,
    RunStatus,
    VerificationStatus,
)
from app.db.orm.activity import ActivityRecord
from app.db.orm.company import (
    CompanyCandidateRecord,
    CompanyProfileRecord,
    LeadRecord,
)
from app.db.orm.contact import ContactRecord
from app.db.orm.contact_enrichment import ContactEnrichmentRecord
from app.db.orm.evidence import EvidenceRecord
from app.db.orm.qualification import CriterionRecord, QualificationRecord
from app.db.orm.run import QueryRecord, RunRecord
from app.db.orm.source import SourceRecord
from app.db.orm.user import UserRecord
from app.models.activity import ActivityEvent
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.contact import Contact
from app.models.contact_enrichment import ContactEnrichment
from app.models.evidence import Evidence
from app.models.lead import QualifiedLead
from app.models.qualification import CriterionResult, QualificationResult
from app.models.run import DiscoveryRun, SearchQuery
from app.models.source import Source
from app.models.user import User


def _uuid_list(values: Optional[list]) -> list[UUID]:
    return [UUID(value) for value in (values or [])]


def _optional_enum(value, enum_cls):
    if value is None or isinstance(value, enum_cls):
        return value
    return enum_cls(value)


# ---------------------------------------------------------------------------
# User / auth session
# ---------------------------------------------------------------------------


def user_to_record(user: User, password_hash: str) -> UserRecord:
    return UserRecord(
        id=user.user_id,
        email=user.email,
        password_hash=password_hash,
        display_name=user.display_name,
        created_at=user.created_at,
    )


def record_to_user(record: UserRecord) -> User:
    """Convert a user row to its API model. ``password_hash`` never maps."""
    return User(
        user_id=record.id,
        email=record.email,
        display_name=record.display_name,
        created_at=record.created_at,
    )


# ---------------------------------------------------------------------------
# DiscoveryRun / SearchQuery
# ---------------------------------------------------------------------------


def run_to_record(run: DiscoveryRun) -> RunRecord:
    return RunRecord(
        id=run.run_id,
        user_id=run.user_id,
        status=run.status,
        target_lead_count=run.target_lead_count,
        qualified_lead_count=run.qualified_lead_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
        current_phase=run.current_phase,
        error_message=run.error_message,
        metadata_json=run.metadata,
    )


def record_to_run(record: RunRecord) -> DiscoveryRun:
    return DiscoveryRun(
        run_id=record.id,
        user_id=record.user_id,
        status=RunStatus(record.status),
        target_lead_count=record.target_lead_count,
        qualified_lead_count=record.qualified_lead_count,
        started_at=record.started_at,
        completed_at=record.completed_at,
        current_phase=_optional_enum(record.current_phase, RunPhase),
        error_message=record.error_message,
        metadata=record.metadata_json or {},
    )


def query_to_record(query: SearchQuery) -> QueryRecord:
    return QueryRecord(
        id=query.query_id,
        run_id=query.run_id,
        query_text=query.query_text,
        strategy=query.strategy,
        provider=query.provider,
        executed_at=query.executed_at,
        result_count=query.result_count,
        error=query.error,
    )


def record_to_query(record: QueryRecord) -> SearchQuery:
    return SearchQuery(
        query_id=record.id,
        run_id=record.run_id,
        query_text=record.query_text,
        strategy=record.strategy,
        provider=record.provider,
        executed_at=record.executed_at,
        result_count=record.result_count,
        error=record.error,
    )


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


def source_to_record(source: Source) -> SourceRecord:
    return SourceRecord(
        id=source.source_id,
        url=source.url,
        normalized_url=source.normalized_url,
        title=source.title,
        snippet=source.snippet,
        domain=source.domain,
        provider=source.provider,
        discovered_at=source.discovered_at,
        fetch_status=source.fetch_status,
        http_status_code=source.http_status_code,
        final_url=source.final_url,
        content_type=source.content_type,
        discovered_by_query_id=source.discovered_by_query_id,
    )


def record_to_source(record: SourceRecord) -> Source:
    return Source(
        source_id=record.id,
        url=record.url,
        normalized_url=record.normalized_url,
        title=record.title,
        snippet=record.snippet,
        domain=record.domain,
        provider=record.provider,
        discovered_at=record.discovered_at,
        fetch_status=_optional_enum(record.fetch_status, FetchStatus),
        http_status_code=record.http_status_code,
        final_url=record.final_url,
        content_type=record.content_type,
        discovered_by_query_id=record.discovered_by_query_id,
    )


# ---------------------------------------------------------------------------
# Company candidate / profile / lead
# ---------------------------------------------------------------------------


def candidate_to_record(candidate: CompanyCandidate) -> CompanyCandidateRecord:
    return CompanyCandidateRecord(
        id=candidate.candidate_id,
        run_id=candidate.run_id,
        company_name=candidate.company_name,
        official_website=candidate.official_website,
        status=candidate.status,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def record_to_candidate(record: CompanyCandidateRecord) -> CompanyCandidate:
    return CompanyCandidate(
        candidate_id=record.id,
        run_id=record.run_id,
        company_name=record.company_name,
        official_website=record.official_website,
        discovery_source_ids=[source.id for source in record.sources],
        status=CandidateStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def profile_to_record(profile: CompanyProfile) -> CompanyProfileRecord:
    return CompanyProfileRecord(
        id=profile.profile_id,
        candidate_id=profile.candidate_id,
        company_name=profile.company_name,
        official_website=profile.official_website,
        description=profile.description,
        industry_or_sector=profile.industry_or_sector,
        primary_location=profile.primary_location,
        funding_amount_usd=profile.funding_amount_usd,
        revenue_amount_usd=profile.revenue_amount_usd,
        evidence_ids=[str(value) for value in profile.evidence_ids],
        updated_at=profile.updated_at,
    )


def record_to_profile(record: CompanyProfileRecord) -> CompanyProfile:
    return CompanyProfile(
        profile_id=record.id,
        candidate_id=record.candidate_id,
        company_name=record.company_name,
        official_website=record.official_website,
        description=record.description,
        industry_or_sector=record.industry_or_sector,
        primary_location=record.primary_location,
        funding_amount_usd=record.funding_amount_usd,
        revenue_amount_usd=record.revenue_amount_usd,
        evidence_ids=_uuid_list(record.evidence_ids),
        updated_at=record.updated_at,
    )


def lead_to_record(lead: QualifiedLead) -> LeadRecord:
    return LeadRecord(
        id=lead.lead_id,
        run_id=lead.run_id,
        candidate_id=lead.candidate_id,
        company_name=lead.company_name,
        description=lead.description,
        industry_or_sector=lead.industry_or_sector,
        ceo_or_cofounder_name=lead.ceo_or_cofounder_name,
        verified_email=lead.verified_email,
        contact_readiness=lead.contact_readiness,
        evidence_ids=[str(value) for value in lead.evidence_ids],
        qualification_id=lead.qualification_id,
        created_at=lead.created_at,
    )


def record_to_lead(record: LeadRecord) -> QualifiedLead:
    return QualifiedLead(
        lead_id=record.id,
        run_id=record.run_id,
        candidate_id=record.candidate_id,
        company_name=record.company_name,
        description=record.description,
        industry_or_sector=record.industry_or_sector,
        ceo_or_cofounder_name=record.ceo_or_cofounder_name,
        verified_email=record.verified_email,
        contact_readiness=_optional_enum(record.contact_readiness, ContactReadiness),
        evidence_ids=_uuid_list(record.evidence_ids),
        qualification_id=record.qualification_id,
        created_at=record.created_at,
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def evidence_to_record(evidence: Evidence) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence.evidence_id,
        candidate_id=evidence.candidate_id,
        evidence_type=evidence.evidence_type,
        claim=evidence.claim,
        extracted_value=evidence.extracted_value,
        source_url=evidence.source_url,
        source_title=evidence.source_title,
        extracted_at=evidence.extracted_at,
        supporting_context=evidence.supporting_context,
        confidence=evidence.confidence,
    )


def record_to_evidence(record: EvidenceRecord) -> Evidence:
    return Evidence(
        evidence_id=record.id,
        candidate_id=record.candidate_id,
        evidence_type=EvidenceType(record.evidence_type),
        claim=record.claim,
        extracted_value=record.extracted_value,
        source_url=record.source_url,
        source_title=record.source_title,
        extracted_at=record.extracted_at,
        supporting_context=record.supporting_context,
        confidence=record.confidence,
    )


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------


def contact_to_record(contact: Contact) -> ContactRecord:
    return ContactRecord(
        id=contact.contact_id,
        candidate_id=contact.candidate_id,
        full_name=contact.full_name,
        role=contact.role,
        email=contact.email,
        verification_status=contact.verification_status,
        created_at=contact.created_at,
    )


def record_to_contact(record: ContactRecord) -> Contact:
    return Contact(
        contact_id=record.id,
        candidate_id=record.candidate_id,
        full_name=record.full_name,
        role=record.role,
        email=record.email,
        verification_status=VerificationStatus(record.verification_status),
        created_at=record.created_at,
    )


# ---------------------------------------------------------------------------
# Contact enrichment
# ---------------------------------------------------------------------------


def enrichment_to_record(enrichment: ContactEnrichment) -> ContactEnrichmentRecord:
    return ContactEnrichmentRecord(
        candidate_id=enrichment.candidate_id,
        readiness=enrichment.readiness,
        named_contact_count=enrichment.named_contact_count,
        public_email_count=enrichment.public_email_count,
        contact_page_url=enrichment.contact_page_url,
        linkedin_url=enrichment.linkedin_url,
        updated_at=enrichment.updated_at,
    )


def record_to_enrichment(record: ContactEnrichmentRecord) -> ContactEnrichment:
    return ContactEnrichment(
        candidate_id=record.candidate_id,
        readiness=ContactReadiness(record.readiness),
        named_contact_count=record.named_contact_count,
        public_email_count=record.public_email_count,
        contact_page_url=record.contact_page_url,
        linkedin_url=record.linkedin_url,
        updated_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------


def qualification_to_components(
    result: QualificationResult,
) -> tuple[QualificationRecord, list[CriterionRecord]]:
    criteria = [
        CriterionRecord(
            id=uuid4(),
            criterion=item.criterion,
            status=item.status,
            reasons=item.reasons,
            evidence_ids=[str(value) for value in item.evidence_ids],
        )
        for item in result.criteria
    ]
    record = QualificationRecord(
        id=result.qualification_id,
        candidate_id=result.candidate_id,
        overall_status=result.overall_status,
        reasons=result.reasons,
        evidence_ids=[str(value) for value in result.evidence_ids],
        evaluated_at=result.evaluated_at,
    )
    return record, criteria


def record_to_qualification(
    record: QualificationRecord, criteria: list[CriterionRecord]
) -> QualificationResult:
    criterion_results = [
        CriterionResult(
            criterion=QualificationCriterion(item.criterion),
            status=QualificationStatus(item.status),
            reasons=item.reasons,
            evidence_ids=_uuid_list(item.evidence_ids),
        )
        for item in criteria
    ]
    criterion_results.sort(key=lambda item: item.criterion.value)
    return QualificationResult(
        qualification_id=record.id,
        candidate_id=record.candidate_id,
        criteria=criterion_results,
        overall_status=QualificationStatus(record.overall_status),
        reasons=record.reasons,
        evidence_ids=_uuid_list(record.evidence_ids),
        evaluated_at=record.evaluated_at,
    )


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


def activity_to_record(event: ActivityEvent) -> ActivityRecord:
    return ActivityRecord(
        id=event.event_id,
        run_id=event.run_id,
        timestamp=event.timestamp,
        phase=event.phase,
        event_type=event.event_type,
        message=event.message,
        related_candidate_id=event.related_candidate_id,
        related_source_id=event.related_source_id,
    )


def record_to_activity(record: ActivityRecord) -> ActivityEvent:
    from app.core.enums import RunPhase as _RunPhase, ActivityEventType as _AET

    return ActivityEvent(
        event_id=record.id,
        run_id=record.run_id,
        timestamp=record.timestamp,
        phase=_RunPhase(record.phase),
        event_type=_AET(record.event_type),
        message=record.message,
        related_candidate_id=record.related_candidate_id,
        related_source_id=record.related_source_id,
    )