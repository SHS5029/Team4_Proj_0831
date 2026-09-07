"""Agent가 FastMCP를 통해 게임 context와 action을 호출하는 client."""

from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx


class AgentContextClient(Protocol):
    """Agent 작업에 필요한 최소 Context 조회 계약이다."""

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """현재 작업에 허용된 Context를 반환한다."""

    async def close(self) -> None:
        """작업 종료 시 provider 자원을 닫는다."""


class FakeAgentContextClient:
    """외부 MCP와 네트워크 없이 Agent 흐름을 검증하는 fake provider다."""

    def __init__(
        self,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.context = context or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """capability 원문은 저장하지 않고 호출 사실과 scope만 기록한다."""

        self.calls.append(("<opaque>", scope))
        if self.error is not None:
            raise self.error
        return dict(self.context)

    async def close(self) -> None:
        """fake provider의 종료 상태만 기록한다."""

        self.closed = True


class FastMcpGameContextClient:
    """FastMCP Streamable HTTP를 호출하는 실제 게임 context adapter.

    MCP session은 한 Agent turn 동안만 유지한다. Backend는 MCP protocol을 우회해
    내부 endpoint를 직접 호출하지 않으며, action 검증과 상태 변경은 MCP 뒤의
    Backend GameEngine에 남긴다.
    """

    def __init__(
        self,
        base_url: str,
        *,
        user_id: UUID,
        game_id: UUID,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """loopback FastMCP endpoint와 현재 게임·사용자를 고정한다."""

        self._base_url = base_url.rstrip("/")
        self._user_id = user_id
        self._game_id = game_id
        self._client = client or httpx.AsyncClient(timeout=15.0, trust_env=False)
        self._owns_client = client is None
        self._session_id: str | None = None
        self._request_id = 0
        self._last_context: dict[str, Any] | None = None

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """FastMCP JSON-RPC 응답을 확인하고 result object만 반환한다."""

        self._request_id += 1
        headers = {"Accept": "application/json, text/event-stream"}
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        response = await self._client.post(
            f"{self._base_url}/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params},
        )
        response.raise_for_status()
        if method == "initialize":
            self._session_id = response.headers.get("mcp-session-id")
        body = response.json()
        if "error" in body or not isinstance(body.get("result"), dict):
            raise RuntimeError("FastMCP request failed")
        return body["result"]

    async def _initialize(self) -> None:
        """MCP protocol session을 한 번만 초기화한다."""

        if self._session_id is not None:
            return
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ai-mafia-agent", "version": "1.0"},
            },
        )
        del result
        await self._client.post(
            f"{self._base_url}/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": self._session_id or "",
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """실제 Resource를 읽어 scope별 context를 반환한다."""

        del capability
        await self._initialize()
        del scope
        result = await self._rpc(
            "resources/read",
            {"uri": f"mafia://context/current/{self._game_id}/{self._user_id}"},
        )
        contents = result.get("contents", [])
        if not contents or not isinstance(contents[0].get("text"), str):
            raise RuntimeError("FastMCP context response is invalid")
        payload = json.loads(contents[0]["text"])
        if not isinstance(payload, dict):
            raise RuntimeError("FastMCP context must be an object")
        self._last_context = payload
        return payload

    async def read_context(self, *, game_id: UUID, player_id: UUID) -> dict[str, Any]:
        """게임 Agent adapter가 사용하는 실제 Resource 조회 포트다."""

        if game_id != self._game_id:
            raise ValueError("game_id does not match the MCP client scope")
        if player_id == self._user_id:
            raise ValueError("MCP owner and AI player identifiers must be distinct")
        return await self.get_context(capability="", scope="public")

    async def submit_action(
        self,
        *,
        game_id: UUID,
        player_id: UUID,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """정규화된 Agent proposal을 FastMCP Tool로 전달한다."""

        if game_id != self._game_id or self._last_context is None:
            raise ValueError("MCP action requires a previously read game context")
        game = self._last_context.get("game", {})
        window = self._last_context.get("action_window") or {}
        action_type = action.get("type")
        result = await self._rpc(
            "tools/call",
            {
                "name": "submit_action",
                "arguments": {
                    "action": action_type,
                    "user_id": str(self._user_id),
                    "game_id": str(self._game_id),
                    "player_id": str(player_id),
                    "expected_state_version": game.get("state_version"),
                    "window_id": window.get("window_id"),
                    "idempotency_key": str(uuid4()),
                    "target_player_id": action.get("target_player_id"),
                    "message": action.get("message"),
                },
            },
        )
        contents = result.get("content", [])
        if not contents or not isinstance(contents[0].get("text"), str):
            raise RuntimeError("FastMCP action response is invalid")
        payload = json.loads(contents[0]["text"])
        if not isinstance(payload, dict):
            raise RuntimeError("FastMCP action result must be an object")
        return payload

    async def close(self) -> None:
        """Agent turn에 사용한 HTTP client를 닫는다."""

        if self._owns_client:
            await self._client.aclose()
