"""밤 행동과 투표를 PostgreSQL 정본에 연결하는 작은 command service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import lock_idempotency
from backend.app.models.enums import GamePhase, PlayerRole, NightActionType
from backend.app.repositories.action_repository import ActionSubmissionInsert
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game_service import PostgresBeginGameService
from backend.app.services.game.helpers import request_hash as _request_hash
from backend.app.services.game.service_errors import rule_error
from backend.app.services.game.postgres_helpers import find_replay, restore_locked_game
from backend.app.services.game.window_service import (
    next_window as build_next_window,
    validate_action_window,
)
from backend.app.services.game.actor_context import ActorContext
from backend.app.game_engine.rules.night_rules import required_actors, role_action


class PostgresActionCommandService(PostgresBeginGameService):
    """인간의 밤 행동·투표를 같은 transaction에서 엔진과 원장에 반영한다."""

    def submit(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
        *,
        actor: ActorContext | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """대상 검증, 강제 해소, 다음 window와 receipt 기록을 원자적으로 처리한다."""

        if payload.type not in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
            raise ValueError("PostgresActionCommandService only accepts action commands")
        request_hash = _request_hash(payload.model_dump(mode="json"))
        route_scope = f"POST /api/v1/games/{game_id}/agent-commands" if actor else f"POST /api/v1/games/{game_id}/commands"
        principal_type = actor.principal_type if actor else "USER"
        principal_id = actor.principal_id if actor else owner_user_id
        current_time = now or datetime.now(UTC)
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    lock_idempotency(cursor, principal_type, principal_id, idempotency_key)
                    game_row = self._games.lock_game(cursor, game_id)
                    if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                    replay = self._receipts.find(
                        cursor, principal_type=principal_type, principal_id=principal_id,
                        idempotency_key=idempotency_key,
                    )
                    if replay is not None:
                        if replay["request_hash"] != request_hash or replay["route_scope"] != route_scope:
                            raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.")
                        return dict(replay["result_body"]), True
                    state, human_player_id = restore_locked_game(self, cursor, game_row)
                    actor_player_id = actor.player_id if actor else human_player_id
                    if actor is not None and self._players.get_kind(cursor, game_id=game_id, player_id=actor.player_id) != "AI":
                        raise ApiError(status_code=403, code="ACTOR_NOT_ALLOWED", message="Agent actor가 아닙니다.")
                    accepted_version = state.state_version
                    if payload.expected_state_version != accepted_version:
                        raise ApiError(
                            status_code=409,
                            code="STALE_STATE_VERSION",
                            message="게임 상태가 변경되었습니다. 최신 상태를 다시 확인하세요.",
                            details={"current_state_version": accepted_version},
                        )
                    window = self._actions.current_window(cursor, game_id=game_id)
                    validate_action_window(state, window, payload)
                    engine = GameEngine()
                    action_type: str
                    night_resolved = False
                    vote_resolved = False
                    if payload.type == "SUBMIT_NIGHT_ACTION":
                        role_actions = {
                            PlayerRole.MAFIA: NightActionType.ATTACK,
                            PlayerRole.DETECTIVE: NightActionType.INVESTIGATE,
                            PlayerRole.DOCTOR: NightActionType.PROTECT,
                        }
                        action = role_actions[state.player_by_id[actor_player_id].role]
                        for previous in self._actions.list_window_action_submissions(
                            cursor, window_id=UUID(str(window["id"]))
                        ):
                            if previous["action_type"] in {item.value for item in NightActionType}:
                                engine.submit_night_action(
                                    state,
                                    UUID(str(previous["actor_player_id"])),
                                    NightActionType(str(previous["action_type"])),
                                    UUID(str(previous["target_player_id"])),
                                )
                        engine.submit_night_action(state, actor_player_id, action, payload.target_player_id)  # type: ignore[arg-type]
                        action_type = action.value
                        required_ids = {player.player_id for player in required_actors(state)}
                        if required_ids.issubset(state.night_actions):
                            engine.resolve_night(state, force=False)
                            night_resolved = True
                    elif state.phase is GamePhase.FINAL_ACCUSATION:
                        engine.submit_final_accusation(
                            state, actor_player_id, payload.target_player_id  # type: ignore[arg-type]
                        )
                        action_type = "VOTE"
                    else:
                        for previous in self._actions.list_window_vote_submissions(
                            cursor, window_id=UUID(str(window["id"]))
                        ):
                            engine.submit_vote(
                                state,
                                UUID(str(previous["actor_player_id"])),
                                UUID(str(previous["target_player_id"])),
                            )
                        engine.submit_vote(
                            state, actor_player_id, payload.target_player_id  # type: ignore[arg-type]
                        )
                        action_type = "VOTE"
                        if all(player.player_id in state.votes for player in state.alive_players):
                            engine.resolve_vote(state, force=False)
                            vote_resolved = True
                    # 엔진은 제출과 해소를 내부 operation 단위로 각각 touch하지만,
                    # 공개 API command 하나는 DB에서 하나의 state version만 소비한다.
                    state.state_version = accepted_version + 1
                    self._players.update_eliminated_players(
                        cursor,
                        game_id=game_id,
                        players=state.players,
                        phase=state.phase.value,
                        round=state.round,
                    )
                    self._actions.insert_submission(
                        cursor,
                        ActionSubmissionInsert(
                            game_id=game_id,
                            window_id=UUID(str(window["id"])),
                            actor_player_id=actor_player_id,
                            action_type=action_type,
                            target_player_id=payload.target_player_id,
                            message=None,
                            source=actor.source if actor else "HUMAN",
                            observed_state_version=accepted_version,
                        ),
                    )
                    self._games.update_game_state(
                        cursor, state=state, expected_state_version=accepted_version
                    )
                    resolved = night_resolved or vote_resolved or state.phase is GamePhase.FINAL_ACCUSATION
                    if resolved:
                        self._actions.cancel_current_window(cursor, game_id=game_id)
                        next_window = build_next_window(state, current_time)
                        if next_window is not None:
                            self._actions.open_window(cursor, next_window)
                    else:
                        next_window = window
                    front_sequence = self._games.next_front_sequence(cursor, game_id)
                    self._append_events(
                        cursor,
                        game_id=game_id,
                        state=state,
                        action_type=action_type,
                        target_player_id=payload.target_player_id,
                        next_window=next_window,
                        front_sequence=front_sequence,
                        now=current_time,
                    )
                    result = {
                        "command_id": str(idempotency_key),
                        "command_type": payload.type,
                        "accepted_state_version": accepted_version,
                        "result_state_version": state.state_version,
                        "sync_url": f"/api/v1/games/{game_id}/sync",
                    }
                    self._receipts.insert(
                        cursor,
                        principal_type=actor.principal_type if actor else "USER",
                        principal_id=actor.principal_id if actor else owner_user_id,
                        idempotency_key=idempotency_key,
                        route_scope=route_scope,
                        game_id=game_id,
                        request_hash=request_hash,
                        result_state_version=state.state_version,
                        http_status=200,
                        result_body=result,
                    )
                    return result, False
        except ApiError:
            raise
        except RuleViolation as exc:
            raise rule_error(exc) from exc
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="게임 행동을 저장할 수 없습니다.",
                retryable=True,
            ) from exc

    def submit_agent_night_actions(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        actions: list[dict[str, UUID]],
        *,
        expected_state_version: int,
        window_id: UUID,
        idempotency_key: UUID,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """모든 AI required actor의 밤 행동을 한 transaction에서 확정한다."""

        if not actions:
            raise ApiError(status_code=422, code="INVALID_REQUEST", message="AI 밤 행동이 없습니다.")
        current_time = now or datetime.now(UTC)
        route_scope = f"POST /api/v1/games/{game_id}/agent-commands"
        body_hash = _request_hash({"actions": [{str(k): str(v) for k, v in item.items()} for item in actions], "expected_state_version": expected_state_version, "window_id": str(window_id)})
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    principal_id = actions[0]["player_id"]
                    lock_idempotency(cursor, "AGENT", principal_id, idempotency_key)
                    previous = self._receipts.find(cursor, principal_type="AGENT", principal_id=principal_id, idempotency_key=idempotency_key)
                    if previous is not None:
                        if previous["request_hash"] != body_hash or previous["route_scope"] != route_scope:
                            raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.")
                        return dict(previous["result_body"]), True
                    game_row = self._games.lock_game(cursor, game_id)
                    if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                    state, _ = restore_locked_game(self, cursor, game_row)
                    if state.state_version != expected_state_version:
                        raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다.")
                    window = self._actions.current_window(cursor, game_id=game_id)
                    if window is None or UUID(str(window["id"])) != window_id or window["window_kind"] != "NIGHT" or window["status"] != "OPEN":
                        raise ApiError(status_code=409, code="WINDOW_CLOSED", message="현재 밤 행동 window가 아닙니다.")
                    required = required_actors(state)
                    required_ids = {player.player_id for player in required}
                    submitted_ids = {item.get("player_id") for item in actions}
                    if submitted_ids != required_ids or any(service_kind != "AI" for service_kind in (self._players.get_kind(cursor, game_id=game_id, player_id=player_id) for player_id in submitted_ids)):
                        raise ApiError(status_code=409, code="ACTION_NOT_READY", message="모든 required AI actor가 준비되지 않았습니다.")
                    engine = GameEngine()
                    for item in actions:
                        player_id = item["player_id"]
                        target_id = item["target_player_id"]
                        action_type = role_action(state, player_id)
                        engine.submit_night_action(state, player_id, action_type, target_id)
                    engine.resolve_night(state, force=False)
                    state.state_version = expected_state_version + 1
                    self._players.update_eliminated_players(cursor, game_id=game_id, players=state.players, phase=state.phase.value, round=state.round)
                    for item in actions:
                        player_id = item["player_id"]
                        self._actions.insert_submission(cursor, ActionSubmissionInsert(game_id=game_id, window_id=window_id, actor_player_id=player_id, action_type=role_action(state, player_id).value, target_player_id=item["target_player_id"], message=None, source="AGENT", observed_state_version=expected_state_version))
                    self._games.update_game_state(cursor, state=state, expected_state_version=expected_state_version)
                    self._actions.cancel_current_window(cursor, game_id=game_id)
                    following = build_next_window(state, current_time)
                    if following is not None:
                        self._actions.open_window(cursor, following)
                    front_sequence = self._games.next_front_sequence(cursor, game_id)
                    self._append_events(cursor, game_id=game_id, state=state, action_type="RESOLVE_NIGHT", target_player_id=None, next_window=following, front_sequence=front_sequence, now=current_time)
                    result = {"command_id": str(idempotency_key), "command_type": "SUBMIT_NIGHT_ACTION", "accepted_state_version": expected_state_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                    self._receipts.insert(cursor, principal_type="AGENT", principal_id=principal_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=body_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                    return result, False
        except ApiError:
            raise
        except RuleViolation as exc:
            raise rule_error(exc) from exc
        except Exception as exc:
            raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="AI 밤 행동을 저장할 수 없습니다.", retryable=True) from exc

    def auto_resolve_citizen_night(
        self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """기존 호출부 호환을 위해 만료 밤 자동 해소 메서드로 위임한다."""

        return self.auto_resolve_expired_night(owner_user_id, game_id, now=now)

    def auto_resolve_expired_night(
        self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """인간 역할을 포함한 만료 밤 행동을 같은 DB transaction에서 자동 해소한다.

        정본은 탐정·의사·마피아의 무응답도 결정적 후보 자동 선택으로 처리한다.
        게임과 window를 잠근 뒤 현재 deadline이 실제로 지났는지는 worker 조회와
        별도로 재검증하지 않고, 호출 시점의 열린 window만 원자적으로 해소한다.
        """

        current_time = now or datetime.now(UTC)
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    game_row = self._games.lock_game(cursor, game_id)
                    if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                        return None
                    state, human_player_id = restore_locked_game(self, cursor, game_row)
                    human = state.player_by_id[human_player_id]
                    if state.phase is not GamePhase.NIGHT_ACTION:
                        return None
                    window = self._actions.current_window(cursor, game_id=game_id)
                    if window is None:
                        return None
                    accepted_version = state.state_version
                    GameEngine().resolve_night(state, force=True)
                    self._players.update_eliminated_players(
                        cursor,
                        game_id=game_id,
                        players=state.players,
                        phase=state.phase.value,
                        round=state.round,
                    )
                    self._games.update_game_state(cursor, state=state, expected_state_version=accepted_version)
                    self._actions.cancel_current_window(cursor, game_id=game_id)
                    next_window = build_next_window(state, current_time)
                    if next_window is not None:
                        self._actions.open_window(cursor, next_window)
                    front_sequence = self._games.next_front_sequence(cursor, game_id)
                    self._append_events(
                        cursor,
                        game_id=game_id,
                        state=state,
                        action_type="AUTO_RESOLVE_NIGHT",
                        target_player_id=None,
                        next_window=next_window,
                        front_sequence=front_sequence,
                        now=current_time,
                    )
                    return {
                        "command_type": "AUTO_RESOLVE_NIGHT",
                        "accepted_state_version": accepted_version,
                        "result_state_version": state.state_version,
                        "sync_url": f"/api/v1/games/{game_id}/sync",
                    }
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="시민 밤 행동을 자동 처리할 수 없습니다.",
                retryable=True,
            ) from exc

    def submit_agent_votes(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        actions: list[dict[str, UUID]],
        *,
        expected_state_version: int,
        window_id: UUID,
        idempotency_key: UUID,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """AI 투표를 한 transaction에서 검증하고 투표·재투표를 해소한다."""

        if not actions:
            raise ApiError(status_code=422, code="INVALID_REQUEST", message="AI 투표가 없습니다.")
        current_time = now or datetime.now(UTC)
        route_scope = f"POST /api/v1/games/{game_id}/agent-commands"
        body_hash = _request_hash({"actions": [{str(k): str(v) for k, v in item.items()} for item in actions], "expected_state_version": expected_state_version, "window_id": str(window_id)})
        principal_id = actions[0]["player_id"]
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    lock_idempotency(cursor, "AGENT", principal_id, idempotency_key)
                    game_row = self._games.lock_game(cursor, game_id)
                    if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                    previous = self._receipts.find(cursor, principal_type="AGENT", principal_id=principal_id, idempotency_key=idempotency_key)
                    if previous is not None:
                        if previous["request_hash"] != body_hash:
                            raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.")
                        return dict(previous["result_body"]), True
                    state, human_player_id = restore_locked_game(self, cursor, game_row)
                    if state.phase is GamePhase.FINAL_ACCUSATION and state.human_alive:
                        raise ApiError(status_code=409, code="HUMAN_ACTION_REQUIRED", message="인간 투표를 먼저 기다려야 합니다.")
                    if state.state_version != expected_state_version:
                        raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다.")
                    window = self._actions.current_window(cursor, game_id=game_id)
                    if window is None or UUID(str(window["id"])) != window_id or window["status"] != "OPEN":
                        raise ApiError(status_code=409, code="WINDOW_CLOSED", message="현재 투표 window가 아닙니다.")
                    for item in actions:
                        if self._players.get_kind(cursor, game_id=game_id, player_id=item["player_id"]) != "AI":
                            raise ApiError(status_code=403, code="ACTOR_NOT_ALLOWED", message="Agent actor가 아닙니다.")
                    engine = GameEngine()
                    action_type = "FINAL_ACCUSATION" if state.phase is GamePhase.FINAL_ACCUSATION else "VOTE"
                    selected = actions[:1] if state.phase is GamePhase.FINAL_ACCUSATION else actions
                    vote_resolved = False
                    if state.phase is not GamePhase.FINAL_ACCUSATION:
                        for previous in self._actions.list_window_vote_submissions(
                            cursor, window_id=window_id
                        ):
                            engine.submit_vote(
                                state,
                                UUID(str(previous["actor_player_id"])),
                                UUID(str(previous["target_player_id"])),
                            )
                    for item in selected:
                        if state.phase is GamePhase.FINAL_ACCUSATION:
                            engine.submit_final_accusation(state, item["player_id"], item["target_player_id"])
                        else:
                            engine.submit_vote(state, item["player_id"], item["target_player_id"])
                    if state.phase is not GamePhase.FINAL_ACCUSATION and all(
                        player.player_id in state.votes for player in state.alive_players
                    ):
                        engine.resolve_vote(state, force=False)
                        vote_resolved = True
                    state.state_version = expected_state_version + 1
                    self._players.update_eliminated_players(cursor, game_id=game_id, players=state.players, phase=state.phase.value, round=state.round)
                    for item in selected:
                        self._actions.insert_submission(cursor, ActionSubmissionInsert(game_id=game_id, window_id=window_id, actor_player_id=item["player_id"], action_type=action_type, target_player_id=item["target_player_id"], message=None, source="AGENT", observed_state_version=expected_state_version))
                    self._games.update_game_state(cursor, state=state, expected_state_version=expected_state_version)
                    resolved = vote_resolved or state.phase is GamePhase.FINAL_ACCUSATION
                    if resolved:
                        self._actions.cancel_current_window(cursor, game_id=game_id)
                        following = build_next_window(state, current_time)
                        if following is not None:
                            self._actions.open_window(cursor, following)
                    else:
                        following = window
                    front_sequence = self._games.next_front_sequence(cursor, game_id)
                    self._append_events(cursor, game_id=game_id, state=state, action_type=action_type, target_player_id=selected[0]["target_player_id"], next_window=following, front_sequence=front_sequence, now=current_time)
                    result = {"command_id": str(idempotency_key), "command_type": "SUBMIT_VOTE", "accepted_state_version": expected_state_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                    self._receipts.insert(cursor, principal_type="AGENT", principal_id=principal_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=body_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                    return result, False
        except ApiError:
            raise
        except RuleViolation as exc:
            raise rule_error(exc) from exc
        except Exception as exc:
            raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="AI 투표를 저장할 수 없습니다.", retryable=True) from exc

    def fast_forward(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """사망한 인간의 남은 게임을 엔진 규칙으로 끝까지 진행한다."""

        if payload.type != "FAST_FORWARD":
            raise ValueError("fast_forward only accepts FAST_FORWARD")
        request_hash = _request_hash(payload.model_dump(mode="json"))
        route_scope = f"POST /api/v1/games/{game_id}/commands"
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                    game_row = self._games.lock_game(cursor, game_id)
                    if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                    replay = find_replay(
                        self,
                        cursor,
                        owner_user_id=owner_user_id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        route_scope=route_scope,
                    )
                    if replay is not None:
                        return replay, True
                    state, human_player_id = restore_locked_game(self, cursor, game_row)
                    accepted_version = state.state_version
                    if payload.expected_state_version != accepted_version:
                        raise ApiError(
                            status_code=409,
                            code="STALE_STATE_VERSION",
                            message="게임 상태가 변경되었습니다. 최신 상태를 다시 확인하세요.",
                            details={"current_state_version": accepted_version},
                        )
                    if state.player_by_id[human_player_id].alive:
                        raise ApiError(
                            status_code=409,
                            code="ACTION_NOT_ALLOWED",
                            message="생존한 플레이어는 빠른 진행을 사용할 수 없습니다.",
                        )
                    window = self._actions.current_window(cursor, game_id=game_id)
                    GameEngine().fast_forward(state)
                    state.state_version = accepted_version + 1
                    self._players.update_eliminated_players(
                        cursor,
                        game_id=game_id,
                        players=state.players,
                        phase=state.phase.value,
                        round=state.round,
                    )
                    self._games.update_game_state(
                        cursor, state=state, expected_state_version=accepted_version
                    )
                    if window is not None:
                        self._actions.cancel_current_window(cursor, game_id=game_id)
                    next_window = build_next_window(state, datetime.now(UTC))
                    if next_window is not None:
                        self._actions.open_window(cursor, next_window)
                    front_sequence = self._games.next_front_sequence(cursor, game_id)
                    self._append_events(
                        cursor,
                        game_id=game_id,
                        state=state,
                        action_type="FAST_FORWARD",
                        target_player_id=None,
                        next_window=next_window,
                        front_sequence=front_sequence,
                        now=datetime.now(UTC),
                    )
                    result = {
                        "command_id": str(idempotency_key),
                        "command_type": "FAST_FORWARD",
                        "accepted_state_version": accepted_version,
                        "result_state_version": state.state_version,
                        "sync_url": f"/api/v1/games/{game_id}/sync",
                    }
                    self._receipts.insert(
                        cursor,
                        principal_type="USER",
                        principal_id=owner_user_id,
                        idempotency_key=idempotency_key,
                        route_scope=route_scope,
                        game_id=game_id,
                        request_hash=request_hash,
                        result_state_version=state.state_version,
                        http_status=200,
                        result_body=result,
                    )
                    return result, False
        except ApiError:
            raise
        except RuleViolation as exc:
            raise rule_error(exc) from exc
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="게임을 빠르게 진행할 수 없습니다.",
                retryable=True,
            ) from exc

    def _append_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state: Any,
        action_type: str,
        target_player_id: UUID | None,
        next_window: Any,
        front_sequence: int,
        now: datetime,
    ) -> None:
        """행동 결과와 다음 window를 하나의 공개 operation batch로 남긴다."""

        events = [
            self._events.append(
                cursor,
                game_id=game_id,
                state_version=state.state_version,
                event_type="PHASE_CHANGED",
                audience="PUBLIC",
                front_sequence=front_sequence,
                operation_index=0,
                operation_type="SET_GAME_STATE",
                payload={
                    "status": state.status.value,
                    "phase": state.phase.value,
                    "round": state.round,
                    "day_number": state.day_number,
                    "state_version": state.state_version,
                    "fast_forward_enabled": not state.human_alive,
                },
            ),
            self._events.append(
                cursor,
                game_id=game_id,
                state_version=state.state_version,
                event_type="ACTION_RESOLVED",
                audience="PUBLIC",
                front_sequence=front_sequence,
                operation_index=1,
                operation_type="APPEND_PUBLIC_EVENT",
                payload={
                    "action_type": action_type,
                    "target_player_id": str(target_player_id) if target_player_id else None,
                    "phase": state.phase.value,
                },
            ),
        ]
        window_payload = {"window_id": None}
        if next_window is not None:
            if isinstance(next_window, Mapping):
                window_payload = {
                    "window_id": str(next_window["id"]),
                    "kind": str(next_window["window_kind"]),
                    "cycle": int(next_window["cycle"]),
                    "paused": str(next_window["status"]) == "PAUSED",
                    "opened_state_version": int(next_window["opened_state_version"]),
                    "server_time": now.isoformat().replace("+00:00", "Z"),
                    "deadline_at": next_window["deadline_at"].isoformat().replace("+00:00", "Z") if next_window["deadline_at"] is not None else None,
                    "remaining_ms": None,
                    "turn_player_id": str(next_window["turn_player_id"]) if next_window["turn_player_id"] is not None else None,
                }
            else:
                window_payload = {
                    "window_id": str(next_window.window_id),
                    "kind": next_window.window_kind,
                    "cycle": next_window.cycle,
                    "paused": False,
                    "opened_state_version": next_window.opened_state_version,
                    "server_time": now.isoformat().replace("+00:00", "Z"),
                    "deadline_at": (
                        next_window.deadline_at.isoformat().replace("+00:00", "Z")
                        if next_window.deadline_at is not None
                        else None
                    ),
                    "remaining_ms": (
                        max(int((next_window.deadline_at - now).total_seconds() * 1000), 0)
                        if next_window.deadline_at is not None
                        else None
                    ),
                    "turn_player_id": (
                        str(next_window.turn_player_id)
                        if next_window.turn_player_id is not None
                        else None
                    ),
                }
            window_payload.update({
                "has_submitted": False,
                "legal_actions": [],
                "valid_targets": [],
            })
        events.append(
            self._events.append(
                cursor,
                game_id=game_id,
                state_version=state.state_version,
                event_type="TURN_OPENED",
                audience="PUBLIC",
                front_sequence=front_sequence,
                operation_index=2,
                operation_type="SET_ACTION_WINDOW" if next_window is not None else "CLEAR_ACTION_WINDOW",
                payload=window_payload,
            )
        )
        for event in events:
            self._outbox.enqueue(cursor, UUID(str(event["id"])))
