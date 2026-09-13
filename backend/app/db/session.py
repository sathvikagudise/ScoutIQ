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


def build_engine(database_url: str | None = None) -> Engine:
    """Create an engine. Tests pass an explicit SQLite URL for isolation."""
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables for the configured database (idempotent).

    Phase 14 adds a nullable ``user_id`` column to the already-existing
    ``runs`` table. SQLite's ``create_all`` never alters existing tables, so a
    legacy database gets the column via a one-time ``ALTER TABLE``. The added
    column is a plain ``CHAR(32)`` (matching how SQLAlchemy stores ``Uuid``
    values on SQLite), exactly as if the table had been created fresh. Rows
    keep ``NULL``: legacy/unowned runs stay invisible to authenticated users.
    """
    import app.db.orm  # noqa: F401  ensures all tables are registered

    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        table_info = connection.exec_driver_sql("PRAGMA table_info(runs)").mappings().all()
        column_names = {row["name"] for row in table_info}
        if "user_id" not in column_names:
            connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN user_id CHAR(32)")


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()