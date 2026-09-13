"""Deterministic discovery-query generation (stratified discovery).

The pipeline used to search a caller-provided flat list of queries, so every
run dug the same hole: broad "b2b software company" style queries return
aggregator/list pages rather than the narrow, first-party pages our extractors
and evaluators actually need.

``generate_strategies`` produces a fixed, reproducible set of discovery queries
from deterministic cross-products over:
  * platform-building angles (the small-business software verticals our
    evaluators recognize: SaaS, software, cloud, logistics, fintech, ...).
  * in-range funding-stage angles (early-stage businesses whose reported figure
    sits inside the evaluator's $1M-$5M window when disclosed).
  * a geography angle toward the US_PRESENCE target: candidates based outside
    the United States (the criterion PASSes a non-US base), so generated
    queries span the densest early-stage SaaS markets (UK, Germany, France,
    India, Australia, Singapore, Brazil, Mexico) rather than US states.
    India is deliberately included: young Indian SaaS/marketplace startups
    routinely announce in-range rounds that an explicit-INR read can ground.

Every query is tagged with a human-readable strategy label that is persisted
on the run's ``SearchQuery.strategy`` row so later stages can see *why* a query
ran and which strategy yielded which sources. Generation never invents data:
it only chooses what to search for.
"""

from __future__ import annotations

# (label, query token) — the small-business software verticals our platform
# evaluator recognizes as platform-building descriptors.
PLATFORM_ANGLES: tuple[tuple[str, str], ...] = (
    ("saas", "saas platform"),
    ("software", "software platform"),
    ("cloud", "cloud platform"),
    ("technology", "technology platform"),
    ("logistics", "logistics platform"),
    ("fintech", "fintech platform"),
    ("hr", "hr software"),
    ("data", "data management platform"),
    ("ai", "ai platform"),
    ("marketplace", "marketplace platform"),
)

# (label, query token) — early-stage funding disclosures that keep recall
# focused below enterprise scale. Selecting "$N million" phrases inside the
# evaluator's range biases recall toward figures that actually qualify, and
# keeps the ledger broad across the funded-company vocabularies "raised",
# "secured", and "seed". Every amount token is explicit; recall is biased, never
# fabricated.
FUNDING_ANGLES: tuple[tuple[str, str], ...] = (
    ("seed_1m", "raised $1 million"),
    ("seed_2m", "raised $2 million"),
    ("seed_3m", "raised $3 million"),
    ("seed_5m", "raised $5 million"),
    ("funding_4m", "secured $4 million"),
    ("seed", "seed funding"),
)

# (label, query token) — non-US geographies that fit the US_PRESENCE target
# (a company must be based OUTSIDE the United States to qualify). Spans the
# dense early-stage SaaS markets our source-backed evaluators can actually
# verify (UK, Germany, France, India, Australia, Singapore, Brazil, Mexico).
GEO_ANGLES: tuple[tuple[str, str], None] = (
    ("uk", "united kingdom"),
    ("de", "germany"),
    ("fr", "france"),
    ("india", "india"),
    ("au", "australia"),
    ("sg", "singapore"),
    ("br", "brazil"),
    ("mx", "mexico"),
    ("eu", "europe"),
)

_STRATEGY_SEP = ";"

# An entity cue ("company") appended to every generated query. Broad web
# search without it is dominated by directories, funding databases, listicles
# and news round-ups; the cue biases recall toward actual company pages — the
# pages our extractors and evaluators can actually ground claims on. It only
# shapes what is searched for; it never changes what a result claims.
_ENTITY_CUE = "company"


def _geo_part(geo: tuple[str | None, str | None]) -> str | None:
    return f"geo:{geo[0]}" if geo[0] else None


# Deterministic (platform, funding, geography) plan. Indices reference the
# angle tables above; each triple is one targeted, evidence-oriented query that
# combines a platform concept, an in-range funding shape, and a non-US region
# so discovery recall lands on first-party funding announcements the
# extractors/evaluators can ground. Kept small so a generated run stays
# researchable end-to-end: the UK/Germany core brings the deepest market, and
# the India/AU/SG/BR/MX entries widen the non-US base where young businesses
# actually announce in-range rounds.
_QUERY_PLAN: tuple[tuple[int, int, int], ...] = (
    # UK core — flagship platform angles x in-range funding stages (8).
    (0, 1, 0), (0, 2, 0), (0, 4, 0), (0, 3, 0),
    (1, 1, 0), (1, 2, 0), (3, 1, 0), (3, 2, 0),
    # Germany — SaaS/cloud breadth (4).
    (0, 1, 1), (0, 2, 1), (2, 1, 1), (2, 2, 1),
    # France and Europe breadth (2).
    (0, 1, 2), (1, 2, 8),
    # India — the SaaS/marketplace startups announcing in-range rounds (4).
    (0, 1, 3), (0, 2, 3), (0, 5, 3), (9, 1, 3),
    # Australia and Singapore (2).
    (0, 1, 4), (0, 1, 5),
    # Brazil and Mexico (2).
    (1, 2, 6), (2, 1, 7),
)


def generate_strategies() -> list[tuple[str, str]]:
    """Return ``(query_text, strategy_label)`` pairs, deterministic.

    The generated set stays small and deliberate (22 queries) so a generated
    run stays researchable end-to-end: each query crosses a platform angle with
    an in-range funding-stage phrase (bias recall toward young, sub-$5M
    businesses) plus a non-US geography (the US_PRESENCE target PASSes only a
    non-US base), spanning the densest early-stage SaaS markets. Every query
    carries a strategy label the run persists, so each source/result is
    traceable to the strategy that produced it. Narrow web-search noise
    (aggregator pages, listicles) stays an honest failure — generation only
    chooses what to search for, never what the answer claims.
    """
    queries: list[tuple[str, str]] = []
    seen: set[str] = set()

    for platform_idx, funding_idx, geo_idx in _QUERY_PLAN:
        platform = PLATFORM_ANGLES[platform_idx]
        funding = FUNDING_ANGLES[funding_idx]
        geo = GEO_ANGLES[geo_idx]
        text = " ".join((platform[1], _ENTITY_CUE, funding[1], geo[1]))
        if text in seen:
            continue
        seen.add(text)
        queries.append(
            (
                text,
                _STRATEGY_SEP.join(
                    (f"platform:{platform[0]}", f"funding:{funding[0]}", _geo_part(geo))
                ),
            )
        )

    return queries