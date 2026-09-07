"""Router·worker가 runtime compatibility 경계를 지키는지 검증한다."""

import ast
from pathlib import Path


APP_ROOT = Path(__file__).parents[1] / "app"


def _imports(path: Path) -> set[str]:
    """파일의 절대 import 경로를 정적으로 수집한다."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def test_game_router_does_not_import_repositories_or_engine() -> None:
    """HTTP router는 validation과 runtime facade 호출만 담당해야 한다."""

    imports = _imports(APP_ROOT / "routers" / "game_router.py")
    assert not any(
        name.startswith("backend.app.repositories")
        or name.startswith("backend.app.game_engine")
        for name in imports
    )


def test_ai_worker_does_not_own_repository_or_engine() -> None:
    """AI worker는 주입받은 runtime의 application method만 호출해야 한다."""

    imports = _imports(APP_ROOT / "services" / "game" / "ai_progress_worker.py")
    assert not any(
        name.startswith("backend.app.repositories")
        or name.startswith("backend.app.game_engine")
        or name.startswith("backend.app.infrastructure")
        for name in imports
    )


def test_router_and_worker_do_not_construct_database_runtime() -> None:
    """runtime 생성과 transaction 소유권이 composition root 밖으로 새지 않는지 확인한다."""

    for relative in ("routers/game_router.py", "services/game/ai_progress_worker.py"):
        source = (APP_ROOT / relative).read_text(encoding="utf-8")
        assert "TransactionManager(" not in source
        assert "Postgres" not in source
