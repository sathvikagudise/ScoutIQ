"""Phase 5B tech-platform qualification evaluator tests -- fully offline, deterministic.

These tests exercise ``TechPlatformEvaluator`` directly with constructed
``Evidence`` records. No network, no database, no LLM, no children.

    EVIDENCE != VERIFICATION != QUALIFICATION

Covered contract (all 22 requirements):

  1. explicit SaaS evidence                        -> PASS
  2. explicit software product evidence            -> PASS
  3. explicit cloud platform evidence              -> PASS
  4. explicit marketplace evidence                 -> PASS
  5. explicit data platform evidence               -> PASS
  6. explicit infrastructure evidence              -> PASS
  7. explicit developer platform evidence          -> PASS
  8. no evidence                                   -> INSUFFICIENT_EVIDENCE
  9. bare "platform"                               -> INSUFFICIENT_EVIDENCE
 10. "Leading platform" only                       -> INSUFFICIENT_EVIDENCE
 11. "Digital platform" without product meaning    -> INSUFFICIENT_EVIDENCE
 12. technology mentioned but not connected to     -> INSUFFICIENT_EVIDENCE
     the company's product
 13. missing extracted_value                       -> INSUFFICIENT_EVIDENCE
 14. empty extracted_value                         -> INSUFFICIENT_EVIDENCE
 15. ambiguous description                         -> INSUFFICIENT_EVIDENCE
 16. explicitly non-tech-platform company          -> FAIL
 17. explicit offline-only business                -> FAIL
 18. physical/service-only company, explicitly no  -> FAIL
     software/technology platform
 19. PASS cites only qualifying evidence IDs       -> integrity
 20. FAIL cites only explicit-negative evidence IDs -> integrity
 21. INSUFFICIENT_EVIDENCE fabricates no evidence IDs -> integrity
 22. every result uses QualificationCriterion.TECH_PLATFORM -> integrity
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.qualification.evaluators.tech_platform import TechPlatformEvaluator

EVALUATOR = TechPlatformEvaluator()

_SOURCE_URL = "https://example.com/source"
_SOURCE_TITLE = "Source of record"

# ---------------------------------------------------------------------------
# PASS: explicit, source-backed statements that the company actually operates,
# builds, provides, or sells a qualifying technology platform as its product.
# ---------------------------------------------------------------------------

_SAAS = "The company provides SaaS software for logistics teams."
_SOFTWARE_PRODUCT = "The company's primary product is a software platform for real-time inventory."
_CLOUD = "We operate a cloud platform for enterprise data management."
_MARKETPLACE = "The company runs a B2B marketplace connecting manufacturers and suppliers."
_DATA_PLATFORM = "The company operates a data platform used by financial institutions."
_INFRASTRUCTURE = "Developer infrastructure platform for API management."
_DEVELOPER_PLATFORM = "We build a developer platform for shipping logistics APIs."

# Phase 10 vertical platform concepts the pipeline recognizes as qualifying
# platform businesses.
_LOGISTICS_PLATFORM = "The company operates a logistics platform for freight brokers."
_HR_PLATFORM = "The company provides HR software for small companies."
_FINTECH_PLATFORM = "We run a fintech platform for payments."
_HEALTH_PLATFORM = "The company operates a healthcare software platform for clinics."
_EDTECH_PLATFORM = "The company builds an edtech platform for schools."
_CLIMATE_PLATFORM = "We build a climate software platform for carbon accounting."
_B2B_PLATFORM = "The company sells a b2b saas platform for procurement teams."

# ---------------------------------------------------------------------------
# INSUFFICIENT_EVIDENCE: no usable qualifying concept. Bare or vague "platform"
# wording never qualifies on its own.
# ---------------------------------------------------------------------------

_BARE_PLATFORM = "The company is a leading platform."
_LEADING_PLATFORM = "Leading platform for business growth."
_DIGITAL_PLATFORM = "We are a digital platform for connecting people."
_TECH_NOT_CONNECTED = "The company mentions cloud in marketing materials but does not tie it to any product."
_AMBIGUOUS = "The company operates in the platform space with many partners."

# ---------------------------------------------------------------------------
# FAIL: explicit evidence that the company does NOT operate a qualifying
# technology platform. These are the ONLY grounds for FAIL.
# ---------------------------------------------------------------------------

_NON_TECH = "The company is a traditional offline consulting firm with no software product."
_OFFLINE_ONLY = "The business exclusively provides physical services with no digital platform."
_PHYSICAL_ONLY = "The company provides only physical manufacturing services and explicitly states it has no software or technology platform."


def make_evidence(
    *,
    evidence_type: EvidenceType,
    extracted_value: object,
    claim: str = "technology platform claim",
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
# PASS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [_SAAS, _SOFTWARE_PRODUCT, _CLOUD, _MARKETPLACE, _DATA_PLATFORM, _INFRASTRUCTURE, _DEVELOPER_PLATFORM])
def test_explicit_qualifying_platform_passes(text):
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=text)])
    assert result.status == QualificationStatus.PASS
    assert result.criterion == QualificationCriterion.TECH_PLATFORM
    assert len(result.evidence_ids) == 1


@pytest.mark.parametrize(
    "text",
    [_LOGISTICS_PLATFORM, _HR_PLATFORM, _FINTECH_PLATFORM, _HEALTH_PLATFORM, _EDTECH_PLATFORM, _CLIMATE_PLATFORM, _B2B_PLATFORM],
)
def test_vertical_platform_concepts_pass(text):
    result = EVALUATOR.evaluate(
        [make_evidence(evidence_type=EvidenceType.COMPANY_DESCRIPTION, extracted_value=text)]
    )
    assert result.status == QualificationStatus.PASS
    assert result.criterion == QualificationCriterion.TECH_PLATFORM


@pytest.mark.parametrize(
    ("evidence_type", "text"),
    [
        (EvidenceType.COMPANY_DESCRIPTION, _SAAS),
        (EvidenceType.COMPANY_NAME, "Acme SaaS Inc."),
        (EvidenceType.INDUSTRY, "cloud infrastructure"),
        (EvidenceType.OFFICIAL_WEBSITE, "software marketplace connecting buyers and sellers"),
        (EvidenceType.PLATFORM, _DATA_PLATFORM),
    ],
)
def test_qualifying_platform_any_relevant_type_passes(evidence_type, text):
    result = EVALUATOR.evaluate([make_evidence(evidence_type=evidence_type, extracted_value=text)])
    assert result.status == QualificationStatus.PASS
    assert result.criterion == QualificationCriterion.TECH_PLATFORM


def test_qualifying_platform_tied_to_actual_product_passes():
    evidence = [
        make_evidence(evidence_type=EvidenceType.COMPANY_DESCRIPTION, extracted_value="a developer platform"),
        make_evidence(evidence_type=EvidenceType.COMPANY_NAME, extracted_value="non-tech holding"),
    ]
    result = EVALUATOR.evaluate(evidence)
    assert result.status == QualificationStatus.PASS
    assert result.evidence_ids == [evidence[0].evidence_id]


# ---------------------------------------------------------------------------
# INSUFFICIENT_EVIDENCE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [_BARE_PLATFORM, _LEADING_PLATFORM, _DIGITAL_PLATFORM, _TECH_NOT_CONNECTED, _AMBIGUOUS],
)
def test_vague_or_unconnected_platform_is_insufficient(text):
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=text)])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert result.criterion == QualificationCriterion.TECH_PLATFORM


def test_no_evidence_is_insufficient():
    result = EVALUATOR.evaluate([])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert result.criterion == QualificationCriterion.TECH_PLATFORM
    assert result.evidence_ids == []


def test_missing_extracted_value_is_insufficient():
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=None)])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_empty_extracted_value_is_insufficient():
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value="   ")])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_irrelevant_evidence_type_is_insufficient():
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.REVENUE, extracted_value="other")])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_explicit_irrelevant_technology_claim_is_insufficient():
    evidence = [
        make_evidence(
            evidence_type=EvidenceType.PLATFORM,
            extracted_value="greatly values SaaS but never offers any product",
        ),
        make_evidence(
            evidence_type=EvidenceType.OFFICIAL_WEBSITE,
            extracted_value="we are a consulting shop",
        ),
    ]
    result = EVALUATOR.evaluate(evidence)
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# FAIL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [_NON_TECH, _OFFLINE_ONLY, _PHYSICAL_ONLY])
def test_explicit_negative_evidence_fails(text):
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=text)])
    assert result.status == QualificationStatus.FAIL
    assert result.criterion == QualificationCriterion.TECH_PLATFORM
    assert len(result.evidence_ids) == 1


# ---------------------------------------------------------------------------
# EVIDENCE INTEGRITY
# ---------------------------------------------------------------------------


def test_pass_cites_only_qualifying_evidence_ids():
    qual = make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=_SOFTWARE_PRODUCT)
    other = make_evidence(evidence_type=EvidenceType.COMPANY_NAME, extracted_value="Acme Holding Co.")
    result = EVALUATOR.evaluate([other, qual])
    assert result.status == QualificationStatus.PASS
    assert set(result.evidence_ids) == {qual.evidence_id}


def test_fail_cites_only_explicit_negative_evidence_ids():
    neg = make_evidence(evidence_type=EvidenceType.COMPANY_DESCRIPTION, extracted_value=_OFFLINE_ONLY)
    other = make_evidence(evidence_type=EvidenceType.REVENUE, extracted_value="$1,500,000")
    result = EVALUATOR.evaluate([other, neg])
    assert result.status == QualificationStatus.FAIL
    assert set(result.evidence_ids) == {neg.evidence_id}


def test_insufficient_evidence_fabricates_no_evidence_ids():
    result = EVALUATOR.evaluate([make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=_BARE_PLATFORM)])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == []


def test_every_result_uses_tech_platform_criterion():
    for evidence in [[], [_BARE_PLATFORM], [_SOFTWARE_PRODUCT], [_NON_TECH]]:
        items = [make_evidence(evidence_type=EvidenceType.PLATFORM, extracted_value=t) for t in evidence]
        result = EVALUATOR.evaluate(items)
        assert result.criterion == QualificationCriterion.TECH_PLATFORM
