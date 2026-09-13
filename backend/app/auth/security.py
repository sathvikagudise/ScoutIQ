"""bcrypt password hashing — the only place passwords are ever touched.

Passwords are hashed at rest with cost 12 and never returned by any endpoint,
logged, or stored anywhere except the ``users.password_hash`` column.
"""

from __future__ import annotations

import bcrypt

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Return a bcrypt hash suitable for ``verify_password``."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode(
        "ascii"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether ``password`` matches a stored bcrypt hash.

    Unknown/invalid hash formats simply fail verification rather than raising,
    so a corrupted record never turns into a login error.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False