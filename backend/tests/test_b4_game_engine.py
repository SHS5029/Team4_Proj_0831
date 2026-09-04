"""B4 순수 게임 엔진 테스트."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.app.agent.game_engine import GameEngine, RuleViolation
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


def test_first_day_has_no_vote_and_all_pass_gets_one_extra_question_cycle():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"day-seed")
    engine.begin_game(state)
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.DAY_DISCUSSION
    assert state.speech_question_cycle_used is True
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.NIGHT_ACTION


def test_invalid_actor_target_and_duplicate_are_rejected():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"validation-seed")
    engine.begin_game(state)
    actor = state.players[0]
    engine.pass_turn(state, actor.player_id)
    with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
        engine.pass_turn(state, actor.player_id)
    with pytest.raises(RuleViolation, match="PLAYER_NOT_FOUND"):
        engine.pass_turn(state, UUID(int=999))


def test_night_resolution_uses_doctor_protection_and_detective_private_result():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"night-seed")
    engine.begin_game(state)
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
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


def test_one_mafia_submission_is_enough_when_two_mafia_are_alive():
    engine = GameEngine()
    state = GameEngine.new_game(players(8), seed=b"two-mafia-seed")
    engine.begin_game(state)
    for _ in range(2):
        for player in state.alive_players:
            engine.pass_turn(state, player.player_id)
    mafia = next(player for player in state.players if player.role is PlayerRole.MAFIA)
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
    target = next(player for player in state.players if player.role is PlayerRole.CITIZEN)
    engine.submit_night_action(state, mafia.player_id, NightActionType.ATTACK, target.player_id)
    engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, target.player_id)
    engine.submit_night_action(state, detective.player_id, NightActionType.INVESTIGATE, target.player_id)
    engine.resolve_night(state)
    assert state.phase is GamePhase.DAY_DISCUSSION


def test_day_vote_tie_uses_one_revote_then_no_execution():
    engine = GameEngine()
    state = GameEngine.new_game(players(6), seed=b"tie-seed")
    engine.begin_game(state)
    for _ in range(2):
        for player in state.alive_players:
            engine.pass_turn(state, player.player_id)
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


def test_final_discussion_one_cycle_moves_to_final_accusation():
    """다섯 번째 밤 이후 최종 토론은 추가 질문 없이 한 순환 뒤 마지막 지목으로 간다."""

    engine = GameEngine()
    state = GameEngine.new_game(players(6, human=1), seed=b"final-discussion-seed")
    state.phase = GamePhase.FINAL_DISCUSSION

    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)

    assert state.phase is GamePhase.FINAL_ACCUSATION
