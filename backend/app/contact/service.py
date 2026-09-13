"""Phase 5L contact assembly — contacts derived only from persisted evidence.

One contact per persistently evidenced named leader. Full name and role come
straight from the extracted evidence. ``email`` is populated ONLY when
persisted source text explicitly attributes that email to the same named
person (the identical explicit-attribution phrases the EMAIL_ATTRIBUTION
evaluator uses); otherwise it stays ``None`` and verification stays
``UNVERIFIED``. An evidence-attributed email is recorded as
``EVIDENCED`` — never ``VERIFIED`` (deliverability is out of scope).

The duplicate contract is idempotent-create by the scoped identity
``(candidate_id, full_name, role)``: re-assembling a candidate returns the
existing contact with the identical name and role instead of duplicating it.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import EvidenceType, VerificationStatus
from app.extraction.service import own_site_host
from app.models.company import CompanyCandidate
from app.models.contact import Contact
from app.models.evidence import Evidence
from app.qualification.evaluators.email_attribution import (
    AttributedEmail,
    find_attributed_emails,
)
from app.repositories.contact_repository import ContactRepository
from app.repositories.evidence_repository import EvidenceRepository

_ROLE_LABEL = {
    EvidenceType.CEO: "CEO",
    EvidenceType.COFOUNDER: "Co-Founder",
    EvidenceType.FOUNDER: "Founder",
}

# The people extractor persists exactly one claim per "Name, Role" mention with
# ``claim`` = the person field and ``extracted_value`` = "<Name>, <Role>".
# Legacy persisted values may hold the bare "<Name>" only. Both forms are
# accepted; sentence-style values ("Jane Doe, CEO - jane@example.com") never are.
_PERSON_CLAIMS = frozenset({"ceo", "cofounder", "founder"})

_ROLE_SUFFIX_RE = (
    r"(?:Chief\s+Executive\s+Officer|CEO|Co-?[fF]ounder|Cofounder|Founder)"
)

# A bare full name (two or more tokens, each capitalized, free of sentence
# punctuation), optionally followed by an explicit leadership-role suffix.
_STRIPPED_NAME_RE = re.compile(
    rf"^([A-Z][-A-Za-z.\u2019']*(?:\s+[A-Z][-A-Za-z.\u2019']*)+)"
    rf"(?:\s*,\s*{_ROLE_SUFFIX_RE}(?:\s+&\s*{_ROLE_SUFFIX_RE})*)?$"
)

# Words that mark a capitalized phrase as an organization/fund rather than a
# person (mirrors the people extractor guard; defense in depth at assembly).
_ORG_WORDS = frozenset(
    "capital group ventures strategy fund funds partners labs media studios "
    "holdings advisory investment llc inc ltd gmbh co corp company startups "
    "platform"
    .split()
)


def _has_org_word(name: str) -> bool:
    return any(token.strip(".,").lower() in _ORG_WORDS for token in name.split())


def _person_name(evidence: Evidence) -> str | None:
    """A usable full person name from a structured people claim, else None."""
    if evidence.evidence_type not in _ROLE_LABEL:
        return None
    if evidence.claim not in _PERSON_CLAIMS:
        return None
    value = evidence.extracted_value
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    match = _STRIPPED_NAME_RE.match(value)
    if match is None:
        return None
    name = match.group(1)
    if _has_org_word(name):
        return None
    return name


def _role_compatible(contact_role: str, evidence_role: str) -> bool:
    """True when an attribution-phrase role aligns with a contact's role label."""
    a = contact_role.lower().replace("-", "")
    b = evidence_role.lower().replace("-", "")
    if a in ("cofounder", "founder") and b in ("cofounder", "founder"):
        return True
    return a == b


def _email_for_contact(
    attributed: list[AttributedEmail], full_name: str, role: str
) -> AttributedEmail | None:
    """The attributed email whose name (and role, when stated) matches the contact."""
    for item in attributed:
        if item.name.lower() != full_name.lower():
            continue
        if item.role is not None and not _role_compatible(role, item.role):
            continue
        return item
    return None


