"""Offline, deterministic COMPANY qualification orchestration (Phase 5F).

``QualificationService`` runs the three locked, source-backed COMPANY criteria
(Funding/Revenue, Tech Platform, US Presence) over the supplied evidence,
preserves each individual ``CriterionResult`` **unchanged**, and derives ONE
overall status under the approved aggregation policy.

Leadership and email-attribution evidence never contribute to the company
decision: they belong to the separate CONTACT dimension (see
``ContactEnrichmentService`` and the ``ContactAvailabilityEvaluator``).

It never queries a database, never calls an API/LLM/network, never invents
evidence IDs or reasons, never combines values across criteria, and never
fabricates a decision for a criterion that has no implemented evaluator.

Evidencing
----------
* Every supplied ``Evidence`` is handed to each of the three company evaluators
  through their public ``evaluate(evidence)`` contract. Each evaluator filters
  to the evidence types it can use; the service does not re-filter or
  pre-decide.
* Individual ``CriterionResult`` objects are collected and preserved exactly as
  the evaluators return them (same status, reasons, and evidence IDs). The
  service never rewrites, re-derives, or enriches them.
* The service aggregates ONLY what those evaluator results contain. It never
  fabricates evidence IDs, names, roles, emails, money amounts, or source
  claims, and it never adds ``CONTACT_AVAILABILITY`` (or any other criterion)
  as a result — contact availability is a separate, non-driving dimension.
* Absence is never treated as PASS. With no evidence, every evaluator returns
  ``INSUFFICIENT_EVIDENCE`` and the overall result is ``INSUFFICIENT_EVIDENCE``.

Overall-status policy (deterministic, all-or-nothing aggregation)
----------------------------------------------------------------
1. Any criterion ``FAIL`` -> overall ``FAIL`` (an explicit disqualification is
   definitive and never overridden by other criteria).
2. No ``FAIL`` and every invoked criterion ``PASS`` -> overall ``PASS``.
3. No ``FAIL`` and at least one ``PASS`` and at least one
   ``INSUFFICIENT_EVIDENCE`` -> overall ``INSUFFICIENT_EVIDENCE`` (a partial
   result must never silently become PASS).
4. Otherwise (all ``INSUFFICIENT_EVIDENCE``, any ``NOT_EVALUATED``, or no
   usable evidence) -> overall ``INSUFFICIENT_EVIDENCE``.

``NOT_EVALUATED`` never becomes an overall ``PASS``.
"""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from app.core.enums import EvidenceType, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult, QualificationResult
from app.qualification.evaluators.financial import FinancialEvaluator
from app.qualification.evaluators.tech_platform import TechPlatformEvaluator
from app.qualification.evaluators.us_presence import USPresenceEvaluator
from app.qualification.support import normalize_money

# The three locked COMPANY evaluators, in a fixed deterministic invocation
# order. The service instantiates each once and calls only its public
# ``evaluate``. Leadership and email attribution are handled separately by the
# contact dimension and never drive the company decision.
_EVALUATORS = (
    FinancialEvaluator,
    TechPlatformEvaluator,
    USPresenceEvaluator,
)


def _first_seen(evidence_ids: Iterable[str | UUID]) -> list[str | UUID]:
    """Deduplicate evidence IDs preserving first appearance across criteria."""
    seen: list[str | UUID] = []
    for item in evidence_ids:
        if item not in seen:
            seen.append(item)
    return seen


def evaluate_qualification(
    candidate_id: str | UUID,
    evidence: Iterable[Evidence],
    company_hosts: Iterable[str] | None = None,
) -> QualificationResult:
    """Run every locked evaluator and aggregate one overall decision.

    :param candidate_id: the candidate being qualified.
    :param evidence: all persisted evidence for the candidate.
    :param company_hosts: the candidate's own-site domain host(s), when known.
        Retained for API compatibility; the three company evaluators never read
        it (it existed to gate EMAIL_ATTRIBUTION, which now lives on the
        contact dimension).
    :returns: a ``QualificationResult`` whose ``criteria`` are the exact
        ``CriterionResult`` objects returned by the evaluators, in the fixed
        order above, and whose ``overall_status`` follows the policy.
    """
    criteria: list[CriterionResult] = []
    for evaluator in _EVALUATORS:
        criteria.append(evaluator().evaluate(evidence))

    overall_status = _overall_status(criteria, evidence)

    # Aggregate ONLY from evaluator results: preserve every child reason and
    # union the evidence IDs in first-seen order; never invent either.
    reasons: list[str] = []
    evidence_ids: list[str | UUID] = []
    for result in criteria:
        reasons.extend(result.reasons)
        evidence_ids = _first_seen((*evidence_ids, *result.evidence_ids))

    return QualificationResult(
        candidate_id=candidate_id,
        criteria=criteria,
        overall_status=overall_status,
        reasons=reasons,
        evidence_ids=evidence_ids,
    )


def _has_conflicting_financial_evidence(evidence: Iterable[Evidence]) -> bool:
    """Return True when the candidate has both in-range and out-of-range money figures.

    The service-level aggregation treats that as a definitive disqualifier even
    when the financial evaluator itself returns PASS for any single qualifying
    value; this avoids a silent pass when evidence contains explicit contrary
    financial signals for the same criterion.
    """
    figures: list[int] = []
    for item in evidence:
        if item.evidence_type not in (EvidenceType.FUNDING, EvidenceType.REVENUE):
            continue
        amount = normalize_money(item.extracted_value)
        if amount is None:
            continue
        figures.append(amount)

    if not figures:
        return False

    has_qualifying = any(1_000_000 <= amount <= 5_000_000 for amount in figures)
    has_out_of_range = any(amount < 1_000_000 or amount > 5_000_000 for amount in figures)
    return has_qualifying and has_out_of_range


def _overall_status(criteria: Iterable[CriterionResult], evidence: Iterable[Evidence] | None = None) -> QualificationStatus:
    """Overall status from individual criterion results (approved policy)."""
    statuses = {result.status for result in criteria}

    if QualificationStatus.FAIL in statuses:
        return QualificationStatus.FAIL

    if evidence is not None and _has_conflicting_financial_evidence(evidence):
        return QualificationStatus.FAIL

    if statuses == {QualificationStatus.PASS}:
        return QualificationStatus.PASS

    # Never a silent PASS: no FAIL but anything less than all-PASS is
    # INSUFFICIENT_EVIDENCE.
    return QualificationStatus.INSUFFICIENT_EVIDENCE


qualify = evaluate_qualification


class QualificationService:
    """Object interface for the Phase 5F qualification orchestration.

    Thin delegation over :func:`evaluate_qualification`, importable and
    callable as ``QualificationService().qualify(candidate_id, evidence)``.
    """

    @staticmethod
    def evaluate(
        candidate_id: str | UUID,
        evidence: Iterable[Evidence],
        company_hosts: Iterable[str] | None = None,
    ) -> QualificationResult:
        return evaluate_qualification(candidate_id, evidence, company_hosts=company_hosts)
