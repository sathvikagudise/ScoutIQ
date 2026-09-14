"""Engine, session factory, application startup init, and FastAPI dependency."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def normalize_database_url(database_url: str) -> str:
    """Make a generic dialect URL explicit before handing it to SQLAlchemy.

    ``postgresql://`` defaults to the psycopg2 driver, which is not a project
    dependency. We route it to the pure-Python ``psycopg`` (v3) driver, the
    driver pinned in ``requirements.txt``. Local development keeps SQLite.
    """
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    return database_url


def build_engine(database_url: str | None = None) -> Engine:
    """Create an engine. Tests pass an explicit SQLite URL for isolation.

    PostgreSQL: the URL is normalized onto the installed psycopg driver and
    ``pool_pre_ping`` keeps connections valid across server-side recycles
    (Render restarts/scale events). SQLite: single-thread guard and the
    foreign-key pragma are applied as before.
    """
    url = normalize_database_url(database_url or settings.database_url)
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=not is_sqlite)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _migrate_legacy_sqlite_runs(connection) -> None:
    """One-time SQLite migration adding the nullable ``user_id`` column.

    SQLite's ``create_all`` never alters existing tables, so a legacy
    database gets the column via a manual ``ALTER TABLE``. The added column
    is a plain ``CHAR(32)`` (matching how SQLAlchemy stores ``Uuid`` values
    on SQLite), exactly as if the table had been created fresh. Rows keep
    ``NULL``: legacy/unowned runs stay invisible to authenticated users.
    This is SQLite-only — NEVER run against PostgreSQL.
    """
    table_info = connection.exec_driver_sql("PRAGMA table_info(runs)").mappings().all()
    column_names = {row["name"] for row in table_info}
    if "user_id" not in column_names:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN user_id CHAR(32)")


def init_db() -> None:
    """Create tables for the configured database (idempotent).

    Table/seed creation works on any SQLAlchemy dialect. The legacy column
    migration above is inherently SQLite-specific (``PRAGMA table_info`` and
    ``CHAR(32)``), so it only runs when the configured URL is SQLite.
    """
    import app.db.orm  # noqa: F401  ensures all tables are registered

    Base.metadata.create_all(bind=engine)
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        _migrate_legacy_sqlite_runs(connection)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()