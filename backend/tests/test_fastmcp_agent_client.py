"""실제 FastMCP Agent client의 session·context·action 왕복을 검증한다."""

import json
from uuid import UUID

import httpx
import pytest

from backend.app.mcp.client import FastMcpGameContextClient


@pytest.mark.anyio
async def test_fastmcp_agent_client_reads_context_and_submits_action() -> None:
    """Agent client가 FastMCP session을 열고 같은 게임 command를 전달하는지 확인한다."""

    requests: list[dict] = []
    context = {
        "game": {"game_id": "00000000-0000-4000-8000-000000000001", "state_version": 2},
        "action_window": {"window_id": "00000000-0000-4000-8000-000000000003"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"mcp-session-id": "agent-session"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "resources/read":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"contents": [{"text": json.dumps(context)}]},
                },
            )
        assert method == "tools/call"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"text": json.dumps({"accepted": True})}],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = FastMcpGameContextClient(
            "http://127.0.0.1:8100",
            user_id=UUID("00000000-0000-4000-8000-000000000002"),
            game_id=UUID("00000000-0000-4000-8000-000000000001"),
            client=http_client,
        )
        read = await client.read_context(
            game_id=UUID("00000000-0000-4000-8000-000000000001"),
            player_id=UUID("00000000-0000-4000-8000-000000000004"),
        )
        result = await client.submit_action(
            game_id=UUID("00000000-0000-4000-8000-000000000001"),
            player_id=UUID("00000000-0000-4000-8000-000000000004"),
            action={"type": "PASS"},
        )

    assert read == context
    assert result == {"accepted": True}
    assert [item["method"] for item in requests] == [
        "initialize",
        "notifications/initialized",
        "resources/read",
        "tools/call",
    ]
    assert requests[-1]["params"]["arguments"]["expected_state_version"] == 2
