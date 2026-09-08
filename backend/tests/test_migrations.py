from pathlib import Path
from traceback import format_exception
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from backend.app.core import config
from backend.app.core.config import Settings
from backend.app.infrastructure import migrations
from backend.app.infrastructure.migrations import MIGRATIONS_DIR

EXPECTED_MIGRATIONS = [
    "001_create_oauth_schema.sql",
    "002_create_scaffold_game_schema.sql",
    "003_create_mystery_v1_schema.sql",
    "004_seed_scenarios_and_personas.sql",
    "005_create_admin_knowledge_schema.sql",
]

EXPECTED_SCENARIOS = (
    "BLACKOUT_STUDIO",
    "SNOWBOUND_LODGE",
    "CLOSING_MUSEUM",
    "LAST_BANQUET_GUEST",
    "STOPPED_NIGHT_TRAIN",
)

EXPECTED_PERSONAS = (
    "CAUTIOUS_ANALYST",
    "ACTIVE_DEBATER",
    "OBSERVANT_NOTEKEEPER",
    "EMOTIONAL_REACTOR",
    "COOPERATIVE_MEDIATOR",
)

CANONICAL_TABLES = (
    "scenario_catalog",
    "scenario_templates",
    "agent_personas",
    "games",
    "game_players",
    "player_scenario_facts",
    "action_windows",
    "action_submissions",
    "action_window_resolutions",
    "game_events",
    "command_receipts",
    "game_snapshots",
    "agent_jobs",
    "agent_capabilities",
    "internal_request_nonces",
    "event_outbox",
    "feedback",
    "admin_audit_events",
)

KNOWLEDGE_TABLES = (
    "admin_knowledge_documents",
    "admin_knowledge_chunks",
)


