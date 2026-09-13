"""Deterministic, run-scoped funnel counts for a discovery run.

Every count is computed ONLY from persisted rows (sources, candidates,
qualification results/criteria, leads). Nothing is synthesized, recomputed
on the fly, or extrapolated from historical steps the backend never wrote
down. The frontend renders these counts verbatim.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import (
    ContactReadiness,
    FetchStatus,
    QualificationCriterion,
    QualificationStatus,
)
from app.db.orm.company import (
    CompanyCandidateRecord,
    CompanyProfileRecord,
    LeadRecord,
)
from app.db.orm.qualification import CriterionRecord, QualificationRecord
from app.db.orm.run import QueryRecord
from app.db.orm.source import SourceRecord

# The three locked COMPANY criteria, in qualification evaluation order. Only
# these decide whether a candidate is company-qualified; contact data and the
# legacy contact/leadership criteria never participate in the funnel.
COMPANY_CRITERIA = (
    QualificationCriterion.FUNDING_OR_REVENUE,
    QualificationCriterion.TECH_PLATFORM,
    QualificationCriterion.US_PRESENCE,
)

CRITERION_FUNNEL_KEYS = {
    QualificationCriterion.FUNDING_OR_REVENUE: "financial_pass",
    QualificationCriterion.TECH_PLATFORM: "tech_pass",
    QualificationCriterion.US_PRESENCE: "geography_pass",
}

# Product-facing keys for each company criterion (dict order = fixed display
# order: financial, tech platform, us presence).
CRITERION_PRODUCT_KEYS = {
    QualificationCriterion.FUNDING_OR_REVENUE: "financial",
    QualificationCriterion.TECH_PLATFORM: "tech_platform",
    QualificationCriterion.US_PRESENCE: "us_presence",
}


def _qualified_candidates_for_run(db: Session, run_id: UUID, *, overall_status: QualificationStatus) -> int:
    """Number of distinct run candidates whose persisted decision is ``overall_status``."""
    run_candidates = select(CompanyCandidateRecord.id).where(
        CompanyCandidateRecord.run_id == run_id
    )
    return (
        db.scalar(
            select(func.count(func.distinct(QualificationRecord.candidate_id))).where(
                QualificationRecord.candidate_id.in_(run_candidates),
                QualificationRecord.overall_status == overall_status,
            )
        )
        or 0
    )


def run_funnel(db: Session, run_id: UUID) -> dict[str, int]:
    """Pipeline funnel for one run, from persisted state only (see module doc)."""
    query_ids = select(QueryRecord.id).where(QueryRecord.run_id == run_id)
    run_candidates = select(CompanyCandidateRecord.id).where(
        CompanyCandidateRecord.run_id == run_id
    )

    sources_discovered = (
        db.scalar(
            select(func.count())
            .select_from(SourceRecord)
            .where(SourceRecord.discovered_by_query_id.in_(query_ids))
        )
        or 0
    )
    sources_researched = (
        db.scalar(
            select(func.count())
            .select_from(SourceRecord)
            .where(
                SourceRecord.discovered_by_query_id.in_(query_ids),
                SourceRecord.fetch_status == FetchStatus.SUCCESS,
            )
        )
        or 0
    )
    candidates_extracted = (
        db.scalar(
            select(func.count())
            .select_from(CompanyCandidateRecord)
            .where(CompanyCandidateRecord.run_id == run_id)
        )
        or 0
    )
    candidates_evaluated = (
        db.scalar(
            select(func.count(func.distinct(QualificationRecord.candidate_id))).where(
                QualificationRecord.candidate_id.in_(run_candidates)
            )
        )
        or 0
    )

    funnel: dict[str, int] = {
        "sources_discovered": sources_discovered,
        "sources_researched": sources_researched,
        "candidates_extracted": candidates_extracted,
        "candidates_evaluated": candidates_evaluated,
    }

    for criterion in COMPANY_CRITERIA:
        passes = (
            db.scalar(
                select(func.count(func.distinct(QualificationRecord.candidate_id)))
                .join(
                    CriterionRecord,
                    CriterionRecord.qualification_id == QualificationRecord.id,
                )
                .where(
                    QualificationRecord.candidate_id.in_(run_candidates),
                    CriterionRecord.criterion == criterion,
                    CriterionRecord.status == QualificationStatus.PASS,
                )
            )
            or 0
        )
        funnel[CRITERION_FUNNEL_KEYS[criterion]] = passes

    funnel["company_qualified"] = _qualified_candidates_for_run(
        db, run_id, overall_status=QualificationStatus.PASS
    )
    return funnel


def contact_readiness_breakdown(db: Session, run_id: UUID) -> dict[str, int]:
    """Breakdown of persisted leads by contact readiness.

    Leads are the only persisted carrier of the per-lead readiness state, so
    candidates with no persisted lead never appear here. Legacy leads predating
    contact enrichment carry ``None`` and are reported under ``not_enriched`` —
    they are never silently promoted to a readiness we never wrote down.
    """
    breakdown = {
        readiness.value: 0
        for readiness in ContactReadiness
    }
    breakdown["not_enriched"] = 0

    rows = db.execute(
        select(LeadRecord.contact_readiness).where(LeadRecord.run_id == run_id)
    ).scalars().all()
    for readiness in rows:
        key = readiness.value if readiness is not None else "not_enriched"
        breakdown[key] += 1
    return breakdown


# ---------------------------------------------------------------------------
# Candidate-level classification (product-facing, deterministic, run-scoped)
# ---------------------------------------------------------------------------

# Whether a given product classification is "analyzed" (a persisted decision
# exists) vs. never evaluated at all.
CLASSIFICATION_COMPANY_QUALIFIED = "company_qualified"
CLASSIFICATION_NEAR_QUALIFIED = "near_qualified"
CLASSIFICATION_NOT_QUALIFIED = "not_qualified"
CLASSIFICATION_NOT_EVALUATED = "not_evaluated"

_NO_EVALUATION_STATUS = "none"


def _classification(
    qualification: Optional[QualificationRecord],
    passed_count: int,
) -> str:
    """Deterministic classification from persisted state only.

    * A persisted overall ``PASS`` IS the company qualification contract — this
      matches the lead-assembly gate exactly, so classification never disagrees
      with the leads table.
    * ``NEAR_QUALIFIED`` requires exactly two of the three company criteria to
      PASS (the remaining criterion may be FAIL or INSUFFICIENT_EVIDENCE).
    * Everything else with a persisted decision is ``NOT_QUALIFIED`` — this also
      covers the rare persisted-overall ``FAIL`` that carries three PASS
      criterion rows (a financial-conflict guard has no per-criterion fail).
    * No persisted decision is ``NOT_EVALUATED``, never passed/failed.
    """
    if qualification is None:
        return CLASSIFICATION_NOT_EVALUATED
    if qualification.overall_status == QualificationStatus.PASS:
        return CLASSIFICATION_COMPANY_QUALIFIED
    if passed_count == 2:
        return CLASSIFICATION_NEAR_QUALIFIED
    return CLASSIFICATION_NOT_QUALIFIED


def candidate_analyses(db: Session, run_id: UUID) -> list[dict]:
    """Per-candidate product analysis for a run, from persisted rows only.

    Every returned value is persisted state: candidate identity, profile
    description/industry (when present), the persisted per-criterion outcomes
    (status + persisted reasons), the overall qualification decision, and the
    derived product classification. Nothing is inferred beyond the counts the
    UI is explicitly told about (see the module docstring).
    """
    candidate_rows = db.scalars(
        select(CompanyCandidateRecord)
        .where(CompanyCandidateRecord.run_id == run_id)
        .order_by(CompanyCandidateRecord.created_at.desc())
    ).all()
    if not candidate_rows:
        return []

    candidate_ids = [row.id for row in candidate_rows]

    profiles = {
        row.candidate_id: row
        for row in db.scalars(
            select(CompanyProfileRecord).where(
                CompanyProfileRecord.candidate_id.in_(candidate_ids)
            )
        ).all()
    }

    qualifications = db.scalars(
        select(QualificationRecord)
        .where(QualificationRecord.candidate_id.in_(candidate_ids))
        .options(selectinload(QualificationRecord.criteria))
    ).all()
    qualification_by_candidate = {row.candidate_id: row for row in qualifications}

    analyses: list[dict] = []
    for row in candidate_rows:
        profile = profiles.get(row.id)
        qualification = qualification_by_candidate.get(row.id)

        criteria: dict[str, dict] = {}
        for criterion in COMPANY_CRITERIA:
            key = CRITERION_PRODUCT_KEYS[criterion]
            criteria[key] = {"status": _NO_EVALUATION_STATUS, "reasons": []}
        if qualification is not None:
            for criterion_row in qualification.criteria:
                key = CRITERION_PRODUCT_KEYS.get(criterion_row.criterion)
                if key is None:
                    continue
                criteria[key] = {
                    "status": criterion_row.status.value,
                    "reasons": list(criterion_row.reasons or []),
                }

        passed_count = sum(
            1 for item in criteria.values() if item["status"] == QualificationStatus.PASS.value
        )
        classification = _classification(qualification, passed_count)
        blocking_criteria = [
            {
                "criterion": key,
                "status": item["status"],
                "reasons": list(item["reasons"]),
            }
            for key, item in criteria.items()
            if item["status"] in (
                QualificationStatus.FAIL.value,
                QualificationStatus.INSUFFICIENT_EVIDENCE.value,
            )
        ]
        overall_status = (
            qualification.overall_status.value if qualification is not None else None
        )

        analyses.append(
            {
                "candidate_id": row.id,
                "company_name": row.company_name,
                "description": profile.description if profile else None,
                "industry_or_sector": profile.industry_or_sector if profile else None,
                "classification": classification,
                "overall_status": overall_status,
                "passed_criteria_count": passed_count,
                "criteria": criteria,
                "blocking_criteria": blocking_criteria,
            }
        )
    return analyses


def candidate_summary(analyses: list[dict]) -> dict[str, int]:
    """Summary counts across a run's candidate analyses (deterministic)."""
    from collections import Counter

    counts = Counter(item["classification"] for item in analyses)
    return {
        "company_qualified": counts[CLASSIFICATION_COMPANY_QUALIFIED],
        "near_qualified": counts[CLASSIFICATION_NEAR_QUALIFIED],
        "not_qualified": counts[CLASSIFICATION_NOT_QUALIFIED],
        "not_evaluated": counts[CLASSIFICATION_NOT_EVALUATED],
        "analyzed_total": len(analyses),
    }