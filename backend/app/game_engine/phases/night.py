"""밤 행동 phase의 실행 진입점을 제공한다."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.fallback import auto_night_target
from backend.app.game_engine.phases.transition import after_night, touch
from backend.app.game_engine.rules.night_rules import required_actors, role_action
from backend.app.game_engine.rules.player_rules import eliminate_player, find_player, require_alive_player
from backend.app.models.enums import NightActionType
from backend.app.models.enums import GamePhase, PlayerRole
from backend.app.models.game_state import GameState, NightAction

if TYPE_CHECKING:
    from backend.app.game_engine.engine import GameEngine


def submit_action(
    state: GameState,
    actor_id: UUID,
    action_type: NightActionType,
    target_id: UUID,
) -> GameState:
    """역할별 밤 행동을 검증하고 첫 유효 제출로 반영한다."""

    if state.phase is not GamePhase.NIGHT_ACTION:
        raise RuleViolation("INVALID_PHASE")
    actor = require_alive_player(state, actor_id)
    if role_action(state, actor.player_id) is not action_type:
        raise RuleViolation("ROLE_ACTION_INVALID")
    if actor.player_id in state.night_actions:
        raise RuleViolation("DUPLICATE_ACTION")
    target = find_player(state, target_id)
    if not target.alive:
        raise RuleViolation("TARGET_DEAD")
    if action_type in {NightActionType.ATTACK, NightActionType.INVESTIGATE} and target.player_id == actor.player_id:
        raise RuleViolation("SELF_TARGET_INVALID")
    if action_type is NightActionType.ATTACK and any(
        action.action_type is NightActionType.ATTACK for action in state.night_actions.values()
    ):
        raise RuleViolation("FACTION_ACTION_ALREADY_SUBMITTED")
    state.night_actions[actor.player_id] = NightAction(actor.player_id, action_type, target_id)
    touch(state)
    return state


def resolve(state: GameState, *, force: bool = False) -> GameState:
    """밤 행동을 모으고 공격·보호·조사 결과를 반영한다."""

    if state.phase is not GamePhase.NIGHT_ACTION:
        raise RuleViolation("INVALID_PHASE")
    required = required_actors(state)
    if not force and any(player.player_id not in state.night_actions for player in required):
        raise RuleViolation("WINDOW_NOT_READY")
    for actor in required:
        if actor.player_id in state.night_actions:
            continue
        action_type = role_action(state, actor.player_id)
        target = auto_night_target(state, actor, action_type)
        state.night_actions[actor.player_id] = NightAction(actor.player_id, action_type, target.player_id)

    attack = next((action for action in state.night_actions.values() if action.action_type is NightActionType.ATTACK), None)
    protection = next((action for action in state.night_actions.values() if action.action_type is NightActionType.PROTECT), None)
    if attack and (not protection or protection.target_id != attack.target_id):
        eliminate_player(state, attack.target_id)
    for action in state.night_actions.values():
        if action.action_type is NightActionType.INVESTIGATE:
            target = find_player(state, action.target_id)
            state.last_detective_result[action.actor_id] = target.role is PlayerRole.MAFIA
    state.round += 1
    state.night_actions.clear()
    touch(state)
    after_night(state)
    return state
