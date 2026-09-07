"""투표 결과를 계산하는 순수 규칙."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from backend.app.models.enums import GamePhase
from backend.app.models.game_state import GameState, PlayerState, Vote


def valid_targets(state: GameState, actor: PlayerState) -> list[PlayerState]:
    """공개된 생존·후보 정보만으로 수동 제출과 자동 선택의 같은 경계를 만든다.

    재투표 후보가 복원되지 않았다면 전체 생존자로 넓히지 않는다. 잘못 복원한
    상태에서 이전 투표의 동률 후보 밖을 선택하는 것을 막기 위해 빈 목록을 유지한다.
    """

    return [
        player
        for player in state.alive_players
        if player.player_id != actor.player_id
        and (state.phase is not GamePhase.REVOTE or player.player_id in state.revote_candidates)
    ]


def leaders(votes: dict[UUID, Vote]) -> list[UUID]:
    """가장 많은 표를 받은 대상 목록을 반환한다."""

    counts = Counter(vote.target_id for vote in votes.values())
    highest = max(counts.values()) if counts else 0
    return [target_id for target_id, count in counts.items() if count == highest]
