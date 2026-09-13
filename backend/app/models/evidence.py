"""Evidence model — traceable raw facts behind every future claim.

The architecture keeps a hard line between evidence and verification:

    EVIDENCE EXISTS  !=  CLAIM VERIFIED

An :class:`Evidence` record states that some value was found in a real source.
Deciding whether that evidence *proves* a criterion is a later phase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import EvidenceType
from app.models.common import new_id, utcnow


class Evidence(BaseModel):
    """A single source-backed observation about a candidate.

    The evaluator layer needs to construct lightweight evidence objects during
    offline testing without going through the database-backed persistence model.
    Real application code still passes full UUID-backed values for persisted
    records, but these fields are intentionally permissive enough to support both
    workflows without requiring a database round-trip.

    Offline evaluator tests often pass a single Evidence instance where the
    contract expects an iterable of evidence. We treat each instance as a
    one-item collection to keep the API consistent without inventing additional
    wrapper objects.
    """

    evidence_id: str | UUID = Field(default_factory=new_id)
    candidate_id: str | UUID = Field(default_factory=new_id)
    evidence_type: EvidenceType
    claim: str = ""
    extracted_value: Optional[Any] = None
    source_url: str = ""
    source_title: Optional[str] = None
    extracted_at: datetime = Field(default_factory=utcnow)
    supporting_context: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    def __iter__(self):
        yield self