"""관리자 read-only Backend API client."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

HttpTransport = Callable[[Request, float], tuple[int, bytes]]


class AdminApiError(RuntimeError):
    """관리자 API의 고정 오류만 전달하는 예외."""

    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def is_demo_mode() -> bool:
    """로컬 화면 확인용 가상 데이터 모드가 명시적으로 켜졌는지 확인한다."""

    return os.getenv("ADMIN_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


class AdminApiClient:
    """조회 endpoint만 노출해 관리자 Front의 변경 요청을 구조적으로 막는다."""

    # 팀 전달 사항: Backend는 ADMIN_USER_IDS에 정확히 등록된 UUID만 관리자 GET에
    # 접근시키고, 관리자 endpoint에는 mutation·강제 종료 기능을 추가하지 않는다.

    def __init__(self, *, user_id: str | UUID, api_url: str = "http://127.0.0.1:8000", transport: HttpTransport | None = None):
        self.user_id = UUID(str(user_id))
        self.api_url = api_url.rstrip("/")
        self._transport = transport or _send

    def metrics(self, *, from_date: str | None = None,
                to_date: str | None = None) -> dict[str, Any]:
        """명세서의 선택적 최대 31일 기간으로 관리자 지표를 조회한다."""

        query = []
        if from_date:
            query.append(f"from={quote(from_date.strip(), safe='-:')}")
        if to_date:
            query.append(f"to={quote(to_date.strip(), safe='-:')}")
        suffix = "?" + "&".join(query) if query else ""
        return self._request("/api/v1/admin/metrics" + suffix)

    def games(self, *, status: str | None = None, phase: str | None = None,
              cursor: str | None = None, limit: int = 20) -> dict[str, Any]:
        """명세서의 관리자 게임 목록 필터와 페이지 cursor를 사용해 조회한다."""

        if not 1 <= limit <= 100:
            raise ValueError("관리자 게임 목록 limit은 1부터 100까지여야 합니다.")
        query = [f"limit={limit}"]
        if status:
            query.append(f"status={status}")
        if phase:
            query.append(f"phase={phase}")
        if cursor:
            normalized_cursor = cursor.strip()
            if not normalized_cursor:
                raise ValueError("관리자 게임 목록 cursor는 비어 있을 수 없습니다.")
            query.append(f"cursor={quote(normalized_cursor, safe='')}")
        suffix = "?" + "&".join(query) if query else ""
        return self._request("/api/v1/admin/games" + suffix)

    def game_detail(self, game_id: str | UUID) -> dict[str, Any]:
        """관리자용 비밀정보 없는 게임 상세를 조회한다."""

        return self._request(f"/api/v1/admin/games/{UUID(str(game_id))}")

    def _request(self, path: str) -> dict[str, Any]:
        request = Request(f"{self.api_url}{path}", headers={"Accept": "application/json", "X-User-Id": str(self.user_id), "X-Request-Id": str(uuid4())})
        try:
            status, body = self._transport(request, 5.0)
        except (OSError, URLError, TimeoutError) as exc:
            raise AdminApiError(503, "DEPENDENCY_UNAVAILABLE") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AdminApiError(503, "INVALID_RESPONSE") from exc
        if not isinstance(payload, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        if status >= 400:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else payload.get("code")
            raise AdminApiError(status, code if isinstance(code, str) else "ADMIN_ACCESS_DENIED")
        return payload


class DemoAdminApiClient:
    """외부 Backend 없이 관리자 화면을 확인하기 위한 읽기 전용 가상 API다.

    가상 응답은 Backend 관리자 API의 공개 응답 모양만 재현한다. 실제 게임의
    역할·행동·투표·시드 같은 비공개 필드는 포함하지 않아 화면 개발 중에도
    관리자 정보 경계를 동일하게 점검할 수 있다.
    """

    def metrics(self, **_: Any) -> dict[str, Any]:
        """운영 현황과 통계 탭에서 사용하는 가상 지표를 반환한다."""

        return {"data": deepcopy(DEMO_METRICS)}

    def games(self, **_: Any) -> dict[str, Any]:
        """운영 현황 탭에서 사용하는 가상 게임 목록을 반환한다."""

        return {"data": {"items": deepcopy(DEMO_GAMES), "next_cursor": None}}

    def game_detail(self, game_id: str | UUID) -> dict[str, Any]:
        """선택한 가상 게임의 공개 상세를 반환한다."""

        normalized_id = str(UUID(str(game_id)))
        detail = next(
            (item for item in DEMO_GAME_DETAILS if item["game_id"] == normalized_id),
            None,
        )
        if detail is None:
            raise AdminApiError(404, "GAME_NOT_FOUND")
        return {"data": deepcopy(detail)}


DEMO_METRICS: dict[str, Any] = {
    "games_created": 128,
    "games_completed": 96,
    "games_saved": 8,
    "completion_rate": 0.75,
    "average_rounds": 4.6,
    "wins_by_faction": {"CITIZEN": 58, "MAFIA": 38},
    "auto_action_count": 12,
    "feedback_average": 4.3,
}

DEMO_GAMES: list[dict[str, Any]] = [
    {
        "game_id": "1e1e1e1e-1111-4111-8111-111111111111",
        "status": "COMPLETED",
        "phase": "RESULT",
        "player_count": 7,
    },
    {
        "game_id": "2e2e2e2e-2222-4222-8222-222222222222",
        "status": "IN_PROGRESS",
        "phase": "DISCUSSION",
        "player_count": 7,
    },
]

DEMO_GAME_DETAILS: list[dict[str, Any]] = [
    {
        "game_id": "1e1e1e1e-1111-4111-8111-111111111111",
        "status": "COMPLETED",
        "phase": "RESULT",
        "player_count": 7,
        "round": 5,
        "winner": "CITIZEN",
        "open_window_kind": None,
        "failure_code": None,
    },
    {
        "game_id": "2e2e2e2e-2222-4222-8222-222222222222",
        "status": "IN_PROGRESS",
        "phase": "DISCUSSION",
        "player_count": 7,
        "round": 2,
        "winner": None,
        "open_window_kind": "DISCUSSION",
        "failure_code": None,
    },
]


def _send(request: Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 관리자 Backend 설정을 사용한다.
            return int(response.status), response.read(256 * 1024)
    except HTTPError as exc:
        return exc.code, exc.read(256 * 1024)
