"""재투표와 최종 승패의 순수 GameEngine 규칙 테스트."""

from uuid import uuid4

from backend.app.game_engine.engine import GameEngine
from backend.app.models.enums import GamePhase, GameStatus, PlayerRole
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
        target = players[0].player_id if actor is players[1] else players[1].player_id
        engine.submit_vote(state, actor.player_id, target)
    engine.resolve_vote(state)
    assert not players[1].alive
    assert state.phase is GamePhase.NIGHT_ACTION


def test_final_accusation_of_mafia_completes_for_citizens() -> None:
    """최종 고발에서 마피아를 지목하면 시민 승리와 종료 상태를 기록한다."""

    state, players = _state()
    state.phase = GamePhase.FINAL_ACCUSATION
    GameEngine().submit_final_accusation(state, players[0].player_id, players[3].player_id)
    assert state.status is GameStatus.COMPLETED
    assert state.phase is GamePhase.ENDED
    assert state.winner is not None and state.winner.value == "CITIZEN"
