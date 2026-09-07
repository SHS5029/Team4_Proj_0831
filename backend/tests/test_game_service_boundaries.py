"""GameService command와 window 조합 경계를 검증한다."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase, GameStatus
from backend.app.services.game.window_service import validate_action_window


class _State:
    """window 검증이 읽는 진행 상태와 phase를 제공하는 최소 게임 상태 대역."""

    def __init__(self, phase: GamePhase) -> None:
        self.phase = phase
        self.status = GameStatus.IN_PROGRESS


class _Payload:
    """window 검증 입력을 단순화한 command 대역."""

    def __init__(self, window_id: object, target_player_id: object) -> None:
        self.window_id = window_id
        self.target_player_id = target_player_id


def test_action_window_validation_accepts_matching_vote_window() -> None:
    """진행 중 게임에서 phase·종류가 맞고 마감 전인 window는 검증을 통과한다."""

    window_id = uuid4()
    now = datetime(2026, 9, 7, tzinfo=UTC)
    validate_action_window(
        _State(GamePhase.DAY_VOTE),
        {
            "id": window_id,
            "status": "OPEN",
            "window_kind": "VOTE",
            "phase": GamePhase.DAY_VOTE.value,
            "deadline_at": now + timedelta(seconds=30),
        },
        _Payload(window_id, uuid4()),  # type: ignore[arg-type]
        now=now,
    )


def test_action_window_validation_rejects_wrong_window_kind() -> None:
    """ID·phase·마감 조건이 유효해도 window 종류만 다르면 공통 오류를 반환한다."""

    window_id = uuid4()
    now = datetime(2026, 9, 7, tzinfo=UTC)
    with pytest.raises(ApiError) as error:
        validate_action_window(
            _State(GamePhase.DAY_VOTE),
            {
                "id": window_id,
                "status": "OPEN",
                "window_kind": "NIGHT",
                "phase": GamePhase.DAY_VOTE.value,
                "deadline_at": now + timedelta(seconds=30),
            },
            _Payload(window_id, uuid4()),  # type: ignore[arg-type]
            now=now,
        )
    assert error.value.status_code == 409
    assert error.value.code == "WINDOW_CLOSED"
