"""연결 뼈대 게임의 소유권·version·idempotency 유스케이스다."""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from backend.app.core.errors import ApiError
from backend.app.models.scaffold_game import ScaffoldGame, ScaffoldOperation
from backend.app.repositories.scaffold_repository import ScaffoldRepository
from backend.app.schemas.scaffold_schema import (
    CreateScaffoldGameRequest,
    CreateScaffoldGameResponse,
    ScaffoldCommandAcceptedResponse,
    ScaffoldCommandRequest,
    ScaffoldGameStateResponse,
    ScaffoldOperationResponse,
    ScaffoldPlayerResponse,
)


class ScaffoldGameService:
    """후속 규칙 엔진을 끼울 수 있는 최소 game service다."""

    def __init__(self, repository: ScaffoldRepository, redis=None, llm=None, mcp_client=None) -> None:
        self.repository = repository
        self.redis = redis
        self.llm = llm
        self.mcp_client = mcp_client

    def create(self, owner_user_id: UUID, payload: CreateScaffoldGameRequest) -> CreateScaffoldGameResponse:
        """소유자와 인간 참가자 한 명을 가진 dummy game을 생성한다."""

        game = ScaffoldGame(uuid4(), owner_user_id, payload.player_count)
        game.players = [uuid4() for _ in range(payload.player_count)]
        # MOCK ONLY: canonical player preset이 연결되면 이 표시명 목록을 제거한다.
        game.display_names = ["민수", "철수", "영희", "태경", "지효", "성주", "환석", "유빈", "태웅", "지혜", "지토"][:payload.player_count]
        self.repository.create_game(game)
        player = ScaffoldPlayerResponse(player_id=game.players[0], display_name=game.display_names[0], kind="HUMAN")
        return CreateScaffoldGameResponse(
            game_id=game.game_id,
            status="IN_PROGRESS",
            phase="ROLE_REVEAL",
            state_version=game.state_version,
            player=player,
            players=[],
        )

    def state(self, owner_user_id: UUID, game_id: UUID) -> ScaffoldGameStateResponse:
        """소유자에게만 상태 projection을 반환한다."""

        game = self._owned_game(owner_user_id, game_id)
        allowed = ["PING", "BEGIN_GAME", "PAUSE"] if game.phase == "ROLE_REVEAL" else ["RESUME"]
        players = [
            ScaffoldPlayerResponse(
                player_id=player_id,
                display_name=game.display_names[index] if index < len(game.display_names) else f"플레이어 {index + 1}",
                kind="HUMAN" if index == 0 else "AI",
            )
            for index, player_id in enumerate(game.players)
        ]
        return ScaffoldGameStateResponse(
            game_id=game.game_id,
            status=game.status,
            phase=game.phase,
            state_version=game.state_version,
            players=players,
            public_events=[],
            private_events=[],
            allowed_commands=allowed,
            active_operation=None,
            updated_at=game.updated_at,
        )

    def list_games(self, owner_user_id: UUID, *, status: str | None = None,
                   limit: int = 20) -> dict:
        """현재 UUID가 소유한 mock 게임 목록을 API 응답 envelope로 만든다."""

        items = []
        for game in self.repository.list_games(owner_user_id, status=status, limit=limit):
            items.append(
                {
                    "game_id": str(game.game_id),
                    "status": game.status,
                    "phase": game.phase,
                    "round": 0,
                    "day_number": 1,
                    "state_version": game.state_version,
                    "scenario_title": "정전된 방송국",
                    "scenario_id": "BLACKOUT_STUDIO",
                    "player_count": game.player_count,
                    "human_alive": True,
                    "winner": None,
                    "can_resume": game.status == "PAUSED",
                    "updated_at": game.updated_at.isoformat(),
                }
            )
        return {"data": {"items": items, "next_cursor": None}}

    def command(self, owner_user_id: UUID, game_id: UUID, payload: ScaffoldCommandRequest) -> ScaffoldCommandAcceptedResponse:
        """version을 확인하고 뼈대 command를 즉시 완료한다."""

        game = self._owned_game(owner_user_id, game_id)
        if game.state_version != payload.expected_version:
            raise ApiError(status_code=409, code="GAME_STATE_CONFLICT", message="게임 상태가 변경되었습니다.", details={"current_version": game.state_version})
        if payload.command == "RESUME" and game.phase != "PAUSED":
            raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 상태에서 허용되지 않는 명령입니다.")
        if payload.command in {"PING", "BEGIN_GAME"} and game.phase != "ROLE_REVEAL":
            raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 상태에서 허용되지 않는 명령입니다.")
        if payload.command == "PAUSE" and game.phase != "ROLE_REVEAL":
            raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 상태에서 허용되지 않는 명령입니다.")
        fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        key = (game_id, payload.idempotency_key)
        previous = self.repository.idempotency.get(key)
        if previous:
            if previous[0] != fingerprint:
                raise ApiError(status_code=409, code="IDEMPOTENCY_CONFLICT", message="idempotency key가 다른 요청에 사용되었습니다.")
            return previous[1]  # type: ignore[return-value]
        lock_token = None
        if self.redis is not None:
            try:
                lock_token = self.redis.acquire_lock(str(game_id))
            except Exception:
                lock_token = None
            if lock_token is None and self.redis is not None:
                raise ApiError(status_code=503, code="GAME_LOCK_UNAVAILABLE", message="게임 잠금을 사용할 수 없습니다.")
        if payload.command != "PING":
            game.state_version += 1
            game.phase = "PAUSED" if payload.command == "PAUSE" else "ROLE_REVEAL"
            game.status = "PAUSED" if payload.command == "PAUSE" else "IN_PROGRESS"
            game.updated_at = datetime.now(timezone.utc)
        operation = ScaffoldOperation(uuid4(), game_id, payload.command, payload.expected_version, game.state_version)
        event_payload = {"game_id": str(game_id), "state_version": game.state_version, "command": payload.command}
        if hasattr(self.repository, "save_command"):
            self.repository.save_command(game, operation, event_payload)
        else:
            self.repository.save_operation(operation)
        response = ScaffoldCommandAcceptedResponse(operation_id=operation.operation_id, state_version=game.state_version, phase=game.phase, status="COMPLETED")
        self.repository.idempotency[key] = (fingerprint, response)
        if self.redis is not None:
            try:
                self.redis.set_operation(str(operation.operation_id), response.model_dump(mode="json"))
                self.redis.publish_event(str(game_id), {"sequence": len(self.repository.events_after(game_id, 0)), **event_payload})
            except Exception:
                pass
            finally:
                try:
                    self.redis.release_lock(str(game_id), lock_token)
                except Exception:
                    pass
        return response

    def operation(self, owner_user_id: UUID, game_id: UUID, operation_id: UUID) -> ScaffoldOperationResponse:
        """소유한 game의 operation만 조회한다."""

        self._owned_game(owner_user_id, game_id)
        operation = self.repository.get_operation(operation_id)
        if operation is None or operation.game_id != game_id:
            raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="리소스를 찾을 수 없습니다.")
        return ScaffoldOperationResponse.model_validate(operation, from_attributes=True)

    def _owned_game(self, owner_user_id: UUID, game_id: UUID) -> ScaffoldGame:
        """존재하지 않는 game과 타 사용자 game을 같은 404로 처리한다."""

        game = self.repository.get_game(game_id)
        if game is None or game.owner_user_id != owner_user_id:
            raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="리소스를 찾을 수 없습니다.")
        return game
