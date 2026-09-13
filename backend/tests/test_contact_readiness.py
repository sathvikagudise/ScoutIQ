"""Contact readiness (CONTACT dimension) tests — fully offline.

``ContactReadiness`` is the contact-enrichment label for a company-qualified
candidate: what publicly evidenced contact information the system actually
holds. It NEVER implies email deliverability (``EVIDENCED_CONTACT`` is a source
page explicitly attributing that email to the named leader) and NEVER invents a
name, email, or URL.

Contract under test
-------------------
1. Deterministic: ``derive_contact_readiness`` maps identical inputs to the
   same label; the ``ContactAvailabilityEvaluator`` maps every non-empty label
   to PASS and ``NO_CONTACT_FOUND`` to INSUFFICIENT_EVIDENCE, and it is NEVER
   part of the three company criteria (see ``test_qualification_service``).
2. Fixed best-first priority:
   EVIDENCED_CONTACT > NAMED_CONTACT_NO_EMAIL > PUBLIC_EMAIL_AVAILABLE >
   COMPANY_CONTACT_AVAILABLE > NO_CONTACT_FOUND.
3. Own-domain gate for public email: an own-domain public email counts only
   when the candidate has an own-site host; a publisher-domain email never
   counts.
4. Own-site gate for channels: contact page URL / LinkedIn URL only become
   COMPANY_CONTACT_AVAILABLE when the candidate actually has an own site (a
   deep publisher canonical yields NO_CONTACT_FOUND, never channels).
5. Persistence is idempotent (one enrichment row per candidate); channel
   capture never fabricates a URL and preserves prior values.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import app.db.orm  # noqa: F401  (register ORM tables before create_all)
from app.contact.enrichment import ContactEnrichmentService, _email_host
from app.core.enums import ContactReadiness, EvidenceType, QualificationStatus
from app.db.base import Base
from app.models.company import CompanyCandidate
from app.models.evidence import Evidence
from app.qualification.evaluators.contact_availability import (
    ContactAvailabilityEvaluator,
    derive_contact_readiness,
)
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_enrichment_repository import ContactEnrichmentRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.research.models import (
    ExtractedLink,
    InternalPage,
    InternalPageCategory,
    ResearchResult,
)
from app.models.run import DiscoveryRun
from app.repositories.run_repository import RunRepository

_EVALUATOR = ContactAvailabilityEvaluator()


def _derive(**kwargs) -> ContactReadiness:
    return derive_contact_readiness(**kwargs)


def _decision(**kwargs) -> tuple[ContactReadiness, QualificationStatus]:
    result = _EVALUATOR.evaluate(**kwargs)
    assert result.criterion.value == "contact_availability"
    # The evaluator surfaces channels as boolean signals for derivation.
    derivable = dict(kwargs)
    if "contact_page_url" in derivable:
        derivable["has_contact_page_url"] = bool(derivable.pop("contact_page_url"))
    if "linkedin_url" in derivable:
        derivable["has_linkedin_url"] = bool(derivable.pop("linkedin_url"))
    return _derive(**derivable), result.status


def _own_site_candidate(db: Session, website: str = "https://acme.example.com") -> CompanyCandidate:
    from datetime import datetime

    run = RunRepository(db).create(
        DiscoveryRun(target_lead_count=5, started_at=datetime.utcnow())
    )
    return CompanyRepository(db).create_candidate(
        CompanyCandidate(
            run_id=run.run_id,
            company_name="Acme Software",
            official_website=website,
        )
    )


def _add_evidence(db: Session, candidate: CompanyCandidate, *, email: str) -> None:
    EvidenceRepository(db).create(
        Evidence(
            candidate_id=candidate.candidate_id,
            evidence_type=EvidenceType.EMAIL,
            claim="contact_email",
            extracted_value=email,
        )
    )


def _own_site_page(candidate: CompanyCandidate) -> ResearchResult:
    return ResearchResult(
        source_url=candidate.official_website,
        final_url=candidate.official_website,
        html_extracted=True,
        relevant_internal_pages=[
            InternalPage(
                url="https://acme.example.com/contact",
                anchor_text="Contact",
                category=InternalPageCategory.CONTACT,
            )
        ],
        links=[
            ExtractedLink(
                original_href="https://www.linkedin.com/company/acme-software",
                resolved_url="https://www.linkedin.com/company/acme-software",
                anchor_text="LinkedIn",
                is_internal=False,
            )
        ],
    )


@pytest.fixture()
def persistence_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'contact_readiness.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    def _enable_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# 1. Derivation is deterministic and maps empty signals to NO_CONTACT_FOUND
# ---------------------------------------------------------------------------


def test_nothing_found_maps_to_no_contact_found_and_insufficient():
    readiness, status = _decision()
    assert readiness == ContactReadiness.NO_CONTACT_FOUND
    assert status == QualificationStatus.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# 2. Each of the four non-empty signals maps to its label (deterministic PASS)
# ---------------------------------------------------------------------------


def test_attributed_leader_email_maps_to_evidenced_contact():
    readiness, status = _decision(
        named_contact_count=1,
        evidenced_contact_email_count=1,
    )
    assert readiness == ContactReadiness.EVIDENCED_CONTACT
    assert status == QualificationStatus.PASS


def test_named_leader_without_email_maps_to_named_contact_no_email():
    readiness, status = _decision(named_contact_count=1)
    assert readiness == ContactReadiness.NAMED_CONTACT_NO_EMAIL
    assert status == QualificationStatus.PASS


def test_own_domain_public_email_maps_to_public_email_available():
    readiness, status = _decision(public_email_count=1)
    assert readiness == ContactReadiness.PUBLIC_EMAIL_AVAILABLE
    assert status == QualificationStatus.PASS


def test_own_site_presence_alone_maps_to_company_contact_available():
    readiness, status = _decision(has_own_site=True)
    assert readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE
    assert status == QualificationStatus.PASS


def test_contact_page_url_maps_to_company_contact_available():
    readiness, status = _decision(contact_page_url="https://acme.example.com/contact")
    assert readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE


def test_linkedin_company_url_maps_to_company_contact_available():
    readiness, _ = _decision(linkedin_url="https://www.linkedin.com/company/acme")
    assert readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE


# ---------------------------------------------------------------------------
# 3. Fixed best-first priority (strongest signal wins)
# ---------------------------------------------------------------------------


def test_evidenced_email_beats_named_and_public():
    readiness, _ = _decision(
        named_contact_count=2,
        evidenced_contact_email_count=1,
        public_email_count=3,
    )
    assert readiness == ContactReadiness.EVIDENCED_CONTACT


def test_named_leader_beats_public_email():
    readiness, _ = _decision(
        named_contact_count=1,
        evidenced_contact_email_count=0,
        public_email_count=2,
    )
    assert readiness == ContactReadiness.NAMED_CONTACT_NO_EMAIL


# ---------------------------------------------------------------------------
# 4. Determinism: same inputs, same label every time
# ---------------------------------------------------------------------------


def test_derivation_is_deterministic():
    kwargs = dict(named_contact_count=1, evidenced_contact_email_count=1)
    labels = [derive_contact_readiness(**kwargs) for _ in range(20)]
    assert len(set(labels)) == 1
    assert labels[0] == ContactReadiness.EVIDENCED_CONTACT


# ---------------------------------------------------------------------------
# 5. Service: evaluate persists exactly one idempotent row from persisted data
# ---------------------------------------------------------------------------


def test_service_evaluate_persists_readiness_and_counts(persistence_db):
    candidate = _own_site_candidate(persistence_db)
    enrichment = ContactEnrichmentService(persistence_db).evaluate(
        candidate.candidate_id, candidate=candidate
    )
    assert enrichment.readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE
    assert enrichment.named_contact_count == 0
    assert enrichment.public_email_count == 0

    again = ContactEnrichmentService(persistence_db).evaluate(
        candidate.candidate_id, candidate=candidate
    )
    assert again.candidate_id == enrichment.candidate_id
    assert ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    ).candidate_id == candidate.candidate_id


def test_service_no_own_site_means_no_contact_found(persistence_db):
    """A deep publisher canonical yields NO_CONTACT_FOUND even with evidence."""
    candidate = _own_site_candidate(
        persistence_db,
        website="https://retailwirehub.example.com/home/2025/4/cloud-retail-raises",
    )
    _add_evidence(persistence_db, candidate, email="scott@retailwirehub.example.com")

    enrichment = ContactEnrichmentService(persistence_db).evaluate(
        candidate.candidate_id, candidate=candidate
    )
    assert enrichment.readiness == ContactReadiness.NO_CONTACT_FOUND
    assert enrichment.public_email_count == 0


# ---------------------------------------------------------------------------
# 6. Own-domain gate: a publisher email is never a public-email signal
# ---------------------------------------------------------------------------


def test_own_domain_public_email_counts(persistence_db):
    candidate = _own_site_candidate(persistence_db)
    _add_evidence(persistence_db, candidate, email="info@acme.example.com")
    enrichment = ContactEnrichmentService(persistence_db).evaluate(
        candidate.candidate_id, candidate=candidate
    )
    assert enrichment.public_email_count == 1
    assert enrichment.readiness == ContactReadiness.PUBLIC_EMAIL_AVAILABLE


def test_email_host_normalisation():
    assert _email_host("Info@WWW.Acme.Example.COM ") == "acme.example.com"


# ---------------------------------------------------------------------------
# 7. Channel capture: only persisted discovered URLs, gated to the own site
# ---------------------------------------------------------------------------


def test_capture_channels_persists_own_site_channels(persistence_db):
    candidate = _own_site_candidate(persistence_db)
    service = ContactEnrichmentService(persistence_db)
    service.capture_channels(candidate, _own_site_page(candidate))

    row = ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    )
    assert row.contact_page_url == "https://acme.example.com/contact"
    assert row.linkedin_url == "https://www.linkedin.com/company/acme-software"
    # The label is derived afterwards by evaluate() once research is complete.
    service.evaluate(candidate.candidate_id, candidate=candidate)
    enriched = ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    )
    assert enriched.readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE


def test_capture_channels_skips_publisher_page(persistence_db):
    candidate = _own_site_candidate(
        persistence_db,
        website="https://retailwirehub.example.com/home/2025/4/cloud-retail-raises",
    )
    service = ContactEnrichmentService(persistence_db)
    page = ResearchResult(
        source_url=candidate.official_website,
        final_url=candidate.official_website,
        html_extracted=True,
        relevant_internal_pages=[
            InternalPage(
                url="https://retailwirehub.example.com/contact",
                anchor_text="Contact",
                category=InternalPageCategory.CONTACT,
            )
        ],
    )
    service.capture_channels(candidate, page)

    row = ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    )
    assert row is None, "a publisher page must never accrue channels"
    assert row is None or row.readiness == ContactReadiness.NO_CONTACT_FOUND


def test_capture_channels_preserves_prior_values(persistence_db):
    candidate = _own_site_candidate(persistence_db)
    service = ContactEnrichmentService(persistence_db)
    first = _own_site_page(candidate)
    second = _own_site_page(candidate)
    second.relevant_internal_pages = []
    service.capture_channels(candidate, first)
    service.capture_channels(candidate, second)

    row = ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    )
    assert row.contact_page_url == "https://acme.example.com/contact"
    assert row.linkedin_url == "https://www.linkedin.com/company/acme-software"


def test_capture_channels_ignores_non_company_linkedin_links(persistence_db):
    candidate = _own_site_candidate(persistence_db)
    service = ContactEnrichmentService(persistence_db)
    page = ResearchResult(
        source_url=candidate.official_website,
        final_url=candidate.official_website,
        html_extracted=True,
        links=[
            ExtractedLink(
                original_href="https://www.linkedin.com/in/jane-doe",
                resolved_url="https://www.linkedin.com/in/jane-doe",
                anchor_text="Jane",
                is_internal=False,
            )
        ],
    )
    service.capture_channels(candidate, page)

    row = ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    )
    # A personal LinkedIn profile link is not a company channel; nothing is
    # captured and no enrichment row is created until evaluate() runs.
    assert row is None
    service.evaluate(candidate.candidate_id, candidate=candidate)
    enriched = ContactEnrichmentRepository(persistence_db).get_by_candidate(
        candidate.candidate_id
    )
    assert enriched.readiness == ContactReadiness.COMPANY_CONTACT_AVAILABLE