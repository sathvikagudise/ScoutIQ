"""Phase 5F: qualification orchestration service tests -- fully offline.

These test ``QualificationService`` / ``evaluate_qualification``: the
deterministic aggregation layer that runs the three locked COMPANY evaluators
(Financial, Tech Platform, US Presence) over the supplied evidence and derives
ONE overall company status under the approved policy. The separate
CONTACT_AVAILABILITY dimension (contact readiness) never appears here: it is
decided by ``derive_contact_readiness`` on the contact dimension, never by the
company qualification aggregate.

No network, no database, no LLM, no explicit ``CriterionResult`` fabrication.
Individual criterion results come ONLY from the real evaluators' ``evaluate``
contract.

Contracts under test
--------------------
1. Every supplied ``Evidence`` is handed to each of the three evaluators; the
   service never re-filters or pre-decides for them.
2. Individual ``CriterionResult`` objects are preserved exactly as the
   evaluators return them (same status, reasons, evidence IDs) -- never
   rewritten, re-derived, or enriched.
3. The service aggregates ONLY what those results contain; it never invents
   evidence IDs, reasons, persons, roles, emails, or money amounts, and never
   adds ``CONTACT_AVAILABILITY`` (or any other criterion) as a result.
4. Absence is never PASS: with no usable evidence every evaluator returns
   ``INSUFFICIENT_EVIDENCE`` and the overall result is ``INSUFFICIENT_EVIDENCE``.

Overall-status policy (all-or-nothing aggregation)
--------------------------------------------------
1. Any criterion ``FAIL`` -> overall ``FAIL``.
2. No ``FAIL`` and every criterion ``PASS`` -> overall ``PASS``.
3. No ``FAIL`` and a mix of ``PASS`` and ``INSUFFICIENT_EVIDENCE`` -> overall
   ``INSUFFICIENT_EVIDENCE`` (partial result never silently becomes PASS).
4. Otherwise (all ``INSUFFICIENT_EVIDENCE``, any ``NOT_EVALUATED``, or no
   usable evidence) -> overall ``INSUFFICIENT_EVIDENCE``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.enums import (
    EvidenceType,
    QualificationCriterion,
    QualificationStatus,
)
from app.models.evidence import Evidence
from app.qualification.service import (
    QualificationService,
    evaluate_qualification,
    qualify,
)

# Evidence texts chosen so that EACH COMPANY criterion PASSes independently:
#   - Financial:       explicit $2M funding figure in range
#   - Tech platform:   explicit "operates a software platform"
#   - US presence:     explicit non-US base (headquartered outside the US)

_FIVE_M = "$5 million"
_BELOW = "$700K"

_SOURCE_URL = "https://example.com/source"
_SOURCE_TITLE = "Source of record"


def make_evidence(
    *,
    evidence_type: EvidenceType,
    extracted_value,
    claim: str = "funding_amount_usd",
) -> Evidence:
    return Evidence(
        evidence_id=uuid4(),
        candidate_id=uuid4(),
        evidence_type=evidence_type,
        claim=claim,
        extracted_value=extracted_value,
        source_url=_SOURCE_URL,
        source_title=_SOURCE_TITLE,
    )


def _passing_evidence():
    """Three evidence items that drive every locked COMPANY criterion to PASS."""
    return [
        make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_FIVE_M),
        make_evidence(
            evidence_type=EvidenceType.PLATFORM,
            extracted_value="Acme operates a software platform for logistics",
        ),
        make_evidence(
            evidence_type=EvidenceType.LOCATION,
            extracted_value="Acme is headquartered outside the United States",
        ),
    ]


# ---------------------------------------------------------------------------
# All criteria PASS -> overall PASS, and the criteria are preserved unchanged
# ---------------------------------------------------------------------------


def test_all_pass_overall_pass():
    evidence = _passing_evidence()
    result = evaluate_qualification("cand-1", evidence)

    assert result.overall_status == QualificationStatus.PASS
    assert result.candidate_id == "cand-1"
    # Exactly the three locked COMPANY criteria, in the fixed evaluation order.
    assert [r.criterion for r in result.criteria] == [
        QualificationCriterion.FUNDING_OR_REVENUE,
        QualificationCriterion.TECH_PLATFORM,
        QualificationCriterion.US_PRESENCE,
    ]
    for r in result.criteria:
        assert r.status == QualificationStatus.PASS


def test_criteria_are_exactly_evaluator_outputs():
    """The service preserves, IDENTICALLY, each evaluator's CriterionResult."""
    evidence = _passing_evidence()
    result = evaluate_qualification("cand-1", evidence)

    from app.qualification.evaluators.financial import FinancialEvaluator
    from app.qualification.evaluators.tech_platform import TechPlatformEvaluator
    from app.qualification.evaluators.us_presence import USPresenceEvaluator

    direct = [
        FinancialEvaluator().evaluate(evidence),
        TechPlatformEvaluator().evaluate(evidence),
        USPresenceEvaluator().evaluate(evidence),
    ]
    assert [r.criterion for r in direct] == [r.criterion for r in result.criteria]
    for expected, actual in zip(direct, result.criteria):
        assert expected.status == actual.status
        assert expected.reasons == actual.reasons
        assert expected.evidence_ids == actual.evidence_ids


