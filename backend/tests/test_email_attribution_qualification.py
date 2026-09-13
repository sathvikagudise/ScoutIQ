"""Offline, deterministic tests for EMAIL_ATTRIBUTION qualification.

These tests verify the email-attribution evaluator's contract:

* PASS only when supplied evidence explicitly ties the SAME person's full name,
  a qualifying leadership role, and an explicitly attributed personal email to
  one another.
* FAIL only when supplied evidence explicitly CONTRADICTS the same-person
  attribution (email ascribed to a different person / explicit contradiction).
* INSUFFICIENT_EVIDENCE for everything else (absence, ambiguity, generic
  mailboxes, missing role, missing name, email without person, person without
  email, never-fabricated inference).

The suite is a pure decision check: no DB, no network, no API, no LLM. It never
asserts a fabricated evidence ID and never guesses an email from a name.
"""

from __future__ import annotations

import pytest

from app.core.enums import (
    EvidenceType,
    QualificationStatus,
)
from app.models.evidence import Evidence
from app.qualification.evaluators.email_attribution import (
    EmailAttributionEvaluator,
    evaluate_email_attribution,
    find_attributed_emails,
)


def _evidence(
    evidence_id: str,
    evidence_type: EvidenceType,
    extracted_value: str,
    *,
    source_id: str = "src-501",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        extracted_value=extracted_value,
        source_id=source_id,
    )


PASS_CASES = (
    # "Jane Doe, CEO — jane@acme.com"
    _evidence("ev-501", EvidenceType.CEO, "Jane Doe, CEO — jane@acme.com"),
    # "Jane Doe is the CEO of Acme and can be reached at jane@acme.com."
    _evidence(
        "ev-502",
        EvidenceType.CEO,
        "Jane Doe is the CEO of Acme and can be reached at jane@acme.com.",
    ),
    # "Jane Doe (CEO). Reach her at jane@acme.com."
    _evidence(
        "ev-503",
        EvidenceType.COFOUNDER,
        "Jane Doe (Cofounder). Reach her at jane@acme.com.",
    ),
    # Explicit cross-statement same-person chain: name+role in one evidence,
    # explicit email attribution in another, still the SAME person.
    (
        _evidence("ev-504", EvidenceType.CEO, "Jane Doe is the CEO of Acme."),
        _evidence("ev-505", EvidenceType.EMAIL, "Jane Doe's email is jane@acme.com."),
    ),
)


def test_email_attribution_pass_same_person() -> None:
    for case in PASS_CASES:
        result = EmailAttributionEvaluator().evaluate(case)
        assert result.status == QualificationStatus.PASS


def test_email_attribution_module_function_pass() -> None:
    for case in PASS_CASES:
        module_result = evaluate_email_attribution(case)
        assert module_result.status == QualificationStatus.PASS
        # evidence_ids reference only supplied IDs; never fabricated.
        supplied = {ev.evidence_id for ev in case}
        assert set(module_result.evidence_ids) <= supplied


def test_email_attribution_pass_uses_only_supplied_evidence_ids() -> None:
    case = PASS_CASES[3]
    result = EmailAttributionEvaluator().evaluate(case)
    supplied = {ev.evidence_id for ev in case}
    assert set(result.evidence_ids) <= supplied


# Generic / shared mailboxes can never be attributed to a single person.
GENERIC_INSUFFICIENT_CASES = (
    _evidence("ev-510", EvidenceType.EMAIL, "contact@acme.com"),
    _evidence("ev-511", EvidenceType.EMAIL, "Jane Doe can be reached at info@acme.com."),
    _evidence("ev-512", EvidenceType.EMAIL, "Reach Jane Doe (CEO) at hello@acme.com."),
)


def test_email_attribution_generic_mailbox_insufficient() -> None:
    for case in GENERIC_INSUFFICIENT_CASES:
        result = EmailAttributionEvaluator().evaluate(case)
        assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


