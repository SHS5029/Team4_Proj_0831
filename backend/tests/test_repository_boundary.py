"""Repository가 SQL과 row 조회를 소유하는지 확인하는 경계 테스트."""

import ast
from pathlib import Path

from backend.app.repositories.player_repository import PostgresPlayerRepository


class _Cursor:
    """repository query와 입력 인자를 기록하는 최소 cursor 대역."""

    def __init__(self, row: dict[str, str] | None) -> None:
        self.row = row
        self.executed: tuple[str, tuple[object, ...]] | None = None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executed = (query, params)

    def fetchone(self) -> dict[str, str] | None:
        return self.row


def test_player_repository_reads_player_kind() -> None:
    """플레이어 종류 조회가 repository 내부 query와 row 변환으로 끝나는지 확인한다."""

    game_id = object()
    player_id = object()
    cursor = _Cursor({"kind": "AI"})

    assert PostgresPlayerRepository().get_kind(cursor, game_id=game_id, player_id=player_id) == "AI"  # type: ignore[arg-type]
    assert cursor.executed is not None
    query, params = cursor.executed
    assert "FROM public.game_players" in query
    assert params == (game_id, player_id)


def test_game_service_has_no_direct_sql_execution() -> None:
    """서비스 계층이 cursor.execute나 SQL 문장을 직접 소유하지 않는지 확인한다."""

    root = Path(__file__).parents[1] / "app" / "services" / "game"
    violations: list[str] = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "execute":
                violations.append(f"{path.name}:{node.lineno}")

    assert violations == []
