from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from hashlib import sha256
from pathlib import Path
from traceback import format_exception
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

from backend.app.core import config
from backend.app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings_environment() -> Iterator[None]:
    """개인 설정을 소비하지 않고 각 테스트의 synthetic 환경만 검증한다."""

    with patch.dict(os.environ):
        for name in (*Settings.__dataclass_fields__, "team_database_url"):
            os.environ.pop(name.upper(), None)
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


def _assert_connection_details_preserved(source_url: str, effective_url: str) -> None:
    source = urlsplit(source_url)
    effective = urlsplit(effective_url)

    assert effective.scheme == source.scheme
    assert effective.hostname == source.hostname
    assert effective.port == source.port
    assert effective.query == source.query
    # 자격 증명은 직접 비교하지 않아 향후 fixture 변경 시에도 실패 출력에 남지 않는다.
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


def test_local_env_database_url_keeps_connection_and_targets_team4_proj(
    tmp_path: Path,
) -> None:
    """실제 .env 대신 임시 파일로 기본 DB 경로 교체를 확인한다."""

    source_url = "postgresql://app_user:synthetic@127.0.0.1:5432/source_db"
    local_env = tmp_path / "local.env"
    local_env.write_text(f"DATABASE_URL={source_url}\n", encoding="utf-8")
    settings = Settings.from_env(local_env)

    effective_url = settings.effective_database_url
    _assert_connection_details_preserved(source_url, effective_url)
    assert urlsplit(effective_url).path == "/Team4_Proj"


