"""WU-FMCP-03 FastMCP ASGI 왕복 테스트."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mafia_game.main import create_fastmcp_server


class RoundtripBackend:
    """FastMCP 왕복에서 Backend 위임 결과를 제공하는 합성 double이다."""

    def __init__(self, *, fail_resource: bool = False) -> None:
        self.fail_resource = fail_resource
        self.calls: list[tuple[str, str]] = []

    async def read_resource(self, uri: str) -> dict[str, Any]:
        self.calls.append(("resource", uri))
        if self.fail_resource:
            raise RuntimeError("synthetic backend failure")
        return {"session_id": "fixture-session", "phase": "DAY"}

    async def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        self.calls.append(("prompt", name))
        return "fixture agent instruction"

    async def submit_action(
        self,
        **payload: str | None,
    ) -> dict[str, object]:
        self.calls.append(("tool", str(payload["action"])))
        return {"status": "accepted", "action": payload["action"]}


def initialize_body(request_id: int = 1) -> dict[str, Any]:
    """MCP SDK initialize 최소 요청을 만든다."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "fixture-client", "version": "0.1.0"},
        },
    }


@pytest.mark.anyio
async def test_fastmcp_asgi_initialize_and_capability_roundtrip() -> None:
    backend = RoundtripBackend()
    headers = {"Accept": "application/json, text/event-stream"}

    server = create_fastmcp_server(backend)
    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            initialize = await client.post("/mcp", headers=headers, json=initialize_body())
            assert initialize.status_code == 200
            session_id = initialize.headers["mcp-session-id"]
            assert initialize.json()["result"]["serverInfo"]["name"] == "ai-mafia-mcp"

            initialized = await client.post(
                "/mcp",
                headers={**headers, "Mcp-Session-Id": session_id},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            assert initialized.status_code == 202

            async def rpc(method: str, params: dict[str, Any]) -> httpx.Response:
                return await client.post(
                    "/mcp",
                    headers={**headers, "Mcp-Session-Id": session_id},
                    json={"jsonrpc": "2.0", "id": method, "method": method, "params": params},
                )

            resource_uri = (
                "mafia://context/current/00000000-0000-4000-8000-000000000001/"
                "00000000-0000-4000-8000-000000000002"
            )
            resource = await rpc("resources/read", {"uri": resource_uri})
            tool = await rpc(
                "tools/call",
                {
                    "name": "submit_action",
                    "arguments": {
                        "action": "PASS",
                        "user_id": "00000000-0000-4000-8000-000000000002",
                        "game_id": "00000000-0000-4000-8000-000000000001",
                        "expected_state_version": 2,
                        "window_id": "00000000-0000-4000-8000-000000000003",
                        "idempotency_key": "00000000-0000-4000-8000-000000000004",
                    },
                },
            )
            prompt = await rpc("prompts/get", {"name": "agent_instruction", "arguments": {}})

            assert resource.status_code == 200
            assert resource.json()["result"]["contents"][0]["uri"] == resource_uri
            assert tool.status_code == 200
            assert "accepted" in tool.text
            assert prompt.status_code == 200
            assert "fixture agent instruction" in prompt.text
            assert backend.calls == [
                ("resource", resource_uri),
                ("tool", "PASS"),
                ("prompt", "agent_instruction"),
            ]


@pytest.mark.anyio
async def test_fastmcp_backend_failure_returns_jsonrpc_error() -> None:
    server = create_fastmcp_server(RoundtripBackend(fail_resource=True))
    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    headers = {"Accept": "application/json, text/event-stream"}

    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            initialize = await client.post("/mcp", headers=headers, json=initialize_body())
            session_id = initialize.headers["mcp-session-id"]
            response = await client.post(
                "/mcp",
                headers={**headers, "Mcp-Session-Id": session_id},
                json={
                    "jsonrpc": "2.0",
                "id": "resource-failure",
                "method": "resources/read",
                "params": {
                    "uri": "mafia://context/current/00000000-0000-4000-8000-000000000001/"
                    "00000000-0000-4000-8000-000000000002"
                },
                },
            )

            assert response.status_code == 200
            assert "error" in response.json()
