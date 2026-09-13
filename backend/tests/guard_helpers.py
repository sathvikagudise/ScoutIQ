"""Shared developer-database integrity guard for the offline test suite.

The test suite must never create or mutate the developer's live SQLite
database (``backend/scoutiq.db``). This helper measures the database's
fingerprint (absent, or size + mtime) so guards can assert *behavior* — "the
test run did not touch the dev database" — which holds whether or not a dev
database already exists on this machine. A dev DB created by running the live
API (``uvicorn`` from ``backend/``) must not make the test suite red.
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEV_DB_PATH = BACKEND_ROOT / "scoutiq.db"


def dev_db_fingerprint() -> tuple:
    """Snapshot of the dev database: absent, or (size, mtime_ns)."""
    if not DEV_DB_PATH.exists():
        return ("absent",)
    stat = DEV_DB_PATH.stat()
    return ("present", stat.st_size, stat.st_mtime_ns)


def assert_developer_db_untouched(start_state: tuple) -> None:
    """Assert the dev database fingerprint is unchanged since ``start_state``."""
    current = dev_db_fingerprint()
    assert current == start_state, (
        "The test suite created or modified the developer database at "
        f"{DEV_DB_PATH}; tests must run offline against temp SQLite files only."
    )
    return None