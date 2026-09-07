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


def test_team_database_url_takes_precedence_and_preserves_remote_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원격 TEAM DSN은 로컬 URL과 DATABASE_NAME보다 우선하고 DB path를 보존한다."""

    team_url = "postgresql://remote_user:s%40nthetic@remote.db.internal:4000/team_remote"
    monkeypatch.setenv("TEAM_DATABASE_URL", team_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql://local:local@127.0.0.1:5432/local_db")
    monkeypatch.setenv("DATABASE_NAME", "Team4_Proj")

    settings = Settings.from_env(PROJECT_ROOT / ".env")

    assert settings.preserve_database_path is True
    assert settings.database_name == "team_remote"
    effective_url = settings.effective_database_url
    _assert_connection_details_preserved(team_url, effective_url)
    assert urlsplit(effective_url).path == "/team_remote"


def test_team_database_url_without_path_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """원격 대상이 불명확한 DSN은 기본 DB로 우회하지 않고 시작 단계에서 거부한다."""

    monkeypatch.setenv("TEAM_DATABASE_URL", "postgresql://remote_user:synthetic@remote.db.internal:4000")

    with pytest.raises(ValueError, match="TEAM_DATABASE_URL"):
        Settings.from_env(PROJECT_ROOT / ".env")


def test_llm_provider_settings_are_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LLM Provider 선택과 호출 제한값을 환경 파일에서 읽어 고정한다."""

    local_env = tmp_path / "llm.env"
    local_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://app_user:synthetic@127.0.0.1:5432/local_db",
                "LLM_PROVIDER=local",
                "LOCAL_LLM_BASE_URL=http://127.0.0.1:1234/v1",
                "LOCAL_LLM_MODEL=synthetic-local-model",
                "LLM_TIMEOUT_SECONDS=12",
                "LLM_MAX_OUTPUT_TOKENS=256",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for name in (
        "TEAM_DATABASE_URL",
        "DATABASE_URL",
        "DATABASE_NAME",
        "LLM_PROVIDER",
        "LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env(local_env)

    assert settings.llm_provider == "local"
    assert settings.local_llm_model == "synthetic-local-model"
    assert settings.llm_timeout_seconds == 12
    assert settings.llm_max_output_tokens == 256


@pytest.mark.parametrize("name", ["LLM_TIMEOUT_SECONDS", "LLM_MAX_OUTPUT_TOKENS"])
def test_llm_limits_reject_non_positive_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    """Provider 호출 제한값이 0 이하이면 시작 단계에서 거부한다."""

    local_env = tmp_path / "invalid-llm.env"
    local_env.write_text(
        "DATABASE_URL=postgresql://app_user:synthetic@127.0.0.1:5432/local_db\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEAM_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValueError, match=name):
        Settings.from_env(local_env)


def test_settings_can_load_the_configured_database_name_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """로컬 fallback 환경이 지정한 DB 이름을 기본값으로 바꾸지 않는지 확인한다."""

    source_url = "postgresql://app_user:synthetic@127.0.0.1:5432/source_db"
    configured_database_name = "Team4_Proj"
    local_env = tmp_path / "local.env"
    local_env.write_text(
        f"DATABASE_URL={source_url}\nDATABASE_NAME={configured_database_name}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_NAME", raising=False)
    monkeypatch.delenv("TEAM_DATABASE_URL", raising=False)

    settings = Settings.from_env(local_env)

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
