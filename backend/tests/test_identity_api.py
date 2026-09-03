from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.repositories.scaffold_repository import ScaffoldRepository

USER = "00000000-0000-4000-8000-000000000001"
USER_V1 = "00000000-0000-1000-8000-000000000001"
GAME_ID = "00000000-0000-4000-8000-000000000099"


def _client() -> TestClient:
    """외부 DB 없이 현재 백엔드 뼈대에 fake 게임 저장소를 연결한다."""

    return TestClient(create_app(ScaffoldRepository()))


def test_legacy_identity_route_is_not_registered() -> None:
    """OIDC provision 경로가 더 이상 공개 API로 열려 있지 않은지 확인한다."""

    response = _client().post("/api/v1/identity/provision", json={})

    assert response.status_code == 404


def test_missing_user_id_returns_canonical_error() -> None:
    """사용자 헤더가 없으면 조회를 실행하지 않고 명확한 오류를 반환한다."""

    response = _client().get(f"/api/v1/games/{GAME_ID}")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_USER_ID"
    assert response.json()["error"]["retryable"] is False


def test_user_id_must_be_uuid_v4() -> None:
    """UUID 형식이어도 v1처럼 다른 버전이면 사용자 식별자로 사용하지 않는다."""

    response = _client().get(
        f"/api/v1/games/{GAME_ID}",
        headers={"X-User-Id": USER_V1},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_valid_uuid_v4_is_accepted_and_request_id_is_returned() -> None:
    """유효한 UUID v4는 통과하고 요청 추적 번호는 응답에도 유지한다."""

    request_id = "00000000-0000-4000-8000-000000000123"
    response = _client().post(
        "/api/v1/games",
        headers={"X-User-Id": USER, "X-Request-Id": request_id},
        json={
            "player_count": 5,
            "ruleset_version": "scaffold-v1",
            "idempotency_key": "00000000-0000-4000-8000-000000000010",
        },
    )

    assert response.status_code == 201
    assert response.headers["X-Request-Id"] == request_id
