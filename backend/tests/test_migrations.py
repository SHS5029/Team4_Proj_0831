from pathlib import Path

from backend.app.infrastructure.migrations import MIGRATIONS_DIR

EXPECTED_MIGRATIONS = [
    "001_create_oauth_schema.sql",
    "002_create_scaffold_game_schema.sql",
    "003_create_mystery_v1_schema.sql",
]

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
