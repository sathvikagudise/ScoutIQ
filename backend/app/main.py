"""ScoutIQ FastAPI application — discovery + contracts + persistence + research."""

import logging
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.service import (
    MIN_PASSWORD_LENGTH,
    authenticate,
    create_session,
    create_user,
    delete_session,
    get_current_user,
    get_session_token,
    is_valid_email,
    normalize_email,
    require_owned_run,
)
from app.core.config import settings
from app.core.constants import DEFAULT_MAX_RESULTS_PER_QUERY, MAX_RESULTS_CAP
from app.core.enums import (
    ActivityEventType,
    CandidateStatus,
    ContactReadiness,
    EvidenceType,
    FetchStatus,
    QualificationCriterion,
    QualificationStatus,
    RunPhase,
    RunStatus,
    VerificationStatus,
)
from app.db.session import get_db, init_db
from app.discovery.ddgs_provider import DDGSProvider
from app.discovery.service import DiscoveryService
from app.extraction.models import ExtractionResult
from app.extraction.service import CandidateExtractionService, own_site_host
from app.models.activity import ActivityEvent
from app.models.company import CompanyCandidate, CompanyProfile
from app.models.common import new_id, utcnow
from app.models.contact import Contact
from app.models.contact_enrichment import ContactEnrichment
from app.models.discovery import (
    DiscoveryRequest,
    DiscoveryResponse,
    ValidateRequest,
    ValidateResponse,
    ValidatedResult,
)
from app.models.evidence import Evidence
from app.models.lead import QualifiedLead
from app.models.qualification import QualificationResult
from app.models.run import DiscoveryRun, SearchQuery
from app.models.source import Source
from app.models.user import AuthResponse, User, UserLogin, UserRegister
from app.orchestration.service import CANDIDATE_STATUS_FROM, PipelineOrchestrator
from app.results.funnel import (
    candidate_analyses,
    candidate_summary,
    contact_readiness_breakdown,
    run_funnel,
)
from app.contact.service import ContactAssemblyService
from app.lead.service import LeadAssemblyService
from app.qualification.service import qualify
from app.repositories.activity_repository import ActivityRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository
from app.research.fetcher import UrlFetcher
from app.research.models import ResearchResult
from app.research.service import ResearchService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="ScoutIQ Discovery API",
    version="0.5.0",
    lifespan=lifespan,
    description=(
        "Phase 0 discovery PoC (zero API keys), Phase 1 core data contracts, "
        "Phase 2 SQLite persistence, Phase 3 web research & scraping engine, "
        "Phase 4 candidate extraction & evidence collection, "
        "Phases 5-7 qualification, contact & lead assembly, run results, "
        "and end-to-end pipeline orchestration."
    ),
)

# Requests from the configured trusted frontend origins only. Wildcards are
# never used; production deploys with a separate frontend origin must set
# CORS_ORIGINS (comma-separated) explicitly. Bearer-token auth also requires
# the Authorization header to be allowed by preflight (allow_headers ["*"]).
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Placeholder wiring: swap DDGSProvider for another provider here, nothing else changes.
discovery_service = DiscoveryService(DDGSProvider())
url_fetcher = UrlFetcher()
research_service = ResearchService(
    fetcher=UrlFetcher(
        timeout=settings.research_timeout_seconds,
        max_response_bytes=settings.research_max_response_bytes,
    )
)