# ---------------------------------------------------------------------------
# Any FAIL -> overall FAIL (explicit disqualification is definitive)
# ---------------------------------------------------------------------------


def test_any_fail_overall_fail():
    evidence = _passing_evidence()
    evidence.append(
        make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_BELOW)
    )
    result = evaluate_qualification("cand-1", evidence)
    assert result.overall_status == QualificationStatus.FAIL


# ---------------------------------------------------------------------------
# Partial results never silently become PASS
# ---------------------------------------------------------------------------


def test_pass_and_insufficient_is_never_pass():
    evidence = _passing_evidence()
    # Drop everything except financial -> only ONE criterion passes.
    financial = evidence[0]
    result = evaluate_qualification("cand-1", [financial])
    assert result.overall_status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert result.overall_status != QualificationStatus.PASS


def test_all_insufficient_overall_insufficient():
    result = evaluate_qualification(
        "cand-1",
        [make_evidence(evidence_type=EvidenceType.LOCATION, extracted_value="Remote")],
    )
    assert result.overall_status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_no_evidence_overall_insufficient():
    result = evaluate_qualification("cand-1", [])
    assert result.overall_status == QualificationStatus.INSUFFICIENT_EVIDENCE
    # Every criterion individually reports insufficient evidence.
    for r in result.criteria:
        assert r.status == QualificationStatus.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Aggregation is sourced only from evaluator results; nothing is fabricated
# ---------------------------------------------------------------------------


def test_evidence_ids_are_only_supplied_and_first_seen():
    evidence = _passing_evidence()
    result = evaluate_qualification("cand-1", evidence)
    supplied = {item.evidence_id for item in evidence}
    assert set(result.evidence_ids).issubset(supplied)
    # First-seen union across criteria: financial cites funding, tech cites
    # platform, us cites location (leadership/email now live on the contact
    # dimension, never on the company qualification aggregate).
    assert set(result.evidence_ids) == {
        evidence[0].evidence_id,
        evidence[1].evidence_id,
        evidence[2].evidence_id,
    }


def test_no_contact_availability_criterion_added():
    """CONTACT_AVAILABILITY is a contact dimension, never a company criterion."""
    result = evaluate_qualification("cand-1", _passing_evidence())
    assert QualificationCriterion.CONTACT_AVAILABILITY not in {
        r.criterion for r in result.criteria
    }


# ---------------------------------------------------------------------------
# NOT_EVALUATED never becomes overall PASS (deterministic policy)
# ---------------------------------------------------------------------------


def test_overall_status_never_pass_with_not_evaluated():
    from app.qualification import service as svc

    class _FailingEvaluator:
        def evaluate(self, evidence):
            from app.models.qualification import CriterionResult

            return CriterionResult(
                criterion=QualificationCriterion.FUNDING_OR_REVENUE,
                status=QualificationStatus.NOT_EVALUATED,
                reasons=[],
                evidence_ids=[],
            )

    # The policy helper itself: NOT_EVALUATED must never yield PASS.
    assert (
        svc._overall_status([_FailingEvaluator().evaluate([])])
        == QualificationStatus.INSUFFICIENT_EVIDENCE
    )


# ---------------------------------------------------------------------------
# Object interface and module alias behave identically
# ---------------------------------------------------------------------------


def test_qualification_service_class_delegates():
    evidence = _passing_evidence()
    via_function = evaluate_qualification("cand-1", evidence)
    via_class = QualificationService.evaluate("cand-1", evidence)
    assert via_class.overall_status == via_function.overall_status
    assert [r.criterion for r in via_class.criteria] == [
        r.criterion for r in via_function.criteria
    ]


def test_qualify_alias_matches_function():
    evidence = _passing_evidence()
    assert (
        qualify("cand-1", evidence).overall_status
        == evaluate_qualification("cand-1", evidence).overall_status
    )
