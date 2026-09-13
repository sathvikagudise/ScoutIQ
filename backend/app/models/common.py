"""Shared factories used as Pydantic defaults across models."""

from datetime import datetime, timezone
from uuid import UUID, uuid4


def new_id() -> UUID:
    """Generate a model-level default UUID."""
    return uuid4()


def utcnow() -> datetime:
    """Return the current UTC timestamp (used as a Pydantic default)."""
    return datetime.now(timezone.utc)