"""Phase 5P orchestrator — drives the run pipeline using existing services.

``PipelineOrchestrator.execute`` wires the full, deterministic run pipeline
over a single run while reusing every existing service and repository verbatim:

    discovery -> (persist queries + sources) -> research -> extraction ->
    qualification -> contacts -> leads -> completion

Constraints honored by the orchestrator:

* No step logic is re-implemented here: each stage calls the established
  service/repository contract exactly as the individual HTTP endpoints do.
* No data is fabricated. Leads and contacts are assembled only from persisted,
  qualified state; candidates that were never qualified, or qualified without
  a PASS decision, produce no lead and no inferred detail.
* Failure isolation matches the endpoints: a discovery provider error or a
  fetch/parse failure for one source never sinks the whole run; the failing
  item is recorded or skipped and the run continues. Any unexpected exception
  marks the run ``FAILED`` with an ``error_message`` and is re-raised.
* Iteration over run data is always deterministic (existing repository
  orderings; sources additionally pinned by source id).
* The orchestrator never writes activity events and never advances
  ``current_phase``; lifecycle is status only (``RUNNING`` -> ``COMPLETED`` /
  ``FAILED``), mirroring the run-completion endpoint's conservatism.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.contact.enrichment import ContactEnrichmentService
from app.contact.service import ContactAssemblyService
from app.core.enums import CandidateStatus, QualificationStatus, RunStatus
from app.discovery.service import DiscoveryService, normalize_url
from app.discovery.strategies import generate_strategies
from app.extraction.service import CandidateExtractionService, own_site_host
from app.lead.service import LeadAssemblyService
from app.models.common import utcnow
from app.models.run import DiscoveryRun, SearchQuery
from app.models.source import Source
from app.qualification.service import qualify
from app.repositories.company_repository import CompanyRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.query_repository import QueryRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository
from app.research.models import InternalPage, InternalPageCategory, ResearchResult
from app.research.service import ResearchService

logger = logging.getLogger(__name__)


def hostname_of(url: str | None) -> str | None:
    """Case-folded hostname of a URL (None when unparseable)."""
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower() if host else None

# Qualification outcome -> candidate lifecycle status (single source of truth,
# shared with the qualification endpoint).
CANDIDATE_STATUS_FROM = {
    QualificationStatus.PASS: CandidateStatus.QUALIFIED,
    QualificationStatus.FAIL: CandidateStatus.REJECTED,
    QualificationStatus.INSUFFICIENT_EVIDENCE: CandidateStatus.PARTIALLY_VERIFIED,
    QualificationStatus.NOT_EVALUATED: CandidateStatus.PARTIALLY_VERIFIED,
}

# Internal pages worth following after a source page yields material: ranked so
# qualification-critical signals (founder/leadership names, team, contacts,
# funding-relevant press) are fetched first. BLOG is deliberately absent.
_INTERNAL_PAGE_PRIORITY = {
    InternalPageCategory.FOUNDERS: 0,
    InternalPageCategory.LEADERSHIP: 1,
    InternalPageCategory.TEAM: 2,
    InternalPageCategory.CONTACT: 3,
    InternalPageCategory.PRESS_NEWS: 4,
    InternalPageCategory.ABOUT: 5,
    InternalPageCategory.COMPANY: 6,
}

# How many internal pages to follow per researched source (single hop).
_INTERNAL_PAGE_CAP = 3

# How many search results to consider when disambiguating a candidate's own
# official website.
_OWN_SITE_SEARCH_MAX = 8

# Publisher / aggregator / portal / directory domains. A funding-announcement
# page on one of these is never the candidate's own site, and its homepage
# canonical is never trusted as the candidate's official website.
_PUBLISHER_DOMAINS = frozenset(
    """techstartups.com thesaasnews.com finsmes.com pulse2.com siliconangle.com
    techcrunch.com crunchbase.com news.crunchbase.com businessinsider.com
    markets.businessinsider.com marketwatch.com cnbctv18.com moneycontrol.com
    economictimes.indiatimes.com travel.economictimes.indiatimes.com ndtv.com
    thedailystar.net startupdaily.net smartcompany.com.au entrepreneur.com
    whalesbook.com aventure.vc inforcapital.com hitconsultant.net adexchanger.com
    dealroom.net growthlist.co startuptalky.com startupfunds.in calcguru.in
    startupcorners.com getstartupfunding.com angelinvestorsnetwork.com
    angelinvestmentnetwork.us pillar.vc startupmag.co.uk startupurban.com
    subvention.co.uk granttree.co.uk fundraiseinsider.com startupgrantshub.com
    nbcnewyork.com fortune.com msn.com medium.com linkedin.com wikipedia.org
    quora.com greyjournal.net fundup.ai harlem.capital seedtable.com
    vcbacked.co idlen.io agentmarketcap.ai startupprojects.com funded.com
    startupindia.gov.in gov.uk bing.com thenextweb.com prnewswire.com
    businesswire.com globalnewswire.com accesswire.com vcnewsdaily.com
    thestartuppitch.com startupsworld.com twoo.com wsj.com reuters.com
    """.split()
)


def _brand_slug(name: str | None) -> str:
    """Lowercased alphanumeric brand key ("Cloud Retail" -> "cloudretail")."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _no_www(host: str | None) -> str:
    if not host:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _host_carries_brand(core: str | None, brand: str | None) -> bool:
    """Whether a bare hostname strongly suggests it belongs to ``brand``.

    A host matches when the whole brand slug ("noriasystems" in
    "noriasystems.com") or a distinctive brand token ("noria" in
    "noria.io") appears in it. Short generic words are never distinctive; the
    identity of the fetched page is re-confirmed against the brand before the
    website is adopted, which is what makes host-level matching safe.
    """
    if not core:
        return False
    brand_lower = (brand or "").lower()
    tokens = [token for token in re.findall(r"[a-z0-9]+", brand_lower) if len(token) >= 4]
    if not tokens:
        return False
    if any(token in core for token in tokens):
        return True
    return _brand_slug(brand_lower) in core


