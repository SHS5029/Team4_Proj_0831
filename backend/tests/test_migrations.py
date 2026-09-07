from pathlib import Path

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
