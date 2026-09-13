"""Offline, deterministic tests for the Phase 5C US-presence evaluator.

The evaluator qualifies whether explicit, source-backed evidence establishes
that the candidate's company is based outside the United States
(``QualificationCriterion.US_PRESENCE``):

* ``PASS`` — explicit evidence ties the company's base to a non-US geography
  (e.g. "headquartered in London", "based in Singapore") with no conflicting
  explicit US presence.
* ``FAIL`` — explicit evidence establishes unambiguous US presence (e.g. "US
  headquarters", "based in San Francisco", "headquartered in the United
  States"). A conflicting explicit US-presence statement wins over any non-US
  base claim.
* ``INSUFFICIENT_EVIDENCE`` — no usable geography evidence, or only weak
  signals (USD, ".com", English, US customers/investors, market reach, bare
  geography words). Absence/weakness is never PASS or FAIL.

All tests run offline against pure decision logic: no database, no network,
no fabricated evidence IDs. Every returned ``evidence_ids`` is limited to the
IDs of evidence actually supplied to the evaluator.
"""

import pytest

from app.qualification.evaluators.us_presence import USPresenceEvaluator
from app.core.enums import QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence, EvidenceType

_EVALUATOR = USPresenceEvaluator()
_CRITERION = QualificationCriterion.US_PRESENCE


def make_evidence(evidence_id: str, evidence_type: EvidenceType, value: str) -> Evidence:
    """Build a single ``Evidence`` value directly (no database access)."""
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        extracted_value=value,
    )


PASS_CASES = [
    ("non-us-headquartered-london", "The company is headquartered in London, United Kingdom."),
    ("non-us-based-singapore", "FinTech startup based in Singapore serving Southeast Asia."),
    ("non-us-hq-berlin", "Headquartered in Berlin, Germany, with engineering in Hamburg."),
    ("non-us-based-toronto", "A payments company based in Toronto, Canada."),
    ("non-us-hq-melbourne", "HQ in Melbourne, Australia; operations across APAC."),
    ("non-us-based-nairobi", "Mobile money provider based in Nairobi, Kenya."),
]


FAIL_CASES = [
    ("us-hq-new-york", "Headquartered in New York, US."),
    ("us-based-san-francisco", "A B2B software company based in San Francisco, California."),
    ("us-headquarters", "US headquarters in Austin, Texas, with offices globally."),
    ("us-based-us", "Based in the United States, serving global customers."),
    ("us-hq-state", "Headquartered in the state of California."),
    ("us-conflict-overrides", "Based in London, but maintains its US headquarters in New York."),
    ("us-capital", "HQ in Washington, DC."),
    ("us-operations", "US operations base in Seattle; company is expanding."),
]


INSUFFICIENT_CASES = [
    ("empty-text", " "),
    ("no-geography", "We build developer tools for teams of all sizes."),
    ("usd-currency", "Raised $12M in funding and bills customers in USD."),
    ("dot-com-domain", "The product is available at company.com."),
    ("english-language", "Company website and documentation are in English."),
    ("us-customers", "Serves US customers in retail and logistics."),
    ("us-investors", "Backed by US venture investors."),
    ("market-reach-us", "Expanding its reach into the US market next year."),
    ("bare-geography-word", "Global company with customers in many countries."),
    ("founder-nationality", "The founder is a US citizen."),
    ("ambiguous-city-austin", "Founded in Austin on a mission to simplify payments."),
    ("non-us-customers-only", "Serves customers primarily in Europe."),
    ("services-non-us-market", "Focuses on the non-US market."),
    ("company-location-missing", ""),
]


@pytest.mark.parametrize("evidence_id,text", PASS_CASES)
def test_pass_on_explicit_non_us_base(evidence_id: str, text: str) -> None:
    evidence = [make_evidence(evidence_id, EvidenceType.LOCATION, text)]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.PASS
    assert result.reasons
    assert result.evidence_ids == [evidence_id]


@pytest.mark.parametrize("evidence_id,text", FAIL_CASES)
def test_fail_on_explicit_us_presence(evidence_id: str, text: str) -> None:
    evidence = [make_evidence(evidence_id, EvidenceType.US_PRESENCE, text)]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.FAIL
    assert result.reasons
    assert result.evidence_ids == [evidence_id]


@pytest.mark.parametrize("evidence_id,text", INSUFFICIENT_CASES)
def test_insufficient_on_weak_or_missing_evidence(evidence_id: str, text: str) -> None:
    evidence = [make_evidence(evidence_id, EvidenceType.COMPANY_DESCRIPTION, text)]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_ids == [evidence_id]


def test_no_evidence_is_insufficient() -> None:
    result = _EVALUATOR.evaluate([])
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_never_fabricates_evidence_ids() -> None:
    supplied_ids = {"e1", "e2", "e3"}
    evidence = [
        make_evidence("e1", EvidenceType.LOCATION, "Based in London."),
        make_evidence("e2", EvidenceType.US_PRESENCE, "US headquarters in New York."),
        make_evidence("e3", EvidenceType.COMPANY_DESCRIPTION, "We build cloud software."),
    ]
    result = _EVALUATOR.evaluate(evidence)
    assert set(result.evidence_ids).issubset(supplied_ids)


def test_conflicting_us_presence_wins() -> None:
    evidence = [
        make_evidence("e1", EvidenceType.LOCATION, "Headquartered in London."),
        make_evidence("e2", EvidenceType.US_PRESENCE, "Also has its US headquarters in New York."),
    ]
    result = _EVALUATOR.evaluate(evidence)
    assert result.status == QualificationStatus.FAIL
    assert set(result.evidence_ids) == {"e2"}


def test_second_tier_non_us_city_headquartered_passes() -> None:
    """Live gap: real non-US SaaS hubs (Surat, Noida, Pune) were not in the
    recognized-city whitelist, so an explicit base statement in Surat read as
    INSUFFICIENT instead of PASS."""
    for text in (
        "Headquartered in Surat.",
        "SaaS company based in Noida.",
        "Pune-based company serving customers globally.",
    ):
        result = _EVALUATOR.evaluate([make_evidence("e1", EvidenceType.LOCATION, text)])
        assert result.status == QualificationStatus.PASS, text
        assert result.evidence_ids == ["e1"]