@pytest.fixture(autouse=True)
def migration_connect(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """성공·거부·오류 경로 모두 실제 PostgreSQL 접속 없이 검증한다."""

    connect = MagicMock()
    monkeypatch.setattr(migrations.psycopg, "connect", connect)
    return connect


@pytest.fixture
def migration_files(tmp_path: Path) -> Path:
    """파일 생성 순서와 무관한 이름순 실행을 synthetic SQL로 확인한다."""

    (tmp_path / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    return tmp_path


def _migration_settings(**overrides: str | bool) -> Settings:
    """runtime과 DDL의 자격 증명·호스트를 분리한 테스트 전용 설정을 만든다."""

    return Settings(**{
        "database_url": "postgresql://runtime:synthetic-runtime@runtime.internal/source_db",
        "database_name": "Team4_Proj",
        "database_migration_url": (
            "postgresql://migrator:synthetic-ddl@ddl.internal:5433/Team4_Proj"
            "?sslmode=require&application_name=migration-test"
        ),
        **overrides,
    })


def test_runner_connects_only_to_explicit_ddl_dsn_in_filename_order(
    migration_connect: MagicMock, migration_files: Path,
) -> None:
    """SQL은 runtime DSN이 아닌 지정 DDL DSN으로 파일당 한 번 실행한다."""

    settings = _migration_settings()

    applied = migrations.run_migrations(settings, migration_files)

    migration_connect.assert_called_once_with(settings.database_migration_url, autocommit=True)
    execute = migration_connect.return_value.__enter__.return_value.cursor.return_value
    assert [call.args[0] for call in execute.__enter__.return_value.execute.call_args_list] == [
        "SELECT 1;", "SELECT 2;",
    ]
    assert applied == ["001_first.sql", "002_second.sql"]


@pytest.mark.parametrize(
    "ddl_url",
    [
        "", "   ",
        "mysql://migrator:synthetic-ddl@ddl.internal/Team4_Proj",
        "postgresql:///Team4_Proj",
        "postgresql://migrator:synthetic-ddl@ddl.internal",
        "postgresql://migrator:synthetic-ddl@ddl.internal/",
        "postgresql://migrator:synthetic-ddl@ddl.internal/other_db",
        "postgresql://migrator:synthetic-ddl@ddl.internal/team4_proj",
        "postgresql://migrator:synthetic-ddl@ddl.internal:synthetic-port/Team4_Proj",
        "postgresql://migrator:synthetic-ddl@ddl.internal:99999/Team4_Proj",
        "postgresql://[synthetic-invalid-host/Team4_Proj",
        "postgresql://ddl.internal/Team4_Proj%00",
        "postgresql://ddl.internal/Team4_Proj%ZZ",
        "postgresql://ddl.internal/Team4_Proj%FF",
        "postgresql://ddl.internal/Team4_Proj/other_db",
        "postgresql://ddl.internal/Team4_Proj#ignored-path",
    ],
)
def test_runner_rejects_missing_invalid_or_mismatched_ddl_without_connecting(
    ddl_url: str, migration_connect: MagicMock, migration_files: Path,
) -> None:
    """잘못된 migration 환경은 runtime DSN으로 대체하거나 경로를 보정하지 않는다."""

    settings = _migration_settings(database_migration_url=ddl_url)

    with pytest.raises(ValueError, match="DATABASE_MIGRATION_URL") as failure:
        migrations.run_migrations(settings, migration_files)

    migration_connect.assert_not_called()
    trace = "".join(format_exception(failure.value))
    assert "synthetic-ddl" not in trace
    assert "synthetic-port" not in trace
    assert "synthetic-invalid-host" not in trace


@pytest.mark.parametrize("dsn_field", ["database_url", "database_migration_url"])
@pytest.mark.parametrize(
    "query", [
        "dbname=other_db", "dbname=", "db%6Eame=other_db", "host=other.internal",
        "hostaddr=127.0.0.2",
        "port=5434", "user=other_user", "password=synthetic-query-password",
        "service=other_service", "servicefile=/synthetic/service", "passfile=/synthetic/pass",
    ],
)
def test_runner_rejects_query_overrides_in_either_dsn(
    dsn_field: str, query: str, migration_connect: MagicMock, migration_files: Path,
) -> None:
    """검증한 URL path나 계정 대신 query의 접속값이 선택되는 우회를 막는다."""

    settings = _migration_settings(**{
        dsn_field: f"postgresql://synthetic:synthetic@db.internal/Team4_Proj?{query}",
    })

    with pytest.raises(ValueError, match="query"):
        migrations.run_migrations(settings, migration_files)

    migration_connect.assert_not_called()


def test_runner_compares_decoded_paths_and_preserves_original_ddl_url(
    migration_connect: MagicMock, migration_files: Path,
) -> None:
    """원격 경로와 동등한 percent-encoding은 허용하되 DDL URL 원형은 보존한다."""

    ddl_url = "postgresql://ddl:p%40synthetic@ddl.internal/remote%20%EB%94%94%EB%B9%84?sslmode=require"
    settings = _migration_settings(
        database_url="postgresql://runtime:synthetic@runtime.internal/remote%20디비",
        preserve_database_path=True,
        database_migration_url=f"  {ddl_url}  ",
    )

    migrations.run_migrations(settings, migration_files)

    migration_connect.assert_called_once_with(ddl_url, autocommit=True)


def test_runner_stops_on_sql_failure_without_raw_exception(
    migration_connect: MagicMock, migration_files: Path,
) -> None:
    """실패 뒤 SQL은 실행하지 않으며 driver가 포함한 DSN·SQL 원문은 숨긴다."""

    cursor = migration_connect.return_value.__enter__.return_value.cursor.return_value
    execute = cursor.__enter__.return_value.execute
    execute.side_effect = psycopg.ProgrammingError("synthetic-secret SQL payload")

    with pytest.raises(RuntimeError, match="Migration execution failed") as failure:
        migrations.run_migrations(_migration_settings(), migration_files)

    execute.assert_called_once_with("SELECT 1;")
    assert "synthetic-secret" not in "".join(format_exception(failure.value))


def test_runner_hides_connection_error_details(
    migration_connect: MagicMock, migration_files: Path,
) -> None:
    migration_connect.side_effect = psycopg.OperationalError("synthetic-secret DSN failure")

    with pytest.raises(RuntimeError, match="Migration execution failed") as failure:
        migrations.run_migrations(_migration_settings(), migration_files)

    assert "synthetic-secret" not in "".join(format_exception(failure.value))


def test_runner_rejects_empty_migration_directory_before_connecting(
    migration_connect: MagicMock, tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="No SQL migrations found"):
        migrations.run_migrations(_migration_settings(), tmp_path)

    migration_connect.assert_not_called()


def test_cli_hides_settings_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI 설정 오류도 원문 traceback 대신 고정 오류와 실패 종료 코드만 남긴다."""

    monkeypatch.setattr(Settings, "from_migration_env", MagicMock(
        side_effect=ValueError("synthetic-secret setting failure"),
    ))

    with pytest.raises(SystemExit) as failure:
        migrations.main()

    assert failure.value.code != 0
    assert "synthetic-secret" not in "".join(format_exception(failure.value))
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.out + captured.err


def test_cli_success_does_not_print_connection_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _migration_settings()
    monkeypatch.setattr(Settings, "from_migration_env", lambda: settings)
    monkeypatch.setattr(migrations, "run_migrations", lambda _: ["001_first.sql"])

    migrations.main()

    captured = capsys.readouterr()
    assert "Applied 1 migration(s)" in captured.out
    assert "001_first.sql" in captured.out
    assert "synthetic" not in captured.out + captured.err
    assert "internal" not in captured.out + captured.err


def test_cli_loads_explicit_migration_environment_before_connecting(
    monkeypatch: pytest.MonkeyPatch, migration_connect: MagicMock, migration_files: Path,
) -> None:
    """CLI부터 실제 설정·runner까지 연결해 DDL 전용 loader 누락을 재발 방지한다."""

    ddl_url = "postgresql://ddl:synthetic-ddl@ddl.internal/Team4_Proj?sslmode=require"
    monkeypatch.setattr(config, "PROJECT_ROOT", migration_files)
    run_migrations = migrations.run_migrations
    monkeypatch.setattr(
        migrations, "run_migrations", lambda settings: run_migrations(settings, migration_files),
    )
    with patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://runtime:synthetic@runtime.internal/source_db",
        "DATABASE_MIGRATION_URL": ddl_url,
    }, clear=True):
        migrations.main()

    migration_connect.assert_called_once_with(ddl_url, autocommit=True)


def test_default_migration_path_is_owned_by_backend() -> None:
    backend_root = Path(__file__).resolve().parents[1]

    assert MIGRATIONS_DIR == backend_root / "migrations"
    assert sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql")) == EXPECTED_MIGRATIONS


def test_mystery_v1_migration_contains_the_canonical_schema() -> None:
    migration = (MIGRATIONS_DIR / "003_create_mystery_v1_schema.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(migration.lower().split())

    assert normalized.startswith("-- ai 마피아 mystery-v1")
    assert "begin;" in normalized
    assert normalized.endswith("commit;")
    assert "alter table public.users" in normalized
    for table in CANONICAL_TABLES:
        assert f"create table if not exists public.{table}" in normalized

    # 순방향 전환 단계에서는 legacy와 실제 데이터를 삭제하는 DDL을 허용하지 않는다.
    assert "drop table" not in normalized
    assert "truncate table" not in normalized


def test_seed_migration_contains_fixed_scenarios_and_personas() -> None:
    """B2 seed가 임의 ID나 추리 실력 차등을 만들지 않는지 확인한다."""

    migration = (MIGRATIONS_DIR / "004_seed_scenarios_and_personas.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(migration.lower().split())

    assert normalized.startswith("-- scenario-v1")
    assert "begin;" in normalized
    assert normalized.endswith("commit;")
    assert "insert into public.scenario_catalog" in normalized
    assert "insert into public.scenario_templates" in normalized
    assert "insert into public.agent_personas" in normalized
    assert "on conflict (version, id) do update" in normalized
    assert "on conflict (scenario_id, template_kind, template_key) do update" in normalized
    assert "on conflict (id) do update" in normalized
    assert "digest(" in normalized

    for scenario_id in EXPECTED_SCENARIOS:
        assert scenario_id.lower() in normalized
    for persona_id in EXPECTED_PERSONAS:
        assert persona_id.lower() in normalized

    # 5개 시나리오에 각각 9개씩 두 종류가 들어가는지 SQL의 배열 구조를
    # 함께 확인한다. 실제 행 개수와 범위 검사는 migration의 DO 검증 블록이 담당한다.
    assert normalized.count("'alibi_' || lpad") == 1
    assert normalized.count("'observation_' || lpad") == 1
    assert normalized.count('"reasoning_skill":0.5') == 5
    assert "all mystery-v1 persona reasoning_skill values must be 0.5" in normalized
    assert "select count(*) filter" in normalized
    assert "select 5 - count(*) into invalid_scenario_count" not in normalized


def test_admin_knowledge_migration_contains_approved_vector_schema() -> None:
    """운영 에이전트 migration이 pgvector와 승인 자료 경계를 정의하는지 확인한다."""

    migration = (MIGRATIONS_DIR / "005_create_admin_knowledge_schema.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(migration.lower().split())
    assert "create extension if not exists vector" in normalized
    assert "using hnsw (embedding vector_cosine_ops)" in normalized
    for table in KNOWLEDGE_TABLES:
        assert f"create table if not exists public.{table}" in normalized
