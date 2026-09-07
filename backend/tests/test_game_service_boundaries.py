"""GameService command와 window 조합 경계를 검증한다."""

from uuid import uuid4

import pytest

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase
from backend.app.services.game.window_service import validate_action_window


class _State:
    """window 검증에 필요한 최소 phase 상태 대역."""

    def __init__(self, phase: GamePhase) -> None:
        self.phase = phase


class _Payload:
    """window 검증 입력을 단순화한 command 대역."""

    def __init__(self, window_id: object, target_player_id: object) -> None:
        self.window_id = window_id
        self.target_player_id = target_player_id


def test_action_window_validation_accepts_matching_vote_window() -> None:
    """현재 phase와 열린 window 종류가 일치하면 검증을 통과한다."""

    window_id = uuid4()
    validate_action_window(
        _State(GamePhase.DAY_VOTE),
        {"id": window_id, "status": "OPEN", "window_kind": "VOTE"},
        _Payload(window_id, uuid4()),  # type: ignore[arg-type]
    )


def test_action_window_validation_rejects_wrong_window_kind() -> None:
    """phase와 window 종류가 다르면 command service 공통 오류를 반환한다."""

    with pytest.raises(ApiError) as error:
        validate_action_window(
            _State(GamePhase.DAY_VOTE),
            {"id": uuid4(), "status": "OPEN", "window_kind": "NIGHT"},
            _Payload(uuid4(), uuid4()),  # type: ignore[arg-type]
        )
    assert error.value.code == "WINDOW_CLOSED"