# Registry of Phase 1 core contracts, exposed for verification via /api/system/contracts.
CORE_MODELS = (
    DiscoveryRun,
    SearchQuery,
    Source,
    CompanyCandidate,
    CompanyProfile,
    Evidence,
    Contact,
    ContactEnrichment,
    QualificationResult,
    QualifiedLead,
    ActivityEvent,
)
CORE_ENUMS = (
    RunStatus,
    RunPhase,
    CandidateStatus,
    QualificationCriterion,
    QualificationStatus,
    EvidenceType,
    FetchStatus,
    VerificationStatus,
    ContactReadiness,
    ActivityEventType,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Confirm the backend is running."""
    return {
        "status": "ok",
        "service": app.title,
        "provider": discovery_service.provider.name,
    }


# ---------------------------------------------------------------------------
# Authentication (Phase 14): email/password accounts + server-side sessions.
# Passwords are hashed with bcrypt and never returned, logged, or stored on
# the client. Register/login return a short-lived bearer token (a server-side
# session UUID) once; the client echoes it as ``Authorization: Bearer <token>``
# on every later request. Logout revokes that session server-side.
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
async def register_user(
    request: UserRegister,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """Create an account and start a session.

    The new user's workspace is empty — they never see legacy or other users'
    runs. Successful registration also logs the user in (fresh bearer token).
    """
    email = normalize_email(request.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    if len(request.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )

    user = create_user(
        db, email=email, password=request.password, display_name=request.display_name
    )
    session = create_session(db, user.user_id)
    return AuthResponse(token=str(session.id), user=user)


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_user(
    request: UserLogin,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """Verify email + password and start a session (fresh bearer token)."""
    user = authenticate(db, email=request.email, password=request.password)
    if user is None:
        # Deliberately identical for unknown email vs wrong password.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    session = create_session(db, user.user_id)
    return AuthResponse(token=str(session.id), user=user)


@app.post("/api/auth/logout", status_code=204)
async def logout_user(
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Revoke the server-side session for the presented token.

    Works even without a valid token, so a stale token never lingers.
    """
    token_value = get_session_token(request)
    if token_value:
        try:
            delete_session(db, UUID(token_value))
        except ValueError:
            pass


@app.get("/api/auth/me", response_model=User)
async def auth_me(user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user (401 when logged out)."""
    return user


@app.post("/api/discovery/search", response_model=DiscoveryResponse)
async def discovery_search(request: DiscoveryRequest) -> DiscoveryResponse:
    """Discover web sources for one or more queries (deduplicated)."""
    return await discovery_service.discover(request.queries, request.max_results_per_query)


@app.post("/api/discovery/validate", response_model=ValidateResponse)
async def discovery_validate(request: ValidateRequest) -> ValidateResponse:
    """Discover sources, then validate a sample of URLs over HTTP."""
    response = await discovery_service.discover(request.queries, request.max_results_per_query)

    validations = await url_fetcher.validate(
        [result.url for result in response.results], request.max_urls_to_validate
    )
    by_url = {validation.url: validation for validation in validations}

    validated = [
        ValidatedResult(source=result, validation=by_url[result.url])
        for result in response.results
        if result.url in by_url
    ]

    return ValidateResponse(**response.model_dump(), validations=validated)


@app.get("/api/system/contracts")
async def system_contracts() -> dict[str, Any]:
    """Metadata about the core data contracts (models + enums)."""
    return {
        "service": "scoutiq-core",
        "models": [model.__name__ for model in CORE_MODELS],
        "enums": {enum.__name__: [member.value for member in enum] for enum in CORE_ENUMS},
    }


class CreateRunRequest(BaseModel):
    """Request body for POST /api/runs."""

    target_lead_count: int = Field(default=10, ge=0)


@app.post("/api/runs", response_model=DiscoveryRun, status_code=201)
async def create_run(
    request: CreateRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiscoveryRun:
    """Create a new DiscoveryRun owned by the authenticated user."""
    run = DiscoveryRun(target_lead_count=request.target_lead_count, user_id=user.user_id)
    return RunRepository(db).create(run)


@app.get("/api/runs", response_model=list[DiscoveryRun])
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DiscoveryRun]:
    """Return the authenticated user's runs, newest first (their workspace only)."""
    return RunRepository(db).list_by_user(user.user_id, limit=limit)


@app.get("/api/runs/{run_id}", response_model=DiscoveryRun)
async def get_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiscoveryRun:
    """Return a run owned by the authenticated user (404 for foreign/legacy)."""
    return require_owned_run(run_id, db, user)


@app.get("/api/runs/{run_id}/activity", response_model=list[ActivityEvent])
async def get_run_activity(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ActivityEvent]:
    """Return an owned run's activity events chronologically."""
    require_owned_run(run_id, db, user)
    return ActivityRepository(db).list_by_run_chronological(run_id)


class ResearchUrlRequest(BaseModel):
    """Request body for POST /api/research/url."""

    url: str


@app.post("/api/research/url", response_model=ResearchResult)
async def research_url(request: ResearchUrlRequest) -> ResearchResult:
    """Fetch one URL and return structured research material."""
    return await research_service.research_url(request.url)


@app.post("/api/research/source/{source_id}", response_model=ResearchResult)
async def research_source(
    source_id: UUID, db: Session = Depends(get_db)
) -> ResearchResult:
    """Research a persisted source, then update its stored fetch metadata."""
    source_repo = SourceRepository(db)
    source = source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    result = await research_service.research_source(source_id, source_repo)
    if result is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return result


class ExtractionResearchRequest(BaseModel):
    """Request body for POST /api/extraction/research."""

    source_id: UUID
    run_id: Optional[UUID] = None


class ExtractionFromResearchRequest(BaseModel):
    """Request body for POST /api/extraction/from-research."""

    research: ResearchResult
    run_id: Optional[UUID] = None
    source_id: Optional[UUID] = None
    source_title: Optional[str] = None


@app.post("/api/extraction/research", response_model=ExtractionResult)
async def extraction_research(
    request: ExtractionResearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExtractionResult:
    """Research a persisted source, then extract + persist candidate evidence.

    When a ``run_id`` is supplied it must belong to the authenticated user;
    otherwise the request is rejected (404) so one user can never write
    candidates into another user's or a legacy run.
    """
    if request.run_id is not None:
        require_owned_run(request.run_id, db, user)
    source_repo = SourceRepository(db)
    source = source_repo.get(request.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    result = await research_service.research_source(request.source_id, source_repo)
    if result is None:
        raise HTTPException(status_code=404, detail="Source not found")

    return CandidateExtractionService(db).extract_and_persist(
        result,
        run_id=request.run_id,
        source_id=source.source_id,
        source_title=source.title,
    )


@app.post("/api/extraction/from-research", response_model=ExtractionResult)
async def extraction_from_research(
    request: ExtractionFromResearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExtractionResult:
    """Extract + persist candidate evidence from a client-supplied research result.

    When a ``run_id`` is supplied it must belong to the authenticated user;
    otherwise the request is rejected (404).
    """
    if request.run_id is not None:
        require_owned_run(request.run_id, db, user)
    return CandidateExtractionService(db).extract_and_persist(
        request.research,
        run_id=request.run_id,
        source_id=request.source_id,
        source_title=request.source_title,
    )


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------


class QualifyRequest(BaseModel):
    """Request body for POST /api/runs/{run_id}/qualify."""

    candidate_ids: list[UUID] = Field(..., min_length=1)


class QualifyResponse(BaseModel):
    """Qualification results for all requested candidates, preserving input order."""

    run_id: UUID
    results: list[QualificationResult]


@app.post("/api/runs/{run_id}/qualify", response_model=QualifyResponse)
async def qualify_candidates(
    run_id: UUID,
    request: QualifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QualifyResponse:
    """Qualify each requested candidate against persisted evidence."""
    require_owned_run(run_id, db, user)

    company_repo = CompanyRepository(db)
    evidence_repo = EvidenceRepository(db)
    qualification_repo = QualificationRepository(db)

    results: list[QualificationResult] = []
    for candidate_id in request.candidate_ids:
        candidate = company_repo.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate.run_id != run_id:
            raise HTTPException(status_code=404, detail="Candidate not found in run")

        evidence = evidence_repo.list_by_candidate(candidate_id)
        own_host = own_site_host(candidate)
        result = qualify(
            candidate_id,
            evidence,
            company_hosts={own_host} if own_host else set(),
        )
        qualification_repo.save(result)

        company_repo.set_candidate_status(
            candidate_id, CANDIDATE_STATUS_FROM[result.overall_status]
        )

        results.append(result)

    return QualifyResponse(run_id=run_id, results=results)


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


class GenerateContactsRequest(BaseModel):
    """Request body for POST /api/runs/{run_id}/contacts."""

    candidate_ids: list[UUID] = Field(..., min_length=1)


class GenerateContactsResponse(BaseModel):
    """Assembled, persisted evidence-backed contacts, preserving input order."""

    run_id: UUID
    contacts: list[Contact]


@app.post("/api/runs/{run_id}/contacts", response_model=GenerateContactsResponse)
async def generate_contacts(
    run_id: UUID,
    request: GenerateContactsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GenerateContactsResponse:
    """Assemble an evidence-backed contact for each named leader in the run.

    A contact is created only when persisted evidence names a leader
    (CEO / Co-Founder / Founder) for the candidate. Re-generating contacts is
    idempotent: an existing contact with the identical ``(full_name, role)``
    for a candidate is returned, never duplicated.
    """
    require_owned_run(run_id, db, user)

    company_repo = CompanyRepository(db)
    contact_service = ContactAssemblyService(db)

    contacts: list[Contact] = []
    for candidate_id in request.candidate_ids:
        candidate = company_repo.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate.run_id != run_id:
            raise HTTPException(status_code=404, detail="Candidate not found in run")
        contacts.extend(contact_service.assemble(candidate_id, candidate=candidate))

    return GenerateContactsResponse(run_id=run_id, contacts=contacts)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


class GenerateLeadsRequest(BaseModel):
    """Request body for POST /api/runs/{run_id}/leads."""

    candidate_ids: list[UUID] = Field(..., min_length=1)


class GenerateLeadsResponse(BaseModel):
    """Assembled, persisted qualified leads, preserving input order."""

    run_id: UUID
    leads: list[QualifiedLead]


@app.post("/api/runs/{run_id}/leads", response_model=GenerateLeadsResponse)
async def generate_leads(
    run_id: UUID,
    request: GenerateLeadsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GenerateLeadsResponse:
    """Assemble a qualified lead for each eligible candidate in the run.

    A candidate is eligible only when it is QUALIFIED and its persisted
    qualification decision is PASS. Ineligible candidates fail the request
    explicitly rather than silently producing a lead.
    """
    require_owned_run(run_id, db, user)

    company_repo = CompanyRepository(db)
    qualification_repo = QualificationRepository(db)
    lead_repo = LeadRepository(db)
    lead_service = LeadAssemblyService(db)

    leads: list[QualifiedLead] = []
    for candidate_id in request.candidate_ids:
        candidate = company_repo.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate.run_id != run_id:
            raise HTTPException(status_code=404, detail="Candidate not found in run")
        if candidate.status != CandidateStatus.QUALIFIED:
            raise HTTPException(status_code=409, detail="Candidate not qualified")

        qualification = qualification_repo.get_by_candidate(candidate_id)
        if qualification is None:
            raise HTTPException(status_code=409, detail="Qualification not found")
        if qualification.overall_status != QualificationStatus.PASS:
            raise HTTPException(
                status_code=409, detail="Candidate qualification is not PASS"
            )

        lead = lead_service.assemble(candidate, qualification)
        leads.append(lead_repo.replace_for_candidate(lead))

    return GenerateLeadsResponse(run_id=run_id, leads=leads)


# ---------------------------------------------------------------------------
# Run completion
# ---------------------------------------------------------------------------


@app.post("/api/runs/{run_id}/complete", response_model=DiscoveryRun)
async def complete_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiscoveryRun:
    """Finalize a run from its persisted state.

    The final ``qualified_lead_count`` is recomputed from the persisted lead
    rows (``LeadRepository.list_by_run``) and never trusted from request input,
    candidate counts, or a prior run value. Completion is idempotent: calling it
    again recomputes the same final state and never creates, deletes, or
    duplicates leads, contacts, qualifications, or candidates.
    """
    require_owned_run(run_id, db, user)

    qualified_lead_count = len(LeadRepository(db).list_by_run(run_id))

    return RunRepository(db).update_progress(
        run_id,
        status=RunStatus.COMPLETED,
        qualified_lead_count=qualified_lead_count,
        completed_at=utcnow(),
    )


# ---------------------------------------------------------------------------
# Run results
# ---------------------------------------------------------------------------


class RunFunnel(BaseModel):
    """Pipeline funnel counts for one run, from persisted state only.

    ``sources_researched`` counts sources whose persisted fetch succeeded (the
    only per-source outcome this backend records) — it is NOT a claim that every
    page was "fully processed". Criterion pass counts are per-criterion over the
    run's evaluated candidates and may overlap (a candidate can pass several
    criteria), so they must not be read as a strict sequential funnel.
    """

    sources_discovered: int
    sources_researched: int
    candidates_extracted: int
    candidates_evaluated: int
    financial_pass: int
    tech_pass: int
    geography_pass: int
    company_qualified: int


class ContactReadinessBreakdown(BaseModel):
    """Persisted-lead breakdown by contact readiness (legacy leads = not_enriched)."""

    evidenced_contact: int = 0
    named_contact_no_email: int = 0
    public_email_available: int = 0
    company_contact_available: int = 0
    no_contact_found: int = 0
    not_enriched: int = 0


class CriterionResultSummary(BaseModel):
    """A candidate's persisted outcome for one company criterion.

    ``status`` is the persisted criterion status verbatim (``none`` when no
    criterion row was ever persisted); ``reasons`` are the persisted reasons
    only. Nothing is recomputed or inferred here.
    """

    status: str
    reasons: list[str] = []


class BlockingCriterion(BaseModel):
    """A criterion that blocked qualification, from persisted status only.

    ``status`` is the persisted FAIL or INSUFFICIENT_EVIDENCE value; the UI
    renders FAIL as a failed criterion and INSUFFICIENT_EVIDENCE as missing
    evidence. A FAIL is never rewritten as "missing evidence".
    """

    criterion: str
    status: str
    reasons: list[str] = []


class CandidateAnalysis(BaseModel):
    """Product-facing analysis of one run candidate (deterministic).

    Everything is persisted state: candidate identity, profile description and
    industry when present, the persisted per-criterion statuses/reasons, the
    persisted overall qualification status (``None`` when no decision was ever
    persisted), the passed-criteria count, and the derived classification.
    Classification is derived only from persisted values:
    company_qualified (overall PASS), near_qualified (exactly two PASS, not
    overall PASS), not_qualified (anything else with a decision), not_evaluated
    (no persisted decision — never "failed").
    """

    candidate_id: UUID
    company_name: str
    description: Optional[str] = None
    industry_or_sector: Optional[str] = None
    classification: Literal[
        "company_qualified", "near_qualified", "not_qualified", "not_evaluated"
    ]
    overall_status: Optional[str] = None
    passed_criteria_count: int = 0
    criteria: dict[str, CriterionResultSummary]
    blocking_criteria: list[BlockingCriterion]


class CandidateSummary(BaseModel):
    """Counts of run candidates by classification (deterministic).

    ``near_qualified`` is a separate bucket and never contributes to the run's
    qualified-lead count; contact readiness never influences these counts.
    """

    company_qualified: int = 0
    near_qualified: int = 0
    not_qualified: int = 0
    not_evaluated: int = 0
    analyzed_total: int = 0


class RunResults(BaseModel):
    """Read-only snapshot of a run's persisted final output.

    Only persisted state is returned: existing domain models are reused
    directly, no derived value is synthesized, and optional fields that were
    never persisted stay ``None``. ``funnel``, ``contact_breakdown``,
    ``candidate_summary`` and ``candidates`` are deterministic counts/views
    over persisted rows — they never invent outcomes.
    """

    run: DiscoveryRun
    funnel: RunFunnel
    contact_breakdown: ContactReadinessBreakdown
    candidate_summary: CandidateSummary
    candidates: list[CandidateAnalysis]
    leads: list[QualifiedLead]
    contacts: list[Contact]


@app.get("/api/runs/{run_id}/results", response_model=RunResults)
async def get_run_results(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResults:
    """Retrieve an owned run's persisted final output (read-only).

    Candidates belong to the run through the persisted ``run_id`` attribute
    (``CompanyRepository.list_candidates`` ordering preserved), contacts belong
    to candidates through the persisted ``candidate_id`` attribute
    (``ContactRepository.list_by_candidate`` ordering preserved), and leads are
    read directly by run (``LeadRepository.list_by_run`` ordering preserved).
    ``candidate_summary`` and ``candidates`` are the run's persisted candidate
    analyses (see ``CandidateAnalysis``). Nothing is inferred, fabricated, or
    written.
    """
    run = require_owned_run(run_id, db, user)

    leads = LeadRepository(db).list_by_run(run_id)

    company_repo = CompanyRepository(db)
    contact_repo = ContactRepository(db)
    contacts: list[Contact] = []
    for candidate in company_repo.list_candidates():
        if candidate.run_id == run_id:
            contacts.extend(contact_repo.list_by_candidate(candidate.candidate_id))

    analyses = candidate_analyses(db, run_id)
    candidates = [
        CandidateAnalysis(
            candidate_id=item["candidate_id"],
            company_name=item["company_name"],
            description=item["description"],
            industry_or_sector=item["industry_or_sector"],
            classification=item["classification"],
            overall_status=item["overall_status"],
            passed_criteria_count=item["passed_criteria_count"],
            criteria={
                key: CriterionResultSummary(**value)
                for key, value in item["criteria"].items()
            },
            blocking_criteria=[
                BlockingCriterion(**blocker) for blocker in item["blocking_criteria"]
            ],
        )
        for item in analyses
    ]

    return RunResults(
        run=run,
        funnel=RunFunnel(**run_funnel(db, run_id)),
        contact_breakdown=ContactReadinessBreakdown(**contact_readiness_breakdown(db, run_id)),
        candidate_summary=CandidateSummary(**candidate_summary(analyses)),
        candidates=candidates,
        leads=leads,
        contacts=contacts,
    )


# ---------------------------------------------------------------------------
# Run diagnostics
# ---------------------------------------------------------------------------


class CandidateDiagnostics(BaseModel):
    """Per-candidate diagnostic snapshot for one run (reused domain models).

    ``qualification`` is the current qualification decision computed from the
    candidate's persisted evidence (read-only: never persisted by this
    endpoint), so cross-criterion funnel analysis can run against live data.
    """

    candidate: CompanyCandidate
    profile: Optional[CompanyProfile] = None
    evidence: list[Evidence]
    qualification: QualificationResult
    contacts: list[Contact]


class RunDiagnostics(BaseModel):
    """Read-only full funnel snapshot for one run.

    Candidates belong to the run through the persisted ``run_id``; contacts
    belong to runs through their candidate; leads are read directly by run.
    Only persisted state is included plus the on-the-fly qualification for each
    candidate. Nothing is written.
    """

    run: DiscoveryRun
    candidates: list[CandidateDiagnostics]
    leads: list[QualifiedLead]


@app.get("/api/runs/{run_id}/diagnostics", response_model=RunDiagnostics)
async def get_run_diagnostics(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunDiagnostics:
    """Retrieve an owned run's full persisted funnel snapshot (read-only).

    For every candidate in the run: the candidate, its profile, its persisted
    evidence, its current qualification decision computed from that evidence
    (``qualify(candidate_id, evidence)``, never written), and its persisted
    contacts. Leads for the run are returned as persisted. State validation and
    ordering preserve repository conventions.
    """
    run = require_owned_run(run_id, db, user)

    company_repo = CompanyRepository(db)
    evidence_repo = EvidenceRepository(db)
    contact_repo = ContactRepository(db)

    candidates = [
        candidate
        for candidate in company_repo.list_candidates()
        if candidate.run_id == run_id
    ]
    items: list[CandidateDiagnostics] = []
    for candidate in candidates:
        evidence = evidence_repo.list_by_candidate(candidate.candidate_id)
        own_host = own_site_host(candidate)
        items.append(
            CandidateDiagnostics(
                candidate=candidate,
                profile=company_repo.get_profile(candidate.candidate_id),
                evidence=evidence,
                qualification=qualify(
                    candidate.candidate_id,
                    evidence,
                    company_hosts={own_host} if own_host else set(),
                ),
                contacts=contact_repo.list_by_candidate(candidate.candidate_id),
            )
        )

    return RunDiagnostics(
        run=run,
        candidates=items,
        leads=LeadRepository(db).list_by_run(run_id),
    )


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


class RunExecuteRequest(BaseModel):
    """Request body for POST /api/runs/{run_id}/execute."""

    queries: list[str] = Field(default_factory=list, min_length=0)
    max_results_per_query: int = Field(
        default=DEFAULT_MAX_RESULTS_PER_QUERY, ge=1, le=MAX_RESULTS_CAP
    )
    generate_queries: bool = Field(
        default=False,
        description=(
            "When true, ignore ``queries`` and generate the deterministic "
            "stratified discovery-query set (each query persists its strategy)."
        ),
    )


@app.post("/api/runs/{run_id}/execute", response_model=RunResults)
async def execute_run(
    run_id: UUID,
    request: RunExecuteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResults:
    """Run the full pipeline for an owned run: discovery, research, extraction,
    qualification, contacts, leads, and completion.

    The orchestrator reuses the board-injected discovery provider and web
    fetcher, drives every existing service verbatim, and returns the run's
    final persisted output (identical read shape to ``GET /results``).
    """
    require_owned_run(run_id, db, user)
    orchestrator = PipelineOrchestrator(db, discovery_service, research_service)
    if not request.generate_queries and not request.queries:
        raise HTTPException(status_code=422, detail="queries must not be empty")
    final_run = await orchestrator.execute(
        run_id,
        None if request.generate_queries else request.queries,
        request.max_results_per_query,
    )
    if final_run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return await get_run_results(run_id, db, user)