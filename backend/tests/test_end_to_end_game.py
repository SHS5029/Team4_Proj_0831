"""B9 synthetic 전체 게임·결정성 회귀 테스트."""

from collections import Counter

from backend.tests.simulations.heuristic_game import run_heuristic_game, simulate_games


def test_b9_heuristic_bot_completes_100_games_per_roster_size() -> None:
    """6~9명 각각 100판이 모두 종료되고 유효한 승패를 남기는지 확인한다."""

    reports = simulate_games(runs_per_player_count=100)
    assert set(reports) == {6, 7, 8, 9}
    for player_count, results in reports.items():
        assert len(results) == 100
        assert all(result.player_count == player_count for result in results)
        assert all(result.winner in {"CITIZEN", "MAFIA"} for result in results)
        assert all(1 <= result.round <= 5 for result in results)
        assert all(result.operation_count > 0 for result in results)
        assert {result.winner for result in results} == {"CITIZEN", "MAFIA"}
        assert sum(result.revote_count for result in results) > 0
        for result in results:
            assert result.win_reason in {
                "ALL_MAFIA_ELIMINATED", "MAFIA_PARITY",
                "FINAL_MAFIA_SELECTED", "FINAL_NON_MAFIA_SELECTED",
            }
            assert (result.final_accusation_target is not None) == result.win_reason.startswith("FINAL_")
        # 승률은 관찰 자료이며 목표 범위를 맞추려고 seed나 규칙을 변경하지 않는다.
        print({"player_count": player_count, "wins": dict(Counter(r.winner for r in results)),
               "win_reasons": dict(Counter(r.win_reason for r in results)),
               "revotes": sum(r.revote_count for r in results),
               "final_accusations": sum(r.final_accusation_target is not None for r in results)})


def test_b9_same_seed_reproduces_roles_targets_and_winner() -> None:
    """같은 seed는 시간값과 관계없이 같은 규칙 결과를 재생산해야 한다."""

    first = run_heuristic_game(9, "b9-deterministic-seed")
    second = run_heuristic_game(9, "b9-deterministic-seed")
    assert first.signature == second.signature
