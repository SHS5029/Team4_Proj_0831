from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from backend.app.core.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_env_value(path: Path, key: str) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    raise AssertionError(f"{key} is missing from {path.name}")


def _assert_connection_details_preserved(source_url: str, effective_url: str) -> None:
    source = urlsplit(source_url)
    effective = urlsplit(effective_url)

    assert effective.scheme == source.scheme
    assert effective.hostname == source.hostname
    assert effective.port == source.port
    assert effective.query == source.query
    # Compare digests so a failing assertion cannot echo real .env credentials.
    assert _credential_digest(effective.username) == _credential_digest(source.username)
    assert _credential_digest(effective.password) == _credential_digest(source.password)


def _credential_digest(value: str | None) -> bytes:
    return sha256((value or "").encode()).digest()


def test_effective_database_url_replaces_only_database_path() -> None:
    source_url = (
        "postgresql://app_user:p%40ssword@db.internal:5433/original_db"
        "?sslmode=require&application_name=team4"
    )

    settings = Settings(database_url=source_url, database_name="Team4_Proj")

    effective_url = settings.effective_database_url
    _assert_connection_details_preserved(source_url, effective_url)
    assert urlsplit(effective_url).path == "/Team4_Proj"


def test_project_env_database_url_keeps_connection_and_targets_team4_proj() -> None:
    source_url = _read_env_value(PROJECT_ROOT / ".env", "DATABASE_URL")

    settings = Settings(database_url=source_url)

    effective_url = settings.effective_database_url
    _assert_connection_details_preserved(source_url, effective_url)
    assert urlsplit(effective_url).path == "/Team4_Proj"


def test_settings_can_load_the_configured_database_name_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실제 .env가 지정한 DB 이름을 임의의 과거 기본값으로 바꾸지 않는지 확인한다."""

    source_url = _read_env_value(PROJECT_ROOT / ".env", "DATABASE_URL")
    configured_database_name = _read_env_value(PROJECT_ROOT / ".env", "DATABASE_NAME")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_NAME", raising=False)

    settings = Settings.from_env(PROJECT_ROOT / ".env")

    _assert_connection_details_preserved(source_url, settings.effective_database_url)
    assert settings.database_name == configured_database_name
    assert urlsplit(settings.effective_database_url).path == f"/{configured_database_name}"


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "   ",
        "mysql://user:password@db.internal/source_db",
        "sqlite:///tmp/team4.db",
        "not-a-database-url",
    ],
)
def test_settings_rejects_empty_or_non_postgresql_database_url(database_url: str) -> None:
    with pytest.raises(ValueError, match="(?i)database|postgres"):
        Settings(database_url=database_url)


def test_internal_api_secret_is_validated_without_appearing_in_repr() -> None:
    secret = "synthetic-signing-value-with-more-than-32-characters"  # noqa: S105
    settings = Settings(
        database_url="postgresql://app:synthetic@localhost/Team4_Proj",
        internal_api_secret=secret,
    )

    assert settings.validated_internal_api_secret == secret.encode()
    assert secret not in repr(settings)


@pytest.mark.parametrize("secret", ["", "too-short", "REPLACE_WITH_A_RANDOM_VALUE_123456"])
def test_internal_api_secret_rejects_missing_or_placeholder_values(secret: str) -> None:
    settings = Settings(
        database_url="postgresql://app:synthetic@localhost/Team4_Proj",
        internal_api_secret=secret,
    )

    with pytest.raises(RuntimeError, match="(?i)signing|configured"):
        _ = settings.validated_internal_api_secret
