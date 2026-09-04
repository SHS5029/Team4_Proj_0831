"""B5 공개 게임·sync·feedback API의 계약 테스트."""

from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game_service import CanonicalGameService, InMemoryGameRepository

USER = "00000000-0000-4000-8000-000000000101"
OTHER_USER = "00000000-0000-4000-8000-000000000102"
CREATE_KEY = "00000000-0000-4000-8000-000000000111"
BEGIN_KEY = "00000000-0000-4000-8000-000000000112"
SPEAK_KEY = "00000000-0000-4000-8000-000000000113"


class FakeUserWriteService:
    """공용 DB를 건드리지 않고 최초 쓰기의 사용자 준비 호출을 기록한다."""

    def __init__(self) -> None:
        self.ensured: list[UUID] = []

    def ensure_user(self, user_id: UUID) -> object:
        """같은 UUID의 반복 호출도 확인할 수 있도록 호출 순서를 보관한다."""

        self.ensured.append(user_id)
        return object()


def _client() -> TestClient:
    """DB 없이 B5 저장소만 주입한 FastAPI client를 만든다."""

    return TestClient(create_app(canonical_repository=InMemoryGameRepository()))


def _headers(key: str | None = None, user: str = USER) -> dict[str, str]:
    """공개 API 공통 header를 만든다."""

    headers = {"X-User-Id": user}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _create(client: TestClient) -> tuple[str, dict]:
    """정본 생성 응답과 game id를 반환한다."""

    response = client.post(
        "/api/v1/games",
        headers=_headers(CREATE_KEY),
        json={
            "player_count": 6,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["data"]["phase"] == "ROLE_REVEAL"
    assert body["data"]["state_version"] == 1
    return body["data"]["game_id"], body


def test_b5_create_snapshot_command_and_sync() -> None:
    """생성부터 첫 발언과 delta sync까지의 기본 흐름을 검증한다."""

    client = _client()
    game_id, created = _create(client)
    snapshot = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    assert snapshot["game"]["state_version"] == created["data"]["state_version"]
    assert len(snapshot["players"]) == 6
    assert snapshot["players"][0]["revealed_role"] is None
    assert snapshot["me"]["role"] in {"MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN"}

    begin = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(BEGIN_KEY),
        json={"type": "BEGIN_GAME", "expected_state_version": 1},
    )
    assert begin.status_code == 200
    assert begin.json()["data"]["result_state_version"] == 2

    current = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    window_id = current["action_window"]["window_id"]
    speak = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(SPEAK_KEY),
        json={
            "type": "SPEAK",
            "expected_state_version": 2,
            "window_id": window_id,
            "message": "조정실 근처에 있었습니다.",
        },
    )
    assert speak.status_code == 200
    assert speak.json()["data"]["result_state_version"] > 2

    sync = client.get(
        f"/api/v1/games/{game_id}/sync?after_state_version=0&after_sequence=0",
        headers=_headers(),
    )
    assert sync.status_code == 200
    data = sync.json()["data"]
    assert data["mode"] == "DELTA"
    assert data["snapshot"] is None
    assert data["operations"]
    assert data["operations"][0]["operations"][0]["operation_index"] == 0


def test_b5_owner_stale_and_idempotency_boundaries() -> None:
    """타 사용자 접근, 오래된 version과 같은 key 재전송을 확인한다."""

    client = _client()
    game_id, _ = _create(client)
    wrong_owner = client.get(f"/api/v1/games/{game_id}", headers=_headers(user=OTHER_USER))
    assert wrong_owner.status_code == 404
    stale = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(BEGIN_KEY),
        json={"type": "BEGIN_GAME", "expected_state_version": 99},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_STATE_VERSION"

    first = client.post(
        "/api/v1/games",
        headers=_headers(CREATE_KEY),
        json={
            "player_count": 6,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
        },
    )
    second = client.post(
        "/api/v1/games",
        headers=_headers(CREATE_KEY),
        json={
            "player_count": 6,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
        },
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["meta"]["replayed"] is True


def test_b5_feedback_validation_and_general_feedback() -> None:
    """일반 feedback은 게임 종료를 기다리지 않고 저장한다."""

    client = _client()
    response = client.post(
        "/api/v1/feedback",
        headers=_headers("00000000-0000-4000-8000-000000000121"),
        json={
            "feedback_type": "GENERAL",
            "rating": 4,
            "comment": "  흐름이 이해하기 쉬웠습니다. ",
            "tags": ["ux"],
        },
    )
    assert response.status_code == 201
    assert UUID(response.json()["data"]["feedback_id"])
    assert response.json()["data"]["feedback_type"] == "GENERAL"


def test_first_game_and_general_feedback_write_prepare_user_before_storage() -> None:
    """game이 없어도 가능한 두 최초 쓰기가 users 준비 단계를 거치는지 확인한다."""

    users = FakeUserWriteService()
    service = CanonicalGameService(InMemoryGameRepository(), user_service=users)
    owner = UUID(USER)

    service.create(
        owner,
        CreateGameRequest(
            player_count=6,
            ruleset_version="mystery-v1",
            scenario_version="scenario-v1",
        ),
        UUID(CREATE_KEY),
    )
    service.feedback(
        owner,
        FeedbackRequest(feedback_type="GENERAL", rating=5),
        UUID("00000000-0000-4000-8000-000000000122"),
    )

    assert users.ensured == [owner, owner]
