from frontend_user.app_pages.game_create_page import ROLE_COUNTS
from frontend_user.app_pages.home_page import should_load_games
from frontend_user.core.api_client import ApiClient


def test_role_preview_matches_mystery_v1_for_six_to_nine_players() -> None:
    assert ROLE_COUNTS[6] == {"마피아": 1, "탐정": 1, "의사": 1, "시민": 3}
    assert ROLE_COUNTS[7]["시민"] == 4
    assert ROLE_COUNTS[8]["마피아"] == 2
    assert sum(ROLE_COUNTS[9].values()) == 9


def test_create_game_posts_contract_and_idempotency_header() -> None:
    # 팀 전달 사항: Backend 계약 테스트와 이 header/body fixture가 일치해야 한다.
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        return 201, b'{"data":{"game_id":"d9ae9b5d-1d17-4f80-8f1a-276bfe170412"}}'

    client = ApiClient(
        user_id="83d40f36-e835-4a1d-88db-e59b6920b739",
        transport=transport,
    )
    client.create_game(
        player_count=6,
        idempotency_key="2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    )
    request = captured["request"]
    assert request.headers["Idempotency-key"] == "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde"
    assert request.data == (
        b'{"player_count":6,"ruleset_version":"mystery-v1","scenario_version":"scenario-v1"}'
    )


def test_home_game_list_load_starts_only_without_data_or_error() -> None:
    assert should_load_games({}) is True
    assert should_load_games({"home.games": []}) is False
    assert should_load_games({"home.games_loading": True}) is False
    assert should_load_games({"home.games_error": "DEPENDENCY_UNAVAILABLE"}) is False
