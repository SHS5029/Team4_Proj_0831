"""B4 순수 게임 엔진 테스트."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.fallback import auto_night_target, auto_vote_target
from backend.app.game_engine.phases import night as night_phase
from backend.app.models.enums import GamePhase, GameStatus, NightActionType, PlayerKind, PlayerRole


IDS = [UUID(int=index) for index in range(1, 10)]


def players(count: int, human: int = 0):
    return [(player_id, PlayerKind.HUMAN if index < human else PlayerKind.AI) for index, player_id in enumerate(IDS[:count])]


@pytest.mark.parametrize("count, expected_mafia", [(6, 1), (7, 1), (8, 2), (9, 2)])
def test_role_counts_match_canonical_table(count, expected_mafia):
    state = GameEngine.new_game(players(count), seed=b"b4-fixed-seed")
    assert sum(player.role is PlayerRole.MAFIA for player in state.players) == expected_mafia
    assert sum(player.role is PlayerRole.DETECTIVE for player in state.players) == 1
    assert sum(player.role is PlayerRole.DOCTOR for player in state.players) == 1


def test_same_seed_repeats_role_assignment_and_different_seed_changes_it():
    first = GameEngine.new_game(players(9), seed=b"same-seed")
    second = GameEngine.new_game(players(9), seed=b"same-seed")
    other = GameEngine.new_game(players(9), seed=b"other-seed")
    assert [player.role for player in first.players] == [player.role for player in second.players]
    assert [player.role for player in first.players] != [player.role for player in other.players]


@pytest.mark.parametrize("kind", [PlayerKind.HUMAN, PlayerKind.AI])
def test_first_day_rejects_pass_without_changing_state(kind):
    """첫날 PASS 거부는 인간·AI 모두의 상태 버전과 원장을 보존해야 한다."""

    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"day-seed")
    engine.begin_game(state)
    state.players[0].kind = kind
    before = deepcopy(state)
    with pytest.raises(RuleViolation, match="ACTION_NOT_ALLOWED"):
        engine.pass_turn(state, state.players[0].player_id)
    assert state == before


def test_first_day_moves_to_night_after_one_speech_cycle():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"day-seed")
    engine.begin_game(state)
    assert state.round == 0
    for player in state.alive_players:
        engine.speak(state, player.player_id, "앞으로 나온 주장을 비교해 볼게.")
    assert state.phase is GamePhase.NIGHT_ACTION
    assert state.round == 1


def test_invalid_actor_target_and_duplicate_are_rejected():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"validation-seed")
    engine.begin_game(state)
    actor = state.players[0]
    engine.speak(state, actor.player_id, "공개 주장을 비교해 볼게.")
    with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
        engine.pass_turn(state, actor.player_id)
    with pytest.raises(RuleViolation, match="PLAYER_NOT_FOUND"):
        engine.pass_turn(state, UUID(int=999))


def test_night_resolution_uses_doctor_protection_and_detective_private_result():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"night-seed")
    engine.begin_game(state)
    for player in state.alive_players:
        engine.speak(state, player.player_id, "공개 주장을 비교해 볼게.")
    mafia = next(player for player in state.players if player.role is PlayerRole.MAFIA)
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
    protected = next(player for player in state.players if player.player_id not in {mafia.player_id, doctor.player_id})
    engine.submit_night_action(state, mafia.player_id, NightActionType.ATTACK, protected.player_id)
    engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, protected.player_id)
    engine.submit_night_action(state, detective.player_id, NightActionType.INVESTIGATE, mafia.player_id)
    engine.resolve_night(state)
    assert protected.alive is True
    assert state.last_detective_result[detective.player_id] is True


def test_one_mafia_submission_waits_for_deadline_when_two_mafia_are_alive():
    engine = GameEngine()
    state = GameEngine.new_game(players(8), seed=b"two-mafia-seed")
    engine.begin_game(state)
    for player in state.alive_players:
        engine.speak(state, player.player_id, "공개 주장을 비교해 볼게.")
    mafia = next(player for player in state.players if player.role is PlayerRole.MAFIA)
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
    target = next(player for player in state.players if player.role is PlayerRole.CITIZEN)
    engine.submit_night_action(state, mafia.player_id, NightActionType.ATTACK, target.player_id)
    engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, target.player_id)
    engine.submit_night_action(state, detective.player_id, NightActionType.INVESTIGATE, target.player_id)
    with pytest.raises(RuleViolation, match="WINDOW_NOT_READY"):
        engine.resolve_night(state)
    engine.resolve_night(state, force=True)
    assert state.phase is GamePhase.DAY_DISCUSSION
    assert all(player.alive for player in state.players)


def test_day_vote_tie_uses_one_revote_then_no_execution():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"tie-seed")
    engine.begin_game(state)
    for player in state.alive_players:
        engine.speak(state, player.player_id, "공개 주장을 비교해 볼게.")
    mafia = next(player for player in state.players if player.role is PlayerRole.MAFIA)
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
    target = next(player for player in state.players if player.role is PlayerRole.CITIZEN)
    engine.submit_night_action(state, mafia.player_id, NightActionType.ATTACK, target.player_id)
    engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, target.player_id)
    engine.submit_night_action(state, detective.player_id, NightActionType.INVESTIGATE, target.player_id)
    engine.resolve_night(state)
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.DAY_DISCUSSION
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)

    first, second = state.alive_players[:2]
    for index, actor in enumerate(state.alive_players):
        if actor.player_id == first.player_id:
            vote_target = second
        elif actor.player_id == second.player_id:
            vote_target = first
        else:
            vote_target = first if index % 2 == 0 else second
        engine.submit_vote(state, actor.player_id, vote_target.player_id)
    engine.resolve_vote(state)
    assert state.phase is GamePhase.REVOTE
    for index, actor in enumerate(state.alive_players):
        if actor.player_id == first.player_id:
            vote_target = second
        elif actor.player_id == second.player_id:
            vote_target = first
        else:
            vote_target = first if index % 2 == 0 else second
        engine.submit_vote(state, actor.player_id, vote_target.player_id)
    engine.resolve_vote(state)
    assert state.phase is GamePhase.NIGHT_ACTION
    assert all(player.alive for player in state.players)


def test_save_resume_keeps_roles_and_rejects_fast_forward_when_human_alive():
    engine = GameEngine()
    state = GameEngine.new_game(players(6, human=1), seed=b"save-seed")
    original_roles = [player.role for player in state.players]
    engine.save(state, 20_000)
    assert state.status is GameStatus.SAVED
    assert state.deadline_at is None
    engine.resume(state)
    assert state.status is GameStatus.IN_PROGRESS
    assert [player.role for player in state.players] == original_roles
    with pytest.raises(RuleViolation, match="FAST_FORWARD_NOT_ALLOWED"):
        engine.fast_forward(state)


def test_save_resume_without_deadline_keeps_a_windowless_state_untimed():
    """발언·ROLE_REVEAL처럼 시간이 없는 저장 상태는 deadline 없이 다시 연다."""

    engine = GameEngine()
    state = GameEngine.new_game(players(6, human=1), seed=b"untimed-save-seed")
    engine.save(state, None)

    engine.resume(state, now=datetime(2026, 1, 1, tzinfo=UTC))

    assert state.status is GameStatus.IN_PROGRESS
    assert state.remaining_ms_on_save is None
    assert state.deadline_at is None


def test_fast_forward_flag_is_independent_of_human_death_and_survives_save_resume():
    """사망은 빠른 진행 동의가 아니며 저장·재개도 이미 정해진 설정을 바꾸지 않는다."""

    engine = GameEngine()
    state = GameEngine.new_game(players(6, human=1), seed=b"fast-forward-state")
    assert state.fast_forward_enabled is False
    state.players[0].alive = False
    assert state.human_alive is False
    assert state.fast_forward_enabled is False

    state.fast_forward_enabled = True
    engine.save(state, None)
    assert state.fast_forward_enabled is True
    engine.resume(state, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert state.fast_forward_enabled is True


def test_final_discussion_one_cycle_moves_to_final_accusation():
    """다섯 번째 밤 이후 최종 토론은 추가 질문 없이 한 순환 뒤 마지막 지목으로 간다."""

    engine = GameEngine()
    state = GameEngine.new_game(players(6, human=1), seed=b"final-discussion-seed")
    state.phase = GamePhase.FINAL_DISCUSSION

    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)

    assert state.phase is GamePhase.FINAL_ACCUSATION


def _night_state(seed=b"two-mafia-regression"):
    """다른 phase 진행에 의존하지 않고 두 마피아의 밤 선택을 검증한다."""

    state = GameEngine.new_game(players(8), seed=seed)
    state.phase = GamePhase.NIGHT_ACTION
    state.round = 1
    return state


@pytest.mark.parametrize("same_target", [True, False])
def test_two_mafia_choices_are_accepted_and_resolution_ignores_arrival_order(same_target):
    initial = _night_state()
    mafia = [player for player in initial.players if player.role is PlayerRole.MAFIA]
    targets = [player for player in initial.players if player.role is PlayerRole.CITIZEN]
    choices = [targets[0], targets[0] if same_target else targets[1]]
    outcomes = []
    for order in ([0, 1], [1, 0]):
        state = deepcopy(initial)
        engine = GameEngine()
        for index in order:
            engine.submit_night_action(
                state, mafia[index].player_id, NightActionType.ATTACK, choices[index].player_id
            )
        with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
            engine.submit_night_action(
                state, mafia[0].player_id, NightActionType.ATTACK, targets[2].player_id
            )
        doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
        detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
        engine.submit_night_action(
            state, doctor.player_id, NightActionType.PROTECT, doctor.player_id
        )
        engine.submit_night_action(
            state, detective.player_id, NightActionType.INVESTIGATE, mafia[0].player_id
        )
        engine.resolve_night(state)
        dead = {player.player_id for player in state.players if not player.alive}
        assert len(dead) == 1
        assert dead <= {target.player_id for target in choices}
        assert state.last_detective_result[detective.player_id] is True
        replayed = GameEngine.replay(initial, state.operations)
        assert {player.player_id for player in replayed.players if not player.alive} == dead
        outcomes.append(dead)
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("responding_mafia_index", [0, 1])
def test_partial_mafia_timeout_preserves_the_only_submitted_choice(responding_mafia_index):
    state = _night_state()
    engine = GameEngine()
    mafia = [player for player in state.players if player.role is PlayerRole.MAFIA]
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
    target = next(player for player in state.players if player.role is PlayerRole.CITIZEN)
    engine.submit_night_action(
        state, mafia[responding_mafia_index].player_id, NightActionType.ATTACK, target.player_id
    )
    engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, doctor.player_id)
    engine.submit_night_action(
        state, detective.player_id, NightActionType.INVESTIGATE, mafia[0].player_id
    )
    with pytest.raises(RuleViolation, match="WINDOW_NOT_READY"):
        engine.resolve_night(state)
    engine.resolve_night(state, force=True)
    assert {player.player_id for player in state.players if not player.alive} == {target.player_id}


def test_all_mafia_timeout_chooses_one_non_mafia_target():
    for index in range(24):
        state = _night_state(f"mafia-timeout-{index}".encode())
        engine = GameEngine()
        doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
        engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, doctor.player_id)
        engine.resolve_night(state, force=True)
        assert all(player.alive for player in state.players if player.role is PlayerRole.MAFIA)
        assert sum(not player.alive for player in state.players) <= 1


def test_automatic_protection_excludes_self_but_manual_protection_allows_self():
    for index in range(24):
        state = _night_state(f"doctor-timeout-{index}".encode())
        doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
        assert auto_night_target(state, doctor, NightActionType.PROTECT).player_id != doctor.player_id
        GameEngine().submit_night_action(
            state, doctor.player_id, NightActionType.PROTECT, doctor.player_id
        )
        assert state.night_actions[doctor.player_id].target_id == doctor.player_id


def test_automatic_votes_do_not_change_when_hidden_roles_change():
    state = GameEngine.new_game(players(6), seed=b"role-blind-vote")
    state.phase = GamePhase.DAY_VOTE
    actor = state.players[0]
    state.players[-1].alive = False
    for player in state.players:
        player.role = PlayerRole.CITIZEN
    selected = auto_vote_target(state, actor)
    assert selected.alive and selected.player_id != actor.player_id
    selected.role = PlayerRole.MAFIA
    assert auto_vote_target(state, actor).player_id == selected.player_id


def test_later_day_all_pass_allows_exactly_one_additional_cycle():
    state = GameEngine.new_game(players(6), seed=b"all-pass-follow-up")
    state.phase = GamePhase.DAY_DISCUSSION
    state.day_number = 2
    engine = GameEngine()
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.DAY_DISCUSSION
    assert state.speech_question_cycle_used is True
    assert state.speech_actors == set()
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.DAY_VOTE


def test_later_day_with_speech_does_not_add_a_cycle():
    state = GameEngine.new_game(players(6), seed=b"all-pass-follow-up")
    state.phase = GamePhase.DAY_DISCUSSION
    state.day_number = 2
    engine = GameEngine()
    engine.speak(state, state.players[0].player_id, "아직 단서가 부족합니다.")
    for player in state.alive_players[1:]:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.DAY_VOTE


def test_new_day_resets_discussion_cycle_flags():
    state = _night_state()
    state.speech_question_cycle_used = True
    state.speech_had_content = True
    GameEngine().resolve_night(state, force=True)
    assert state.phase is GamePhase.DAY_DISCUSSION
    assert state.speech_question_cycle_used is False
    assert state.speech_had_content is False


def test_all_mafia_timeout_draws_once_for_the_faction(monkeypatch):
    state = _night_state()
    calls = []

    def record_selection(current, actor, action_type):
        """실제 선택은 유지하고 진영 자동 공격이 중복 추첨되는지만 관찰한다."""

        target = auto_night_target(current, actor, action_type)
        calls.append((action_type, target.player_id))
        return target

    monkeypatch.setattr(night_phase, "auto_night_target", record_selection)
    GameEngine().resolve_night(state, force=True)
    attacks = [target for action, target in calls if action is NightActionType.ATTACK]
    assert len(attacks) == 1
    assert state.player_by_id[attacks[0]].role is not PlayerRole.MAFIA
