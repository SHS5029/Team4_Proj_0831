"""연결 뼈대의 교체 가능한 in-memory 저장소다."""

from uuid import UUID

from backend.app.models.scaffold_game import ScaffoldGame, ScaffoldOperation


class ScaffoldRepository:
    """실제 PostgreSQL adapter로 교체하기 전 사용하는 저장소다."""

    def __init__(self) -> None:
        self.games: dict[UUID, ScaffoldGame] = {}
        self.operations: dict[UUID, ScaffoldOperation] = {}
        self.idempotency: dict[tuple[UUID, UUID], tuple[str, object]] = {}

    def create_game(self, game: ScaffoldGame) -> None:
        """생성된 game을 메모리에 기록한다."""

        self.games[game.game_id] = game

    def get_game(self, game_id: UUID) -> ScaffoldGame | None:
        """game 식별자로 상태를 조회한다."""

        return self.games.get(game_id)

    def save_operation(self, operation: ScaffoldOperation) -> None:
        """operation 결과를 기록한다."""

        self.operations[operation.operation_id] = operation

    def get_operation(self, operation_id: UUID) -> ScaffoldOperation | None:
        """operation 식별자로 결과를 조회한다."""

        return self.operations.get(operation_id)

