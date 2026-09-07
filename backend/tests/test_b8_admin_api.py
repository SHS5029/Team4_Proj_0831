"""B8 관리자 allowlist·read-only·redaction 계약 테스트."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repositories.admin_repository import AdminRepository

ADMIN = "00000000-0000-4000-8000-000000000201"
USER = "00000000-0000-4000-8000-000000000202"
CREATE_KEY = "00000000-0000-4000-8000-000000000211"


GAME_ID = UUID("00000000-0000-4000-8000-000000000299")


class FakeAdminRepository:
    """게임 runtime과 분리된 관리자 repository 계약 대역."""

    def __init__(self, *, include_game: bool = True) -> None:
        self.audit_events: list[dict[str, str]] = []
        self.item = {
            "game_id": str(GAME_ID),
            "owner_user_id": USER,
            "status": "IN_PROGRESS",
            "phase": "ROLE_REVEAL",
            "round": 0,
            "state_version": 1,
            "player_count": 6,
            "open_window_kind": None,
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        } if include_game else None

    def list_games(self, *, status, phase, cursor, limit):
        """관리자 목록 계약에 맞는 공개 row만 반환한다."""

        del status, phase, cursor, limit
        return ([self.item] if self.item else []), None

    def get_game(self, game_id):
        """역할·seed·private event가 없는 관리자 상세를 반환한다."""

        if self.item is None or game_id != GAME_ID:
            return None
        return {
            "game": {key: self.item[key] for key in ("game_id", "status", "phase", "round", "state_version")},
            "public_events": [],
        }

    def metrics(self, *, from_time, to_time):
        """관리자 지표 계약의 최소 synthetic 결과를 반환한다."""

        del from_time, to_time
        return {"games_created": 1 if self.item else 0, "games_completed": 0}

    def append_audit(self, *, admin_user_id, action, target_game_id, request_id):
        """성공한 관리자 조회의 audit 기록을 보관한다."""

        self.audit_events.append({"admin_user_id": str(admin_user_id), "action": action, "request_id": str(request_id)})


def _client(*, allowlist: tuple[str, ...] = (ADMIN,), include_game: bool = True) -> tuple[TestClient, FakeAdminRepository]:
    """게임 runtime 없이 관리자 repository 계약만 주입한 테스트 앱을 만든다."""

    repository = FakeAdminRepository(include_game=include_game)
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        admin_user_ids=allowlist,
    )
    return (
        TestClient(
            create_app(
                settings=settings,
                admin_repository=repository,
                enable_background_worker=False,
            )
        ),
        repository,
    )


def _create_game(client: TestClient) -> str:
    """관리자 fake가 제공하는 synthetic 게임 식별자를 반환한다."""

    del client
    return str(GAME_ID)


def test_b8_admin_list_detail_and_metrics_are_read_only() -> None:
    """관리자 조회가 동작하고 공개 정보 밖의 필드는 노출하지 않는지 확인한다."""

    client, repository = _client()
    game_id = _create_game(client)
    before = repository.item["state_version"]

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
    assert repository.item["state_version"] == before
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

    client, _ = _client(include_game=False)
    response = client.get(
        "/api/v1/admin/games/00000000-0000-4000-8000-000000000299",
        headers={"X-User-Id": ADMIN},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GAME_NOT_FOUND"
