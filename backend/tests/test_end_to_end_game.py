"""B9 synthetic 전체 게임·결정성 회귀 테스트."""

from backend.tests.simulations.heuristic_game import run_heuristic_game, simulate_games


def test_b9_heuristic_bot_completes_100_games_per_roster_size() -> None:
    """6~9명 각각 100판이 모두 종료되고 유효한 승패를 남기는지 확인한다."""

    reports = simulate_games(runs_per_player_count=100)
    assert set(reports) == {6, 7, 8, 9}
    for player_count, results in reports.items():
        assert len(results) == 100
        assert all(result.player_count == player_count for result in results)
        assert all(result.winner in {"CITIZEN", "MAFIA"} for result in results)
        assert all(0 <= result.round <= 5 for result in results)
        assert all(result.operation_count > 0 for result in results)


def test_b9_same_seed_reproduces_roles_targets_and_winner() -> None:
    """같은 seed는 시간값과 관계없이 같은 규칙 결과를 재생산해야 한다."""

    first = run_heuristic_game(9, "b9-deterministic-seed")
    second = run_heuristic_game(9, "b9-deterministic-seed")
    assert first.signature == second.signature
