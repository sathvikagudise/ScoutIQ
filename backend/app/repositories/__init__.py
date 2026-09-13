"""Repositories handle persistence for the core contracts."""

from app.repositories.activity_repository import ActivityRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.qualification_repository import QualificationRepository
from app.repositories.query_repository import QueryRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository

__all__ = [
    "RunRepository",
    "QueryRepository",
    "SourceRepository",
    "CompanyRepository",
    "EvidenceRepository",
    "ContactRepository",
    "QualificationRepository",
    "LeadRepository",
    "ActivityRepository",
]