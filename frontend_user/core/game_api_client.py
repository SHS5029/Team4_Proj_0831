"""연결 뼈대 게임 API를 호출하는 최소 Frontend client다."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID


class GameApiError(RuntimeError):
    """Backend 오류 code와 HTTP status를 화면 계층에 전달한다."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class GameApiClient:
    """Backend URL과 개발용 사용자 ID만 보유하는 game client다."""

    def __init__(self, *, api_url: str | None = None, user_id: str) -> None:
        self.api_url = (api_url or os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.user_id = str(UUID(user_id))

    def create_game(self, player_count: int = 5) -> dict:
        """뼈대 ruleset으로 game을 생성한다."""

        return self._request("POST", "/api/v1/games", {"player_count": player_count, "ruleset_version": "scaffold-v1", "idempotency_key": "00000000-0000-4000-8000-000000000010"})

    def get_game(self, game_id: str) -> dict:
        """game 상태를 조회한다."""

        return self._request("GET", f"/api/v1/games/{UUID(game_id)}")

    def ping(self, game_id: str, expected_version: int) -> dict:
        """Backend command 왕복을 실행한다."""

        return self._request("POST", f"/api/v1/games/{UUID(game_id)}/commands", {"command": "PING", "expected_version": expected_version, "idempotency_key": "00000000-0000-4000-8000-000000000012"})

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        """JSON object만 허용하고 Backend 오류를 고정 타입으로 변환한다."""

        raw = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        request = Request(f"{self.api_url}{path}", data=raw, method=method, headers={"X-User-Id": self.user_id, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310 - URL은 로컬 또는 배포 설정이다.
                payload = json.loads(response.read().decode())
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode())
            except (UnicodeError, json.JSONDecodeError) as decode_error:
                raise GameApiError(error.code, "BACKEND_ERROR") from decode_error
            raise GameApiError(error.code, payload.get("code", "BACKEND_ERROR"))
        except (OSError, URLError, TimeoutError) as error:
            raise GameApiError(503, "DEPENDENCY_UNAVAILABLE") from error
        if not isinstance(payload, dict):
            raise GameApiError(503, "INVALID_RESPONSE")
        return payload
