"""Persistence operations for Contact records."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mappers import contact_to_record, record_to_contact
from app.db.orm.contact import ContactRecord
from app.models.contact import Contact


class ContactRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, contact: Contact) -> Contact:
        self.db.add(contact_to_record(contact))
        self.db.commit()
        return self.get(contact.contact_id)

    def get(self, contact_id: UUID) -> Optional[Contact]:
        record = self.db.get(ContactRecord, contact_id)
        return record_to_contact(record) if record else None

    def update(self, contact: Contact) -> Optional[Contact]:
        record = self.db.get(ContactRecord, contact.contact_id)
        if record is None:
            return None
        record.full_name = contact.full_name
        record.role = contact.role
        record.email = contact.email
        record.verification_status = contact.verification_status
        self.db.commit()
        return self.get(contact.contact_id)

    def find_existing(
        self,
        candidate_id: UUID,
        full_name: str,
        role: Optional[str] = None,
    ) -> Optional[Contact]:
        """The contact with the identical scoped identity, if one exists.

        The idempotency scope is ``(candidate_id, full_name, role)``. A ``None``
        role matches only contacts recorded without a role.
        """
        statement = select(ContactRecord).where(
            ContactRecord.candidate_id == candidate_id,
            ContactRecord.full_name == full_name,
        )
        if role is None:
            statement = statement.where(ContactRecord.role.is_(None))
        else:
            statement = statement.where(ContactRecord.role == role)
        record = self.db.scalars(statement).first()
        return record_to_contact(record) if record else None

    def list_by_candidate(self, candidate_id: UUID) -> list[Contact]:
        records = self.db.scalars(
            select(ContactRecord)
            .where(ContactRecord.candidate_id == candidate_id)
            .order_by(ContactRecord.created_at.asc())
        ).all()
        return [record_to_contact(record) for record in records]