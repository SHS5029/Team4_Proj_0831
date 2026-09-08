"""FastMCP 등록부가 Backend synthetic endpoint를 호출하는 최소 adapter다."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlsplit

import httpx

from mafia_game.schemas.common import (
    RESOURCE_SCOPE_ORDER,
    WireContractError,
    canonical_uuid,
    integer,
    require_keys,
    string,
)


class BackendContextError(RuntimeError):
    """Backend 실패를 외부 문구 없는 고정 코드로만 전달한다."""

    def __init__(self, code: str = "MCP_BACKEND_ERROR") -> None:
        """응답·URL·예외 원문이 실수로 들어와도 허용된 진단 코드만 남긴다."""

        allowed = {
            "MCP_BACKEND_ERROR", "MCP_BACKEND_TIMEOUT", "MCP_BACKEND_CONNECTION_ERROR",
            "MCP_BACKEND_INVALID_JSON", "MCP_BACKEND_INVALID_RESPONSE",
        }
        self.code = code if isinstance(code, str) and (
            code in allowed or re.fullmatch(r"MCP_BACKEND_HTTP_[1-5][0-9]{2}", code)
        ) else "MCP_BACKEND_ERROR"
        super().__init__(self.code)


class BackendContextClient(Protocol):
    """MCP 등록부가 의존하는 최소 Backend 호출 계약이다."""

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Backend context를 읽는다."""

    async def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Backend prompt 본문을 읽는다."""

    async def submit_action(self, **payload: str | None) -> dict[str, Any]:
        """행동 payload를 Backend에 전달한다."""

    async def inspect_special_roles(self, *, user_id: str, game_id: str) -> dict[str, Any]:
        """Backend가 소유자에게 허용한 특수 직업만 요청별로 조회한다."""


class MinimalBackendContextClient:
    """인증·세션·게임 판정 없이 Backend HTTP endpoint만 호출한다."""

    def __init__(
        self,
        backend_api_url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(backend_api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BACKEND_API_URL must be an absolute HTTP(S) URL")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("BACKEND_API_URL must not include query, fragment, or userinfo")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("plain HTTP is allowed only for loopback development")
        self._base_url = backend_api_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10.0, trust_env=False)
        self._owns_client = client is None

    async def _request(
        self, method: str, path: str, *, body: bytes = b""
    ) -> dict[str, Any]:
        """Backend JSON object 응답만 허용하고 내부 오류 원문은 숨긴다."""

        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException:
            raise BackendContextError("MCP_BACKEND_TIMEOUT") from None
        except httpx.TransportError:
            raise BackendContextError("MCP_BACKEND_CONNECTION_ERROR") from None
        except (httpx.HTTPError, ValueError):
            raise BackendContextError from None
        # 상태를 먼저 확인해야 HTML 오류 페이지를 JSON 오류로 잘못 분류하지 않는다.
        # 외부 예외 체인은 숨겨 FastMCP traceback에도 요청 URL과 본문이 남지 않게 한다.
        if response.status_code < 200 or response.status_code >= 300:
            raise BackendContextError(f"MCP_BACKEND_HTTP_{response.status_code}") from None
        try:
            payload = response.json()
        except ValueError:
            raise BackendContextError("MCP_BACKEND_INVALID_JSON") from None
        if not isinstance(payload, dict):
            raise BackendContextError("MCP_BACKEND_INVALID_RESPONSE") from None
        return payload

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """URI 형식·UUID·scope를 검증한 뒤 Backend에 전달하며 projection은 재구성하지 않는다."""

        parts = uri.split("/")
        current = len(parts) == 6 and parts[:4] == ["mafia:", "", "context", "current"]
        scoped = len(parts) == 8 and parts[:4] == ["mafia:", "", "context", "scoped"]
        if not (current or scoped):
            raise BackendContextError
        try:
            parameters = {
                "game_id": canonical_uuid(parts[4]),
                "user_id": canonical_uuid(parts[5]),
            }
            if scoped:
                parameters["player_id"] = canonical_uuid(parts[6])
                if parts[7] not in RESOURCE_SCOPE_ORDER:
                    raise WireContractError
            parameters["scope"] = parts[7] if scoped else "public"
        except WireContractError:
            raise BackendContextError from None
        return await self._request(
            "GET", f"/internal/mcp/context?{urlencode(parameters)}"
        )

    async def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Prompt 이름을 Backend에 전달하고 문자열 본문만 반환한다."""

        if name != "agent_instruction":
            raise BackendContextError
        # FastMCP의 생략된 선택 인자는 빈 문자열이므로 UUID query에 보내지 않는다.
        # 값이 있는 인자는 그대로 전달해 Backend의 형식 검증을 우회하지 않는다.
        arguments = {
            key: value for key, value in arguments.items()
            if key not in {"game_id", "user_id"} or value != ""
        }
        query = ""
        if arguments:
            query = "?" + "&".join(
                f"{quote(key, safe='-._~')}={quote(value, safe='-._~')}"
                for key, value in arguments.items()
            )
        payload = await self._request(
            "GET", f"/internal/mcp/prompts/{quote(name, safe='-._~')}{query}"
        )
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            raise BackendContextError
        return prompt

    async def submit_action(self, **payload: str | None) -> dict[str, Any]:
        """Backend가 명시적으로 승인한 응답만 반환해 HTTP 200과 행동 성공을 구분한다."""

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        result = await self._request("POST", "/internal/mcp/actions", body=body)
        if result.get("accepted") is not True or result.get("error") is not None:
            raise BackendContextError
        return result

    async def inspect_special_roles(self, *, user_id: str, game_id: str) -> dict[str, Any]:
        """소유자 조회를 위임하고 추가 비공개 필드·다른 게임 응답을 폐쇄형 검증으로 막는다."""

        try:
            parameters = {
                "user_id": canonical_uuid(user_id),
                "game_id": canonical_uuid(game_id),
            }
        except WireContractError:
            raise BackendContextError from None
        result = await self._request(
            "GET", f"/internal/mcp/special-roles?{urlencode(parameters)}"
        )
        try:
            require_keys(result, {"game_id", "player_id", "ability_id", "state_version", "roles"})
            if canonical_uuid(result["game_id"]) != game_id:
                raise WireContractError
            actor_id = canonical_uuid(result["player_id"])
            if result["ability_id"] != "intel.special_roles.v1":
                raise WireContractError
            integer(result["state_version"], minimum=1)
            if not isinstance(result["roles"], list):
                raise WireContractError
            # actor는 Backend가 소유 HUMAN으로 확정한다. MCP는 응답의 본인 제외와
            # 중복만 확인하고 직업 소유권·생존·첫 밤 해금 판정을 새로 만들지 않는다.
            seen = {actor_id}
            for item in result["roles"]:
                require_keys(item, {"player_id", "display_name", "role", "alive"})
                player_id = canonical_uuid(item["player_id"])
                if player_id in seen:
                    raise WireContractError
                seen.add(player_id)
                string(item["display_name"])
                if string(item["role"]) not in {"DETECTIVE", "DOCTOR"}:
                    raise WireContractError
                if not isinstance(item["alive"], bool):
                    raise WireContractError
        except WireContractError:
            raise BackendContextError("MCP_BACKEND_INVALID_RESPONSE") from None
        return result

    async def aclose(self) -> None:
        """adapter가 생성한 HTTP client만 닫는다."""

        if self._owns_client:
            await self._client.aclose()
