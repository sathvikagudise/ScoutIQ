# ScoutIQ — Technical documentation

> Deep-dive engineering guide for ScoutIQ. For the concise product overview,
> installation, and deployment steps, see the
> [README](../README.md).

> ScoutIQ is built incrementally. Phases 0–4 deliver discovery, persistence,
> web research, and deterministic extraction. Phases 5–7 deliver the
> qualification decision engine, evidence-backed contact & lead assembly, a
> read-only run results view, and the end-to-end pipeline orchestrator. Phase 8
> delivers the React frontend. Phases 9–11 add contact enrichment & readiness,
> funnel transparency, and per-candidate classification (company-qualified,
> near-qualified, other). Phase 12 hardens release readiness: a fully green,
> developer-DB-independent test suite and submission packaging.

## Current architecture (final)

### What ScoutIQ does

ScoutIQ autonomously discovers web sources from search queries (zero API
keys), researches them, extracts company candidates with source-backed
evidence, and evaluates each candidate against a fixed company-qualification
contract. Every analyzed candidate stays visible in the results — including
companies that did not qualify — so discovery work is never silently discarded.

### Qualification contract

A company **qualifies as a lead only when all three persisted company criteria
pass**:

1. **Funding/revenue between $1M–$5M USD**
2. **Operates a tech-related platform**
3. **Minimal or no US presence**

Contact availability **never** affects company qualification. A company is
company-qualified (or not) from its company evidence alone.

### Contact policy

- CEO/co-founder name and email may legitimately be blank; a company-qualified
  lead is not removed because contact data is missing.
- Missing information stays blank (`—` in the UI). ScoutIQ **never fabricates,
  guesses, or invents** names or emails.
- Contact readiness/enrichment (evidenced contact, named contact no email,
  public email, company contact channel, no contact found, not enriched) is
  **supplementary information only** and never changes the company-qualified
  classification or the funnel.

### Result transparency

The results experience exposes every analyzed candidate in one of three
buckets:

- **Company-qualified** — all three company criteria passed (the qualified
  leads table).
- **Near-qualified** — exactly two criteria passed; explicitly labeled and
  never counted as a qualified lead.
- **Other analyzed** — fewer than two criteria passed, or never evaluated
  (reported truthfully as `not evaluated`, never as failed).

A company that was researched/evaluated never disappears merely because it did
not become a qualified lead; the funnel and per-candidate criteria explain why
each company landed where it did.

## Product interface

The frontend is an account-based product surface — users sign up with
email/password, every run belongs to its owner, and each workspace is private
(Phase 14).

