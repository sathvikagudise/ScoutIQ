"""Phase 14 auth + ownership tests -- fully offline, isolated SQLite.

Covers the Part Q scenarios: registration, login, logout, bearer-token
persistence, password storage safety, empty workspace for a new user,
backend-enforced run ownership, 401/404 behavior for unauthenticated and
cross-user access, and PostgreSQL persistence compatibility.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.common import utcnow
from app.models.run import DiscoveryRun
from app.repositories.run_repository import RunRepository

EMAIL_A = "alice@example.com"
EMAIL_B = "bob@example.com"
PASSWORD = "correct-horse-battery"

from api_helpers import authed_client  # noqa: E402

TEST_PASSWORD = "test-password-123"


def _authorize(client: TestClient, body: dict) -> None:
    """Attach the bearer token returned by register/login to ``client``."""
    client.headers.update({"Authorization": f"Bearer {body['token']}"})


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'phase14.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    def _enable_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db) -> TestClient:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------


def test_register_creates_account_and_starts_session(client):
    response = client.post(
        "/api/auth/register",
        json={"email": EMAIL_A, "password": PASSWORD, "display_name": "Alice"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    user = body["user"]
    assert user["email"] == EMAIL_A
    assert user["display_name"] == "Alice"
    assert user["user_id"]
    assert "created_at" in user
    assert "password_hash" not in user
    assert "password" not in user
    assert "password_hash" not in body

    _authorize(client, body)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL_A


def test_register_duplicate_email_rejected(client):
    first = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    assert second.status_code == 409


def test_register_normalizes_email_case(client):
    response = client.post(
        "/api/auth/register", json={"email": "  Alice@Example.COM ", "password": PASSWORD}
    )
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "alice@example.com"


def test_register_rejects_invalid_email(client):
    for bad in ("not-an-email", "no-at", "spaces in@email.com"):
        response = client.post("/api/auth/register", json={"email": bad, "password": PASSWORD})
        assert response.status_code == 422


def test_register_rejects_short_password(client):
    response = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": "short"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 2. Password storage safety
# ---------------------------------------------------------------------------


def test_password_not_stored_in_plaintext(db, client):
    client.post("/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD})
    # Any password hash must be a bcrypt blob, never the plaintext itself.
    import sqlalchemy as sa

    from app.db.orm.user import UserRecord

    row = db.scalar(sa.select(UserRecord).where(UserRecord.email == EMAIL_A))
    assert row is not None
    assert row.password_hash != PASSWORD
    assert row.password_hash.startswith("$2")
    assert PASSWORD not in db.execute(sa.text("SELECT password_hash FROM users")).scalar_one()


def test_login_wrong_password_rejected(client):
    client.post("/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD})
    bad = client.post(
        "/api/auth/login", json={"email": EMAIL_A, "password": "wrong-password"}
    )
    assert bad.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# 3. Login / logout / bearer-token session
# ---------------------------------------------------------------------------


def test_login_success_and_me(client):
    register = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    _authorize(client, register.json())
    client.post("/api/auth/logout")
    client.headers.pop("Authorization", None)

    login = client.post(
        "/api/auth/login", json={"email": EMAIL_A, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["user"]["email"] == EMAIL_A

    _authorize(client, login.json())
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL_A


def test_login_unknown_email_rejected(client):
    response = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_logout_revokes_server_side_session(db, client):
    register = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    token = register.json()["token"]
    assert token is not None
    _authorize(client, register.json())

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 204

    import sqlalchemy as sa

    from app.db.orm.user import AuthSessionRecord

    remaining = db.scalar(
        sa.select(sa.func.count()).select_from(AuthSessionRecord)
    )
    assert remaining == 0

    assert client.get("/api/auth/me").status_code == 401


def test_bearer_token_scheme_variants_accepted(db, client):
    register = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    token = register.json()["token"]

    for header in (f"Bearer {token}", f"bearer {token}", token):
        probe = TestClient(app)
        probe.headers.update({"Authorization": header})
        me = probe.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == EMAIL_A


def test_missing_malformed_or_unknown_token_rejected(db, client):
    # No header at all, UUID that parses but is unknown, and non-UUID garbage.
    assert client.get("/api/auth/me").status_code == 401

    unknown = TestClient(app)
    unknown.headers.update({"Authorization": f"Bearer {uuid4()}"})
    assert unknown.get("/api/auth/me").status_code == 401

    for garbage in ("Bearer not-a-uuid", "two words here"):
        probe = TestClient(app)
        probe.headers.update({"Authorization": garbage})
        assert probe.get("/api/auth/me").status_code == 401


def test_expired_token_rejected(db, client):
    from app.db.orm.user import AuthSessionRecord

    register = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    token = UUID(register.json()["token"])
    _authorize(client, register.json())
    assert client.get("/api/auth/me").status_code == 200

    session = db.get(AuthSessionRecord, token)
    session.expires_at = utcnow().replace(tzinfo=None) - timedelta(days=1)
    db.commit()

    assert client.get("/api/auth/me").status_code == 401
    # The expired session row is cleaned up server-side.
    assert db.get(AuthSessionRecord, token) is None


# ---------------------------------------------------------------------------
# 4. Unauthenticated access
# ---------------------------------------------------------------------------


def test_run_endpoints_require_authentication(client):
    assert client.get("/api/runs").status_code == 401
    assert client.post("/api/runs", json={"target_lead_count": 5}).status_code == 401
    assert client.get(f"/api/runs/{uuid4()}").status_code == 401
    assert client.get(f"/api/runs/{uuid4()}/results").status_code == 401
    assert client.get(f"/api/runs/{uuid4()}/diagnostics").status_code == 401
    assert client.get(f"/api/runs/{uuid4()}/activity").status_code == 401
    assert client.post(f"/api/runs/{uuid4()}/execute", json={"queries": ["x"]}).status_code == 401
    assert client.post(f"/api/runs/{uuid4()}/qualify", json={"candidate_ids": [str(uuid4())]}).status_code == 401
    assert client.post(f"/api/runs/{uuid4()}/contacts", json={"candidate_ids": [str(uuid4())]}).status_code == 401
    assert client.post(f"/api/runs/{uuid4()}/leads", json={"candidate_ids": [str(uuid4())]}).status_code == 401
    assert client.post(f"/api/runs/{uuid4()}/complete").status_code == 401


def test_auth_me_unauthenticated_returns_401(client):
    assert client.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# 5. Ownership isolation (User A vs User B)
# ---------------------------------------------------------------------------


def test_new_user_has_empty_workspace(client):
    register = client.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    _authorize(client, register.json())
    runs = client.get("/api/runs")
    assert runs.status_code == 200
    assert runs.json() == []


def test_user_b_cannot_list_user_a_runs(client):
    alice = TestClient(app)
    alice_register = alice.post(
        "/api/auth/register", json={"email": EMAIL_A, "password": PASSWORD}
    )
    _authorize(alice, alice_register.json())
    alice.post("/api/runs", json={"target_lead_count": 3})

    bob = client.post("/api/auth/register", json={"email": EMAIL_B, "password": PASSWORD})
    assert bob.status_code == 201
    _authorize(client, bob.json())

    bob_runs = client.get("/api/runs")
    assert bob_runs.status_code == 200
    assert bob_runs.json() == []


def test_user_b_cannot_access_user_a_run_by_direct_url(db):
    # Alice owns a completed run.
    alice_client = authed_client(app, db, email=EMAIL_A)
    alice_run_id = alice_client.post("/api/runs", json={"target_lead_count": 2}).json()["run_id"]

    # Bob, a completely separate account in the same database, must get 404.
    bob_client = authed_client(app, db, email=EMAIL_B)
    assert bob_client.get(f"/api/runs/{alice_run_id}").status_code == 404
    assert bob_client.get(f"/api/runs/{alice_run_id}/results").status_code == 404
    assert bob_client.get(f"/api/runs/{alice_run_id}/diagnostics").status_code == 404
    assert bob_client.get(f"/api/runs/{alice_run_id}/activity").status_code == 404


def test_user_b_cannot_operate_on_user_a_run(db):
    alice_client = authed_client(app, db, email=EMAIL_A)
    alice_run_id = alice_client.post("/api/runs", json={"target_lead_count": 2}).json()["run_id"]

    bob_client = authed_client(app, db, email=EMAIL_B)
    bob_response = bob_client.post(
        f"/api/runs/{alice_run_id}/complete"
    )
    assert bob_response.status_code == 404
    bob_exec = bob_client.post(
        f"/api/runs/{alice_run_id}/execute", json={"queries": ["acme"]}
    )
    assert bob_exec.status_code == 404


# ---------------------------------------------------------------------------
# 6. History persists across logout/login for the SAME user
# ---------------------------------------------------------------------------


def test_same_user_history_persists_after_logout_login(db):
    client = authed_client(app, db, email=EMAIL_A)
    created = client.post(
        "/api/runs", json={"target_lead_count": 4}
    ).json()["run_id"]
    assert len(client.get("/api/runs").json()) == 1

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    login = client.post(
        "/api/auth/login", json={"email": EMAIL_A, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200

    _authorize(client, login.json())
    runs = client.get("/api/runs")
    assert runs.status_code == 200
    assert [run["run_id"] for run in runs.json()] == [created]


# ---------------------------------------------------------------------------
# 7. Legacy unowned runs are invisible
# ---------------------------------------------------------------------------


def test_legacy_unowned_run_invisible_to_authenticated_user(db):
    # A run created without any user (mimics pre-auth migration state).
    legacy = RunRepository(db).create(DiscoveryRun(target_lead_count=9))
    assert legacy.user_id is None

    client = authed_client(app, db, email=EMAIL_A)
    workspace = client.get("/api/runs")
    assert workspace.status_code == 200
    assert workspace.json() == []

    assert client.get(f"/api/runs/{legacy.run_id}").status_code == 404


# ---------------------------------------------------------------------------
# 8. Guard: response never reveals another user's run exists
# ---------------------------------------------------------------------------


def test_foreign_and_missing_runs_are_indistinguishable(db):
    alice_client = authed_client(app, db, email=EMAIL_A)
    alice_run_id = alice_client.post("/api/runs", json={"target_lead_count": 2}).json()["run_id"]

    bob_client = authed_client(app, db, email=EMAIL_B)
    foreign_response = bob_client.get(f"/api/runs/{alice_run_id}")
    missing_response = bob_client.get(f"/api/runs/{uuid4()}")

    assert foreign_response.status_code == 404
    assert missing_response.status_code == 404
    assert foreign_response.json()["detail"] == missing_response.json()["detail"] == "Run not found"


# ---------------------------------------------------------------------------
# 9. Register with a display name, persisted in the profile
# ---------------------------------------------------------------------------


def test_registered_full_name_round_trip(client):
    response = client.post(
        "/api/auth/register",
        json={"email": EMAIL_A, "password": PASSWORD, "display_name": "Alice Example"},
    )
    assert response.status_code == 201
    _authorize(client, response.json())
    me = client.get("/api/auth/me")
    assert me.json()["display_name"] == "Alice Example"


# ---------------------------------------------------------------------------
# 10. PostgreSQL persistence compatibility
# ---------------------------------------------------------------------------


def test_build_engine_normalizes_postgres_url_to_psycopg():
    from app.db.session import build_engine

    engine = build_engine("postgresql://user:secret@db-host:5432/tvbfundradar")
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_build_engine_keeps_sqlite_local():
    from app.db.session import build_engine

    engine = build_engine("sqlite:///./local.db")
    assert engine.url.drivername == "sqlite"
    assert engine.pool._pre_ping is False
    engine.dispose()


def test_init_db_never_runs_sqlite_migration_on_postgres(monkeypatch):
    import app.db.session as db_session

    recorded = {"create_all": 0, "begin": 0}

    def _fake_create_all(bind, **kwargs):
        recorded["create_all"] += 1

    class _FakeEngine:
        class _Dialect:
            name = "postgresql"

        dialect = _Dialect()

        def begin(self):
            recorded["begin"] += 1
            raise AssertionError("SQLite-only migration must not run on PostgreSQL")

    monkeypatch.setattr(db_session.Base.metadata, "create_all", _fake_create_all)
    monkeypatch.setattr(db_session, "engine", _FakeEngine())

    db_session.init_db()
    assert recorded["create_all"] == 1
    assert recorded["begin"] == 0


def test_init_db_sqlite_migrates_legacy_runs_table(tmp_path, monkeypatch):
    """A pre-auth SQLite DB gains the nullable ``user_id`` column idempotently."""
    import app.db.session as db_session

    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE runs (id CHAR(32) PRIMARY KEY, status VARCHAR(20))"
        )
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)").fetchall()}
    assert "user_id" not in columns

    monkeypatch.setattr(db_session, "engine", engine)
    db_session.init_db()

    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)").fetchall()}
    assert "user_id" in columns
    engine.dispose()