"""연결 뼈대 REST API의 독립 계약을 검증한다."""

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.repositories.scaffold_repository import ScaffoldRepository

USER = "00000000-0000-4000-8000-000000000001"
OTHER_USER = "00000000-0000-4000-8000-000000000002"


def _create(client: TestClient) -> dict:
    """공통 game 생성 요청을 실행한다."""

    response = client.post(
        "/api/v1/games",
        headers={"X-User-Id": USER},
        json={
            "player_count": 5,
            "ruleset_version": "scaffold-v1",
            "idempotency_key": "00000000-0000-4000-8000-000000000010",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_scaffold_game_smoke_and_idempotency() -> None:
    """생성·조회·command·operation과 동일 재전송을 검증한다."""

    client = TestClient(create_app(ScaffoldRepository()))
    game = _create(client)
    game_id = game["game_id"]
    command = {
        "command": "PING",
        "expected_version": 1,
        "idempotency_key": "00000000-0000-4000-8000-000000000012",
    }
    first = client.post(f"/api/v1/games/{game_id}/commands", headers={"X-User-Id": USER}, json=command)
    second = client.post(f"/api/v1/games/{game_id}/commands", headers={"X-User-Id": USER}, json=command)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    operation = client.get(f"/api/v1/games/{game_id}/operations/{first.json()['operation_id']}", headers={"X-User-Id": USER})
    assert operation.status_code == 200
    assert operation.json()["status"] == "COMPLETED"


def test_scaffold_game_rejects_wrong_owner_and_version() -> None:
    """타 사용자와 오래된 version이 game을 변경하지 못하는지 검증한다."""

    client = TestClient(create_app(ScaffoldRepository()))
    game_id = _create(client)["game_id"]
    wrong_owner = client.get(f"/api/v1/games/{game_id}", headers={"X-User-Id": OTHER_USER})
    assert wrong_owner.status_code == 404
    stale = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers={"X-User-Id": USER},
        json={"command": "PAUSE", "expected_version": 99, "idempotency_key": "00000000-0000-4000-8000-000000000014"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "GAME_STATE_CONFLICT"


def test_scaffold_game_list_returns_owned_mock_games_and_empty_for_unknown_user() -> None:
    """목데이터 목록은 소유자별로 격리되고 게임이 없으면 200 빈 목록을 반환한다."""

    client = TestClient(create_app(ScaffoldRepository()))
    created = _create(client)
    listed = client.get("/api/v1/games?limit=20", headers={"X-User-Id": USER})
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["game_id"] == created["game_id"]

    empty = client.get("/api/v1/games", headers={"X-User-Id": OTHER_USER})
    assert empty.status_code == 200
    assert empty.json() == {"data": {"items": [], "next_cursor": None}}