- **Landing page (`/`)** — public positioning: "Autonomous company
  intelligence and qualification". Sections cover the four-step flow
  (Discover → Research → Qualify → Review), product capabilities, and the
  truthfulness stance ("ScoutIQ does not turn missing information into
  confident guesses"). No fake metrics, logos, or testimonials; the hero
  composition is explicitly labelled as illustrative.
- **Workspace (sidebar shell)** — shared chrome for Runs and their results,
  with a persistent theme toggle and a clear path back to the landing page
  via the brand mark.
- **Research runs (`/runs`, `/runs/new`)** — run list with quick metrics and
  the new-run composer. The composer separates research input (queries,
  target lead count, max results per query) from the active **qualification
  profile** (Financial $1M–$5M, Tech-related platform, Minimal/no US
  presence, Contact: optional enrichment) and execution.
- **Qualification results (`/runs/:runId/results`)** — a top-line summary
  ("ScoutIQ researched X sources from Y URLs and evaluated Z companies"),
  qualification funnel, company-qualified leads, near-qualified companies,
  other analyzed companies (collapsible <details>), per-candidate criteria,
  contact readiness, and evidence-based explanations.
- **Candidate transparency** — every evaluated candidate is shown in exactly
  one bucket (company-qualified / near-qualified / other analyzed); missing
  decisions render as "not evaluated", blank contacts stay blank.

## Current progress

| Phase | Scope                                        | Status    |
| ----- | -------------------------------------------- | --------- |
| 0     | Dynamic web discovery PoC (zero API keys)    | Completed |
| 1     | Project foundation + core data contracts     | Completed |
| 2     | Persistence: SQLite + SQLAlchemy + repos     | Completed |
| 3     | Web research & scraping engine               | Completed |
| 4     | Candidate extraction & evidence collection   | Completed |
| 5     | Qualification: deterministic evaluators + overall policy | Completed |
| 6     | Contacts & leads: evidence-backed assembly + run completion  | Completed |
| 7     | Read-only run results + end-to-end pipeline orchestration    | Completed |
| 8     | Frontend: React run workspace (create / execute / monitor / results) | Completed |
| 9     | Contact enrichment & readiness tracking     | Completed |
| 10    | Run funnel + contact-readiness transparency | Completed |
| 11    | Candidate classification: company / near / other visibility | Completed |
| 12    | Release readiness: green suite + packaging  | Completed |
| 13    | SaaS product surface: landing, workspace nav, qualification profile | Completed |
| 14    | User accounts & personal workspaces: auth, sessions, ownership, protected frontend | Completed |

## What Phase 0 proved

The most important early project risk:

> Can ScoutIQ autonomously discover new web sources on the open web without
> relying on a fixed company list or requiring API keys?

Yes. The system takes one or more search queries, discovers live web sources
via DuckDuckGo search (zero API keys), deduplicates them across queries, and
validates that the discovered URLs can be fetched by the HTTP research layer.

## What Phase 2 added

A full persistence layer for the Phase 1 contracts, following a strict layering
rule:

```text
Pydantic Models → Service Layer → Repository Layer → SQLAlchemy ORM → SQLite
```

ORM objects never leak into API responses — repositories convert every row back
into the Phase 1 Pydantic contracts, so enums round-trip as typed values and
`UUID` lists stored in JSON columns come back as real UUIDs. The database is
just durable memory for the same typed objects the rest of the system uses.

### The architecture invariant

```text
EVIDENCE EXISTS != CLAIM VERIFIED
```

`Evidence` states that a value was observed in a real source. Deciding whether
evidence *proves* a criterion is a later phase. Nothing is guessed: unknown
values stay `NULL`, contacts and leads can exist without an email, and
qualification can record `INSUFFICIENT_EVIDENCE` without silently becoming
`PASS`. The qualification **engine** is still not implemented — the contract
and its storage exist.

### What is stored

- **Runs & queries** — `DiscoveryRun` lifecycle + `SearchQuery` attempts, with
  progress updates.
- **Sources** — unique on `normalized_url` (rebuild: create the same source
  twice, get the same row back).
- **Candidates & profiles** — `CompanyCandidate` (with discovered-source links)
  and the accumulated, unadjudicated `CompanyProfile`.
- **Evidence** — multiple records per claim are allowed by design (conflicting
  values coexist until adjudication); `source_url` is required.
- **Contacts** — a person exists before any email is known.
- **Qualification** — one result per candidate; re-evaluating replaces the old
  row; criterion-level `INSUFFICIENT_EVIDENCE` is representable.
- **Leads / activity** — qualified leads per run and a chronological activity
  feed.

## What Phase 3 added

Phase 3 turns one URL into structured research material. The research
pipeline:

```text
Discovered URL
      ↓
HTTP Fetch (redirects, timeout, bounded body)
      ↓
Response Classification (FetchStatus)
      ↓
Content-type gate (HTML/XHTML only, else skipped)
      ↓
HTML Parsing (BeautifulSoup)
      ↓
Metadata + Visible Text + Links + Emails
      ↓
Relevant Internal Pages (deterministic classifier)
```

Responsibilities are separated: `PageFetcher` (HTTP), `parser` (HTML content
gate + parse), five independent extractors (metadata, text, links, emails,
internal pages), and a `ResearchService` that orchestrates them into a single
`ResearchResult`. The fetcher is injected, so every test is offline.

### Research rules

- **Extraction ≠ verification.** An extracted email is always reported as
  `VerificationStatus.UNVERIFIED`. ScoutIQ never guesses an email, never builds
  emails from names or domains, and never attributes one to a person/role.
- **Metadata is never fabricated.** Missing title/description/canonical/OG
  fields stay `None`.
- **Text is cleaned, not summarized.** Scripts, styles, `noscript`, comments,
  and navigation sections are removed; whitespace is normalized while
  paragraph boundaries are preserved. No AI, no LLM.
- **Links are resolved, classified, and deduplicated.** Relative URLs resolve
  against the final URL; `mailto:`/`tel:`/`javascript:`/fragment-only links are
  ignored; equivalent links collapse to one; internal vs external is decided
  by hostname.
- **No recursive crawling.** One requested URL → one page fetch → links are
  only *extracted*, never followed.
- **Bot-blocked sources are classified, not ignored.** 401/403 → `ACCESS_BLOCKED`,
  429 → `RATE_LIMITED`, 404/410 → `NOT_FOUND`, 5xx → `SERVER_ERROR`,
  timeouts → `TIMEOUT`, connection failures → `NETWORK_ERROR`. A failed page
  produces a structured `ResearchResult` with `html_extracted=false` and a
  reason, never a crashed run.
- **Non-HTML is skipped safely.** PDFs/images/JSON/etc. are not parsed; the
  result records `content_type` and a "HTML extraction skipped" reason.

### Persistence integration

`POST /api/research/source/{source_id}` researches a stored `Source` and then
persists its fetch metadata (`fetch_status`, `http_status_code`, `final_url`,
`content_type`) back onto the source row. Raw page bodies are **not** stored in
SQLite; extracted artifacts remain service output until a later phase decides
what to persist.

## What Phase 4 added

Phase 4 adds the deterministic candidate-extraction stage: it reads the
structured `ResearchResult` and produces a `CompanyCandidate` plus
source-backed `Evidence`, in memory first and persistently via two endpoints.

```text
ResearchResult (one URL, structured + source-backed)
      ↓
Deterministic signal extraction (regex-only, no AI/LLM)
      ↓
ExtractedClaims (typed fields + normalized values + context)
      ↓
Company Candidate
      +
Source-backed Evidence (one traceable record per claim)
```

Extraction is entirely deterministic and offline-testable: no LLM, no network,
no guessing. The extractors (company name, description, sector, website,
geography, funding, revenue, platform, people, contact) are pure functions over
the already-cleaned research material.

### Extraction ≠ verification

The rules Phase 3 established for research extend to extraction:

- **Extraction ≠ verification.** Every claim is an observed value in a real
  source, captured with its `source_url`. Deciding whether a claim *proves* a
  criterion is still a future phase — extraction never adjudicates.
- **Evidence is mandatory.** A candidate is never persisted without its
  source-backed evidence. Evidence `source_url` is required; conflicting values
  from different sources coexist (never overwritten blindly).
- **Funding & revenue are extracted, not qualification.** A funding/revenue
  value is recorded as observed evidence; it is **not** a decision to pass or
  fail a candidate. Logic deciding what these prove is a later phase.
- **Platform signals are extracted, not qualification.** Observing "built on
  Salesforce" records a signal; it does **not** classify the company as
  qualified.
- **Emails stay unverified.** Extracted public emails are always reported
  `UNVERIFIED`. ScoutIQ never guesses an email, never builds emails from names
  or domains, and never attributes one to a person/role. Contacts may exist
  with no email at all.
- **Identity matching is conservative.** A candidate is matched to an existing
  company only when a website or a normalized company name clearly matches.
  Distinct companies that merely share a suffix or domain quirk stay distinct —
  no forced merges, no guessing.

### Evidence areas extraction covers

- Company name, description, sector, website (URL)
- Geography (headquarters / "based in" / "founded in" wording)
- Funding round + amount, revenue wording
- Tech platform signals, people (founder/CEO/co-founder), and public contact
  emails

### Endpoints

Two offline, deterministic endpoints:

```text
POST /api/extraction/research        # Research a persisted source, then extract
POST /api/extraction/from-research   # Extract from a client-supplied ResearchResult
```

`POST /api/extraction/research` takes a persisted `source_id` (and optional
`run_id`), researches the stored source, extracts signals, and persists the
candidate, its profile, and its evidence. `POST /api/extraction/from-research`
takes a full `ResearchResult` (and optional `run_id`/`source_id`), extracts,
and persists the same artifacts.

## What Phases 5–7 added (qualification, contacts & leads, orchestration)

Phases 5–7 close the loop that Phase 4 opened: accumulated candidate evidence
is adjudicated by a deterministic qualification engine, evidence-backed
contacts and leads are assembled, and the whole pipeline runs end to end from
one run.

### Qualification (Phase 5)

The company-qualification decision is driven by **three locked COMPANY
criteria**, in evaluation order: financial (funding/revenue), tech platform,
and US presence. Each deterministic, source-backed evaluator receives the
candidate's persisted ``Evidence`` and returns a single ``CriterionResult``.
The legacy leadership (CEO/founder) and email-attribution evaluators are no
longer part of company qualification — names and emails are supplementary
contact data (see Contact policy) and never affect a company's qualification or
classification.

One overall decision combines the three company criteria under a fixed
all-or-nothing policy:

1. Any company criterion ``FAIL`` → overall ``FAIL`` (an explicit
   disqualification is definitive and never overridden).
2. No ``FAIL`` and every company criterion ``PASS`` → overall ``PASS``.
3. No ``FAIL`` but at least one ``INSUFFICIENT_EVIDENCE`` → overall
   ``INSUFFICIENT_EVIDENCE`` — a partial result never silently becomes ``PASS``.
4. Otherwise (all ``INSUFFICIENT_EVIDENCE``, any ``NOT_EVALUATED``, or no
   usable evidence) → overall ``INSUFFICIENT_EVIDENCE``.
5. Conflicting in-range and out-of-range funding/revenue figures → overall
   ``FAIL`` (criterion rows may still persist PASS — the guarded overall
   decision wins, and the candidate is never counted as company-qualified).

Absence is never a pass: with no evidence every criterion is
``INSUFFICIENT_EVIDENCE``. A persisted overall ``PASS`` is the single contract
that makes a candidate a qualified lead, and it must always equal the leads
table and ``funnel.company_qualified``. Extraction persists money figures with
their explicit unit/USD marker (Phase 4 revision), so candidates built from
research→extraction *can* satisfy the financial criterion when the evidence
actually carries a ``$``/``USD`` figure in the $1M–$5M range.

Endpoint: ``POST /api/runs/{id}/qualify`` — qualifies each requested candidate
against its persisted evidence and persists the decision.

### Contacts & leads (Phase 6)

- ``ContactAssemblyService`` assembles a contact only when persisted evidence
  names a leader (CEO / Co-Founder / Founder). Assembly is idempotent: an
  existing contact with the identical ``(full_name, role)`` for a candidate is
  returned, never duplicated. Emails stay ``UNVERIFIED`` and are never guessed,
  built from names, or attributed to a person.
- ``LeadAssemblyService`` produces a qualified lead only for a candidate that is
  ``QUALIFIED`` **and** has an overall ``PASS`` decision; ineligible candidates
  fail the request explicitly (409) rather than silently producing a lead.

Endpoints: ``POST /api/runs/{id}/contacts``, ``POST /api/runs/{id}/leads``, and
``POST /api/runs/{id}/complete`` (recomputes ``qualified_lead_count`` from the
persisted lead rows — never from request input or a prior value — and is
idempotent).

### Run results, funnel & candidate analysis (Phases 7, 10, 11)

- ``GET /api/runs/{id}/results`` is a read-only snapshot of a run's persisted
  final output: the run itself, its qualified leads, its evidence-backed
  contacts, a deterministic run funnel, a contact-readiness breakdown, a
  per-candidate classification summary, and the full per-candidate analysis
  array (candidate_id, description, industry, classification, each criterion's
  persisted status/reason, passed-criteria count, and blocking criteria). Only
  persisted state is returned; nothing is inferred, fabricated, or written.
- The funnel counts (`run_funnel`) are per-criterion per-candidate counts that
  can overlap — a company can pass several criteria — and ``company_qualified``
  is the only count that requires all three company criteria to pass.
- Every analyzed candidate is classified company-qualified / near-qualified /
  not-qualified / not-evaluated from persisted statuses only; near-qualified
  never leaks into the qualified-lead count.
- ``PipelineOrchestrator`` drives a run end to end — ``discovery → research →
  extraction → qualification → contacts + lead assembly → completion`` —
  reusing every existing service and repository verbatim. Per-query discovery
  errors are collected and non-HTML/failed sources are skipped (soft failures
  never sink the run); any unexpected exception marks the run ``FAILED`` with
  an ``error_message`` and is re-raised. The orchestrator never fabricates data
  and lifecycle is status-only (``RUNNING → COMPLETED``/``FAILED``) with no
  activity-event or ``current_phase`` writes.

Endpoint: ``POST /api/runs/{id}/execute`` — runs the full pipeline for a run
using the real DuckDuckGo provider and fetcher (a live execution needs the
network) and returns the same read shape as ``GET /results``.

## What Phase 8 added (the frontend)

Phase 8 pairs the read-only API with a typed React workspace so a run can be
created, executed, followed live, and analyzed end to end from a browser:

| Concern     | Choice                                                        |
| ----------- | ------------------------------------------------------------- |
| Language/UI | React 19 + TypeScript + Vite 8                               |
| Routing     | react-router-dom 7 (declarative routes)                       |
| HTTP        | Browser ``fetch`` against same-origin ``/api`` (dev: Vite proxy) |
| Styling     | Hand-written CSS + design tokens (CSS variables), dark/light themes |
| Data access | Small typed hook layer (``useRuns``, ``useRun``, ``useRunResults``, activity) |

```text
Vite dev server (5173)
     ↓ /api and /health proxied to http://127.0.0.1:8000
FastAPI backend (same source of truth as the curl/CLI examples)
```

- **Workspace** — a single sidebar nav (runs list) plus a persisted theme
  toggle; responsive layout for desktop, tablet, and mobile.
- **Create & execute** (``/runs/new``) — compose run-level search queries and
  target lead count, validate client-side, launch ``POST /runs/{id}/execute``,
  and follow the run.
- **Monitor** (``/runs/:runId``) — pending, running, completed, and failed
  states; active runs keep polling while running, with an animated running
  badge that respects ``prefers-reduced-motion``.
- **Results** (``/runs/:runId/results``) — a read-only report over the
  persisted run: company-qualified leads, near-qualified companies, other
  analyzed companies (collapsible), evidence-backed contacts, a funnel overview
  with criterion pass counts and classification buckets, per-candidate company-
  criteria chips (pass/failed/insufficient), and contact-readiness breakdown.
  Blank CEO/email fields render honestly as ``—``. The UI never guesses or
  synthesizes a value the pipeline did not persist.
- **Theming & accessibility** — no-FOUC theme bootstrap in ``index.html``,
  ``data-theme`` + ``localStorage`` persistence, keyboard-focusable table
  scroll regions, aria-labels, and a contrast-safe token palette.

Frontend verification is ``npm run typecheck`` and ``npm run build`` (both
green), with rendered surfaces validated across light/dark themes and
desktop/tablet/mobile viewports.

## What Phase 14 added (user accounts & personal workspaces)

Phase 14 adds end-to-end authentication and per-user run isolation so every
workspace is private by default.

### Backend

- **Register / sign-in / sign-out / current-user** — four endpoints at
  `/api/auth/register` (201), `/api/auth/login` (200), `/api/auth/logout` (204),
  `/api/auth/me` (200/401).
- **Password storage** — bcrypt (cost 12); the hash is never returned in any
  response.
- **Session management** — server-side rows in `auth_sessions`; register/login
  return the session UUID once as a bearer token, and the client echoes it as an
  `Authorization: Bearer <token>` header on every request. No cookie is set, so
  cross-site (Vercel → Render) auth needs no SameSite/Secure cookie
  configuration.
- **Ownership model** — every run row carries an optional `user_id` (CHAR(32) on
  SQLite, native UUID on PostgreSQL). `create_run` sets it from the authenticated
  session; `list_runs` only returns the current user's runs; `require_owned_run`
  returns a uniform 404 for missing, unowned (legacy `user_id IS NULL`), or
  foreign runs.
- **Extraction endpoints** (`/api/extraction/research`,
  `/api/extraction/from-research`) are also protected; any supplied `run_id` is
  ownership-checked against the caller.
- **CORS** — explicit trusted-origin allowlist (default
  `http://localhost:5173,http://127.0.0.1:5173`), credentials allowed; configured
  via `CORS_ORIGINS` env var for production cross-origin deployments.
- **Migration** — SQLite-only: `init_db` performs `ALTER TABLE runs ADD COLUMN
  user_id CHAR(32)` on upgrade, guarded by a `PRAGMA table_info` check so it is
  idempotent. On PostgreSQL the migration path is skipped (tables are created
  fresh with a native UUID `user_id` column).
- **Persistence** — the configured `DATABASE_URL` drives the engine. Local dev
  defaults to SQLite; production points at external PostgreSQL (`postgresql://`
  URLs are normalized onto the bundled psycopg driver with `pool_pre_ping`).
- **Legacy visibility** — unowned (pre-auth) runs are invisible to authenticated
  users; no demo or shared account is created.

### Frontend

- **Bearer-token client** — the API client attaches `Authorization: Bearer
  <token>` from `sessionStorage` on every fetch; `credentials: "include"` is no
  longer used (auth is header-based).
- **`AuthProvider`** — wraps the app; restores the stored token and resolves the
  session via `GET /api/auth/me` on mount (clearing any stale/expired token), and
  exposes `login`, `register`, `logout`, and the current `User`.
- **`ProtectedRoute`** — renders a neutral skeleton while the session resolves,
  then redirects unauthenticated visitors to `/login?from=…`.
- **`LoginPage` / `RegisterPage`** — standalone branded forms with client
  validation, duplicate-email handling (409 → “already exists”), and minimum
  8-character password enforcement.
- **`AppShell`** user area — avatar initial, display name / email, and a
  **Sign out** button that calls `POST /api/auth/logout` and navigates home.
- **`LandingPage`** — unauthenticated nav shows *Sign in* / *Create account*;
  authenticated nav shows *Workspace*.

### Tests

- `test_auth.py` — 27 scenarios: registration, duplicate detection, email
  normalisation, invalid-email / short-password rejection, bcrypt-via-hash check,
  wrong-password rejection, login → me, login → logout → me (401), bearer-token
  scheme variants (Bearer / bearer / bare) and missing, malformed, unknown, or
  expired token rejection, all protected endpoints return 401 when
  unauthenticated, empty workspace for new users, cross-user isolation (list,
  direct-URL, operate all 404), same-user history persistence across
  logout/login, legacy unowned-run invisibility, and PostgreSQL compatibility
  (URL normalization onto psycopg, no SQLite-only migration on PostgreSQL,
  legacy-Migration idempotence on SQLite).
- All existing endpoint modules updated to use `authed_client` and
  `make_owned_run`.
- Full suite: **537 passed, 0 failed**.

A typed foundation for the whole system: core enums, structured models for
runs, queries, sources, candidates, profiles, evidence, contacts,
qualification, leads, and activity — plus a `FetchStatus` enum that replaces
the Phase 0 boolean with meaningful fetch outcomes.

A key architectural invariant established in Phase 1:

```text
EVIDENCE EXISTS != CLAIM VERIFIED
```

`Evidence` records that a value was observed in a real source (with a
mandatory `source_url`). Deciding whether evidence proves a criterion is a
future phase. Unknown values are always `None` — the system never guesses.
`verified_email` is optional; a contact exists before any email is known.

## The pipeline, end to end

Phases 0–11 implement the full autonomous pipeline:

```text
Discovery  (DiscoveryService → DiscoveryProvider → DDGSProvider)
    ↓
Sources  (Source / DiscoveredSource, URL normalization + dedup)
    ↓
Fetch validation (UrlFetcher with FetchStatus classification)
    ↓
Research (ResearchService → PageFetcher → parser → extractors)
    ↓
Extraction (CandidateExtractionService → CompanyCandidate + source-backed Evidence)
    ↓
Qualification (3 COMPANY criteria: financial → tech platform → US presence)
    ↓
Contact enrichment (supplementary only — never affects qualification)
    ↓
Lead assembly (persisted overall PASS only)
    ↓
Candidate analysis (company-qualified / near-qualified / not-qualified / not-evaluated)
    ↓
Run results (funnel + classification + readiness + leads + contacts)
```

Email *verification* is still intentionally absent — emails are extracted but
never verified, guessed, or attributed. The React frontend drives the pipeline
from a browser: run workspace, live monitoring, and final results.

## Current implementation

Every stage above is implemented and offline-testable: discovery, research,
extraction, qualification, contact & lead assembly, run completion, the
read-only results view, and the end-to-end orchestrator. Each section below
documents one phase; the "Downstream pipeline" example shows the run-level API,
and the Phase 8 frontend drives the same stages from a browser.

## Technology

| Layer        | Choice                                                |
| ------------ | ----------------------------------------------------- |
| Language     | Python 3.11+                                          |
| API          | FastAPI + Pydantic                                    |
| Discovery    | `ddgs` (DuckDuckGo search — **no API keys**)          |
| HTTP layer   | HTTPX (async, redirects, timeouts)                    |
| HTML parsing | BeautifulSoup 4 (stdlib `html.parser`, no lxml)       |
| Persistence  | SQLite + SQLAlchemy 2.x (repositories, no Alembic)    |
| Tests        | pytest (mocked / offline — no live internet required) |
| Frontend     | React 19 + TypeScript + Vite 8 (react-router-dom 7; hand-written CSS tokens) |

No API keys, no paid services, no external databases (SQLite file only), no
LLM APIs.

## Project layout

```
backend/
├── app/
│   ├── main.py                  # FastAPI app + endpoints + lifespan init_db
│   ├── core/
│   │   ├── config.py            # Settings; DATABASE_URL override, default sqlite:///./scoutiq.db
│   │   ├── enums.py             # all domain enums
│   │   └── constants.py         # shared defaults + target profile constants
│   ├── db/
│   │   ├── base.py              # DeclarativeBase + enum_column (non-native enums)
│   │   ├── session.py           # engine, SessionLocal, init_db, get_db dependency
│   │   ├── mappers.py           # single ORM ↔ Pydantic conversion layer
│   │   └── orm/                 # SQLAlchemy table definitions
│   │       ├── run.py           # runs + search_queries
│   │       ├── source.py        # sources (normalized_url unique)
│   │       ├── company.py       # company_candidates, company_profiles, leads
│   │       ├── evidence.py      # evidence
│   │       ├── contact.py       # contacts
│   │       ├── qualification.py # qualification_results + qualification_criteria
│   │       └── activity.py      # activity_events
│   ├── models/
│   │   ├── common.py            # id/datetime factories
│   │   ├── discovery.py         # Phase 0 discovery API models
│   │   ├── source.py            # Source + FetchValidation
│   │   ├── company.py           # CompanyCandidate + CompanyProfile
│   │   ├── evidence.py          # Evidence
│   │   ├── contact.py           # Contact
│   │   ├── qualification.py     # CriterionResult + QualificationResult
│   │   ├── lead.py              # QualifiedLead
│   │   ├── run.py               # DiscoveryRun + SearchQuery
│   │   └── activity.py          # ActivityEvent
│   ├── discovery/
│   │   ├── base.py              # DiscoveryProvider interface
│   │   ├── ddgs_provider.py     # DuckDuckGo zero-key provider
│   │   └── service.py           # orchestration, URL normalization, dedup
│   ├── extraction/
│   │   ├── models.py            # ExtractResult / ExtractionResult contracts
│   │   ├── service.py           # CandidateExtractionService: research → candidate + evidence
│   │   └── extractors/          # deterministic signal extractors (funding, revenue, …)
│   ├── research/
│   │   ├── models.py            # FetchRecord, PageMetadata, ResearchResult, …
│   │   ├── fetcher.py           # HTTPX fetch + URL validation + FetchStatus
│   │   ├── parser.py            # content-type gate + HTML parsing
│   │   ├── extractors/          # independent, deterministic extractors
│   │   │   ├── metadata.py      #   title/description/canonical/OG
│   │   │   ├── text.py          #   visible text (scripts/styles/nav removed)
│   │   │   ├── links.py         #   resolved, classified, deduplicated links
│   │   │   ├── emails.py        #   public emails — never verified
│   │   │   └── internal_pages.py#   keyword/path page classifier
│   │   └── service.py           # ResearchService orchestration
│   ├── qualification/
│   │   ├── service.py           # 3-CRITERION overall qualification + policy
│   │   ├── support.py           # normalize_money helper
│   │   └── evaluators/          # financial / tech platform / US presence
│   ├── contact/
│   │   ├── service.py           # ContactAssemblyService (evidence-backed, idempotent)
│   │   └── enrichment.py        # ContactEnrichmentService (readiness, supplementary)
│   ├── lead/
│   │   └── service.py           # LeadAssemblyService (QUALIFIED + PASS only)
│   ├── results/
│   │   ├── __init__.py
│   │   └── funnel.py            # run_funnel + contact_readiness_breakdown + candidate_analyses
│   ├── orchestration/
│   │   └── service.py           # PipelineOrchestrator + CANDIDATE_STATUS_FROM
│   └── repositories/
│   │   ├── run_repository.py    # runs: create/get/update/list
│   │   ├── query_repository.py  # run-associated search queries
│   │   ├── source_repository.py # sources + duplicate normalized URL handling
│   │   ├── company_repository.py# candidates, profiles, source links
│   │   ├── evidence_repository.py
│   │   ├── contact_repository.py
│   │   ├── qualification_repository.py  # one result per candidate
│   │   ├── lead_repository.py
│   │   └── activity_repository.py
├── requirements.txt
└── tests/
    ├── conftest.py              # path bootstrap + dev-DB integrity guard (session)
    ├── fakes.py                 # shared offline doubles (FakeAsyncClient, FakeResponse)
    ├── guard_helpers.py         # dev-database fingerprint guard (tests never touch it)
    ├── test_discovery.py        # Phase 0 regression (provider, dedup, fetch, API)
    ├── test_contracts.py        # Phase 1 model contracts
    ├── test_persistence.py      # Phase 2 persistence + endpoints (isolated SQLite)
    ├── test_research.py         # Phase 3 research engine (offline mocked HTTP)
    ├── test_extraction.py       # Phase 4 extraction + evidence (offline)
    ├── test_financial_qualification.py, test_tech_platform_qualification.py,
    │   test_us_presence_qualification.py   # Phase 5 company criterion evaluators
    ├── test_qualification_service.py  # Phase 5 overall qualification service
    ├── test_qualify_endpoint.py      # POST /api/runs/{id}/qualify
    ├── test_contact_pipeline.py      # Phase 6 contact assembly
    ├── test_lead_endpoint.py         # Phase 6 lead assembly endpoint
    ├── test_run_completion_endpoint.py  # POST /api/runs/{id}/complete
    ├── test_run_results_endpoint.py  # Phase 7 GET /api/runs/{id}/results
    ├── test_pipeline_orchestration.py # Phase 7 PipelineOrchestrator (+ execute endpoint)
    ├── test_contact_readiness.py     # Phase 9 readiness tracking
    ├── test_email_attribution_qualification.py  # legacy criteria (retained, not in contract)
    ├── test_run_funnel.py            # Phase 10 funnel + readiness breakdown
    ├── test_candidate_analysis.py    # Phase 11 candidate classification
    ├── test_run_diagnostics.py       # run diagnostics snapshot
    ├── test_audit_regressions.py     # cross-contract regression guardrails
    └── test_leadership_qualification.py  # legacy criteria (retained, not in contract)

frontend/
├── index.html                   # theme no-FOUC bootstrap + app mount
├── package.json                 # scripts: dev / typecheck / build / preview
├── vite.config.ts               # dev server + /api, /health proxy to :8000
├── tsconfig.json
├── .env.example                 # VITE_API_BASE_URL (empty = same-origin)
└── src/
    ├── main.tsx                 # StrictMode → ThemeProvider → BrowserRouter → App
    ├── App.tsx                  # routes + AppShell layout (sidebar + theme toggle)
    ├── api/                     # typed client; VITE_API_BASE_URL ?? "" (same-origin)
    ├── hooks/                   # useRuns · useRun (poll-while-active) · useRunResults
    ├── pages/                   # RunsPage · NewRunPage · RunDetailPage · RunResultsPage · NotFoundPage
    ├── components/
    │   ├── runs/                # RunStatusBadge · LeadsTable · ContactsList · AnalysisTable ·
    │   │                        # CandidateCriteriaStatus · ContactReadinessBadge
    │   ├── layout/              # AppShell
    │   └── ui/                  # Card · Metric · Badge · SectionHeader · EmptyState · …
    ├── theme/                   # tokens.css (palettes) · base.css · ThemeProvider
    └── utils/                   # formatting + unknown-value fallbacks

TEST_QUERIES.txt                # root-level manual test query sets (see below)
```

## Core models (Phase 1)

- **DiscoveryRun** — one autonomous execution lifecycle: `run_id`, `status`,
  target/qualified lead counts, timestamps, `current_phase`, `error_message`.
- **SearchQuery** — a recorded search attempt (agent memory groundwork):
  `query_id`, `run_id`, text, strategy, provider, result count, error.
- **Source** — any web source (discovered or researched): URL, normalized URL,
  title, snippet, domain, provider, discovery time, fetch status, HTTP status,
  final redirect URL, content type. `DiscoveredSource` adds the query text.
- **CompanyCandidate** — discovered, not yet qualified: company name, website,
  discovery sources, lifecycle status.
- **CompanyProfile** — accumulated unadjudicated info (description, sector,
  location, funding/revenue USD), never a qualification decision.
- **Evidence** — a traceable, source-backed observation; `source_url` required.
- **Contact** — a person (name, role, optional email, verification status);
  exists before any email is known.
- **QualificationResult** — independent criterion decisions
  (funding/revenue, tech platform, US presence, contact availability) each
  `PASS`/`FAIL`/`INSUFFICIENT_EVIDENCE`/`NOT_EVALUATED`, plus overall status.
  Can represent partial evidence without silently becoming `PASS`.
- **QualifiedLead** — future TVB-facing output; `verified_email` optional.
- **ActivityEvent** — live agent-feed events (`run_id`, `phase`, `event_type`,
  message, related candidate/source).

## Common values

`FetchStatus` classification: `SUCCESS`, `ACCESS_BLOCKED` (401/403),
`RATE_LIMITED` (429), `NOT_FOUND` (404/410), `SERVER_ERROR` (5xx), `TIMEOUT`,
`NETWORK_ERROR`, `UNKNOWN_ERROR`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

## Run the backend

```bash
cd backend
uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"ScoutIQ Discovery API","provider":"duckduckgo"}
```

Contracts metadata:

```bash
curl http://127.0.0.1:8000/api/system/contracts
# {"service":"scoutiq-core","models":["DiscoveryRun", ...],
#  "enums":{"RunStatus":["pending", ...], "FetchStatus":[...], ...}}
```

## Run the frontend

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173
```

The Vite dev server proxies `/api` and `/health` to
`http://127.0.0.1:8000`, so the browser only ever sees same-origin relative URLs
in development (the backend also carries a CORS allowlist for credentialed
cross-origin deployments). Start the backend first.

Production build (type-checks, then bundles to `frontend/dist`):

```bash
npm run build
npm run preview
```

When the built assets are served separately from the backend, set
`VITE_API_BASE_URL` to the backend origin (see `frontend/.env.example`).

## Example API requests

Discovery only:

```bash
curl -X POST http://127.0.0.1:8000/api/discovery/search \
  -H "Content-Type: application/json" \
  -d '{
    "queries": [
      "Southeast Asia fintech platform startup funding",
      "Africa SaaS platform startup seed funding",
      "Europe B2B technology platform raised funding"
    ],
    "max_results_per_query": 5
  }'
```

Discovery + fetch validation:

```bash
curl -X POST http://127.0.0.1:8000/api/discovery/validate \
  -H "Content-Type: application/json" \
  -d '{"queries": ["India enterprise software platform funding"],
       "max_results_per_query": 5,
       "max_urls_to_validate": 8}'
```

Each discovered result is a `Source`-compatible object now carrying
`source_id`, `normalized_url`, and `domain` in addition to the Phase 0 fields.

## Research (Phase 3)

Research a URL directly:

```bash
curl -X POST http://127.0.0.1:8000/api/research/url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

```bash
# Returns
{
  "source_url": "https://example.com",
  "final_url": "https://example.com",
  "fetch_status": "success",
  "http_status_code": 200,
  "content_type": "text/html; charset=utf-8",
  "html_extracted": true,
  "extraction_skip_reason": null,
  "metadata": { "title": ..., "meta_description": ..., "canonical_url": ...,
                "og_title": ..., "og_description": ..., "og_site_name": ... },
  "visible_text": "...",
  "links": [ { "original_href": ..., "resolved_url": ..., "anchor_text": ...,
               "is_internal": true } ],
  "emails": [ { "email": ..., "context": ..., "verification_status": "unverified" } ],
  "relevant_internal_pages": [ { "url": ..., "anchor_text": ..., "category": "about" } ],
  "researched_at": ...,
  "error": null
}
```

Research a persisted source (updates its stored fetch metadata):

```bash
curl -X POST http://127.0.0.1:8000/api/research/source/{source_id}
```

Research tuning (all optional env vars): `RESEARCH_TIMEOUT_SECONDS` (default
`8.0`), `RESEARCH_MAX_RESPONSE_BYTES` (default `2000000`). A response over the
byte limit is still classified but its body/extraction is skipped.

## Persistence (Phase 2)

SQLite file (default `scoutiq.db` in the directory you launch from). Override
with the `DATABASE_URL` env var, e.g.:

```bash
set DATABASE_URL=sqlite:///C:/data/scoutiq.db   # PowerShell
export DATABASE_URL=sqlite:////data/scoutiq.db  # bash
```

Tables are created automatically on startup (lifespan `init_db()`), no
migrations tool. Run endpoints (proof of persistence):

```bash
curl -X POST http://127.0.0.1:8000/api/runs -H "Content-Type: application/json" -d '{"target_lead_count": 10}'
curl http://127.0.0.1:8000/api/runs
curl http://127.0.0.1:8000/api/runs/{run_id}
curl http://127.0.0.1:8000/api/runs/{run_id}/activity
```

Design decisions:

- Enums stored as controlled `member.value` strings (non-native) and convert
  back through Pydantic — a DB value always maps to a valid enum or `NULL`.
- Unknown values are `NULL`, never empty strings; contacts/leads may have no
  email.
- `Evidence.source_url` is required; no uniqueness on `claim` so several
  sources can back (or contradict) the same claim until adjudication.
- Duplicate `normalized_url` sources collapse to the existing row.
- Re-qualifying a candidate replaces its previous qualification row.
- ORM objects never appear in API responses.

## Downstream pipeline (Phases 5–7)

Qualify candidates in a run against their persisted evidence:

```bash
curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/qualify \
  -H "Content-Type: application/json" \
  -d '{"candidate_ids": ["<candidate_id>"]}'
# {"run_id": "...", "results": [{"candidate_id": "...", "overall_status": "pass", "criteria": [...], ...}]}
```

Assemble evidence-backed contacts and qualified leads (eligibility enforced —
contacts require a named leader in evidence; leads require `QUALIFIED` + overall
`PASS`):

```bash
curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/contacts \
  -H "Content-Type: application/json" -d '{"candidate_ids": ["<candidate_id>"]}'
curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/leads \
  -H "Content-Type: application/json" -d '{"candidate_ids": ["<candidate_id>"]}'
```

Finalize a run (recomputes `qualified_lead_count` from persisted leads) and
read its final output:

```bash
curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/complete
curl http://127.0.0.1:8000/api/runs/{run_id}/results
# {"run": {"status": "completed", "qualified_lead_count": 1, ...},
#  "leads": [...], "contacts": [...]}
```

Run the whole pipeline for a run in one call (live network required):

```bash
curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/execute \
  -H "Content-Type: application/json" \
  -d '{"queries": ["Berlin B2B software platform funding"], "max_results_per_query": 5}'
```

## Tests

From the repo root, using the project venv:

```bash
.venv/Scripts/python -m pytest -q   # collects backend/tests (537 tests)
```

Expected: **537 passed, 0 failed**. The suite is fully offline — discovery
uses in-memory providers, HTTP fetching uses a fake async client with canned
responses, and every persistence test uses an isolated temp SQLite file. A
session-level guard (`backend/tests/guard_helpers.py`) fingerprints the
developer's `backend/scoutiq.db` at session start and asserts, in selected
tests and session teardown, that it is untouched — the tests never create,
modify, or depend on the developer database, and the suite stays green whether
that file is present (from live API use) or absent. Orchestration tests
inject fake discovery providers and fetchers, so the happy path of the
`execute` endpoint is exercised through the orchestrator (its 404/422 routing
is also covered). The frontend is gated by `npm run typecheck` and
`npm run build` (from `frontend/`).

`pytest.ini` at the repo root pins `testpaths = backend/tests` and the
`pythonpath` entries so the `app` package and the shared `fakes.py` helper
import cleanly under modern pytest.

## Manual testing with `TEST_QUERIES.txt`

The root-level `TEST_QUERIES.txt` groups real, copy-paste search queries for
manual end-to-end runs: funding/revenue wording variations ($1M–$5M), regional
surveys (South Asia, Europe, APAC, LATAM), high-signal funding phrases, and
three ready-made **Demo Set A/B/C** batches. Results depend on currently
available web evidence and source accessibility, so exact outputs vary between
runs and a healthy run may produce zero qualified leads — the funnel and
per-candidate criteria analysis explain why.

## Known limitations

- `DDGS` is a free, zero-key provider: results can be throttled, vary run to
  run, and DuckDuckGo may alter its response format. Provider isolation exists
  behind the `DiscoveryProvider` interface and per-query failures are caught.
- Some sites return `403`/`429`/`5xx` to a browser-like fetcher and are
  classified via `FetchStatus` rather than failing the run.
- Research is an engine, not a crawler: links are extracted, never followed
  recursively; content types are limited to HTML/XHTML; the internal page
  classifier is deterministic keyword/path heuristics and may mis-categorize
  unusual site structures; extracted emails are candidates, never verified.
- Extraction extracts, never adjudicates. Funding/revenue figures are
  persisted with their explicit unit/USD markers so the financial criterion
  *can* pass from research→extraction evidence, but only when the source truly
  carries a figure in the $1M–$5M range (in USD-normalized terms).
- Emails are never guessed, verified, or attributed to a person/role; a
  qualified lead carries an optional, still-`UNVERIFIED` email and may hold no
  leadership name at all — a lead is not removed because contact data is
  missing.
- `POST /api/runs/{id}/execute` drives the real DuckDuckGo provider and
  fetcher, so a live end-to-end execution needs the network; failure isolation
  keeps per-source problems from sinking the run. Live runs can legitimately
  finish with zero qualified leads; the funnel and candidate analysis report
  the honest outcome.
- The `/api/research/*` and `/api/discovery/*` endpoints remain public
  (unauthenticated); run-scoped and extraction endpoints are protected.
- Auth is bearer-token based: no cookies are set or read, so no
  SameSite/Secure cookie configuration is needed for any deployment. The token
  is a server-side session UUID in `auth_sessions`, sent over HTTPS only, and
  revoked server-side on logout.
- Not implemented by design: email guessing/verification, OAuth/social login,
  teams, RBAC beyond per-user ownership, and any billing integration.
- The frontend has no automated browser test runner; it is gated by `npm run
  typecheck` and `npm run build`, with rendered UI validated manually across
  light/dark themes and desktop/tablet/mobile viewports.