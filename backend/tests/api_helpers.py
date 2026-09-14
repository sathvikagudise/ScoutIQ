"""Shared helpers for tests that exercise authenticated API endpoints.

Every helper here uses an isolated session (``db``) provided by the calling
test module. The default test user email is constant within a single test's
database, so repository-created runs and the authenticated ``TestClient``
always resolve to the same user.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.auth.service import normalize_email

TEST_PASSWORD = "test-password-123"
TEST_EMAIL = "test@scoutiq.local"


def ensure_test_user(db: Session, email: Optional[str] = None):
    """Return the ORM user row for ``email``, creating it on first use."""
    from app.db.orm.user import UserRecord

    normalized = normalize_email(email or TEST_EMAIL)
    record = db.scalar(select(UserRecord).where(UserRecord.email == normalized))
    if record is None:
        record = UserRecord(
            id=uuid4(),
            email=normalized,
            password_hash=hash_password(TEST_PASSWORD),
            display_name="Test User",
            created_at=datetime.now(timezone.utc),
        )
        db.add(record)
        db.commit()
        record = db.scalar(select(UserRecord).where(UserRecord.email == normalized))
    return record


def authed_client(app_obj, db: Session, email: Optional[str] = None) -> TestClient:
    """Install a ``get_db`` override for ``db`` and return a token-authed TestClient.

    Uses the real public register/login endpoints (register first; falls back to
    login when the user already exists), then attaches the returned bearer
    token to the client so every request carries ``Authorization: Bearer <token>``.
    """
    from app.db.session import get_db

    def override_get_db():
        yield db

    app_obj.dependency_overrides[get_db] = override_get_db

    email = normalize_email(email or TEST_EMAIL)
    client = TestClient(app_obj)
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "display_name": "Test User",
        },
    )
    if response.status_code == 409:
        response = client.post(
            "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
        )
    assert response.status_code in (200, 201), response.text
    token = response.json()["token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def make_owned_run(
    db: Session,
    *,
    target_lead_count: int = 5,
    completed: bool = False,
    email: Optional[str] = None,
):
    """Persist a run owned by the (created-on-demand) test user for ``db``."""
    from app.core.enums import RunStatus
    from app.models.run import DiscoveryRun
    from app.repositories.run_repository import RunRepository

    user = ensure_test_user(db, email=email)
    run = DiscoveryRun(target_lead_count=target_lead_count, user_id=user.id)
    persisted = RunRepository(db).create(run)
    if completed:
        RunRepository(db).update_progress(
            persisted.run_id,
            status=RunStatus.COMPLETED,
            qualified_lead_count=0,
            completed_at=datetime.now(timezone.utc),
        )
    return RunRepository(db).get(persisted.run_id)