def _email_evidence_id(evidence_items: list[Evidence], email: str) -> UUID | None:
    """The id of the EMAIL evidence that carried this exact address, if present."""
    for item in evidence_items:
        if (
            item.evidence_type is EvidenceType.EMAIL
            and isinstance(item.extracted_value, str)
            and item.extracted_value.strip().lower() == email.lower()
        ):
            return item.evidence_id
    return None


class ContactAssemblyService:
    """Assemble evidence-backed contacts for a candidate."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.evidence_repo = EvidenceRepository(db)
        self.contact_repo = ContactRepository(db)

    def assemble(
        self,
        candidate_id: UUID,
        candidate: CompanyCandidate | None = None,
    ) -> list[Contact]:
        """One contact per evidenced named leader; idempotent by name and role.

        :param candidate_id: the candidate whose persisted evidence is used.
        :param candidate: the candidate model (for its own-site domain). An
            email only populates a contact when it is explicitly attributed to
            that same named person AND sits on the candidate's own-site domain
            (a publisher/article-host email is never the leader's work email).
        :returns: the assembled contacts for this candidate. Contact creation
            is scoped to persisted evidence only: ``full_name`` and ``role``
            come from the leader claim. ``email`` is populated ONLY when the
            persisted source text explicitly attributes that email to the same
            named person on the candidate's own-site domain (the identical
            explicit-attribution phrases the EMAIL_ATTRIBUTION evaluator
            requires); the contact is then recorded as ``EVIDENCED`` — never
            ``VERIFIED``. Without attribution ``email`` stays ``None`` and
            ``verification_status`` stays ``UNVERIFIED``. ``evidence_ids``
            reference only the evidence actually used. The current Contact ORM
            does not persist ``evidence_ids``; the assembled object carries the
            linkage, a later DB round-trip drops it.
        """
        evidence_items = self.evidence_repo.list_by_candidate(candidate_id)
        if candidate is None:
            company_hosts = None
        else:
            own_host = own_site_host(candidate)
            company_hosts = {own_host} if own_host else set()
        attributed = find_attributed_emails(evidence_items, company_hosts=company_hosts)
        contacts: list[Contact] = []
        for evidence in self._person_evidence(candidate_id):
            name = _person_name(evidence)
            if name is None:
                continue
            role = _ROLE_LABEL[evidence.evidence_type]
            matched = _email_for_contact(attributed, name, role)
            email = matched.email if matched is not None else None
            email_evidence_id = (
                _email_evidence_id(evidence_items, email) if email is not None else None
            )
            if email is not None:
                verification_status = VerificationStatus.EVIDENCED
                evidence_ids = [
                    evidence.evidence_id,
                    *( [email_evidence_id] if email_evidence_id is not None else [] ),
                ]
            else:
                verification_status = VerificationStatus.UNVERIFIED
                evidence_ids = [evidence.evidence_id]
            existing = self.contact_repo.find_existing(candidate_id, name, role)
            if existing is not None:
                if email is not None and existing.email is None:
                    upgraded = existing.model_copy(
                        update={
                            "email": email,
                            "verification_status": verification_status,
                            "evidence_ids": evidence_ids,
                        }
                    )
                    contacts.append(self.contact_repo.update(upgraded))
                else:
                    contacts.append(existing)
                continue
            contact = Contact(
                candidate_id=candidate_id,
                full_name=name,
                role=role,
                email=email,
                verification_status=verification_status,
                evidence_ids=evidence_ids,
            )
            self.contact_repo.create(contact)
            contacts.append(contact)
        return contacts

    def _person_evidence(self, candidate_id: UUID) -> list[Evidence]:
        """Distinct named-leader claims for the candidate, deterministically ordered."""
        candidates: dict[tuple[str, str], Evidence] = {}
        for evidence_type in _ROLE_LABEL:
            rows = sorted(
                self.evidence_repo.list_by_candidate_and_type(candidate_id, evidence_type),
                key=lambda item: (item.extracted_at, str(item.evidence_id)),
            )
            for evidence in rows:
                name = _person_name(evidence)
                if name is None:
                    continue
                key = (evidence.evidence_type.value, name.lower())
                candidates.setdefault(key, evidence)
        return [
            evidence
            for _, evidence in sorted(
                candidates.items(), key=lambda pair: (pair[0][0], pair[0][1])
            )
        ]