"""재투표와 최종 승패의 순수 GameEngine 규칙 테스트."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.fallback import auto_vote_target
from backend.app.models.enums import GamePhase, GameStatus, NightActionType, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, PlayerState


def _state() -> tuple[GameState, list[PlayerState]]:
    """테스트에서 반복 사용하는 4인 시민 3명·마피아 1명 상태를 만든다."""

    players = [
        PlayerState(uuid4(), 1, PlayerRole.CITIZEN, display_name="human"),
        PlayerState(uuid4(), 2, PlayerRole.CITIZEN, display_name="citizen-2"),
        PlayerState(uuid4(), 3, PlayerRole.CITIZEN, display_name="citizen-3"),
        PlayerState(uuid4(), 4, PlayerRole.MAFIA, display_name="mafia"),
    ]
    return GameState(uuid4(), b"test", players, phase=GamePhase.DAY_VOTE), players


def test_tied_vote_moves_to_revote_then_eliminates_target() -> None:
    """첫 투표 동률은 재투표로, 재투표 단독 결과는 처형으로 전환한다."""

    state, players = _state()
    engine = GameEngine()
    engine.submit_vote(state, players[0].player_id, players[1].player_id)
    engine.submit_vote(state, players[1].player_id, players[2].player_id)
    engine.submit_vote(state, players[2].player_id, players[1].player_id)
    engine.submit_vote(state, players[3].player_id, players[2].player_id)
    engine.resolve_vote(state)
    assert state.phase is GamePhase.REVOTE
    assert all(player.alive for player in players)

    for actor in players:
        target = players[2].player_id if actor is players[1] else players[1].player_id
        engine.submit_vote(state, actor.player_id, target)
    engine.resolve_vote(state)
    assert not players[1].alive
    assert state.phase is GamePhase.NIGHT_ACTION
    assert state.revote_candidates == set()


def test_final_accusation_of_mafia_completes_for_citizens() -> None:
    """생존자 전원의 최종 고발을 모은 뒤 최다 득표가 마피아이면 시민이 승리한다."""

    state, players = _state()
    state.phase = GamePhase.FINAL_ACCUSATION
    engine = GameEngine()
    for actor in players:
        target = players[0] if actor is players[3] else players[3]
        engine.submit_final_accusation(state, actor.player_id, target.player_id)
    assert state.status is GameStatus.COMPLETED
    assert state.phase is GamePhase.ENDED
    assert state.winner is not None and state.winner.value == "CITIZEN"


def _revote_state():
    """좌석 2·3만 최다 득표하는 첫 투표를 실제 엔진 명령으로 만든다."""

    state, players = _state()
    engine = GameEngine()
    for actor, target in zip(players, [players[1], players[2], players[1], players[2]], strict=True):
        engine.submit_vote(state, actor.player_id, target.player_id)
    engine.resolve_vote(state)
    return state, players


def test_revote_keeps_only_tied_candidates_for_manual_and_automatic_votes():
    state, players = _revote_state()
    engine = GameEngine()
    candidates = {players[1].player_id, players[2].player_id}
    assert state.revote_candidates == candidates
    assert state.votes == {}
    with pytest.raises(RuleViolation, match="TARGET_INVALID"):
        engine.submit_vote(state, players[1].player_id, players[0].player_id)
    assert state.votes == {}
    with pytest.raises(RuleViolation, match="SELF_TARGET_INVALID"):
        engine.submit_vote(state, players[1].player_id, players[1].player_id)
    for actor in players:
        selected = auto_vote_target(state, actor)
        assert selected.player_id in candidates - {actor.player_id}
    engine.resolve_vote(state, force=True)
    assert all(player.alive for player in (players[0], players[3]))
    assert state.revote_candidates == set()


def test_final_accusation_waits_for_every_living_actor_and_rejects_duplicates():
    state, players = _state()
    state.phase = GamePhase.FINAL_ACCUSATION
    engine = GameEngine()
    engine.submit_final_accusation(state, players[0].player_id, players[3].player_id)
    assert state.phase is GamePhase.FINAL_ACCUSATION
    assert state.status is GameStatus.IN_PROGRESS
    assert state.final_accusation_target is None
    assert state.votes[players[0].player_id].target_id == players[3].player_id
    with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
        engine.submit_final_accusation(state, players[0].player_id, players[2].player_id)
    with pytest.raises(RuleViolation, match="WINDOW_NOT_READY"):
        engine.resolve_final_accusation(state)


@pytest.mark.parametrize("target_index", [0, 3])
def test_final_accusation_majority_determines_winner(target_index):
    state, players = _state()
    state.phase = GamePhase.FINAL_ACCUSATION
    engine = GameEngine()
    target = players[target_index]
    alternate = players[1]
    for actor in players:
        selected = alternate if actor is target else target
        engine.submit_final_accusation(state, actor.player_id, selected.player_id)
    assert state.final_accusation_target == target.player_id
    assert state.winner.value == ("CITIZEN" if target_index == 3 else "MAFIA")


def test_final_tie_is_seeded_and_independent_of_submission_order_and_replays():
    initial, players = _state()
    initial.phase = GamePhase.FINAL_ACCUSATION
    for index, player in enumerate(players, start=1):
        player.player_id = UUID(int=index)
    outcomes = set()
    for index in range(12):
        initial.seed = f"final-tie-{index}".encode()
        targets = [players[3], players[3], players[0], players[0]]
        results = []
        for order in (range(4), reversed(range(4))):
            state = deepcopy(initial)
            engine = GameEngine()
            for actor_index in order:
                engine.submit_final_accusation(
                    state, players[actor_index].player_id, targets[actor_index].player_id
                )
            assert state.phase is GamePhase.ENDED
            assert state.final_accusation_target in {players[0].player_id, players[3].player_id}
            replayed = GameEngine.replay(initial, state.operations)
            assert replayed.final_accusation_target == state.final_accusation_target
            assert replayed.winner == state.winner
            results.append(state.final_accusation_target)
        assert results[0] == results[1]
        outcomes.add(results[0])
    assert outcomes == {players[0].player_id, players[3].player_id}


def test_final_timeout_keeps_submitted_votes_fills_missing_and_replays():
    initial, players = _state()
    initial.phase = GamePhase.FINAL_ACCUSATION
    state = deepcopy(initial)
    engine = GameEngine()
    engine.submit_final_accusation(state, players[0].player_id, players[3].player_id)
    engine.resolve_final_accusation(state, force=True)
    assert state.status is GameStatus.COMPLETED
    assert state.votes[players[0].player_id].target_id == players[3].player_id
    assert set(state.votes) == {player.player_id for player in players}
    assert all(vote.actor_id != vote.target_id for vote in state.votes.values())
    replayed = GameEngine.replay(initial, state.operations)
    assert replayed.final_accusation_target == state.final_accusation_target
    assert replayed.votes == state.votes


@pytest.mark.parametrize("count", [6, 7, 8, 9])
def test_final_fast_forward_collects_every_vote(count):
    state = GameEngine.new_game(
        [(UUID(int=index), PlayerKind.AI) for index in range(1, count + 1)],
        seed=b"final-fast-forward",
    )
    state.phase = GamePhase.FINAL_ACCUSATION
    GameEngine().fast_forward(state)
    assert state.status is GameStatus.COMPLETED
    assert len(state.votes) == count


@pytest.mark.parametrize("invalid", ["self", "dead_target", "dead_actor", "missing_target"])
def test_final_accusation_rejects_invalid_submissions_without_recording_votes(invalid):
    state, players = _state()
    state.phase = GamePhase.FINAL_ACCUSATION
    actor = players[0]
    target_id = players[3].player_id
    if invalid == "self":
        target_id = actor.player_id
    elif invalid == "dead_target":
        players[3].alive = False
    elif invalid == "dead_actor":
        actor.alive = False
    else:
        target_id = UUID(int=999)
    before_version = state.state_version
    with pytest.raises(RuleViolation):
        GameEngine().submit_final_accusation(state, actor.player_id, target_id)
    assert state.votes == {}
    assert state.operations == []
    assert state.state_version == before_version
    assert state.status is GameStatus.IN_PROGRESS


def test_final_accusation_does_not_wait_for_a_dead_actor():
    state, players = _state()
    state.phase = GamePhase.FINAL_ACCUSATION
    players[2].alive = False
    engine = GameEngine()
    for actor in state.alive_players:
        target = players[0] if actor is players[3] else players[3]
        engine.submit_final_accusation(state, actor.player_id, target.player_id)
    assert state.status is GameStatus.COMPLETED
    assert players[2].player_id not in state.votes
    assert state.final_accusation_target == players[3].player_id


def test_missing_revote_candidates_are_not_expanded_to_all_players():
    state, players = _state()
    state.phase = GamePhase.REVOTE
    with pytest.raises(RuleViolation, match="TARGET_INVALID"):
        GameEngine().submit_vote(state, players[0].player_id, players[1].player_id)
    with pytest.raises(ValueError, match="no valid vote target"):
        auto_vote_target(state, players[0])
    assert state.votes == {}


@pytest.mark.parametrize("count", [6, 7, 8, 9])
def test_round_advances_on_night_entry_and_fifth_night_opens_final_discussion(count):
    """무탈락 다섯 밤을 실제 명령으로 진행해 round·재투표·최종 판정 경계를 검증한다."""

    initial = GameEngine.new_game(
        [(UUID(int=index), PlayerKind.AI) for index in range(1, count + 1)],
        seed=b"five-nights-round-boundary",
    )
    state = deepcopy(initial)
    engine = GameEngine()
    engine.begin_game(state)
    assert (state.round, state.day_number) == (0, 1)
    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)

    mafia = [player for player in state.players if player.role is PlayerRole.MAFIA]
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    detective = next(player for player in state.players if player.role is PlayerRole.DETECTIVE)
    protected = next(player for player in state.players if player.role is PlayerRole.CITIZEN)
    for night_number in range(1, 6):
        assert state.phase is GamePhase.NIGHT_ACTION
        assert (state.round, state.day_number) == (night_number, night_number)
        for actor in mafia:
            engine.submit_night_action(
                state, actor.player_id, NightActionType.ATTACK, protected.player_id
            )
        engine.submit_night_action(
            state, doctor.player_id, NightActionType.PROTECT, protected.player_id
        )
        engine.submit_night_action(
            state, detective.player_id, NightActionType.INVESTIGATE, mafia[0].player_id
        )
        assert state.round == night_number
        engine.resolve_night(state)
        assert (state.round, state.day_number) == (night_number, night_number + 1)
        assert len(state.alive_players) == count
        if night_number == 5:
            assert state.phase is GamePhase.FINAL_DISCUSSION
            break

        assert state.phase is GamePhase.DAY_DISCUSSION
        for player in state.alive_players:
            engine.pass_turn(state, player.player_id)
        assert state.phase is GamePhase.DAY_DISCUSSION
        assert state.speech_question_cycle_used is True
        assert state.round == night_number
        for player in state.alive_players:
            engine.pass_turn(state, player.player_id)
        assert state.phase is GamePhase.DAY_VOTE
        assert state.round == night_number

        # 인원수가 홀수여도 전원 한 표씩 받도록 순환 투표하여 탈락 없이 다음 밤으로 간다.
        for expected_phase in (GamePhase.DAY_VOTE, GamePhase.REVOTE):
            assert state.phase is expected_phase
            assert state.round == night_number
            for index, actor in enumerate(state.alive_players):
                target = state.alive_players[(index + 1) % count]
                engine.submit_vote(state, actor.player_id, target.player_id)
            engine.resolve_vote(state)
        assert state.revote_candidates == set()

    for player in state.alive_players:
        engine.pass_turn(state, player.player_id)
    assert state.phase is GamePhase.FINAL_ACCUSATION
    assert (state.round, state.day_number) == (5, 6)
    for actor in state.alive_players:
        target = protected if actor is mafia[0] else mafia[0]
        engine.submit_final_accusation(state, actor.player_id, target.player_id)
    assert state.phase is GamePhase.ENDED
    assert state.winner.value == "CITIZEN"
    assert len(state.votes) == count
    assert state.round == 5

    replayed = GameEngine.replay(initial, state.operations)
    assert (replayed.phase, replayed.round, replayed.day_number) == (GamePhase.ENDED, 5, 6)
    assert replayed.final_accusation_target == state.final_accusation_target
    assert replayed.votes == state.votes


def test_fifth_night_standard_victory_finishes_before_final_discussion():
    """다섯 번째 밤의 표준 승패를 우선하고 해소 후에도 밤 번호는 5로 유지한다."""

    state = GameEngine.new_game(
        [(UUID(int=index), PlayerKind.AI) for index in range(1, 7)],
        seed=b"fifth-night-victory",
    )
    state.phase = GamePhase.NIGHT_ACTION
    state.round = 5
    state.day_number = 5
    mafia = next(player for player in state.players if player.role is PlayerRole.MAFIA)
    doctor = next(player for player in state.players if player.role is PlayerRole.DOCTOR)
    target = next(player for player in state.players if player.role is PlayerRole.CITIZEN)
    for player in state.players:
        player.alive = player in [mafia, doctor, target]
    engine = GameEngine()
    engine.submit_night_action(state, mafia.player_id, NightActionType.ATTACK, target.player_id)
    engine.submit_night_action(state, doctor.player_id, NightActionType.PROTECT, doctor.player_id)

    engine.resolve_night(state)

    assert state.phase is GamePhase.ENDED
    assert state.status is GameStatus.COMPLETED
    assert state.winner.value == "MAFIA"
    assert state.win_reason.value == "MAFIA_PARITY"
    assert state.round == 5
