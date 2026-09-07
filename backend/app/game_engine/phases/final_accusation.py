"""최종 고발 phase의 실행 진입점을 제공한다."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.phases.transition import touch
from backend.app.game_engine.rules.player_rules import find_player, require_alive_player
from backend.app.game_engine.rules.victory_rules import finish
from backend.app.models.enums import Faction, GamePhase, PlayerRole, WinReason
from backend.app.models.game_state import GameState

if TYPE_CHECKING:
    from backend.app.game_engine.engine import GameEngine


def submit(state: GameState, actor_id: UUID, target_id: UUID) -> GameState:
    """최종 고발 대상을 검증하고 게임을 종료한다."""

    if state.phase is not GamePhase.FINAL_ACCUSATION:
        raise RuleViolation("INVALID_PHASE")
    actor = require_alive_player(state, actor_id)
    target = find_player(state, target_id)
    if not target.alive or target.player_id == actor.player_id:
        raise RuleViolation("TARGET_INVALID")
    if state.final_accusation_target is not None:
        raise RuleViolation("DUPLICATE_ACTION")
    state.final_accusation_target = target_id
    winner = Faction.CITIZEN if target.role is PlayerRole.MAFIA else Faction.MAFIA
    reason = WinReason.FINAL_MAFIA_SELECTED if target.role is PlayerRole.MAFIA else WinReason.FINAL_NON_MAFIA_SELECTED
    touch(state)
    finish(state, winner, reason)
    return state
