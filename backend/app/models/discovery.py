"""Discovery pipeline models (Phase 0 API surface, preserved)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.constants import (
    DEFAULT_MAX_RESULTS_PER_QUERY,
    DEFAULT_MAX_URLS_TO_VALIDATE,
    MAX_RESULTS_CAP,
)
from app.models.source import FetchValidation, Source


class DiscoveredSource(Source):
    """A source returned by a discovery provider for a specific query.

    Adds the discovery query text to the shared :class:`Source` contract.
    """

    query: str


class DiscoveryRequest(BaseModel):
    """Request body for POST /api/discovery/search."""

    queries: list[str] = Field(min_length=1, description="One or more search queries.")
    max_results_per_query: int = Field(
        default=DEFAULT_MAX_RESULTS_PER_QUERY, ge=1, le=MAX_RESULTS_CAP
    )


class DiscoveryResponse(BaseModel):
    """Structured response for a discovery run."""

    results: list[DiscoveredSource]
    total_results: int
    deduplicated_count: int
    provider: str
    errors: list[str] = Field(default_factory=list)


class ValidateRequest(DiscoveryRequest):
    """Request body for POST /api/discovery/validate."""

    max_urls_to_validate: int = Field(
        default=DEFAULT_MAX_URLS_TO_VALIDATE, ge=1, le=MAX_RESULTS_CAP
    )


class ValidatedResult(BaseModel):
    """A discovered source paired with its HTTP validation outcome."""

    source: DiscoveredSource
    validation: FetchValidation


class ValidateResponse(DiscoveryResponse):
    """Response for POST /api/discovery/validate."""

    validations: list[ValidatedResult] = Field(default_factory=list)