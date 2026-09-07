"""GameEngine과 phase 모듈의 외부 연결 경계를 검증한다."""

import ast
from pathlib import Path


ENGINE_ROOT = Path(__file__).parents[1] / "app" / "game_engine"
FORBIDDEN_IMPORT_PARTS = (
    "infrastructure",
    "repositories",
    "redis",
    "llm_provider",
    "mcp",
    "httpx",
    "fastapi",
)


def _imports(path: Path) -> set[str]:
    """엔진 파일의 정적 import 경로를 수집한다.

    실행 중 import 결과가 아니라 소스의 경계를 검사하므로, 테스트 자체가 DB나
    외부 서비스 연결을 만들지 않는다. 상대 import는 현재 package 내부 모듈로
    간주하고 외부 연결 금지 판정에서 제외한다.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def test_game_engine_has_no_external_connection_imports() -> None:
    """순수 엔진과 phase가 DB·Redis·HTTP·LLM·MCP를 직접 참조하지 않는지 확인한다."""

    imported = set().union(*(_imports(path) for path in ENGINE_ROOT.rglob("*.py")))
    violations = sorted(
        name
        for name in imported
        if any(part == name or name.startswith(f"{part}.") for part in FORBIDDEN_IMPORT_PARTS)
        or name.startswith("backend.app.infrastructure")
        or name.startswith("backend.app.repositories")
        or name.startswith("backend.app.llm_provider")
        or name.startswith("backend.app.mcp")
    )
    assert violations == []


def test_existing_phases_are_the_action_execution_boundary() -> None:
    """기존 phase가 행동 실행을 담당하므로 조건부 actions 디렉터리를 만들지 않는다."""

    expected = {"role_reveal.py", "discussion.py", "night.py", "vote.py", "final_accusation.py"}
    phase_files = {path.name for path in (ENGINE_ROOT / "phases").glob("*.py")}

    assert expected <= phase_files
    assert not (ENGINE_ROOT / "actions").exists()
