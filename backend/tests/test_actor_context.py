"""인간·AI 공통 actor 계약 테스트."""

from uuid import uuid4

import pytest

from backend.app.services.game.actor_context import ActorContext


def test_human_context_uses_user_principal() -> None:
    """인간 행동은 owner user를 receipt principal로 사용한다."""

    owner, player = uuid4(), uuid4()
    actor = ActorContext.human(owner_user_id=owner, player_id=player)

    assert actor.kind == "HUMAN"
    assert actor.principal_id == owner
    assert actor.principal_type == "USER"
    assert actor.source == "HUMAN"


def test_agent_context_uses_player_principal() -> None:
    """AI 행동은 소유자와 분리된 AI player를 receipt principal로 사용한다."""

    owner, player = uuid4(), uuid4()
    actor = ActorContext.agent(owner_user_id=owner, player_id=player)

    assert actor.kind == "AGENT"
    assert actor.principal_id == player
    assert actor.principal_type == "AGENT"
    assert actor.source == "AGENT"


def test_actor_context_rejects_non_uuid_identity() -> None:
    """외부 문자열이 내부 actor 계약에 직접 주입되지 않도록 차단한다."""

    with pytest.raises(TypeError):
        ActorContext("AGENT", uuid4(), "not-a-uuid", uuid4())  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["HUMAN", "AI"])
@pytest.mark.parametrize("timed", [False, True])
def test_day1_pass_rejected_before_transaction_writes(monkeypatch, kind, timed):
    """인간·AI의 시간제·기존 차례제 PASS 모두 저장 직전 경계에서 거부한다."""

    from contextlib import nullcontext
    from copy import deepcopy
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock
    from backend.app.core.errors import ApiError
    from backend.app.game_engine.engine import GameEngine
    from backend.app.models.enums import PlayerKind
    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.app.services.game import discussion_transaction as transaction

    owner, player, window_id = uuid4(), uuid4(), uuid4()
    state = GameEngine.new_game([(player, PlayerKind(kind)),
                                *[(uuid4(), PlayerKind.AI) for _ in range(5)]], seed=b"day1")
    GameEngine().begin_game(state)
    before = deepcopy(state)
    service, connection, cursor = MagicMock(), MagicMock(), MagicMock()
    service._transactions.transaction.side_effect = lambda: nullcontext(connection)
    connection.cursor.side_effect = lambda **kwargs: nullcontext(cursor)
    service._games.lock_game.return_value = {"owner_user_id": owner}
    service._receipts.find.return_value = None
    service._players.get_kind.return_value = kind
    service._actions.current_window.return_value = {
        "id": window_id, "status": "OPEN", "window_kind": "SPEECH",
        "phase": "DAY_DISCUSSION", "turn_player_id": player,
        "deadline_at": datetime.now(UTC) + timedelta(seconds=105) if timed else None,
    }
    monkeypatch.setattr(transaction, "lock_idempotency", lambda *args: None)
    monkeypatch.setattr(transaction, "restore_locked_game", lambda *args: (state, player))
    actor = ActorContext.agent(owner_user_id=owner, player_id=player) if kind == "AI" else None
    with pytest.raises(ApiError) as failure:
        transaction.submit_discussion_transaction(
            service, owner, state.game_id,
            GameCommandRequest(type="PASS", expected_state_version=state.state_version,
                               window_id=window_id), uuid4(), actor=actor,
        )
    assert (failure.value.status_code, failure.value.code) == (409, "ACTION_NOT_ALLOWED")
    assert state == before
    service._games.update_game_state.assert_not_called()
    service._actions.cancel_current_window.assert_not_called()
    service._actions.insert_submission.assert_not_called()
    service._receipts.insert.assert_not_called()
    service.append_discussion_events.assert_not_called()