INSUFFICIENT_CASES = (
    (),  # no evidence at all
    _evidence("ev-520", EvidenceType.EMAIL, ""),  # missing extracted_value
    _evidence("ev-521", EvidenceType.COMPANY_NAME, "Jane Doe"),  # no email, no role
    _evidence("ev-522", EvidenceType.EMAIL, "jane@acme.com"),  # email without person/role
    _evidence("ev-523", EvidenceType.CEO, "Jane Doe is the CEO of Acme."),  # no email
    _evidence("ev-524", EvidenceType.CEO, "Jane Doe, CEO"),  # no email
    # Name+role but email NOT explicitly attributed (only pattern resemblance).
    _evidence("ev-525", EvidenceType.EMAIL, "Jane Doe is the CEO. jane.doe@acme.com"),
    # Role without a full person's name.
    _evidence("ev-526", EvidenceType.CEO, "The CEO can be reached at jane@acme.com."),
    # Email attributed to a DIFFERENT person.
    _evidence("ev-527", EvidenceType.EMAIL, "John Smith can be reached at jane@acme.com."),
)


def test_email_attribution_insufficient_evidence() -> None:
    for case in INSUFFICIENT_CASES:
        result = EmailAttributionEvaluator().evaluate(case)
        assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE
        supplied = {ev.evidence_id for ev in case}
        assert set(result.evidence_ids) <= supplied


FAIL_CASES = (
    # Explicit contradiction: the email is explicitly stated to belong to a
    # different person.
    _evidence(
        "ev-530",
        EvidenceType.EMAIL,
        "Contrary to the filing, jane@acme.com is the email of John Smith, not Jane Doe.",
    ),
)


def test_email_attribution_fail_on_explicit_contradiction() -> None:
    for case in FAIL_CASES:
        result = EmailAttributionEvaluator().evaluate(case)
        assert result.status == QualificationStatus.FAIL


# Own-site domain gating: an explicitly attributed email only counts as the
# leader's work email when it sits on the candidate's own-site host.
def test_email_attribution_company_hosts_filters_off_domain() -> None:
    case = PASS_CASES[0]
    same_host = EmailAttributionEvaluator().evaluate(case, company_hosts={"acme.com"})
    assert same_host.status == QualificationStatus.PASS

    # www. normalizes away; the ''www''-less host still matches.
    www_host = EmailAttributionEvaluator().evaluate(
        case, company_hosts={"www.acme.com"}
    )
    assert www_host.status == QualificationStatus.PASS

    off_host = EmailAttributionEvaluator().evaluate(
        case, company_hosts={"elsewhere.example"}
    )
    assert off_host.status == QualificationStatus.INSUFFICIENT_EVIDENCE

    empty_hosts = EmailAttributionEvaluator().evaluate(case, company_hosts=set())
    assert empty_hosts.status == QualificationStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("company_hosts", [None])
def test_email_attribution_company_hosts_none_preserves_legacy_behavior(
    company_hosts,
) -> None:
    case = PASS_CASES[0]
    result = EmailAttributionEvaluator().evaluate(case, company_hosts=company_hosts)
    assert result.status == QualificationStatus.PASS


def test_email_attribution_company_hosts_empty_means_no_own_site() -> None:
    """An empty host set means the candidate has NO own site: nothing counts."""
    case = PASS_CASES[0]
    result = EmailAttributionEvaluator().evaluate(case, company_hosts=[])
    assert result.status == QualificationStatus.INSUFFICIENT_EVIDENCE


def test_find_attributed_emails_gates_on_company_hosts() -> None:
    case = PASS_CASES[0]
    on_host = find_attributed_emails(case, company_hosts={"acme.com"})
    assert len(on_host) == 1
    assert on_host[0].email == "jane@acme.com"

    off_host = find_attributed_emails(case, company_hosts={"elsewhere.example"})
    assert off_host == []

    empty_hosts = find_attributed_emails(case, company_hosts=set())
    assert empty_hosts == []

    unconstrained = find_attributed_emails(case)
    assert len(unconstrained) == 1