def test_team_database_url_takes_precedence_and_preserves_remote_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """원격 TEAM DSN은 로컬 URL과 DATABASE_NAME보다 우선하고 DB path를 보존한다."""

    team_url = "postgresql://remote_user:s%40nthetic@remote.db.internal:4000/team_remote"
    monkeypatch.setenv("TEAM_DATABASE_URL", team_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql://local:local@127.0.0.1:5432/local_db")
    monkeypatch.setenv("DATABASE_NAME", "Team4_Proj")

    settings = Settings.from_env(tmp_path / "absent.env")

    assert settings.preserve_database_path is True
    assert settings.database_name == "team_remote"
    effective_url = settings.effective_database_url
    _assert_connection_details_preserved(team_url, effective_url)
    assert urlsplit(effective_url).path == "/team_remote"


def test_team_database_url_without_path_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """원격 대상이 불명확한 DSN은 기본 DB로 우회하지 않고 시작 단계에서 거부한다."""

    monkeypatch.setenv("TEAM_DATABASE_URL", "postgresql://remote_user:synthetic@remote.db.internal:4000")

    with pytest.raises(ValueError, match="TEAM_DATABASE_URL"):
        Settings.from_env(tmp_path / "absent.env")


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


def test_settings_preserve_local_legacy_without_keyring() -> None:
    """양쪽 keyring 미설정은 기존 로컬 legacy 시작을 계속 허용한다."""

    settings = Settings(database_url="postgresql://app_user:synthetic@localhost/source_db")

    assert settings.game_state_keyring_file == ""
    assert settings.game_state_active_key_id == ""


@pytest.mark.parametrize(
    "keyring_settings",
    [
        {"game_state_keyring_file": "/synthetic/keyring.json"},
        {"game_state_active_key_id": "synthetic-key-id"},
    ],
)
def test_settings_reject_partial_keyring_configuration(keyring_settings: dict[str, str]) -> None:
    """암호화 설정이 반쪽이면 legacy로 조용히 우회하지 않도록 거부한다."""

    with pytest.raises(ValueError, match="must be set together"):
        Settings(
            database_url="postgresql://app_user:synthetic@localhost/source_db",
            **keyring_settings,
        )


def test_migration_url_loads_without_replacing_runtime_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """환경에 주입한 DDL DSN은 파일보다 우선하지만 runtime 접속에는 사용하지 않는다."""

    runtime_url = "postgresql://runtime:synthetic-runtime@runtime.internal/remote_db"
    ddl_url = "postgresql://ddl:synthetic-ddl@ddl.internal/remote_db?sslmode=require"
    local_env = tmp_path / "migration.env"
    local_env.write_text(
        f"TEAM_DATABASE_URL={runtime_url}\n"
        "DATABASE_MIGRATION_URL=postgresql://file:synthetic-file@file.internal/remote_db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_MIGRATION_URL", f"  {ddl_url}  ")

    settings = Settings.from_migration_env(local_env)

    assert settings.effective_database_url == runtime_url
    assert settings.database_migration_url == ddl_url
    assert settings.effective_migration_database_url == ddl_url
    representation = repr(settings)
    for secret in ("synthetic-runtime", "synthetic-ddl", "runtime.internal", "ddl.internal"):
        assert secret not in representation


def test_runtime_settings_do_not_require_migration_credentials(tmp_path: Path) -> None:
    local_env = tmp_path / "runtime.env"
    local_env.write_text(
        "DATABASE_URL=postgresql://runtime:synthetic-runtime@runtime.internal/source_db\n",
        encoding="utf-8",
    )

    settings = Settings.from_env(local_env)

    assert settings.database_migration_url == ""
    assert urlsplit(settings.effective_database_url).path == "/Team4_Proj"
    with pytest.raises(ValueError, match="DATABASE_MIGRATION_URL"):
        _ = settings.effective_migration_database_url


@pytest.mark.parametrize("loader", [Settings.from_env, get_settings])
def test_runtime_loaders_do_not_read_injected_migration_credentials(
    loader: Callable[[], Settings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """DDL 값이 잘못 주입돼도 일반 loader와 캐시는 해당 환경키를 소비하지 않는다."""

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:synthetic@runtime.internal/source_db")
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "synthetic-forbidden-ddl-setting")

    with patch.object(config.os, "getenv", wraps=os.getenv) as getenv:
        settings = loader()

    assert not any(call.args[0] == "DATABASE_MIGRATION_URL" for call in getenv.call_args_list)
    assert settings.database_migration_url == ""
    assert urlsplit(settings.effective_database_url).path == "/Team4_Proj"


def test_migration_loader_does_not_reuse_or_modify_runtime_settings_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """runner는 최신 전용 환경을 읽고 기존 Backend 캐시에 DDL 자격 증명을 남기지 않는다."""

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:synthetic@runtime.internal/source_db")
    runtime_settings = get_settings()
    runner_runtime_url = "postgresql://runtime:synthetic@runtime.internal/runner_db"
    ddl_url = "postgresql://ddl:synthetic@ddl.internal/runner_db"
    monkeypatch.setenv("TEAM_DATABASE_URL", runner_runtime_url)
    monkeypatch.setenv("DATABASE_MIGRATION_URL", ddl_url)

    migration_settings = Settings.from_migration_env()

    assert migration_settings.effective_database_url == runner_runtime_url
    assert migration_settings.effective_migration_database_url == ddl_url
    assert get_settings() is runtime_settings
    assert runtime_settings.database_migration_url == ""
    assert urlsplit(runtime_settings.effective_database_url).path == "/Team4_Proj"


def test_migration_url_can_load_from_isolated_env_file(tmp_path: Path) -> None:
    local_env = tmp_path / "migration.env"
    ddl_url = "postgresql://ddl:synthetic-ddl@ddl.internal/Team4_Proj"
    local_env.write_text(
        "DATABASE_URL=postgresql://runtime:synthetic-runtime@runtime.internal/source_db\n"
        f"DATABASE_MIGRATION_URL={ddl_url}\n",
        encoding="utf-8",
    )

    settings = Settings.from_migration_env(local_env)

    assert settings.effective_migration_database_url == ddl_url


@pytest.mark.parametrize(
    "runtime_url",
    [
        "postgresql://[synthetic-invalid-host/Team4_Proj",
        "postgresql://runtime:synthetic-password@db.internal:synthetic-port/Team4_Proj",
    ],
)
def test_runtime_url_parse_failures_hide_raw_exception(
    runtime_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """공통 설정 단계에서 거부한 DSN도 하위 파서의 원문 오류를 출력하지 않는다."""

    monkeypatch.setenv("TEAM_DATABASE_URL", runtime_url)

    with pytest.raises(ValueError, match="DATABASE_URL") as failure:
        Settings.from_env(tmp_path / "absent.env")

    trace = "".join(format_exception(failure.value))
    assert "synthetic-invalid-host" not in trace
    assert "synthetic-password" not in trace
    assert "synthetic-port" not in trace
