"""게임 종료 상태를 공개 API 결과 projection으로 변환한다."""

from __future__ import annotations

from typing import Any

from backend.app.models.enums import GameStatus
from backend.app.models.game_state import GameState


def build_result(state: GameState) -> dict[str, Any] | None:
    """완료된 게임만 승패와 최종 플레이어 정보를 반환한다."""

    if state.status is not GameStatus.COMPLETED:
        return None
    return {
        "winner": state.winner.value if state.winner else None,
        "win_reason": state.win_reason.value if state.win_reason else None,
        "finished_at": state.updated_at.isoformat(),
        "players": [
            {
                "player_id": str(player.player_id),
                "display_name": player.display_name,
                "role": player.role.value,
                "alive": player.alive,
            }
            for player in sorted(state.players, key=lambda item: item.seat)
        ],
    }
