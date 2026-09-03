"""AI Mafia의 외부 서비스 없는 순수 규칙 엔진.

이 엔진은 DB, Redis, LLM, MCP를 호출하지 않는다. 하나의 명령을 검증하고 상태를
바꾸는 역할만 하며, 실제 저장·event·transaction 연결은 다음 Backend WU에서
서비스 계층이 담당한다. 따라서 이 파일만으로도 고정 seed 전체 replay가 가능하다.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from backend.app.agent.fallback import auto_night_target, auto_vote_target
from backend.app.agent.rng import DeterministicRng, generate_seed
from backend.app.agent.state_machine import (
    after_night,
    after_vote,
    check_standard_winner,
    finish_game,
    touch,
)
from backend.app.models.enums import (
    Faction,
    GamePhase,
    GameStatus,
    NightActionType,
    PlayerKind,
    PlayerRole,
    WinReason,
)
from backend.app.models.game_state import EngineOperation, GameState, NightAction, PlayerState, Vote


class RuleViolation(ValueError):
    """사용자 명령이 현재 게임 규칙에 맞지 않을 때 발생한다."""


ROLE_COUNTS: dict[int, tuple[int, int, int, int]] = {
    6: (1, 1, 1, 3),
    7: (1, 1, 1, 4),
    8: (2, 1, 1, 4),
    9: (2, 1, 1, 5),
}
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class GameEngine:
    """명령을 순서대로 적용하는 게임 엔진."""

    @classmethod
    def new_game(
        cls,
        players: list[tuple[UUID, PlayerKind]] | list[PlayerState],
        *,
        seed: bytes | str | None = None,
        game_id: UUID | None = None,
    ) -> GameState:
        """6~9명에게 seed 기반 역할을 배정해 ROLE_REVEAL 상태를 만든다."""

        if not 6 <= len(players) <= 9:
            raise RuleViolation("PLAYER_COUNT_INVALID")
        seed_bytes = seed.encode("utf-8") if isinstance(seed, str) else seed or generate_seed()
        source: list[PlayerState] = []
        for seat, item in enumerate(players, start=1):
            if isinstance(item, PlayerState):
                source.append(copy.copy(item))
                source[-1].seat = seat
            else:
                player_id, kind = item
                source.append(PlayerState(player_id=player_id, seat=seat, role=PlayerRole.CITIZEN, kind=kind))

        mafia, detective, doctor, citizen = ROLE_COUNTS[len(source)]
        roles = (
            [PlayerRole.MAFIA] * mafia
            + [PlayerRole.DETECTIVE] * detective
            + [PlayerRole.DOCTOR] * doctor
            + [PlayerRole.CITIZEN] * citizen
        )
        shuffled = DeterministicRng(seed_bytes).shuffle(source, "role-assignment")
        for player, role in zip(shuffled, roles):
            player.role = role
        # 역할 배정 순서와 좌석은 별개다. 공개 화면의 좌석은 생성 입력 순서를 유지한다.
        ordered = sorted(shuffled, key=lambda player: player.seat)
        return GameState(game_id=game_id or uuid4(), seed=seed_bytes, players=ordered)

    @classmethod
    def replay(
        cls,
        initial: GameState,
        operations: list[EngineOperation],
    ) -> GameState:
        """초기 상태의 복사본에 명령 기록을 재생한다.

        replay 입력은 서버가 검증해 만든 내부 기록만 받아야 한다. 클라이언트가
        임의로 만든 operation을 신뢰하거나 DB에 바로 반영하는 용도로 사용하지 않는다.
        """

        state = copy.deepcopy(initial)
        state.operations.clear()
        engine = cls()
        for operation in operations:
            if operation.command == "BEGIN_GAME":
                engine.begin_game(state)
            elif operation.command == "SPEAK":
                engine.speak(state, operation.actor_id, operation.text or "")
            elif operation.command == "PASS":
                engine.pass_turn(state, operation.actor_id)
            elif operation.command == "SUBMIT_NIGHT_ACTION":
                if operation.target_id is None:
                    raise RuleViolation("TARGET_REQUIRED")
                action = engine._role_action(state, operation.actor_id)
                engine.submit_night_action(state, operation.actor_id, action, operation.target_id)
            elif operation.command == "SUBMIT_VOTE":
                if operation.target_id is None:
                    raise RuleViolation("TARGET_REQUIRED")
                engine.submit_vote(state, operation.actor_id, operation.target_id)
            elif operation.command == "RESOLVE_NIGHT":
                engine.resolve_night(state, force=True)
            elif operation.command == "RESOLVE_VOTE":
                engine.resolve_vote(state, force=True)
            elif operation.command == "RESOLVE_REVOTE":
                engine.resolve_vote(state, force=True)
            elif operation.command == "SAVE_AND_EXIT":
                engine.save(state, state.remaining_ms_on_save or 0)
            elif operation.command == "RESUME":
                engine.resume(state)
            elif operation.command == "FINAL_DISCUSSION":
                engine.advance_final_discussion(state)
            elif operation.command == "FINAL_ACCUSATION":
                if operation.target_id is None:
                    raise RuleViolation("TARGET_REQUIRED")
                engine.submit_final_accusation(state, operation.actor_id, operation.target_id)
            else:
                raise RuleViolation("REPLAY_COMMAND_INVALID")
        return state

    def _player(self, state: GameState, player_id: UUID | None) -> PlayerState:
        if player_id is None or player_id not in state.player_by_id:
            raise RuleViolation("PLAYER_NOT_FOUND")
        return state.player_by_id[player_id]

    def _alive_actor(self, state: GameState, actor_id: UUID | None) -> PlayerState:
        actor = self._player(state, actor_id)
        if not actor.alive:
            raise RuleViolation("PLAYER_DEAD")
        return actor

    def _record(self, state: GameState, command: str, actor_id: UUID | None = None, **kwargs: object) -> None:
        state.operations.append(
            EngineOperation(command=command, actor_id=actor_id, result_state_version=state.state_version, **kwargs)
        )

    def _advance_if_speeches_done(self, state: GameState) -> None:
        """생존자 발언이 끝났을 때 첫날 예외 또는 다음 phase를 적용한다."""

        alive_ids = {player.player_id for player in state.alive_players}
        if self._speech_pending(state, alive_ids):
            return
        if (
            state.day_number == 1
            and not state.speech_question_cycle_used
            and not state.speech_had_content
        ):
            state.speech_question_cycle_used = True
            state.speech_actors.clear()
            state.speech_had_content = False
            return
        state.phase = GamePhase.NIGHT_ACTION if state.day_number == 1 else GamePhase.DAY_VOTE
        state.speech_actors.clear()

    def _speech_pending(self, state: GameState, alive_ids: set[UUID]) -> bool:
        return alive_ids - state.speech_actors != set()

    def begin_game(self, state: GameState) -> GameState:
        """역할 공개 화면을 끝내고 첫날 토론을 시작한다."""

        if state.status is not GameStatus.IN_PROGRESS or state.phase is not GamePhase.ROLE_REVEAL:
            raise RuleViolation("INVALID_PHASE")
        state.phase = GamePhase.DAY_DISCUSSION
        touch(state)
        self._record(state, "BEGIN_GAME")
        return state

    def speak(self, state: GameState, actor_id: UUID | None, text: str) -> GameState:
        """생존 플레이어의 발언을 1~200자로 정규화해 처리한다."""

        if state.phase is not GamePhase.DAY_DISCUSSION:
            raise RuleViolation("INVALID_PHASE")
        actor = self._alive_actor(state, actor_id)
        if actor.player_id in state.speech_actors:
            raise RuleViolation("DUPLICATE_ACTION")
        normalized = self.normalize_speech(text)
        state.speech_actors.add(actor.player_id)
        state.speech_had_content = True
        touch(state)
        self._advance_if_speeches_done(state)
        self._record(state, "SPEAK", actor.player_id, text=normalized)
        return state

    def pass_turn(self, state: GameState, actor_id: UUID | None) -> GameState:
        """발언하지 않고 PASS한 것으로 처리한다."""

        if state.phase is not GamePhase.DAY_DISCUSSION:
            raise RuleViolation("INVALID_PHASE")
        actor = self._alive_actor(state, actor_id)
        if actor.player_id in state.speech_actors:
            raise RuleViolation("DUPLICATE_ACTION")
        state.speech_actors.add(actor.player_id)
        touch(state)
        self._advance_if_speeches_done(state)
        self._record(state, "PASS", actor.player_id)
        return state

    @staticmethod
    def normalize_speech(text: str) -> str:
        """제어문자를 제거하고 Unicode NFC·공백 규칙을 적용한다."""

        import unicodedata

        normalized = unicodedata.normalize("NFC", str(text))
        normalized = _CONTROL_RE.sub(" ", normalized)
        normalized = " ".join(normalized.split())
        if not 1 <= len(normalized) <= 200:
            raise RuleViolation("SPEECH_LENGTH_INVALID")
        return normalized

    def _role_action(self, state: GameState, actor_id: UUID | None) -> NightActionType:
        actor = self._player(state, actor_id)
        actions = {
            PlayerRole.MAFIA: NightActionType.ATTACK,
            PlayerRole.DETECTIVE: NightActionType.INVESTIGATE,
            PlayerRole.DOCTOR: NightActionType.PROTECT,
        }
        try:
            return actions[actor.role]
        except KeyError as exc:
            # 시민은 밤 행동을 제출할 수 없다. 기본값으로 ATTACK을 주면
            # 시민이 마피아 행동을 위조할 수 있으므로 명시적으로 거부한다.
            raise RuleViolation("ROLE_ACTION_NOT_ALLOWED") from exc

    @staticmethod
    def _required_night_actors(state: GameState) -> list[PlayerState]:
        """밤 해소에 필요한 대표 제출자를 반환한다.

        마피아가 여러 명이어도 진영 공격은 첫 번째 유효 제출 하나면 충분하다.
        나머지 마피아의 미제출 때문에 창이 영원히 끝나지 않도록 대표 마피아만
        required 목록에 넣고, force 해소 때도 같은 규칙을 사용한다.
        """

        living = state.alive_players
        actors: list[PlayerState] = []
        mafia = next((player for player in living if player.role is PlayerRole.MAFIA), None)
        if mafia:
            actors.append(mafia)
        actors.extend(
            player
            for player in living
            if player.role in {PlayerRole.DETECTIVE, PlayerRole.DOCTOR}
        )
        return actors

    def submit_night_action(
        self,
        state: GameState,
        actor_id: UUID | None,
        action_type: NightActionType,
        target_id: UUID,
    ) -> GameState:
        """역할에 맞는 밤 행동을 첫 유효 제출만 저장한다."""

        if state.phase is not GamePhase.NIGHT_ACTION:
            raise RuleViolation("INVALID_PHASE")
        actor = self._alive_actor(state, actor_id)
        expected = self._role_action(state, actor.player_id)
        if expected is not action_type:
            raise RuleViolation("ROLE_ACTION_INVALID")
        if actor.player_id in state.night_actions:
            raise RuleViolation("DUPLICATE_ACTION")
        target = self._player(state, target_id)
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
        self._record(state, "SUBMIT_NIGHT_ACTION", actor.player_id, target_id=target_id)
        return state

    def resolve_night(self, state: GameState, *, force: bool = False) -> GameState:
        """밤 행동을 모으고 내부 NIGHT_RESOLUTION을 거쳐 다음 phase로 이동한다."""

        if state.phase is not GamePhase.NIGHT_ACTION:
            raise RuleViolation("INVALID_PHASE")
        required = self._required_night_actors(state)
        if not force and any(player.player_id not in state.night_actions for player in required):
            raise RuleViolation("WINDOW_NOT_READY")
        for actor in required:
            if actor.player_id in state.night_actions:
                continue
            action_type = self._role_action(state, actor.player_id)
            target = auto_night_target(state, actor, action_type)
            state.night_actions[actor.player_id] = NightAction(actor.player_id, action_type, target.player_id)

        attack = next(
            (action for action in state.night_actions.values() if action.action_type is NightActionType.ATTACK),
            None,
        )
        protection = next(
            (action for action in state.night_actions.values() if action.action_type is NightActionType.PROTECT),
            None,
        )
        if attack and (not protection or protection.target_id != attack.target_id):
            self._eliminate(state, attack.target_id)
        for action in state.night_actions.values():
            if action.action_type is NightActionType.INVESTIGATE:
                target = self._player(state, action.target_id)
                state.last_detective_result[action.actor_id] = target.role is PlayerRole.MAFIA
        state.round += 1
        state.night_actions.clear()
        touch(state)
        after_night(state)
        self._record(state, "RESOLVE_NIGHT")
        return state

    def submit_vote(self, state: GameState, actor_id: UUID | None, target_id: UUID) -> GameState:
        """낮 투표 또는 재투표에서 유효한 첫 표를 저장한다."""

        if state.phase not in {GamePhase.DAY_VOTE, GamePhase.REVOTE}:
            raise RuleViolation("INVALID_PHASE")
        actor = self._alive_actor(state, actor_id)
        if actor.player_id in state.votes:
            raise RuleViolation("DUPLICATE_ACTION")
        target = self._player(state, target_id)
        if not target.alive:
            raise RuleViolation("TARGET_DEAD")
        if actor.player_id == target.player_id:
            raise RuleViolation("SELF_TARGET_INVALID")
        state.votes[actor.player_id] = Vote(actor.player_id, target_id)
        touch(state)
        self._record(state, "SUBMIT_VOTE", actor.player_id, target_id=target_id)
        return state

    def resolve_vote(self, state: GameState, *, force: bool = False) -> GameState:
        """표를 집계하고 동률이면 한 번만 REVOTE로 전환한다."""

        if state.phase not in {GamePhase.DAY_VOTE, GamePhase.REVOTE}:
            raise RuleViolation("INVALID_PHASE")
        vote_phase = state.phase
        alive = state.alive_players
        if not force and any(player.player_id not in state.votes for player in alive):
            raise RuleViolation("WINDOW_NOT_READY")
        for actor in alive:
            if actor.player_id not in state.votes:
                target = auto_vote_target(state, actor)
                state.votes[actor.player_id] = Vote(actor.player_id, target.player_id)
        counts = Counter(vote.target_id for vote in state.votes.values())
        highest = max(counts.values()) if counts else 0
        leaders = [target_id for target_id, count in counts.items() if count == highest]
        if len(leaders) > 1 and state.phase is GamePhase.DAY_VOTE:
            state.phase = GamePhase.REVOTE
            state.votes.clear()
            touch(state)
            self._record(state, "RESOLVE_VOTE")
            return state
        if len(leaders) == 1:
            self._eliminate(state, leaders[0])
        state.votes.clear()
        touch(state)
        after_vote(state)
        self._record(
            state,
            "RESOLVE_REVOTE" if vote_phase is GamePhase.REVOTE else "RESOLVE_VOTE",
        )
        return state

    def advance_final_discussion(self, state: GameState) -> GameState:
        """다섯 번째 밤 뒤 최종 토론을 최종 고발 단계로 넘긴다."""

        if state.phase is not GamePhase.FINAL_DISCUSSION:
            raise RuleViolation("INVALID_PHASE")
        state.phase = GamePhase.FINAL_ACCUSATION
        touch(state)
        self._record(state, "FINAL_DISCUSSION")
        return state

    def submit_final_accusation(self, state: GameState, actor_id: UUID | None, target_id: UUID) -> GameState:
        """최종 고발 대상을 확정하고 고발 결과로 게임을 끝낸다."""

        if state.phase is not GamePhase.FINAL_ACCUSATION:
            raise RuleViolation("INVALID_PHASE")
        actor = self._alive_actor(state, actor_id)
        target = self._player(state, target_id)
        if not target.alive or target.player_id == actor.player_id:
            raise RuleViolation("TARGET_INVALID")
        if state.final_accusation_target is not None:
            raise RuleViolation("DUPLICATE_ACTION")
        state.final_accusation_target = target_id
        winner = Faction.CITIZEN if target.role is PlayerRole.MAFIA else Faction.MAFIA
        reason = (
            WinReason.FINAL_MAFIA_SELECTED
            if target.role is PlayerRole.MAFIA
            else WinReason.FINAL_NON_MAFIA_SELECTED
        )
        touch(state)
        finish_game(state, winner, reason)
        self._record(state, "FINAL_ACCUSATION", actor.player_id, target_id=target_id)
        return state

    def save(self, state: GameState, remaining_ms: int) -> GameState:
        """저장 시 deadline을 멈추고 남은 시간만 보관한다."""

        if state.status is not GameStatus.IN_PROGRESS:
            raise RuleViolation("GAME_NOT_IN_PROGRESS")
        if remaining_ms < 0:
            raise RuleViolation("REMAINING_TIME_INVALID")
        state.status = GameStatus.SAVED
        state.remaining_ms_on_save = remaining_ms
        state.deadline_at = None
        touch(state)
        self._record(state, "SAVE_AND_EXIT")
        return state

    def resume(self, state: GameState, now: datetime | None = None) -> GameState:
        """저장된 게임의 timed window만 새로 시작한다."""

        if state.status is not GameStatus.SAVED or state.remaining_ms_on_save is None:
            raise RuleViolation("GAME_NOT_SAVED")
        current = now or datetime.now(timezone.utc)
        state.status = GameStatus.IN_PROGRESS
        state.deadline_at = current + timedelta(milliseconds=state.remaining_ms_on_save)
        state.remaining_ms_on_save = None
        touch(state)
        self._record(state, "RESUME")
        return state

    def fast_forward(self, state: GameState) -> GameState:
        """인간이 사망한 게임을 AI fallback만으로 자동 진행한다."""

        if state.human_alive:
            raise RuleViolation("FAST_FORWARD_NOT_ALLOWED")
        for _ in range(100):
            if state.status is GameStatus.COMPLETED:
                return state
            if state.phase is GamePhase.ROLE_REVEAL:
                self.begin_game(state)
            elif state.phase is GamePhase.DAY_DISCUSSION:
                for player in state.alive_players:
                    if player.player_id not in state.speech_actors:
                        self.pass_turn(state, player.player_id)
            elif state.phase is GamePhase.NIGHT_ACTION:
                self.resolve_night(state, force=True)
            elif state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE}:
                self.resolve_vote(state, force=True)
            elif state.phase is GamePhase.FINAL_DISCUSSION:
                self.advance_final_discussion(state)
            elif state.phase is GamePhase.FINAL_ACCUSATION:
                actor = state.alive_players[0]
                target = next(player for player in state.alive_players if player.player_id != actor.player_id)
                self.submit_final_accusation(state, actor.player_id, target.player_id)
            else:
                raise RuleViolation("FAST_FORWARD_PHASE_INVALID")
        raise RuleViolation("FAST_FORWARD_STEP_LIMIT")

    @staticmethod
    def _eliminate(state: GameState, target_id: UUID) -> None:
        """대상을 사망 처리한다. 이미 죽은 대상은 다시 처리하지 않는다."""

        target = state.player_by_id.get(target_id)
        if target is None or not target.alive:
            raise RuleViolation("TARGET_DEAD")
        target.alive = False
