"""B5 공개 게임·sync·feedback API의 PostgreSQL 계약 테스트."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app

USER_ID = uuid4()


@pytest.fixture(autouse=True)
def cleanup_test_user() -> None:
    """각 테스트가 만든 UUID 사용자와 종속 행만 PostgreSQL에서 정리한다."""

    yield
    settings: Settings = get_settings()
    with psycopg.connect(settings.effective_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM public.feedback WHERE user_id = %s", (USER_ID,))
            cursor.execute("DELETE FROM public.games WHERE owner_user_id = %s", (USER_ID,))
            cursor.execute("DELETE FROM public.users WHERE id = %s", (USER_ID,))


def _client() -> TestClient:
    """실제 PostgreSQL runtime을 사용하는 FastAPI client를 만든다."""

    return TestClient(create_app(settings=get_settings(), enable_background_worker=False))


def _headers(key: UUID | None = None, user: UUID = USER_ID) -> dict[str, str]:
    """공개 API 공통 header를 만든다."""

    headers = {"X-User-Id": str(user)}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    return headers


def _create(client: TestClient) -> tuple[UUID, dict]:
    """정본 생성 응답과 game id를 반환한다."""

    response = client.post(
        "/api/v1/games",
        headers=_headers(uuid4()),
        json={
            "player_count": 6,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(body["data"]["game_id"]), body


def test_b5_create_snapshot_command_and_sync() -> None:
    """생성부터 첫 발언과 delta sync까지의 PostgreSQL 흐름을 검증한다."""

    client = _client()
    game_id, created = _create(client)
    snapshot = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    assert snapshot["game"]["state_version"] == created["data"]["state_version"]
    assert len(snapshot["players"]) == 6

    begin = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(uuid4()),
        json={"type": "BEGIN_GAME", "expected_state_version": 1},
    )
    assert begin.status_code == 200, begin.text

    current = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    speak = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(uuid4()),
        json={
            "type": "SPEAK",
            "expected_state_version": current["game"]["state_version"],
            "window_id": current["action_window"]["window_id"],
            "message": "조정실 근처에 있었습니다.",
        },
    )
    assert speak.status_code == 200, speak.text

    sync = client.get(
        f"/api/v1/games/{game_id}/sync?after_state_version=0&after_sequence=0",
        headers=_headers(),
    )
    assert sync.status_code == 200, sync.text
    assert sync.json()["data"]["operations"]


def test_b5_owner_and_create_idempotency_boundaries() -> None:
    """타 사용자 접근과 같은 생성 key 재전송을 확인한다."""

    client = _client()
    game_id, _ = _create(client)
    wrong_owner = client.get(f"/api/v1/games/{game_id}", headers=_headers(user=uuid4()))
    assert wrong_owner.status_code == 404

    key = uuid4()
    payload = {
        "player_count": 6,
        "ruleset_version": "mystery-v1",
        "scenario_version": "scenario-v1",
    }
    first = client.post("/api/v1/games", headers=_headers(key), json=payload)
    second = client.post("/api/v1/games", headers=_headers(key), json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["meta"]["replayed"] is True


def test_b5_general_feedback_is_persisted_and_replayed() -> None:
    """일반 feedback을 PostgreSQL에 저장하고 동일 key 재요청을 replay한다."""

    client = _client()
    key = uuid4()
    payload = {
        "feedback_type": "GENERAL",
        "rating": 4,
        "comment": "  흐름이 이해하기 쉬웠습니다. ",
        "tags": ["ux"],
    }
    first = client.post("/api/v1/feedback", headers=_headers(key), json=payload)
    second = client.post("/api/v1/feedback", headers=_headers(key), json=payload)

    assert first.status_code == second.status_code == 201
    assert UUID(first.json()["data"]["feedback_id"])
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["meta"]["replayed"] is True

    with psycopg.connect(get_settings().effective_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rating, comment, tags FROM public.feedback WHERE user_id = %s",
                (USER_ID,),
            )
            row = cursor.fetchone()
    assert row == (4, "흐름이 이해하기 쉬웠습니다.", ["UX"])


def test_b5_feedback_validation_is_kept_at_http_boundary() -> None:
    """허용되지 않은 tag는 DB transaction 전에 422로 거부한다."""

    response = _client().post(
        "/api/v1/feedback",
        headers=_headers(uuid4()),
        json={"feedback_type": "GENERAL", "rating": 4, "tags": ["UNKNOWN"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
