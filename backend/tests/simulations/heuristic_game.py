"""외부 서비스 없이 한 판을 끝까지 진행하는 heuristic bot.

이 모듈은 LLM을 사용하지 않는다. 각 플레이어는 자신의 역할만 알고, 대상은
seed와 행동 목적 문자열로 결정한다. 따라서 실제 DB·Redis·MCP가 없어도 규칙
엔진의 phase 전이와 결정성만 반복 검증할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.rng import DeterministicRng
from backend.app.game_engine.rules.night_rules import required_actors, role_action
from backend.app.models.enums import (
    GamePhase,
    GameStatus,
    NightActionType,
    PlayerKind,
)
from backend.app.models.game_state import GameState, PlayerState


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """한 synthetic game의 외부 검증용 결과다."""

    player_count: int
    winner: str
    win_reason: str
    round: int
    operation_count: int
    revote_count: int
    final_accusation_target: UUID | None
    signature: tuple[object, ...]


def _players(player_count: int, seed: str) -> list[tuple[UUID, PlayerKind]]:
    """재실행할 때 같은 좌석 UUID를 만드는 synthetic 참가자 목록이다."""

    return [
        (uuid5(NAMESPACE_URL, f"ai-mafia-b9:{seed}:player:{seat}"), PlayerKind.AI)
        for seat in range(1, player_count + 1)
    ]


def _target(
    state: GameState, actor: PlayerState, purpose: str, *, allow_self: bool = False
) -> UUID:
    """숨은 역할 없이 생존·재투표 후보의 교집합에서 한 명을 결정한다."""

    candidates = [
        player
        for player in state.alive_players
        if (allow_self or player.player_id != actor.player_id)
        and (state.phase is not GamePhase.REVOTE or player.player_id in state.revote_candidates)
    ]
    return DeterministicRng(state.seed).choice(candidates, purpose).player_id


def _pass_discussion(engine: GameEngine, state: GameState) -> None:
    """현재 토론 cycle에서 아직 말하지 않은 생존자를 모두 PASS 처리한다."""

    pending = [
        player for player in state.alive_players if player.player_id not in state.speech_actors
    ]
    for player in pending:
        engine.pass_turn(state, player.player_id)


def _resolve_heuristic_night(engine: GameEngine, state: GameState) -> None:
    """각 역할이 자기 역할에 맞는 대상만 제출한 뒤 밤을 해소한다."""

    for actor in required_actors(state):
        if actor.player_id in state.night_actions:
            continue
        action = role_action(state, actor.player_id)
        target = _target(
            state,
            actor,
            f"b9-night:{state.round}:{actor.player_id}:{action.value}",
            allow_self=action is NightActionType.PROTECT,
        )
        engine.submit_night_action(state, actor.player_id, action, target)
    engine.resolve_night(state)


def _resolve_heuristic_vote(engine: GameEngine, state: GameState) -> None:
    """일반·재투표·최종 지목 모두 생존자 전원의 첫 유효 표를 제출한다."""

    final_accusation = state.phase is GamePhase.FINAL_ACCUSATION
    submit = engine.submit_final_accusation if final_accusation else engine.submit_vote
    for actor in state.alive_players:
        if actor.player_id in state.votes:
            continue
        target = _target(
            state,
            actor,
            f"b9-vote:{state.round}:{state.phase.value}:{actor.player_id}",
        )
        submit(state, actor.player_id, target)
    # 최종 지목은 마지막 유효 표가 들어오면 엔진이 즉시 판정하므로 이중 해소하지 않는다.
    if not final_accusation:
        engine.resolve_vote(state)


def _signature(state: GameState) -> tuple[object, ...]:
    """시각처럼 재실행마다 달라지는 값은 제외하고 규칙 결과만 비교한다."""

    players = tuple(
        (player.seat, player.player_id, player.role.value, player.alive) for player in state.players
    )
    operations = tuple(
        (
            operation.command,
            operation.actor_id,
            operation.target_id,
            operation.text,
            operation.result_state_version,
        )
        for operation in state.operations
    )
    return (
        players,
        state.phase.value,
        state.status.value,
        state.winner.value if state.winner else None,
        state.win_reason.value if state.win_reason else None,
        state.round,
        state.final_accusation_target,
        tuple(sorted(state.last_detective_result.items())),
        operations,
    )


def run_heuristic_game(player_count: int, seed: str) -> SimulationResult:
    """6~9명 synthetic game을 외부 의존성 없이 완료한다."""

    if player_count not in {6, 7, 8, 9}:
        raise ValueError("player_count must be between 6 and 9")
    state = GameEngine.new_game(
        _players(player_count, seed),
        seed=seed,
        game_id=uuid5(NAMESPACE_URL, f"ai-mafia-b9:{seed}:game"),
    )
    engine = GameEngine()
    for _ in range(100):
        if state.status is GameStatus.COMPLETED:
            break
        if state.phase is GamePhase.ROLE_REVEAL:
            engine.begin_game(state)
        elif state.phase is GamePhase.DAY_DISCUSSION:
            _pass_discussion(engine, state)
        elif state.phase is GamePhase.NIGHT_ACTION:
            _resolve_heuristic_night(engine, state)
        elif state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}:
            _resolve_heuristic_vote(engine, state)
        elif state.phase is GamePhase.FINAL_DISCUSSION:
            engine.advance_final_discussion(state)
        else:
            raise AssertionError(f"unexpected simulation phase: {state.phase}")
    if state.status is not GameStatus.COMPLETED or state.winner is None or state.win_reason is None:
        raise AssertionError("synthetic game did not finish within 100 steps")
    return SimulationResult(
        player_count=player_count,
        winner=state.winner.value,
        win_reason=state.win_reason.value,
        round=state.round,
        operation_count=len(state.operations),
        revote_count=sum(operation.command == "RESOLVE_REVOTE" for operation in state.operations),
        final_accusation_target=state.final_accusation_target,
        signature=_signature(state),
    )


def simulate_games(*, runs_per_player_count: int = 100) -> dict[int, list[SimulationResult]]:
    """인원별로 같은 규칙을 여러 번 실행해 회귀 자료를 만든다."""

    if runs_per_player_count <= 0:
        raise ValueError("runs_per_player_count must be positive")
    return {
        player_count: [
            run_heuristic_game(player_count, f"b9-seed:{player_count}:{index}")
            for index in range(runs_per_player_count)
        ]
        for player_count in (6, 7, 8, 9)
    }
