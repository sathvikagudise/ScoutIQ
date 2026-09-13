"""Phase 5A financial qualification evaluator tests -- fully offline, deterministic.

These tests exercise ``FinancialEvaluator`` directly with constructed
``Evidence`` records. No network, no database, no LLM, no children.

    EVIDENCE != VERIFICATION != QUALIFICATION

Covered contract (all 10 requirements):

  1. explicit revenue within [$1M, $5M]        -> PASS
  2. explicit funding within [$1M, $5M]        -> PASS
  3. exactly $1M (revenue and funding)         -> PASS
  4. exactly $5M (revenue and funding)         -> PASS
  5. explicit revenue below $1M                -> FAIL
  6. explicit funding above $5M                -> FAIL
  7. no financial evidence                     -> INSUFFICIENT_EVIDENCE
  8. valuation / GMV / TPV / AUM / market size -> INSUFFICIENT_EVIDENCE
  9. revenue and funding are never combined    -> never PASS on the sum
 10. evidence_ids in CriterionResult are real  -> traceable to supplied evidence

Evaluator API under test (Phase 5A handoff):

    FinancialEvaluator().evaluate(evidence: Iterable[Evidence]) -> CriterionResult
      .criterion      = QualificationCriterion.FUNDING_OR_REVENUE
      .status         = QualificationStatus.(PASS|FAIL|INSUFFICIENT_EVIDENCE|...)
      .reasons        = ...
      .evidence_ids   = list[UUID] -- only ids of supplied evidence
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.qualification.evaluators.financial import FinancialEvaluator

EVALUATOR = FinancialEvaluator()

_ONE_M = "$1 million"
_FIVE_M = "$5 million"
_ONE_M_ABBREV = "$1M"
_FIVE_M_ABBREV = "$5M"
_BELOW = "$700K"
_ABOVE = "$8 million"

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


# ---------------------------------------------------------------------------
# PASS: any single explicit figure in [$1M, $5M] (inclusive), independently
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("evidence_type", "value"),
    [
        (EvidenceType.REVENUE, _ONE_M),
        (EvidenceType.REVENUE, _FIVE_M),
        (EvidenceType.REVENUE, _ONE_M_ABBREV),
        (EvidenceType.REVENUE, _FIVE_M_ABBREV),
        (EvidenceType.FUNDING, _ONE_M),
        (EvidenceType.FUNDING, _FIVE_M),
        (EvidenceType.FUNDING, _ONE_M_ABBREV),
        (EvidenceType.FUNDING, _FIVE_M_ABBREV),
    ],
)
def test_explicit_figure_within_range_passes(evidence_type, value):
    result = EVALUATOR.evaluate([make_evidence(evidence_type=evidence_type, extracted_value=value)])
    assert result.status == QualificationStatus.PASS
    assert result.criterion == QualificationCriterion.FUNDING_OR_REVENUE
    assert len(result.evidence_ids) == 1


def test_funding_outside_but_revenue_inside_passes():
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_ABOVE)
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_FIVE_M,
        claim="revenue_amount_usd",
    )
    result = EVALUATOR.evaluate([funding, revenue])
    assert result.status == QualificationStatus.PASS
    assert set(result.evidence_ids) == {revenue.evidence_id}


def test_revenue_outside_but_funding_inside_passes():
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_ABOVE,
        claim="revenue_amount_usd",
    )
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_ONE_M)
    result = EVALUATOR.evaluate([revenue, funding])
    assert result.status == QualificationStatus.PASS
    assert set(result.evidence_ids) == {funding.evidence_id}


def test_two_figures_where_one_qualifies_passes():
    inside = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_TWO_M if False else _FIVE_M,
        claim="revenue_amount_usd",
    )
    outside = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_ABOVE,
        claim="revenue_amount_usd",
    )
    result = EVALUATOR.evaluate([inside, outside])
    assert result.status == QualificationStatus.PASS
    assert set(result.evidence_ids) == {inside.evidence_id}


# ---------------------------------------------------------------------------
# FAIL: explicit financial evidence exists but every figure is out of range
# ---------------------------------------------------------------------------


def test_explicit_revenue_below_min_fails():
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_BELOW,
        claim="revenue_amount_usd",
    )
    result = EVALUATOR.evaluate([revenue])
    assert result.status == QualificationStatus.FAIL
    assert set(result.evidence_ids) == {revenue.evidence_id}


def test_explicit_funding_above_max_fails():
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_ABOVE)
    result = EVALUATOR.evaluate([funding])
    assert result.status == QualificationStatus.FAIL
    assert set(result.evidence_ids) == {funding.evidence_id}


def test_all_financial_figures_outside_range_fails():
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_BELOW)
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_ABOVE,
        claim="revenue_amount_usd",
    )
    result = EVALUATOR.evaluate([funding, revenue])
    assert result.status == QualificationStatus.FAIL
    assert set(result.evidence_ids) == {funding.evidence_id, revenue.evidence_id}


# ---------------------------------------------------------------------------
# Never combine: two small values must not add up to a qualifying figure
# ---------------------------------------------------------------------------


def test_small_funding_and_small_revenue_never_combine():
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_BELOW)
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value="$500K",
        claim="revenue_amount_usd",
    )
    result = EVALUATOR.evaluate([funding, revenue])
    # 700K + 500K = 1.2M on paper, but combining is explicitly forbidden.
    assert result.status != QualificationStatus.PASS
    assert result.status in (QualificationStatus.FAIL, QualificationStatus.INSUFFICIENT_EVIDENCE)


def test_below_and_above_never_combine():
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_BELOW)
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_ABOVE,
        claim="revenue_amount_usd",
    )
    result = EVALUATOR.evaluate([funding, revenue])
    assert result.status != QualificationStatus.PASS
    assert result.status in (QualificationStatus.FAIL, QualificationStatus.INSUFFICIENT_EVIDENCE)


# ---------------------------------------------------------------------------
# INSUFFICIENT_EVIDENCE: no usable explicit financial figure
# ---------------------------------------------------------------------------


def test_no_financial_evidence_is_insufficient():
    result = EVALUATOR.evaluate(
        [
            make_evidence(evidence_type=EvidenceType.LOCATION, extracted_value="Singapore"),
            make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value="SaaS platform"),
        ]
    )
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_missing_extracted_value_is_insufficient():
    result = EVALUATOR.evaluate(
        [make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=None)]
    )
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_bare_small_number_without_unit_is_insufficient():
    result = EVALUATOR.evaluate(
        [make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value="3")]
    )
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_non_numeric_text_is_insufficient():
    result = EVALUATOR.evaluate(
        [make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value="Series A closed")]
    )
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_mixed_parseable_and_unparseable_never_passes():
    clear = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_ABOVE)
    unclear = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value="3")
    result = EVALUATOR.evaluate([clear, unclear])
    assert result.status != QualificationStatus.PASS
    assert result.status in (QualificationStatus.FAIL, QualificationStatus.INSUFFICIENT_EVIDENCE)


# ---------------------------------------------------------------------------
# Unsupported metrics never satisfy the financial criterion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "valuation_amount_usd",
        "gmv_amount_usd",
        "total_payments_volume_usd",
        "aum_amount_usd",
        "market_size_usd",
    ],
)
def test_unsupported_metrics_never_pass(claim):
    result = EVALUATOR.evaluate(
        [
            make_evidence(
                evidence_type=EvidenceType.FUNDING,
                extracted_value=_FIVE_M,
                claim=claim,
            )
        ]
    )
    assert result.status != QualificationStatus.PASS
    assert result.status in (QualificationStatus.FAIL, QualificationStatus.INSUFFICIENT_EVIDENCE)


@pytest.mark.parametrize(
    "evidence_type",
    [EvidenceType.LOCATION, EvidenceType.PLATFORM],
)
def test_non_financial_evidence_never_passes_even_with_money(evidence_type):
    result = EVALUATOR.evaluate(
        [make_evidence(evidence_type=evidence_type, extracted_value=_FIVE_M)]
    )
    assert result.status != QualificationStatus.PASS
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Evidence traceability -- only ids of supplied evidence, never fabricated
# ---------------------------------------------------------------------------


def test_pass_cites_exactly_the_qualifying_evidence():
    inside = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_TWO_M if False else _FIVE_M)
    outside = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_ABOVE)
    result = EVALUATOR.evaluate([outside, inside])
    assert result.status == QualificationStatus.PASS
    assert set(result.evidence_ids) == {inside.evidence_id}


def test_fail_cites_every_usable_figure_and_nothing_else():
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_BELOW)
    revenue = make_evidence(
        evidence_type=EvidenceType.REVENUE,
        extracted_value=_ABOVE,
        claim="revenue_amount_usd",
    )
    irrelevant = make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value="SaaS")
    result = EVALUATOR.evaluate([funding, revenue, irrelevant])
    supplied_ids = {funding.evidence_id, revenue.evidence_id, irrelevant.evidence_id}
    assert result.status == QualificationStatus.FAIL
    # Every cited id is a real id that was supplied, and the irrelevant
    # evidence is never cited.
    assert set(result.evidence_ids).issubset(supplied_ids)
    assert irrelevant.evidence_id not in result.evidence_ids


def test_all_result_evidence_ids_are_supplied_and_criterion_is_financial():
    supplied = [
        make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_BELOW),
        make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=_ABOVE),
    ]
    result = EVALUATOR.evaluate(supplied)
    supplied_ids = {item.evidence_id for item in supplied}
    assert set(result.evidence_ids).issubset(supplied_ids)
    assert result.criterion == QualificationCriterion.FUNDING_OR_REVENUE


# ---------------------------------------------------------------------------
# INR / Indian numbering normalization (Phase 6 gap: ₹20.5 crore ≈ $2.4M)
# ---------------------------------------------------------------------------
# The extractor persists non-USD figures together with their explicit converted
# USD equivalent ("₹ 20.5 crore (≈ $2,460,000)"); qualification reads the
# explicit USD equivalent so an INR funding disclosure in range can qualify.
@pytest.mark.parametrize(
    "value",
    [
        "₹ 20.5 crore (≈ $2,460,000)",
        "Rs 20.5 crore (≈ $2,460,000)",
        "INR 20.5 crore (≈ $2,460,000)",
    ],
)
def test_inr_funding_with_explicit_usd_equivalent_qualifies(value):
    funding = make_evidence(evidence_type=EvidenceType.FUNDING, extracted_value=value)
    result = EVALUATOR.evaluate([funding])
    assert result.status == QualificationStatus.PASS
    assert funding.evidence_id in result.evidence_ids


def test_inr_funding_out_of_range_stays_fail():
    funding = make_evidence(
        evidence_type=EvidenceType.FUNDING, extracted_value="₹ 5 crore (≈ $600,000)"
    )
    result = EVALUATOR.evaluate([funding])
    assert result.status == QualificationStatus.FAIL
