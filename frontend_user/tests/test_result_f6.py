from frontend_user.app_pages.result_page import (
    _player_status,
    _round_count,
    _winner_presentation,
)


def test_failed_result_is_not_treated_as_completed() -> None:
    snapshot = {"game": {"status": "FAILED"}, "result": {"winner": "MAFIA"}}
    assert snapshot["game"]["status"] != "COMPLETED"


def test_winner_presentation_uses_backend_winner_enum() -> None:
    title, caption = _winner_presentation("CITIZEN")
    assert title == "시민 진영 승리"
    assert "마피아" in caption


def test_player_status_uses_eliminated_phase_without_role_inference() -> None:
    status, detail = _player_status(
        {"alive": False, "eliminated_phase": "DAY_VOTE", "eliminated_round": 2}
    )
    assert status == "처형됨"
    assert detail == "낮 투표 · 라운드 2"


def test_round_count_uses_only_confirmed_result_rounds() -> None:
    result = {
        "nights": [{"round": 1}, {"round": 2}],
        "votes": [{"round": 3}],
    }
    assert _round_count(game={"round": 2}, result=result) == 3
