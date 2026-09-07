"""관리자 read-only Backend API client."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from frontend_admin.core.auth import parse_admin_uuid
from frontend_admin.core.models import ADMIN_PHASES, ADMIN_STATUSES

HttpTransport = Callable[[Request, float], tuple[int, bytes]]


class AdminApiError(RuntimeError):
    """관리자 API의 고정 오류만 전달하는 예외."""

    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class AdminApiClient:
    """조회 endpoint만 노출해 관리자 Front의 변경 요청을 구조적으로 막는다."""

    # 팀 전달 사항: Backend는 ADMIN_USER_IDS에 정확히 등록된 UUID만 관리자 GET에
    # 접근시키고, 관리자 endpoint에는 mutation·강제 종료 기능을 추가하지 않는다.

    def __init__(self, *, user_id: str | UUID, api_url: str = "http://127.0.0.1:8000", transport: HttpTransport | None = None):
        self.user_id = parse_admin_uuid(str(user_id))
        if self.user_id is None:
            raise ValueError("관리자 식별자는 UUID v4여야 합니다.")
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
        if status is not None and status not in ADMIN_STATUSES:
            raise ValueError("관리자 게임 상태 필터가 올바르지 않습니다.")
        if phase is not None and phase not in ADMIN_PHASES:
            raise ValueError("관리자 게임 단계 필터가 올바르지 않습니다.")
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
        if status != 200:
            raise AdminApiError(503, "INVALID_RESPONSE")
        return payload


def _send(request: Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 관리자 Backend 설정을 사용한다.
            return int(response.status), response.read(256 * 1024)
    except HTTPError as exc:
        return exc.code, exc.read(256 * 1024)
