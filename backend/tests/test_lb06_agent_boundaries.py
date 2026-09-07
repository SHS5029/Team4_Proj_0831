"""Agent package와 GameEngine·저장 계층의 import 경계를 검증한다."""

import ast
from pathlib import Path


AGENT_ROOT = Path(__file__).parents[1] / "app" / "agent"


def _runtime_imports(path: Path) -> set[str]:
    """TYPE_CHECKING 블록을 제외한 런타임 import만 수집한다."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    def visit(nodes: list[ast.stmt], *, type_checking: bool = False) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                visit(node.body, type_checking=True)
                continue
            if type_checking:
                continue
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module)
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    visit([child], type_checking=type_checking)

    visit(tree.body)
    return imports


def test_agent_modules_do_not_runtime_import_database_or_engine() -> None:
    """Agent는 외부 adapter와 입력 모델만 런타임 의존성으로 가져야 한다."""

    imports = set().union(*(_runtime_imports(path) for path in AGENT_ROOT.glob("*.py")))
    forbidden = {
        name
        for name in imports
        if name.startswith("backend.app.repositories")
        or name.startswith("backend.app.infrastructure")
        or name.startswith("backend.app.game_engine")
    }
    assert forbidden == set()


def test_agent_package_has_single_orchestration_and_projection_entrypoints() -> None:
    """Agent 실행 조합과 context projection의 정본 파일이 유지되는지 확인한다."""

    assert (AGENT_ROOT / "orchestrator.py").exists()
    assert (AGENT_ROOT / "policies.py").exists()
    assert (AGENT_ROOT / "projections.py").exists()
    assert (Path(__file__).parents[1] / "app" / "game_engine" / "rng.py").exists()
