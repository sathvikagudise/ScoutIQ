"""Central configuration. Environment variables are optional."""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///./scoutiq.db"
DEFAULT_RESEARCH_TIMEOUT_SECONDS = 8.0
DEFAULT_RESEARCH_MAX_RESPONSE_BYTES = 2_000_000
# Dev uses the Vite dev proxy (same origin from the browser's perspective), so
# the dev origin is the only one configured by default. Production deploys on a
# separate frontend origin must set CORS_ORIGINS explicitly. Wildcard origins
# are never used with credentialed requests.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _parse_origins(value: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


@dataclass(frozen=True)
class Settings:
    """Runtime settings for ScoutIQ, all optional over ENV overrides."""

    database_url: str = DEFAULT_DATABASE_URL
    research_timeout_seconds: float = DEFAULT_RESEARCH_TIMEOUT_SECONDS
    research_max_response_bytes: int = DEFAULT_RESEARCH_MAX_RESPONSE_BYTES
    cors_origins: tuple[str, ...] = _parse_origins(DEFAULT_CORS_ORIGINS)
    session_cookie_secure: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            research_timeout_seconds=float(
                os.getenv("RESEARCH_TIMEOUT_SECONDS", DEFAULT_RESEARCH_TIMEOUT_SECONDS)
            ),
            research_max_response_bytes=int(
                os.getenv("RESEARCH_MAX_RESPONSE_BYTES", DEFAULT_RESEARCH_MAX_RESPONSE_BYTES)
            ),
            cors_origins=_parse_origins(os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)),
            session_cookie_secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower()
            in ("1", "true", "yes"),
        )


settings = Settings.from_env()