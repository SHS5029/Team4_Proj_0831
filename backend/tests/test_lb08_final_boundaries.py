"""Redis·event·snapshot·legacy compatibility 경계를 최종 검증한다."""

import ast
from pathlib import Path


APP_ROOT = Path(__file__).parents[1] / "app"


def _imports(path: Path) -> set[str]:
    """파일의 절대 import 경로를 정적으로 수집한다."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_game_services_do_not_directly_import_redis() -> None:
    """게임 command·read service가 Redis 구현을 직접 알지 않는지 확인한다."""

    imports: set[str] = set()
    for path in (APP_ROOT / "services" / "game").glob("*.py"):
        imports.update(_imports(path))
    assert not any(name == "redis" or name.startswith("redis.") for name in imports)


def test_legacy_snapshot_and_sync_modules_are_reexports_only() -> None:
    """호환 모듈이 별도 조회·변환 로직을 다시 소유하지 않는지 확인한다."""

    for name in ("snapshot_service.py", "sync_service.py"):
        source = (APP_ROOT / "services" / "game" / name).read_text(encoding="utf-8")
        assert "from backend.app.services.game.game_read_service" in source or "from backend.app.services.game.event_sync_service" in source
        assert "cursor.execute" not in source


def test_outbox_boundary_keeps_postgres_source_and_redis_fanout_separate() -> None:
    """outbox publisher가 repository와 Redis stream adapter를 조합하는지 확인한다."""

    source = (APP_ROOT / "services" / "outbox_service.py").read_text(encoding="utf-8")
    assert "PostgresOutboxRepository" in source
    assert "RedisEventStream" in source
    assert "INSERT INTO" not in source
    assert "SELECT " not in source
    assert "UPDATE " not in source
    assert "DELETE FROM" not in source


def test_outbox_schema_remains_referenced_by_repository_and_migration() -> None:
    """최종 정리에서 event_outbox schema와 migration을 삭제하지 않았는지 확인한다."""

    repository = (APP_ROOT / "repositories" / "outbox_repository.py").read_text(encoding="utf-8")
    migrations = Path(__file__).parents[1] / "migrations"
    migration_text = "\n".join(path.read_text(encoding="utf-8") for path in migrations.glob("*.sql"))
    assert "event_outbox" in repository
    assert "event_outbox" in migration_text
