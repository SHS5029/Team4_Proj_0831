"""게임 phase에서 다음 행동 주체와 순서를 계산하는 모듈."""

from __future__ import annotations

from backend.app.models.enums import GamePhase
from backend.app.models.game_state import GameState, PlayerState


def next_speech_actor(state: GameState) -> PlayerState | None:
    """현재 토론 순환에서 아직 발언하지 않은 첫 생존자를 반환한다."""

    if state.phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        return None
    return next(
        (player for player in state.alive_players if player.player_id not in state.speech_actors),
        None,
    )


def speech_cycle(state: GameState) -> int:
    """현재 토론 window의 순환 번호를 반환한다.

    MVP에서는 첫날을 포함해 생존자별 발언 순환을 한 번만 연다. 기존 DB의
    ``cycle`` 컬럼은 호환성을 위해 유지하지만 신규 window는 항상 1이다.
    """

    del state
    return 1


__all__ = ["next_speech_actor", "speech_cycle"]
