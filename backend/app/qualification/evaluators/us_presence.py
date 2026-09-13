"""Deterministic, source-backed US-presence qualification evaluator (offline).

``USPresenceEvaluator`` decides whether explicit, source-backed evidence
establishes that the candidate's company is **based outside the United States**
with no conflicting explicit US presence:

    QualificationCriterion.US_PRESENCE  (Phase 5C)

The evaluator is a pure decision function over evidence. It never queries a
database, never fabricates an extracted value, never invents an evidence ID,
never guesses geography from weak signals (domain, language, currency,
customers, investors, market), and never calls out to any external source. It
does not perform a worldwide geocoding lookup — it applies conservative,
deterministic, explicit-text rules only.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from app.core.enums import EvidenceType, QualificationCriterion, QualificationStatus
from app.models.evidence import Evidence
from app.models.qualification import CriterionResult

_CRITERION = QualificationCriterion.US_PRESENCE

# Evidence types whose extracted text can carry explicit company-base or
# company-geography information. Evidence outside these types (raw USD figures,
# a person's email, a CEO name, …) can never establish a base.
_RELEVANT_TYPES = frozenset(
    {
        EvidenceType.LOCATION,
        EvidenceType.US_PRESENCE,
        EvidenceType.COMPANY_DESCRIPTION,
        EvidenceType.COMPANY_NAME,
        EvidenceType.OFFICIAL_WEBSITE,
    }
)

# ---------------------------------------------------------------------------
# Explicit non-US base locations (maintained, deliberately conservative).
# A location only qualifies when it is attached to the company's actual base
# ("headquartered in …", "based in …", "<place>-based company"). We never infer
# location from a domain suffix, language, currency, or market reach.
# ---------------------------------------------------------------------------

_NON_US_COUNTRIES = frozenset(
    {
        "argentina", "australia", "austria", "belgium", "brazil", "bulgaria",
        "canada", "chile", "china", "colombia", "costa rica", "croatia", "czechia",
        "czech republic", "denmark", "egypt", "estonia", "finland", "france",
        "germany", "ghana", "greece", "hungary", "iceland", "india", "indonesia",
        "ireland", "israel", "italy", "japan", "kenya", "malaysia", "mexico",
        "netherlands", "new zealand", "nigeria", "norway", "peru", "philippines",
        "poland", "portugal", "romania", "rwanda", "saudi arabia", "singapore",
        "south africa", "south korea", "spain", "sweden", "switzerland", "taiwan",
        "thailand", "turkey", "uae", "ukraine", "united kingdom", "uk", "uruguay",
        "vietnam",
    }
)

_NON_US_CITIES = frozenset(
    {
        "accra", "ahmedabad", "amsterdam", "auckland", "austin", "bangalore",
        "bangkok", "barcelona", "beijing", "bengaluru", "berlin", "bogota",
        "brisbane", "brussels", "buenos aires", "cape town", "chennai",
        "coimbatore", "copenhagen", "delhi", "dubai", "dublin", "geneva",
        "guwahati", "gurugram", "hamburg", "hanoi", "helsinki", "hong kong",
        "hyderabad", "indore", "istanbul", "jaipur", "jakarta", "kigali",
        "kochi", "kolkata", "kuala lumpur", "lagos", "lisbon", "london",
        "lucknow", "madrid", "manila", "melbourne", "mexico city", "milan",
        "moscow", "mumbai", "munich", "nairobi", "new delhi", "noida", "oslo",
        "paris", "perth", "prague", "pune", "rio de janeiro", "riyadh",
        "santiago", "sao paulo", "seoul", "shanghai", "shenzhen", "singapore",
        "stockholm", "surat", "sydney", "tel aviv", "tokyo", "toronto",
        "vadodara", "vancouver", "vienna", "visakhapatnam", "warsaw",
        "wellington", "zurich",
    }
)

# NOTE: "austin" intentionally appears in BOTH the non-US and US sets below.
# "Austin" is a city in Texas, US, but the name also refers to ambivalent
# affordances; the US evaluator only FAILs on unambiguous, base-framed US
# geography, and never on a bare mention.
_US_STATES = frozenset(
    {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming",
    }
)

_US_CITIES = frozenset(
    {
        "new york", "san francisco", "los angeles", "chicago", "seattle",
        "boston", "miami", "denver", "atlanta", "dallas", "houston", "phoenix",
        "portland", "san diego", "san jose", "philadelphia", "detroit",
        "minneapolis", "nashville", "austin", "palo alto", "mountain view",
        "menlo park", "santa clara", "sunnyvale", "redwood city", "boulder",
        "brooklyn", "oakland", "berkeley", "pittsburgh", "cincinnati",
        "cleveland", "kansas city", "st. louis", "salt lake city", "milwaukee",
        "new orleans", "charlotte", "raleigh", "orlando", "tampa", "las vegas",
        "sacramento", "san antonio", "fort worth", "columbus", "indianapolis",
    }
)

# Explicit US-presence statements. These are the ONLY grounds for FAIL. Failure
# requires an unambiguous company-base/office/operations reference to US
# geography — never a bare "serves US customers", "US investors", "USD",
# ".com", English wording, or global-market reach.
_US_PRESENCE_PATTERNS = (
    re.compile(
        r"\b(?:headquartered|based|HQ)\s+in\s+(?:the\s+)?"
        r"(?:United\s+States|US|USA|U\.S\.|America|California|Texas|New\s+York|"
        r"San\s+Francisco|Seattle|Chicago|Boston|Denver|Atlanta|Miami|Austin|"
        r"Portland|Phoenix|Houston|Dallas|Los\s+Angeles|San\s+Diego|San\s+Jose|"
        r"Philadelphia|Detroit|Pittsburgh|Minneapolis|Nashville|Washington|"
        r"DC|D\.C\.)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:US|USA|U\.S\.)-based\b", re.IGNORECASE),
    re.compile(
        r"\b(?:US|USA|U\.S\.|United\s+States)\s+"
        r"(?:headquarters|office|offices|operations|base|subsidiary)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:headquarters?|HQ|offices?|operations?|base)\s+in\s+(?:the\s+)?"
        r"(?:US|USA|U\.S\.|United\s+States)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:headquartered|based)\s+in\s+(?:the\s+)?(?:US\s+)?state\s+of\s+"
        r"(?:California|Texas|New\s+York|Washington|Florida|Illinois)\b",
        re.IGNORECASE,
    ),
)

# ---------------------------------------------------------------------------
# Explicit non-US base statements (the ONLY grounds for PASS). "Absence of US
# presence" is never PASS on its own.
# ---------------------------------------------------------------------------

_NON_US_COUNTRIES_ALT = "|".join(_NON_US_COUNTRIES)
_NON_US_CITIES_ALT = "|".join(_NON_US_CITIES)

_NON_US_PATTERNS = (
    re.compile(
        r"\b(?:headquartered|based|HQ)\s+in\s+(?:the\s+)?(?:%s|%s)\b"
        % (_NON_US_COUNTRIES_ALT, _NON_US_CITIES_ALT),
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:%s|%s)-based\b" % (_NON_US_CITIES_ALT, _NON_US_COUNTRIES_ALT), re.IGNORECASE),
    re.compile(
        r"\b(?:headquartered|based|HQ)\s+outside\s+(?:of\s+)?(?:the\s+)?"
        r"(?:United\s+States|US|USA)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnon-?US\s+(?:company|headquarters|base|business)\b", re.IGNORECASE),
    re.compile(r"\b(?:headquarters?|HQ)\s+(?:are|is|located|based)\s+(?:outside|abroad)\b", re.IGNORECASE),
)


def _evidence_texts(evidence: Iterable[Evidence]) -> Iterator[tuple[Evidence, str]]:
    """``(evidence, text)`` pairs with a string extracted value.

    Empty strings are still meaningful for the insufficient-evidence path: they
    represent a supplied record that provided no usable geography signal and
    must therefore remain traceable to its source evidence ID.
    """
    for item in evidence:
        value = item.extracted_value
        if not isinstance(value, str):
            continue
        yield item, value.strip()


def _matches(text: str, patterns: tuple[re.Pattern, ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def evaluate_us_presence(evidence: Iterable[Evidence]) -> CriterionResult:
    """Qualify whether the company is based outside the United States.

    :param evidence: all persisted evidence for the candidate.
    :returns: a ``CriterionResult`` for ``US_PRESENCE``.
    """
    result = CriterionResult(criterion=_CRITERION, status=QualificationStatus.NOT_EVALUATED)

    pass_evidence: list[tuple[Evidence, str]] = []
    fail_evidence: list[tuple[Evidence, str]] = []
    other_evidence: list[tuple[Evidence, str]] = []

    for item, text in _evidence_texts(evidence):
        if item.evidence_type not in _RELEVANT_TYPES:
            other_evidence.append((item, text))
            continue
        if _matches(text, _US_PRESENCE_PATTERNS):
            fail_evidence.append((item, text))
        elif _matches(text, _NON_US_PATTERNS):
            pass_evidence.append((item, text))
        else:
            other_evidence.append((item, text))

    # Explicit conflicting explicit US presence grounds FAIL regardless of any
    # non-US base statement: a qualified non-US base requires no conflicting
    # explicit US presence.
    if fail_evidence:
        reasons = [
            f"explicit US-presence evidence: {text!r} (evidence "
            f"{item.evidence_id})"
            for item, text in fail_evidence
        ]
        result.status = QualificationStatus.FAIL
        result.reasons = reasons
        result.evidence_ids = [item.evidence_id for item, _ in fail_evidence]
        return result

    if pass_evidence:
        reasons = [
            f"explicit non-US base evidence: {text!r} (evidence "
            f"{item.evidence_id})"
            for item, text in pass_evidence
        ]
        result.status = QualificationStatus.PASS
        result.reasons = reasons
        result.evidence_ids = [item.evidence_id for item, _ in pass_evidence]
        return result

    result.status = QualificationStatus.INSUFFICIENT_EVIDENCE
    result.reasons = [
        "insufficient evidence to establish a non-US base: no explicit "
        "headquarters/operations geography statement ties the company to a "
        "non-US location, and weak signals (domain, currency, language, US "
        "customers/investors, market reach) do not establish presence"
    ]
    result.evidence_ids = [item.evidence_id for item, _ in other_evidence]
    return result


class USPresenceEvaluator:
    """Object interface for the Phase 5C US-presence qualification evaluator.

    Thin delegation over :func:`evaluate_us_presence` so the evaluator is
    importable and callable as ``USPresenceEvaluator().evaluate(evidence)``
    without duplicating the qualification logic.
    """

    def evaluate(self, evidence: Iterable[Evidence]) -> CriterionResult:
        return evaluate_us_presence(evidence)
