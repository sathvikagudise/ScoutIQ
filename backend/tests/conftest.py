"""Test bootstrap. Primary import wiring lives in ``pytest.ini`` (``pythonpath``
entries for ``app`` and the ``fakes`` helper); this sys.path fallback remains for
older pytest versions that honor conftest-time inserts."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

for path in (ROOT / "backend", TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from guard_helpers import dev_db_fingerprint  # noqa: E402


@pytest.fixture(scope="session")
def dev_db_start_state():
    """Fingerprint of the developer's ``scoutiq.db`` at session start.

    The three ``test_developer_database_not_created`` guards compare their
    live fingerprint against this snapshot, proving the offline test suite
    neither created nor modified the developer database during the run -
    regardless of whether a dev database already exists from live API use.
    """
    return dev_db_fingerprint()


@pytest.fixture(scope="session", autouse=True)
def _fast_bcrypt_for_tests():
    """Lower bcrypt cost so registrations across hundreds of isolated tests
    stay fast. bcrypt embeds the cost in the hash, so ``verify_password`` still
    works against the cheaper test hashes. The production module default
    (``_BCRYPT_ROUNDS = 12``) is restored afterwards."""
    from app.auth import security

    previous = security._BCRYPT_ROUNDS
    security._BCRYPT_ROUNDS = 4
    yield
    security._BCRYPT_ROUNDS = previous


@pytest.fixture(scope="session", autouse=True)
def _developer_database_integrity(dev_db_start_state):
    """Session-wide backstop: fail loudly at teardown if any test mutated the
    developer database. This catches mutations that happen after the module
    guards run, not just before them."""
    yield dev_db_start_state
    _ = dev_db_start_state  # retained for clarity
    from guard_helpers import assert_developer_db_untouched

    assert_developer_db_untouched(dev_db_start_state)