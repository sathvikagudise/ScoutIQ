"""User and session models (identity layer)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.common import new_id, utcnow


class User(BaseModel):
    """A TVBFundRadar account. ``password_hash`` never appears on this model."""

    user_id: UUID = Field(default_factory=new_id)
    email: str
    display_name: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class UserRegister(BaseModel):
    """Request body for POST /auth/register."""

    email: str
    password: str
    display_name: Optional[str] = None


class UserLogin(BaseModel):
    """Request body for POST /auth/login."""

    email: str
    password: str


class AuthResponse(BaseModel):
    """Response body for register/login: a fresh bearer token + the user."""

    token: str
    user: User