"""ScoutIQ domain enums. Single source of truth for status/type strings."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle state of a DiscoveryRun."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunPhase(StrEnum):
    """High-level phase of an autonomous run's execution pipeline."""

    DISCOVERY = "discovery"
    RESEARCH = "research"
    QUALIFICATION = "qualification"
    CONTACT_AND_LEAD = "contact_and_lead"
    COMPLETED = "completed"


class CandidateStatus(StrEnum):
    """Lifecycle state of a CompanyCandidate."""

    DISCOVERED = "discovered"
    RESEARCHING = "researching"
    PARTIALLY_VERIFIED = "partially_verified"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


class QualificationStatus(StrEnum):
    """Outcome of a single criterion or an overall qualification decision."""

    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_EVALUATED = "not_evaluated"


class QualificationCriterion(StrEnum):
    """The independent criteria a qualification evaluates."""

    FUNDING_OR_REVENUE = "funding_or_revenue"
    TECH_PLATFORM = "tech_platform"
    US_PRESENCE = "us_presence"
    CONTACT_AVAILABILITY = "contact_availability"
    LEADERSHIP = "leadership"
    EMAIL_ATTRIBUTION = "email_attribution"


class EvidenceType(StrEnum):
    """Category of a piece of evidence."""

    FUNDING = "funding"
    REVENUE = "revenue"
    COMPANY_DESCRIPTION = "company_description"
    COMPANY_NAME = "company_name"
    INDUSTRY = "industry"
    LOCATION = "location"
    US_PRESENCE = "us_presence"
    OFFICIAL_WEBSITE = "official_website"
    PLATFORM = "platform"
    CEO = "ceo"
    COFOUNDER = "cofounder"
    FOUNDER = "founder"
    EMAIL = "email"


class FetchStatus(StrEnum):
    """Meaningful outcome of fetching a URL (improves on a bare boolean)."""

    SUCCESS = "success"
    ACCESS_BLOCKED = "access_blocked"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    UNKNOWN_ERROR = "unknown_error"


class VerificationStatus(StrEnum):
    """Verification state of a contact detail such as an email."""

    UNVERIFIED = "unverified"
    EVIDENCED = "evidenced"
    VERIFIED = "verified"


class ContactReadiness(StrEnum):
    """Contact-enrichment readiness of a company-qualified candidate.

    Describes what publicly evidenced contact information exists. It NEVER
    implies email deliverability or SMTP/MX verification: ``EVIDENCED_CONTACT``
    is a source page explicitly attributing that email to the named leader.
    Derived ONLY from persisted, evidenced data — nothing is guessed.
    """

    EVIDENCED_CONTACT = "evidenced_contact"
    NAMED_CONTACT_NO_EMAIL = "named_contact_no_email"
    PUBLIC_EMAIL_AVAILABLE = "public_email_available"
    COMPANY_CONTACT_AVAILABLE = "company_contact_available"
    NO_CONTACT_FOUND = "no_contact_found"


class ActivityEventType(StrEnum):
    """Types of events surfaced in a run's activity feed."""

    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    QUERY_EXECUTED = "query_executed"
    QUERY_FAILED = "query_failed"
    CANDIDATE_DISCOVERED = "candidate_discovered"
    CANDIDATE_REJECTED = "candidate_rejected"
    EVIDENCE_COLLECTED = "evidence_collected"
    CONTACT_IDENTIFIED = "contact_identified"
    EMAIL_VERIFIED = "email_verified"
    LEAD_QUALIFIED = "lead_qualified"