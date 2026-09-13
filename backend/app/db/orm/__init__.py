"""Register all ORM models so ``Base.metadata`` knows every table."""

from app.db.orm.activity import ActivityRecord
from app.db.orm.company import (
    CompanyCandidateRecord,
    CompanyProfileRecord,
    LeadRecord,
    company_candidate_sources,
)
from app.db.orm.contact import ContactRecord
from app.db.orm.contact_enrichment import ContactEnrichmentRecord
from app.db.orm.evidence import EvidenceRecord
from app.db.orm.qualification import CriterionRecord, QualificationRecord
from app.db.orm.run import QueryRecord, RunRecord
from app.db.orm.source import SourceRecord
from app.db.orm.user import AuthSessionRecord, UserRecord

__all__ = [
    "RunRecord",
    "QueryRecord",
    "SourceRecord",
    "CompanyCandidateRecord",
    "CompanyProfileRecord",
    "EvidenceRecord",
    "ContactRecord",
    "ContactEnrichmentRecord",
    "QualificationRecord",
    "CriterionRecord",
    "LeadRecord",
    "ActivityRecord",
    "UserRecord",
    "AuthSessionRecord",
    "company_candidate_sources",
]