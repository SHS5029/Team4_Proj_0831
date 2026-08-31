"""Environment-backed application configuration.

The root ``.env`` file remains the source of connection credentials.  The
database name is deliberately replaced with ``Team4_Proj`` so an unrelated
database from a shared developer URL can never be used by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings needed by the authentication persistence layer."""

    database_url: str = field(repr=False)
    database_name: str = "Team4_Proj"
    app_env: str = "development"

    def __post_init__(self) -> None:
        raw_url = self.database_url.strip()
        if not raw_url:
            raise ValueError("DATABASE_URL must contain a PostgreSQL connection URL")

        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("DATABASE_URL is not a valid PostgreSQL URL") from exc

        if parsed.scheme.lower() not in POSTGRES_SCHEMES:
            raise ValueError("DATABASE_URL must use the postgres or postgresql scheme")
        if not parsed.hostname:
            raise ValueError("DATABASE_URL must include a PostgreSQL host")
        if port is not None and not 1 <= port <= 65_535:
            raise ValueError("DATABASE_URL contains an invalid PostgreSQL port")
        if not self.database_name.strip():
            raise ValueError("DATABASE_NAME must not be empty")
        if any(character in self.database_name for character in ("/", "\x00")):
            raise ValueError("DATABASE_NAME contains an invalid character")

        object.__setattr__(self, "database_url", raw_url)
        object.__setattr__(self, "database_name", self.database_name.strip())

    @property
    def effective_database_url(self) -> str:
        """Return the configured server URL targeting only ``database_name``.

        ``urlsplit``/``urlunsplit`` preserve encoded credentials, host, port,
        and connection query options.  No credential is decoded or logged.
        """

        parsed = urlsplit(self.database_url)
        database_path = f"/{quote(self.database_name, safe='')}"
        return urlunsplit(
            (parsed.scheme, parsed.netloc, database_path, parsed.query, parsed.fragment)
        )

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Settings:
        """Load settings without overriding variables already set by the host."""

        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            database_name=os.getenv("DATABASE_NAME", "Team4_Proj"),
            app_env=os.getenv("APP_ENV", "development"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable settings instance per application process."""

    return Settings.from_env()

