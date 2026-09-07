"""밤 행동에 필요한 역할별 규칙을 제공한다."""

from __future__ import annotations

from backend.app.game_engine.errors import RuleViolation
from backend.app.models.enums import NightActionType, PlayerRole
from backend.app.models.game_state import GameState, PlayerState


def role_action(state: GameState, actor_id) -> NightActionType:
    """플레이어 역할에 대응하는 밤 행동을 반환한다."""

    actor = state.player_by_id.get(actor_id)
    if actor is None:
        raise RuleViolation("PLAYER_NOT_FOUND")
    actions = {
        PlayerRole.MAFIA: NightActionType.ATTACK,
        PlayerRole.DETECTIVE: NightActionType.INVESTIGATE,
        PlayerRole.DOCTOR: NightActionType.PROTECT,
    }
    try:
        return actions[actor.role]
    except KeyError as exc:
        raise RuleViolation("ROLE_ACTION_NOT_ALLOWED") from exc


def required_actors(state: GameState) -> list[PlayerState]:
    """마감 전 해소에 필요한 모든 생존 역할 행동자를 좌석순으로 반환한다.

    마피아 한 명의 응답만으로 창을 닫으면 다른 마피아의 첫 제출 기회가 사라진다.
    부분 응답과 전원 무응답의 차이는 마감 후 밤 해소에서 따로 처리한다.
    """

    return [
        player
        for player in state.alive_players
        if player.role in {PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR}
    ]
