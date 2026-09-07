"""인간·AI discussion command의 공통 PostgreSQL transaction."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.infrastructure.transaction import lock_idempotency
from backend.app.repositories.action_repository import ActionSubmissionInsert
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.actor_context import ActorContext, validate_discussion_actor
from backend.app.services.game.helpers import request_hash
from backend.app.services.game.postgres_helpers import restore_locked_game
from backend.app.services.game.service_errors import rule_error
from backend.app.services.game.window_service import next_window


def submit_discussion_transaction(service: Any, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest, idempotency_key: UUID, *, actor: ActorContext | None = None, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """actor 종류만 달리하고 모든 discussion 저장 절차는 공유한다."""

    if payload.type not in {"SPEAK", "PASS"}:
        raise ValueError("discussion command only accepts SPEAK or PASS")
    if actor is not None and actor.owner_user_id != owner_user_id:
        raise ValueError("actor owner does not match command owner")
    route_scope = f"POST /api/v1/games/{game_id}/agent-commands" if actor else f"POST /api/v1/games/{game_id}/commands"
    principal_type = actor.principal_type if actor else "USER"
    principal_id = actor.principal_id if actor else owner_user_id
    body_hash = request_hash(payload.model_dump(mode="json"))
    current_time = now or datetime.now(UTC)
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, principal_type, principal_id, idempotency_key)
                game_row = service._games.lock_game(cursor, game_id)
                if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                previous = service._receipts.find(cursor, principal_type=principal_type, principal_id=principal_id, idempotency_key=idempotency_key)
                if previous is not None:
                    if previous["request_hash"] != body_hash or previous["route_scope"] != route_scope:
                        raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.")
                    return deepcopy(previous["result_body"]), True
                state, human_player_id = restore_locked_game(service, cursor, game_row)
                current_actor = actor or ActorContext.human(owner_user_id=owner_user_id, player_id=human_player_id)
                if actor is not None and service._players.get_kind(cursor, game_id=game_id, player_id=actor.player_id) != "AI":
                    raise ApiError(status_code=403, code="ACTOR_NOT_ALLOWED", message="Agent actor가 아닙니다.")
                if payload.expected_state_version != state.state_version:
                    raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다.", details={"current_state_version": state.state_version})
                window = service._actions.current_window(cursor, game_id=game_id)
                validate_discussion_actor(state=state, window=window, actor=current_actor, window_id=payload.window_id)
                service.hydrate_discussion_state(cursor, state=state, window=window)
                accepted_version = state.state_version
                try:
                    if payload.type == "SPEAK":
                        if payload.message is None:
                            raise ApiError(status_code=422, code="INVALID_REQUEST", message="SPEAK에는 message가 필요합니다.")
                        GameEngine().speak(state, current_actor.player_id, payload.message)
                    else:
                        if payload.message is not None:
                            raise ApiError(status_code=422, code="INVALID_REQUEST", message="PASS에는 message를 보낼 수 없습니다.")
                        GameEngine().pass_turn(state, current_actor.player_id)
                except RuleViolation as exc:
                    raise rule_error(exc) from exc
                operation = state.operations[-1]
                service._actions.insert_submission(cursor, ActionSubmissionInsert(game_id=game_id, window_id=UUID(str(window["id"])), actor_player_id=current_actor.player_id, action_type=payload.type, target_player_id=None, message=operation.text if payload.type == "SPEAK" else None, source=current_actor.source, observed_state_version=accepted_version))
                service._games.update_game_state(cursor, state=state, expected_state_version=accepted_version)
                service._actions.cancel_current_window(cursor, game_id=game_id)
                following = next_window(state, current_time)
                if following is not None:
                    service._actions.open_window(cursor, following)
                front_sequence = service._games.next_front_sequence(cursor, game_id)
                service.append_discussion_events(cursor, game_id=game_id, state=state, actor_player_id=current_actor.player_id, command_type=payload.type, message=operation.text, next_window=following, front_sequence=front_sequence, now=current_time)
                result = {"command_id": str(idempotency_key), "command_type": payload.type, "accepted_state_version": accepted_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                service._receipts.insert(cursor, principal_type=current_actor.principal_type, principal_id=current_actor.principal_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=body_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                return result, False
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 저장소를 사용할 수 없습니다.", retryable=True) from exc
