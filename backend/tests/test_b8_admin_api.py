"""B8 관리자 allowlist·read-only·redaction 계약 테스트."""

from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repositories.admin_repository import InMemoryAdminRepository
from backend.app.services.game_service import InMemoryGameRepository

ADMIN = "00000000-0000-4000-8000-000000000201"
USER = "00000000-0000-4000-8000-000000000202"
CREATE_KEY = "00000000-0000-4000-8000-000000000211"


def _client(*, allowlist: tuple[str, ...] = (ADMIN,)) -> tuple[TestClient, InMemoryGameRepository]:
    """DB 없이 B8와 B5가 같은 메모리 게임 저장소를 보게 한다."""

    repository = InMemoryGameRepository()
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        admin_user_ids=allowlist,
    )
    admin_repository = InMemoryAdminRepository(repository)
    return (
        TestClient(
            create_app(
                settings=settings,
                canonical_repository=repository,
                admin_repository=admin_repository,
            )
        ),
        repository,
    )


def _create_game(client: TestClient) -> str:
    """관리자 목록에 표시할 공개 게임 하나를 만든다."""

    response = client.post(
        "/api/v1/games",
        headers={"X-User-Id": USER, "Idempotency-Key": CREATE_KEY},
        json={
            "player_count": 6,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["game_id"]


def test_b8_admin_list_detail_and_metrics_are_read_only() -> None:
    """관리자 조회가 동작하고 공개 정보 밖의 필드는 노출하지 않는지 확인한다."""

    client, repository = _client()
    game_id = _create_game(client)
    before = repository.games[UUID(game_id)].state.state_version

    listed = client.get(
        "/api/v1/admin/games",
        headers={"X-User-Id": ADMIN},
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["game_id"] == game_id
    assert listed.json()["data"]["items"][0]["owner_user_id"] == USER

    detail = client.get(
        f"/api/v1/admin/games/{game_id}",
        headers={"X-User-Id": ADMIN},
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["game"]["game_id"] == game_id
    assert detail_data["public_events"] == []
    assert "role" not in detail_data
    assert "seed" not in detail_data
    assert "private_events" not in detail_data
    assert "actions" not in detail_data
    assert "votes" not in detail_data

    metrics = client.get(
        "/api/v1/admin/metrics",
        headers={"X-User-Id": ADMIN},
    )
    assert metrics.status_code == 200
    assert metrics.json()["data"]["games_created"] == 1
    assert metrics.json()["data"]["games_completed"] == 0
    assert repository.games[UUID(game_id)].state.state_version == before
    assert [event["action"] for event in repository.audit_events] == [
        "ADMIN_LIST_GAMES",
        "ADMIN_GET_GAME",
        "ADMIN_GET_METRICS",
    ]


def test_b8_empty_or_invalid_allowlist_fails_closed() -> None:
    """allowlist가 비었거나 잘못된 UUID를 포함하면 모두 403인지 확인한다."""

    client, _ = _client(allowlist=())
    response = client.get("/api/v1/admin/games", headers={"X-User-Id": ADMIN})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"

    invalid_client, _ = _client(allowlist=(ADMIN, "not-a-uuid"))
    invalid_response = invalid_client.get("/api/v1/admin/metrics", headers={"X-User-Id": ADMIN})
    assert invalid_response.status_code == 403
    assert invalid_response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_b8_unknown_game_is_not_disclosed() -> None:
    """관리자도 존재하지 않는 게임의 내부 상태를 구분해 받지 않는다."""

    client, _ = _client()
    response = client.get(
        "/api/v1/admin/games/00000000-0000-4000-8000-000000000299",
        headers={"X-User-Id": ADMIN},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GAME_NOT_FOUND"
