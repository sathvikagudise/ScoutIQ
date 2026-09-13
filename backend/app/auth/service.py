"""Authentication service: user creation, server-side sessions, request guards.

The browser only ever holds the ``session_id`` cookie value (an unguessable
server-side session UUID). No password or long-lived token is ever stored on
the client. Logout deletes the session row, so a stolen cookie is inert after
sign-out. Session expiry is enforced server-side on every request.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.core.config import settings
from app.db.mappers import record_to_user, user_to_record
from app.db.orm.user import AuthSessionRecord, UserRecord
from app.db.session import get_db
from app.models.common import utcnow
from app.models.run import DiscoveryRun
from app.models.user import User
from app.repositories.run_repository import RunRepository

SESSION_COOKIE_NAME = "session_id"
SESSION_TTL_DAYS = 7
SESSION_COOKIE_MAX_AGE = SESSION_TTL_DAYS * 24 * 60 * 60
MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str) -> str:
    """Trim and lowercase so one identifier can never register under two spellings."""
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    """Lightweight shape check (no external validation dependency)."""
    if "@" not in email or len(email) < 6:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain and not any(c in email for c in (" ", "\n", "\t"))


def create_user(db: Session, *, email: str, password: str, display_name: Optional[str] = None) -> User:
    """Create and persist a user with a bcrypt password hash.

    Raises ``HTTPException(409)`` when the (normalized) email is already
    registered. The email column is unique+indexed, so this is belt-and-braces
    around the database constraint.
    """
    normalized = normalize_email(email)
    if get_user_by_email(db, normalized) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=normalized, display_name=display_name)
    db.add(user_to_record(user, password_hash=hash_password(password)))
    db.commit()
    existing = get_user_by_email(db, normalized)
    if existing is None:
        raise HTTPException(status_code=500, detail="User could not be created")
    return existing


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    normalized = normalize_email(email)
    record = db.scalar(select(UserRecord).where(UserRecord.email == normalized))
    return record_to_user(record) if record else None


def get_user_record_by_email(db: Session, email: str) -> Optional[UserRecord]:
    record = db.scalar(
        select(UserRecord).where(UserRecord.email == normalize_email(email))
    )
    return record


def authenticate(db: Session, *, email: str, password: str) -> Optional[User]:
    """Return the user only when the email exists and the password matches."""
    record = get_user_record_by_email(db, email)
    if record is None:
        return None
    if not verify_password(password, record.password_hash):
        return None
    return record_to_user(record)


def create_session(db: Session, user_id: UUID) -> AuthSessionRecord:
    now = utcnow()
    record = AuthSessionRecord(
        id=uuid4(),
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(days=SESSION_TTL_DAYS),
    )
    db.add(record)
    db.commit()
    return record


def delete_session(db: Session, token: UUID) -> None:
    record = db.get(AuthSessionRecord, token)
    if record is not None:
        db.delete(record)
        db.commit()


def set_session_cookie(response: Response, record: AuthSessionRecord) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value=str(record.id),
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """FastAPI dependency: resolve the session cookie to an authenticated user.

    Any missing, malformed, expired, or revoked session yields a generic 401.
    """
    token_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not token_value:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        token = UUID(token_value)
    except ValueError:
        raise HTTPException(status_code=401, detail="Not authenticated")

    record = db.get(AuthSessionRecord, token)
    if record is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if record.expires_at < utcnow().replace(tzinfo=None):
        db.delete(record)
        db.commit()
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_record = db.get(UserRecord, record.user_id)
    if user_record is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return record_to_user(user_record)


def require_owned_run(run_id: UUID, db: Session, user: User) -> DiscoveryRun:
    """Return a run only when the authenticated user owns it.

    Ownership is enforced here, in the backend, for every run-scoped endpoint.
    Runs that do not exist, are unowned (legacy, ``user_id`` NULL), or belong to
    a different user all resolve to the same 404 — the response never reveals
    that another user's run exists.
    """
    run = RunRepository(db).get(run_id)
    if run is None or run.user_id is None or run.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run