"""PostgreSQL 게임 command가 공유하는 원장 복원·멱등성 helper."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase, GameStatus, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, PlayerState


def find_replay(
    service: Any,
    cursor: Any,
    *,
    owner_user_id: UUID,
    idempotency_key: UUID,
    request_hash: str,
    route_scope: str,
) -> dict[str, Any] | None:
    """사용자·멱등 key·route가 모두 같은 이전 결과만 재사용한다."""

    previous = service._receipts.find(
        cursor,
        principal_type="USER",
        principal_id=owner_user_id,
        idempotency_key=idempotency_key,
    )
    if previous is None:
        return None
    if previous["request_hash"] != request_hash or previous["route_scope"] != route_scope:
        raise ApiError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
        )
    result_body = previous["result_body"]
    if not isinstance(result_body, dict):
        raise RuntimeError("Stored command receipt is invalid")
    return copy.deepcopy(result_body)


def restore_locked_game(
    service: Any,
    cursor: Any,
    game_row: Mapping[str, Any],
) -> tuple[GameState, UUID]:
    """FOR UPDATE game row와 player row를 순수 엔진 상태로 복원한다."""

    game_id = UUID(str(game_row["id"]))
    seed = service._keyring.decrypt_seed(
        ciphertext=bytes(game_row["seed_ciphertext"]),
        nonce=bytes(game_row["seed_nonce"]),
        key_id=str(game_row["seed_key_id"]),
    )
    players: list[PlayerState] = []
    human_player_id: UUID | None = None
    for row in service._players.list_players(cursor, game_id=game_id):
        player_id = UUID(str(row["id"]))
        kind = PlayerKind(str(row["kind"]))
        players.append(PlayerState(player_id=player_id, seat=int(row["seat"]), role=PlayerRole(str(row["role"])), kind=kind, display_name=str(row["display_name"]), alive=bool(row["alive"])))
        if kind is PlayerKind.HUMAN:
            if human_player_id is not None or row["user_id"] is None:
                raise RuntimeError("Persisted human player is invalid")
            human_player_id = player_id
    if human_player_id is None or len(players) != int(game_row["player_count"]):
        raise RuntimeError("Persisted players are incomplete")
    if not isinstance(game_row["updated_at"], datetime):
        raise RuntimeError("Persisted game timestamp is invalid")
    return GameState(game_id=game_id, seed=seed, players=players, phase=GamePhase(str(game_row["phase"])), status=GameStatus(str(game_row["status"])), round=int(game_row["round"]), day_number=int(game_row["day_number"]), state_version=int(game_row["state_version"]), updated_at=game_row["updated_at"]), human_player_id
