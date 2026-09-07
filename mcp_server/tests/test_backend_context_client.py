"""최소 Backend adapter가 고정 endpoint를 호출하는지 검증한다."""

from __future__ import annotations

import json

import httpx
import pytest

from mafia_game.integrations.engine_http import (
    BackendContextError,
    MinimalBackendContextClient,
)


@pytest.mark.anyio
async def test_minimal_adapter_forwards_resource_prompt_and_action() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/internal/mcp/context":
            return httpx.Response(200, json={"status": "ok", "context": {}})
        if request.url.path == "/internal/mcp/prompts/agent_instruction":
            return httpx.Response(200, json={"prompt": "fixture instruction"})
        assert request.url.path == "/internal/mcp/actions"
        assert json.loads(request.content)["action"] == "PASS"
        return httpx.Response(200, json={"status": "accepted", "accepted": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)

    assert await adapter.read_resource(
        "mafia://context/current/00000000-0000-4000-8000-000000000001/00000000-0000-4000-8000-000000000002"
    ) == {
        "status": "ok",
        "context": {},
    }
    assert await adapter.get_prompt("agent_instruction", {}) == "fixture instruction"
    assert await adapter.submit_action(
        action="PASS",
        user_id="00000000-0000-4000-8000-000000000002",
        game_id="00000000-0000-4000-8000-000000000001",
        expected_state_version="2",
        window_id="00000000-0000-4000-8000-000000000003",
        idempotency_key="00000000-0000-4000-8000-000000000004",
        target_player_id=None,
        message=None,
    ) == {
        "status": "accepted",
        "accepted": True,
    }
    assert [request.url.path for request in requests] == [
        "/internal/mcp/context",
        "/internal/mcp/prompts/agent_instruction",
        "/internal/mcp/actions",
    ]
    await client.aclose()


@pytest.mark.anyio
async def test_minimal_adapter_rejects_backend_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500, json={"error": "failed"}))
    )
    adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)

    with pytest.raises(BackendContextError):
        await adapter.read_resource("mafia://context/current/invalid/invalid")
    await client.aclose()
