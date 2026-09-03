import re
from pathlib import Path

from backend.app.infrastructure.migrations import MIGRATIONS_DIR

EXPECTED_MIGRATIONS = [
    "001_create_oauth_schema.sql",
    "002_create_scaffold_game_schema.sql",
    "003_create_mystery_v1_schema.sql",
    "004_seed_mystery_v1_catalog.sql",
]

SCENARIO_IDS = (
    "BLACKOUT_STUDIO",
    "SNOWBOUND_LODGE",
    "CLOSING_MUSEUM",
    "LAST_BANQUET_GUEST",
    "STOPPED_NIGHT_TRAIN",
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


def test_mystery_v1_seed_contains_minimum_approved_catalog() -> None:
    migration = (MIGRATIONS_DIR / "004_seed_mystery_v1_catalog.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(migration.lower().split())

    assert normalized.startswith("-- ai 마피아 mystery-v1 최소 정적 콘텐츠를 등록한다.")
    assert "begin;" in normalized
    assert normalized.endswith("commit;")
    assert normalized.count("on conflict (id) do update") == 2
    assert "on conflict (scenario_id, template_kind, template_key) do update" in normalized
    assert "digest(" in normalized
    assert "approved_at" in normalized
    assert "drop table" not in normalized
    assert "truncate table" not in normalized

    template_rows = re.findall(
        r"\('([A-Z_]+)', '(ALIBI|OBSERVATION)', '([A-Z]+_\d{2})', "
        r"'([^']+)', '(NONE|SEAT|ANONYMOUS)'\)",
        migration,
    )
    assert len(template_rows) == 90

    for scenario_id in SCENARIO_IDS:
        for template_kind in ("ALIBI", "OBSERVATION"):
            matching = [
                row
                for row in template_rows
                if row[0] == scenario_id and row[1] == template_kind
            ]
            assert len(matching) == 9
            assert len({row[2] for row in matching}) == 9

    for _, _, _, text, _ in template_rows:
        assert 1 <= len(text) <= 240
        assert text.endswith(".")


def test_mystery_v1_seed_persona_has_closed_parameter_shape() -> None:
    migration = (MIGRATIONS_DIR / "004_seed_mystery_v1_catalog.sql").read_text(
        encoding="utf-8"
    )
    parameter_keys = (
        "sociability",
        "assertiveness",
        "suspicion",
        "deception",
        "risk_tolerance",
        "memory_recall",
        "reasoning_skill",
        "emotionality",
        "cooperativeness",
        "verbosity",
    )

    assert "BALANCED_OBSERVER" in migration
    for key in parameter_keys:
        assert migration.count(f"'{key}'") == 1

    values = re.findall(r"'(?:" + "|".join(parameter_keys) + r")', ([0-9.]+)", migration)
    assert len(values) == len(parameter_keys)
    for value in values:
        assert 0.0 <= float(value) <= 1.0

    # 모든 preset의 추론 능력은 같은 승인값이어야 하므로 최소 seed도 중간값을 사용한다.
    assert "'reasoning_skill', 0.5" in migration
