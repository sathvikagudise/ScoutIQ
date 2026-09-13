"""Offline, deterministic tests for the Phase 5D leadership evaluator.

The evaluator decides whether explicit, source-backed evidence establishes that
a named individual holds a qualifying leadership role at the candidate company
(``QualificationCriterion.LEADERSHIP``):

* ``PASS`` — explicit evidence connects a full person's name to a qualifying
  role in the same source-backed statement:
  * "Jane Doe is the CEO of Acme."
  * "John Smith, Founder of Example Corp"
  * "Sarah Lee, Co-founder and CEO"
  * "Michael Brown serves as Chief Executive Officer."
* ``FAIL`` — explicit evidence contradicts a qualifying leadership claim for a
  named person: "Jane Doe is not the CEO.", "John Smith is a former CEO and no
  longer holds the role.", any explicit contradiction of a qualifying role.
  We never FAIL merely because evidence is missing, and never FAIL a person who
  merely holds a non-qualifying role (CTO, VP, Director, Manager, employee).
* ``INSUFFICIENT_EVIDENCE`` — no evidence, or evidence that does not explicitly
  establish BOTH a full person's name AND a qualifying role with an explicit
  name-role connection (name without role, role without full name, CTO-only,
  VP-only, Director-only, Manager-only, employee/team-member only, ambiguous
  role, incomplete/single-name identity, no explicit connection, "Founder-led
  company" with no named person, "Our leadership team includes Jane Doe." with
  no explicit role).

All tests are offline and deterministic: pure decision logic, no database, no
network, no LLM, no fabricated evidence IDs. Everything returned is limited to
the evidence actually supplied.
"""

import pytest

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult
from app.qualification.evaluators.leadership import LeadershipEvaluator

_CRITERION = QualificationCriterion.LEADERSHIP
_EVALUATOR = LeadershipEvaluator()


def make_evidence(
    evidence_id: str,
    evidence_type: EvidenceType,
    value: str,
) -> Evidence:
    """Build one ``Evidence`` value directly (no database access)."""
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        extracted_value=value,
    )


PASS_CASES = [
    ("ceo-full", "Jane Doe is the CEO of Acme."),
    ("ceo-full-equative", "John Smith, CEO of Example Corp"),
    ("ceo-expanded", "Michael Brown serves as Chief Executive Officer."),
    ("founder-full", "Alice Johnson, Founder of Aether Labs"),
    ("cofounder-full", "Bob Chen, Co-founder of Northwind"),
    ("cofounder-full-hyphen", "Carol Davis, Cofounder of Bluepeak"),
    ("founder-and-ceo", "Sarah Lee, Co-founder and CEO"),
    ("founder-of", "David Evans is a Founder of Greenfield Systems."),
    ("ceo-currently", "Emma Wilson currently serves as the CEO of Solstice."),
    ("ceo-verb-served", "Frank Miller has served as Chief Executive Officer."),
]


FAIL_CASES = [
    ("not-ceo", "Jane Doe is not the CEO."),
    ("not-founder", "John Smith is not a Founder."),
    ("former-ceo", "Alice Johnson is a former CEO and no longer holds the role."),
    ("stepped-down", "Bob Chen stepped down as CEO of Northwind."),
    ("never-was-ceo", "contrary to the filing, Carol Davis never served as CEO."),
    ("former-cofounder", "David Evans is a former Co-founder and no longer holds the role."),
    ("was-not-ceo", "Emma Wilson was not the Chief Executive Officer."),
    ("resigned-founder", "Frank Miller resigned as a Founder of Greenfield Systems."),
]


INSUFFICIENT_CASES = [
    ("empty", " "),
    ("no-evidence-name-no-role", "Jane Doe works at Acme."),
    ("role-no-name", "The company has a CEO."),
    ("role-single-name", "CEO: Jane."),
    ("cto-only", "John Smith is the CTO."),
    ("vp-only", "Our VP of Engineering leads the team."),
    ("director-only", "Jane Doe is a Director."),
    ("manager-only", "Manager at Acme."),
    ("employee-only", "Jane Doe is a team member."),
    ("founder-led-no-person", "Founder-led company with a strong roadmap."),
    ("leadership-team-list", "Our leadership team includes Jane Doe."),
    ("role-without-full-name", "The founder of Acme."),
    ("cto-no-fail", "Sarah Lee is CTO."),
    ("cto-of", "Michael Brown, CTO of Example Corp"),
]


@pytest.mark.parametrize("evidence_id,text", PASS_CASES)
def test_pass_on_explicit_name_role_connection(evidence_id: str, text: str) -> None:
    evidence = [make_evidence(evidence_id, EvidenceType.COMPANY_DESCRIPTION, text)]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.PASS
    assert result.reasons
    assert result.evidence_ids == [evidence_id]


@pytest.mark.parametrize("evidence_id,text", FAIL_CASES)
def test_fail_on_explicit_contradiction(evidence_id: str, text: str) -> None:
    evidence = [make_evidence(evidence_id, EvidenceType.COMPANY_DESCRIPTION, text)]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.FAIL
    assert result.reasons
    assert result.evidence_ids == [evidence_id]


@pytest.mark.parametrize("evidence_id,text", INSUFFICIENT_CASES)
def test_insufficient_on_missing_or_non_qualifying_evidence(
    evidence_id: str, text: str
) -> None:
    evidence = [make_evidence(evidence_id, EvidenceType.COMPANY_DESCRIPTION, text)]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_no_evidence_is_insufficient() -> None:
    result = _EVALUATOR.evaluate([])
    assert result.criterion == _CRITERION
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_never_fabricates_evidence_ids() -> None:
    supplied_ids = {"e1", "e2", "e3"}
    evidence = [
        make_evidence("e1", EvidenceType.COMPANY_DESCRIPTION, "Jane Doe is the CEO of Acme."),
        make_evidence("e2", EvidenceType.INDUSTRY, "software"),
        make_evidence("e3", EvidenceType.LOCATION, "London"),
    ]
    result = _EVALUATOR.evaluate(evidence)
    assert set(result.evidence_ids).issubset(supplied_ids)


def test_cto_alone_never_fails() -> None:
    evidence = [make_evidence("e1", EvidenceType.COMPANY_DESCRIPTION, "Sarah Lee is CTO.")]
    result = _EVALUATOR.evaluate(evidence)
    assert result.criterion == _CRITERION
    assert result.status != QualificationStatus.FAIL


def test_conflicting_evidence_fails() -> None:
    evidence = [
        make_evidence("e1", EvidenceType.COMPANY_DESCRIPTION, "Jane Doe is the CEO of Acme."),
        make_evidence("e2", EvidenceType.COMPANY_DESCRIPTION, "Jane Doe is not the CEO."),
    ]
    result = _EVALUATOR.evaluate(evidence)
    assert result.status == QualificationStatus.FAIL
    assert set(result.evidence_ids) == {"e1", "e2"}
