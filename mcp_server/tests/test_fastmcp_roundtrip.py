"""WU-FMCP-03 FastMCP ASGI 왕복 테스트."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mafia_game.integrations.engine_http import MinimalBackendContextClient
from mafia_game.main import create_fastmcp_server
from mafia_game.api.prompts.instructions import role_instruction


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
        return {"status": "accepted", "accepted": True, "action": payload["action"]}


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
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/internal/mcp/context":
            return httpx.Response(200, json={"fixture_query": dict(request.url.params)})
        if request.url.path == "/internal/mcp/special-roles":
            assert dict(request.url.params) == {
                "user_id": "00000000-0000-4000-8000-000000000002",
                "game_id": "00000000-0000-4000-8000-000000000001",
            }
            return httpx.Response(200, json={
                "game_id": "00000000-0000-4000-8000-000000000001",
                "player_id": "00000000-0000-4000-8000-000000000003",
                "ability_id": "intel.special_roles.v1",
                "state_version": 8,
                "roles": [{
                    "player_id": "00000000-0000-4000-8000-000000000005",
                    "display_name": "합성 탐정",
                    "role": "DETECTIVE",
                    "alive": False,
                }],
            })
        assert request.url.path == "/internal/mcp/actions"
        payload = json.loads(request.content)
        if payload["action"] == "VOTE":
            assert payload == {
                "action": "VOTE", "ability_id": "vote.triple.v1",
                "user_id": "00000000-0000-4000-8000-000000000002",
                "game_id": "00000000-0000-4000-8000-000000000001",
                "expected_state_version": "8",
                "window_id": "00000000-0000-4000-8000-000000000003",
                "idempotency_key": "00000000-0000-4000-8000-000000000004",
                "target_player_id": "00000000-0000-4000-8000-000000000005",
            }
        else:
            assert payload["action"] == "PASS"
        return httpx.Response(200, json={"accepted": True})

    backend_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = MinimalBackendContextClient("http://127.0.0.1:8000", client=backend_http)
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
            assert resource.status_code == 200
            resource_content = resource.json()["result"]["contents"][0]
            assert resource_content["uri"] == resource_uri
            assert resource_content["mimeType"] == "application/json"
            assert json.loads(resource_content["text"]) == {
                "fixture_query": {
                    "game_id": "00000000-0000-4000-8000-000000000001",
                    "user_id": "00000000-0000-4000-8000-000000000002",
                    "scope": "public",
                },
            }
            for scope in ("public", "me", "turn", "persona"):
                scoped_uri = (
                    "mafia://context/scoped/00000000-0000-4000-8000-000000000001/"
                    "00000000-0000-4000-8000-000000000002/"
                    f"00000000-0000-4000-8000-000000000003/{scope}"
                )
                scoped = await rpc("resources/read", {"uri": scoped_uri})
                assert scoped.status_code == 200
                scoped_content = scoped.json()["result"]["contents"][0]
                assert scoped_content["uri"] == scoped_uri
                assert scoped_content["mimeType"] == "application/json"
                assert json.loads(scoped_content["text"]) == {
                    "fixture_query": {
                        "game_id": "00000000-0000-4000-8000-000000000001",
                        "user_id": "00000000-0000-4000-8000-000000000002",
                        "player_id": "00000000-0000-4000-8000-000000000003",
                        "scope": scope,
                    },
                }
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

            assert tool.status_code == 200
            tool_result = tool.json()["result"]
            assert tool_result.get("isError") is False
            assert json.loads(tool_result["content"][0]["text"])["accepted"] is True
            assert prompt.status_code == 200
            assert prompt.json()["result"]["messages"][0]["content"]["text"] == (
                role_instruction("CITIZEN", "DAY_DISCUSSION")
            )
            manipulated_vote = await rpc("tools/call", {
                "name": "manipulate_vote",
                "arguments": {
                    "user_id": "00000000-0000-4000-8000-000000000002",
                    "game_id": "00000000-0000-4000-8000-000000000001",
                    "expected_state_version": 8,
                    "window_id": "00000000-0000-4000-8000-000000000003",
                    "idempotency_key": "00000000-0000-4000-8000-000000000004",
                    "target_player_id": "00000000-0000-4000-8000-000000000005",
                },
            })
            assert manipulated_vote.json()["result"]["isError"] is False
            special_roles = await rpc("tools/call", {
                "name": "inspect_special_roles",
                "arguments": {
                    "user_id": "00000000-0000-4000-8000-000000000002",
                    "game_id": "00000000-0000-4000-8000-000000000001",
                },
            })
            assert special_roles.json()["result"]["isError"] is False
            roles_result = json.loads(special_roles.json()["result"]["content"][0]["text"])
            assert roles_result["roles"] == [{
                "player_id": "00000000-0000-4000-8000-000000000005",
                "display_name": "합성 탐정", "role": "DETECTIVE", "alive": False,
            }]
            assert [request.url.path for request in requests] == [
                *(["/internal/mcp/context"] * 5),
                "/internal/mcp/actions", "/internal/mcp/actions", "/internal/mcp/special-roles",
            ]
    await backend_http.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", ["manipulate_vote", "inspect_special_roles"])
@pytest.mark.parametrize("extra_arguments", [
    pytest.param({"player_id": "00000000-0000-4000-8000-000000000099"}, id="actor"),
    pytest.param({"weight": 999}, id="weight"),
    pytest.param({"ability_id": "night.attack.v1"}, id="ability"),
    pytest.param({"action": "ATTACK"}, id="action"),
    pytest.param({
        "player_id": "00000000-0000-4000-8000-000000000099",
        "weight": 999,
        "ability_id": "night.attack.v1",
        "action": "ATTACK",
        "actor": "ADMIN",
        "role": "GM",
        "source": "HUMAN",
        "is_admin": True,
        "permissions": ["*"],
        "day_number": 99,
    }, id="combined-authority-injection"),
])
async def test_human_tool_asgi_ignores_extra_authority_arguments(
    tool_name: str, extra_arguments: dict[str, Any],
) -> None:
    """실제 tools/call의 추가 인수는 무시되며 Backend 최소 요청을 확장할 수 없다.

    현재 FastMCP의 무시 정책을 성공 응답과 정확한 HTTP 요청으로 함께 고정한다.
    actor·권한·해금 판정은 Backend에 남기고 공격 인수가 투표 고정값을 덮거나
    조회 query·본문으로 우회 전달되는 경우도 전체 payload 비교로 탐지한다.
    """

    requests: list[httpx.Request] = []
    arguments: dict[str, Any] = {
        "user_id": "00000000-0000-4000-8000-000000000002",
        "game_id": "00000000-0000-4000-8000-000000000001",
    }
    if tool_name == "manipulate_vote":
        arguments.update({
            "expected_state_version": 8,
            "window_id": "00000000-0000-4000-8000-000000000003",
            "idempotency_key": "00000000-0000-4000-8000-000000000004",
            "target_player_id": "00000000-0000-4000-8000-000000000005",
        })

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if tool_name == "manipulate_vote":
            return httpx.Response(200, json={"accepted": True})
        return httpx.Response(200, json={
            "game_id": arguments["game_id"],
            "player_id": "00000000-0000-4000-8000-000000000003",
            "ability_id": "intel.special_roles.v1",
            "state_version": 8,
            "roles": [],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend_http:
        backend = MinimalBackendContextClient("http://127.0.0.1:8000", client=backend_http)
        server = create_fastmcp_server(backend)
        app = server.streamable_http_app()
        headers = {"Accept": "application/json, text/event-stream"}
        async with server.session_manager.run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                initialized = await client.post("/mcp", headers=headers, json=initialize_body())
                assert initialized.status_code == 200
                headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
                notification = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized",
                })
                assert notification.status_code == 202
                response = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": "extra-authority", "method": "tools/call",
                    "params": {
                        "name": tool_name, "arguments": {**arguments, **extra_arguments},
                    },
                })

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert len(requests) == 1
    request = requests[0]
    if tool_name == "manipulate_vote":
        assert request.method == "POST"
        assert request.url.path == "/internal/mcp/actions"
        assert not request.url.query
        assert json.loads(request.content) == {
            **arguments,
            "expected_state_version": "8",
            "action": "VOTE",
            "ability_id": "vote.triple.v1",
        }
        assert json.loads(result["content"][0]["text"]) == {"accepted": True}
    else:
        assert request.method == "GET"
        assert request.url.path == "/internal/mcp/special-roles"
        assert list(request.url.params.multi_items()) == list(arguments.items())
        assert request.content == b""
        assert json.loads(result["content"][0]["text"])["player_id"] == (
            "00000000-0000-4000-8000-000000000003"
        )


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", ["manipulate_vote", "inspect_special_roles"])
@pytest.mark.parametrize("status", [403, 404, 409])
async def test_human_tool_asgi_denial_redacts_backend_body(tool_name, status, caplog) -> None:
    """HUMAN 전용 권한 거부는 Tool 오류로 전달하고 Backend 비공개 본문을 숨긴다."""

    marker = "SYNTHETIC_PRIVATE_ABILITY_DETAIL"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json={"error": marker})
    )) as backend_http:
        backend = MinimalBackendContextClient("http://127.0.0.1:8000", client=backend_http)
        server = create_fastmcp_server(backend)
        app = server.streamable_http_app()
        headers = {"Accept": "application/json, text/event-stream"}
        async with server.session_manager.run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                initialized = await client.post("/mcp", headers=headers, json=initialize_body())
                headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
                arguments = {
                    "user_id": "00000000-0000-4000-8000-000000000002",
                    "game_id": "00000000-0000-4000-8000-000000000001",
                }
                if tool_name == "manipulate_vote":
                    arguments.update({
                        "expected_state_version": 8,
                        "window_id": "00000000-0000-4000-8000-000000000003",
                        "idempotency_key": "00000000-0000-4000-8000-000000000004",
                        "target_player_id": "00000000-0000-4000-8000-000000000005",
                    })
                response = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": "ability-denial", "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                })
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    assert f"MCP_BACKEND_HTTP_{status}" in response.text
    assert marker not in response.text
    assert marker not in caplog.text


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
