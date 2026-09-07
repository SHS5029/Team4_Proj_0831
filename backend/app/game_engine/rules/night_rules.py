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
    """밤 해소에 필요한 대표 제출자를 반환한다."""

    living = state.alive_players
    actors: list[PlayerState] = []
    mafia = next((player for player in living if player.role is PlayerRole.MAFIA), None)
    if mafia:
        actors.append(mafia)
    actors.extend(
        player for player in living if player.role in {PlayerRole.DETECTIVE, PlayerRole.DOCTOR}
    )
    return actors