class PipelineOrchestrator:
    """Run the persisted pipeline for one run, end to end.

    :param db: the session to persist through.
    :param discovery_service: a configured ``DiscoveryService`` (provider
        injected by the caller so tests stay fully offline).
    :param research_service: a configured ``ResearchService`` (fetcher injected
        by the caller).
    """

    def __init__(
        self,
        db: Session,
        discovery_service: DiscoveryService,
        research_service: ResearchService,
    ) -> None:
        self.db = db
        self.discovery_service = discovery_service
        self.research_service = research_service
        self.run_repo = RunRepository(db)
        self.company_repo = CompanyRepository(db)
        self.query_repo = QueryRepository(db)
        self.source_repo = SourceRepository(db)

    async def execute(
        self,
        run_id: UUID,
        queries: list[str] | None = None,
        max_results_per_query: int = 10,
        query_strategies: Optional[dict[str, str]] = None,
    ) -> Optional[DiscoveryRun]:
        """Execute the full pipeline for ``run_id`` and return the final run.

        ``queries`` may be empty/``None``: the orchestrator then generates a
        deterministic stratified query set (each tagged with a strategy label
        persisted on its ``SearchQuery`` row). Explicit queries keep their
        caller-provided text and, when ``query_strategies`` maps a query text to
        a label, persist that strategy.

        Returns ``None`` when the run does not exist. On an unexpected error
        the run is marked ``FAILED`` (with ``error_message``) and the exception
        is re-raised.
        """
        run = self.run_repo.get(run_id)
        if run is None:
            return None

        self.run_repo.update_status(run_id, RunStatus.RUNNING)

        try:
            resolved_queries, strategies = self._resolve_queries(queries, query_strategies)
            await self._discover_and_persist(
                resolved_queries, run_id, max_results_per_query, strategies
            )
            await self._research_and_extract(run_id)
            self._qualify_candidates(run_id)
            self._assemble_contacts(run_id)
            self._enrich_contacts(run_id)
            self._assemble_leads(run_id)
        except asyncio.CancelledError:
            # Client disconnect / server shutdown cancels the handler coroutine.
            # asyncio.CancelledError is a BaseException (Python 3.8+), so the
            # generic ``except Exception`` below never ran — the run would be
            # left permanently RUNNING with the request gone. Persist FAILED so
            # polling clients reach a terminal state.
            logger.warning("Run %s cancelled during orchestration", run_id)
            self._fail_run(run_id, "Run cancelled while executing")
            raise
        except Exception as exc:  # unexpected failure -> FAILED, then re-raise
            logger.exception("Run %s failed during orchestration", run_id)
            self._fail_run(run_id, str(exc))
            raise

        qualified_lead_count = len(LeadRepository(self.db).list_by_run(run_id))
        return self.run_repo.update_progress(
            run_id,
            status=RunStatus.COMPLETED,
            qualified_lead_count=qualified_lead_count,
            error_message=None,
            completed_at=utcnow(),
        )

    def _fail_run(self, run_id: UUID, message: str) -> None:
        """Persist ``FAILED`` on a fresh session so it always survives.

        The shared request session may be unusable by the time an error is
        handled: a mid-pipeline database error leaves PostgreSQL's transaction
        aborted, and ANY further statement on that session — including the
        FAILED write — fails until rollback. We therefore roll back the shared
        session best-effort and write the terminal state through a brand-new
        session on the same engine.
        """
        try:
            self.db.rollback()
        except Exception:
            logger.exception("Run %s rollback failed; continuing", run_id)

        fresh = Session(bind=self.db.get_bind(), expire_on_commit=False)
        try:
            RunRepository(fresh).update_progress(
                run_id, status=RunStatus.FAILED, error_message=message
            )
        except Exception:
            logger.exception(
                "Run %s could not be marked FAILED (terminal state not persisted)",
                run_id,
            )
        finally:
            fresh.close()

    @staticmethod
    def _resolve_queries(
        queries: list[str] | None,
        query_strategies: Optional[dict[str, str]],
    ) -> tuple[list[str], dict[str, str]]:
        """Resolve explicit queries or generate the stratified strategy set.

        Generated queries always carry their strategy label; explicit queries
        carry one only when the caller provides the mapping.
        """
        if queries:
            strategies = dict(query_strategies or {})
            return [query.strip() for query in queries if query.strip()], strategies
        return [text for text, _ in generate_strategies()], dict(generate_strategies())

    # ------------------------------------------------------------------
    # Discovery -> persist queries and sources
    # ------------------------------------------------------------------

    async def _discover_and_persist(
        self,
        queries: list[str],
        run_id: UUID,
        max_results_per_query: int,
        query_strategies: Optional[dict[str, str]] = None,
    ) -> None:
        if not queries:
            raise ValueError("queries must not be empty")

        response = await self.discovery_service.discover(
            queries, max_results_per_query=max_results_per_query
        )

        strategies = query_strategies or {}
        query_by_text: dict[str, SearchQuery] = {}
        for text in queries:
            stripped = text.strip()
            if not stripped or stripped in query_by_text:
                continue
            query_by_text[stripped] = self.query_repo.create(
                SearchQuery(
                    run_id=run_id,
                    query_text=stripped,
                    strategy=strategies.get(stripped),
                    provider=response.provider,
                    result_count=sum(
                        1 for result in response.results if result.query == stripped
                    ),
                )
            )

        for result in response.results:
            query = query_by_text.get(result.query)
            self.source_repo.create(
                Source(
                    source_id=result.source_id,
                    url=result.url,
                    normalized_url=result.normalized_url,
                    title=result.title,
                    snippet=result.snippet,
                    domain=result.domain,
                    provider=result.provider,
                    discovered_by_query_id=query.query_id if query else None,
                )
            )

    # ------------------------------------------------------------------
    # Research -> extract + persist
    # ------------------------------------------------------------------

    async def _research_and_extract(self, run_id: UUID) -> None:
        extraction = CandidateExtractionService(self.db)
        sources = sorted(
            self.source_repo.list_by_run(run_id), key=lambda item: str(item.source_id)
        )
        researched_urls: set[str] = set()

        for source in sources:
            research = await self.research_service.research_source(
                source.source_id, self.source_repo
            )
            if research is None:
                continue
            if not research.html_extracted:
                logger.info(
                    "Source %s skipped: no HTML material (%s)",
                    source.source_id,
                    research.extraction_skip_reason,
                )
                continue
            researched_urls.add(
                normalize_url(research.final_url or research.source_url)
            )
            extracted = extraction.extract_and_persist(
                research,
                run_id=run_id,
                source_id=source.source_id,
                source_title=source.title,
            )
            if extracted.skipped_reason:
                logger.info(
                    "Source %s skipped extraction: %s",
                    source.source_id,
                    extracted.skipped_reason,
                )
            ContactEnrichmentService(self.db).capture_channels(
                extracted.candidate, research
            )
            await self._follow_internal_pages(
                extraction, research, run_id, researched_urls
            )
            await self._follow_own_site(
                extraction,
                extracted,
                research,
                source,
                run_id,
                researched_urls,
            )

    async def _follow_own_site(
        self,
        extraction: CandidateExtractionService,
        extracted: ExtractionResult,
        research: ResearchResult,
        source: Source,
        run_id: UUID,
        researched_urls: set[str],
    ) -> None:
        """Anchor a brand-new candidate on its own official website.

        Three shapes are handled:

        1. The source page already IS the candidate's own site (its canonical is
           a homepage on the same domain): nothing further is needed.
        2. The candidate was identified through a THIRD-PARTY page (press
           article, directory, round-up) and its canonical is the publisher's
           deep article URL, so ``own_site_host`` is None and the candidate is
           starved of the own-domain material (team, contact, location,
           leadership) that qualification and email attribution actually need.
           This method then locates the candidate's real site — first from a
           brand-host link on the researched page, then from a disambiguating
           search of the quoted company name — and fetches it, re-anchoring
           ``official_website`` to the confirmed homepage and following its
           internal pages like any researched source.
        3. A press/listing page whose canonical is already the company's own
           root homepage: the candidate is anchored but the homepage has not
           been researched, so it is fetched for own-domain evidence before
           its internal pages are followed.

        Every step is failure-isolated: a botched fetch, missing metadata, or a
        site whose identity does not confirm the candidate leaves the candidate
        exactly as it was and never sinks the run.
        """
        if not extracted.created_candidate or not extracted.candidate:
            return
        candidate = extracted.candidate

        own_host = own_site_host(candidate)
        if own_host is not None:
            # The candidate already has an identity homepage. When the page we
            # just researched IS that homepage, its material is already in the
            # pool and nothing further is needed. When the candidate reached us
            # from a press/listing page but its canonical homepage is on the own
            # domain, we still fetch that homepage so own-domain location,
            # leadership, platform, and email evidence grounds qualification.
            current_host = hostname_of(research.final_url or research.source_url)
            if current_host and _no_www(current_host) == own_host:
                return
            own_link = candidate.official_website
            if not own_link:
                return
        else:
            own_link = self._company_site_link(candidate, research.links)
            if own_link is None:
                own_link = await self._search_company_site(
                    candidate, hostname_of(source.url or source.normalized_url)
                )
            if not own_link:
                return

        key = normalize_url(own_link)
        if key in researched_urls:
            return
        researched_urls.add(key)

        try:
            own = await self.research_service.research_url(own_link)
        except Exception as exc:
            logger.warning("Own-site %s failed to research: %s", own_link, exc)
            return
        if own is None or not own.html_extracted:
            logger.info("Own-site %s skipped: no HTML material", own_link)
            return

        result = extraction.extract_and_persist(
            own,
            run_id=run_id,
            source_id=None,
            source_title="official website",
        )
        if result.candidate is None:
            return
        if _brand_slug(result.candidate.company_name) != _brand_slug(candidate.company_name):
            logger.info(
                "Own-site %s did not confirm candidate %r; not re-anchoring",
                own_link,
                candidate.company_name,
            )
            return

        ContactEnrichmentService(self.db).capture_channels(result.candidate, own)

        homepage = own_link
        if own.metadata and own.metadata.canonical_url:
            parsed = urlparse(own.metadata.canonical_url)
            host = _no_www(parsed.hostname or "")
            if parsed.path in ("", "/") and host and host not in _PUBLISHER_DOMAINS:
                homepage = own.metadata.canonical_url

        new_host = hostname_of(homepage)
        if not new_host or new_host in _PUBLISHER_DOMAINS:
            return

        own_candidate = result.candidate
        if hostname_of(own_candidate.official_website) != new_host:
            own_candidate.official_website = homepage
            self.company_repo.update_candidate(own_candidate)
            logger.info(
                "Candidate %r re-anchored to own site %s",
                candidate.company_name,
                homepage,
            )
        await self._follow_internal_pages(extraction, own, run_id, researched_urls)

    @staticmethod
    def _company_site_link(candidate, links: list) -> Optional[str]:
        """A link on the researched page whose host clearly carries the brand.

        Only external links count; the host must contain the candidate's brand
        slug and must not be a publisher domain. Without a convincing host the
        method returns None (search disambiguation takes over).
        """
        slug = _brand_slug(candidate.company_name)
        if not slug or len(slug) < 4:
            return None
        for link in links:
            if link.is_internal:
                continue
            host = hostname_of(link.resolved_url)
            if not host:
                continue
            key = _no_www(host)
            if key in _PUBLISHER_DOMAINS:
                continue
            core = re.sub(r"[^a-z0-9]", "", key)
            if _host_carries_brand(core, candidate.company_name):
                return link.resolved_url
        return None

    async def _search_company_site(self, candidate, source_host: Optional[str]) -> Optional[str]:
        """Disambiguate the candidate's own site via a quoted-brand search.

        Only a result whose hostname contains the brand slug and is not a
        publisher domain is accepted; anything else is too ambiguous to trust
        as the company's own website. Failure isolates to ``None``.
        """
        brand = (candidate.company_name or "").strip()
        slug = _brand_slug(brand)
        if not brand or len(slug) < 4:
            return None
        try:
            results = await self.discovery_service.provider.search(
                f'"{brand}"', max_results=_OWN_SITE_SEARCH_MAX
            )
        except Exception as exc:
            logger.warning("Own-site search for %r failed: %s", brand, exc)
            return None
        for item in results:
            url = getattr(item, "url", None)
            host = hostname_of(url)
            if not host:
                continue
            key = _no_www(host)
            if key in _PUBLISHER_DOMAINS:
                continue
            if host == source_host:
                continue
            core = re.sub(r"[^a-z0-9]", "", key)
            if _host_carries_brand(core, candidate.company_name):
                return url
        return None

    # ------------------------------------------------------------------
    # Internal-page follow-up (single hop, evidence attribution only)
    # ------------------------------------------------------------------

    @staticmethod
    def _prioritized_internal_pages(
        pages: list[InternalPage],
    ) -> list[InternalPage]:
        """Rank internal pages by qualification-signal priority (BLOG excluded)."""
        return sorted(
            (
                page
                for page in pages
                if page.category in _INTERNAL_PAGE_PRIORITY
            ),
            key=lambda page: (_INTERNAL_PAGE_PRIORITY[page.category], page.url),
        )

    async def _follow_internal_pages(
        self,
        extraction: CandidateExtractionService,
        research: ResearchResult,
        run_id: UUID,
        researched_urls: set[str],
    ) -> None:
        """Fetch the most valuable internal pages of a researched page and
        extract their evidence into the candidate pool (single hop).

        Pages already researched this run (including the parent page and any
        internal URL reached from another source) are skipped, and each fetch
        is failure-isolated: a broken internal page never sinks the run. The
        internal pages are evidence sources only — no Source row is created for
        them, because this orchestrator treats ``Source`` rows as *discovered*
        results (the persisted source-URL attribution on each claim already
        records where the evidence came from).
        """
        for page in self._prioritized_internal_pages(
            research.relevant_internal_pages
        )[: _INTERNAL_PAGE_CAP]:
            key = normalize_url(page.url)
            if key in researched_urls:
                continue
            researched_urls.add(key)
            try:
                internal = await self.research_service.research_url(page.url)
            except Exception as exc:
                logger.warning(
                    "Internal page %s failed to research: %s", page.url, exc
                )
                continue
            if internal is None or not internal.html_extracted:
                continue
            source_title = page.anchor_text.strip() or page.category.value
            extracted = extraction.extract_and_persist(
                internal,
                run_id=run_id,
                source_id=None,
                source_title=source_title,
            )
            if extracted.skipped_reason:
                logger.info(
                    "Internal page %s skipped extraction: %s",
                    page.url,
                    extracted.skipped_reason,
                )
            ContactEnrichmentService(self.db).capture_channels(
                extracted.candidate, internal
            )

    # ------------------------------------------------------------------
    # Qualification -> persist decision + candidate status
    # ------------------------------------------------------------------

    def _qualify_candidates(self, run_id: UUID) -> None:
        evidence_repo = EvidenceRepository(self.db)
        qualification_repo = QualificationRepository(self.db)

        for candidate in self._run_candidates(run_id):
            evidence = evidence_repo.list_by_candidate(candidate.candidate_id)
            own_host = own_site_host(candidate)
            company_hosts = {own_host} if own_host else set()
            result = qualify(
                candidate.candidate_id,
                evidence,
                company_hosts=company_hosts,
            )
            qualification_repo.save(result)
            self.company_repo.set_candidate_status(
                candidate.candidate_id, CANDIDATE_STATUS_FROM[result.overall_status]
            )

    # ------------------------------------------------------------------
    # Contacts (evidence-backed, idempotent)
    # ------------------------------------------------------------------

    def _assemble_contacts(self, run_id: UUID) -> None:
        contact_service = ContactAssemblyService(self.db)
        for candidate in self._run_candidates(run_id):
            contact_service.assemble(candidate.candidate_id, candidate=candidate)

    # ------------------------------------------------------------------
    # Contact enrichment (contact readiness + channel capture)
    # ------------------------------------------------------------------

    def _enrich_contacts(self, run_id: UUID) -> None:
        """Derive and persist one ``ContactReadiness`` per run candidate.

        Runs after contact assembly so any evidence-attributed contact emails
        are in the pool; runs before lead assembly so ``QualifiedLead`` rows
        can carry the label. Offline and idempotent (one row per candidate).
        """
        enrichment_service = ContactEnrichmentService(self.db)
        for candidate in self._run_candidates(run_id):
            try:
                enrichment_service.evaluate(candidate.candidate_id, candidate=candidate)
            except Exception:
                logger.exception(
                    "Contact enrichment failed for candidate %s",
                    candidate.candidate_id,
                )

    # ------------------------------------------------------------------
    # Leads (qualified PASS candidates only)
    # ------------------------------------------------------------------

    def _assemble_leads(self, run_id: UUID) -> None:
        qualification_repo = QualificationRepository(self.db)
        lead_repo = LeadRepository(self.db)
        lead_service = LeadAssemblyService(self.db)

        for candidate in self._run_candidates(run_id):
            fresh = self.company_repo.get_candidate(candidate.candidate_id)
            if fresh is None or fresh.status != CandidateStatus.QUALIFIED:
                continue
            qualification = qualification_repo.get_by_candidate(fresh.candidate_id)
            if qualification is None or qualification.overall_status != QualificationStatus.PASS:
                continue
            lead = lead_service.assemble(fresh, qualification)
            lead_repo.replace_for_candidate(lead)

    # ------------------------------------------------------------------
    # Deterministic run-scoped candidates (existing repo ordering)
    # ------------------------------------------------------------------

    def _run_candidates(self, run_id: UUID) -> list:
        return [
            candidate
            for candidate in self.company_repo.list_candidates()
            if candidate.run_id == run_id
        ]