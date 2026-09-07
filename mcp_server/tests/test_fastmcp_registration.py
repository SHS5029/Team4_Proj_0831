"""WU-FMCP-02 FastMCP 등록부의 Backend 위임 테스트."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mafia_game.main import create_fastmcp_server


class FakeBackend:
    """실제 네트워크 없이 등록부의 호출 경계를 확인하는 합성 Backend다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def read_resource(self, uri: str) -> dict[str, Any]:
        self.calls.append(("resource", uri))
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


@pytest.mark.anyio
async def test_fastmcp_registers_and_delegates_minimal_capabilities() -> None:
    backend = FakeBackend()
    server = create_fastmcp_server(backend)

    resources = await server.list_resources()
    resource_templates = await server.list_resource_templates()
    tools = await server.list_tools()
    prompts = await server.list_prompts()

    assert resources == []
    assert [item.uriTemplate for item in resource_templates] == [
        "mafia://context/current/{game_id}/{user_id}",
        "mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}",
    ]
    assert [item.mimeType for item in resource_templates] == [
        "application/json", "application/json",
    ]
    assert [item.name for item in tools] == ["submit_action"]
    assert [item.name for item in prompts] == ["agent_instruction"]

    resource = await server.read_resource(
        "mafia://context/current/00000000-0000-4000-8000-000000000001/00000000-0000-4000-8000-000000000002"
    )
    tool = await server.call_tool(
        "submit_action",
        {
            "action": "PASS",
            "user_id": "00000000-0000-4000-8000-000000000002",
            "game_id": "00000000-0000-4000-8000-000000000001",
            "expected_state_version": 2,
            "window_id": "00000000-0000-4000-8000-000000000003",
            "idempotency_key": "00000000-0000-4000-8000-000000000004",
        },
    )
    prompt = await server.get_prompt("agent_instruction", {})

    assert resource[0].mime_type == "application/json"
    assert json.loads(resource[0].content) == {
        "session_id": "fixture-session",
        "phase": "DAY",
    }
    assert json.loads(tool[0][0].text) == {
        "status": "accepted", "accepted": True, "action": "PASS",
    }
    assert prompt.messages[0].content.text == "fixture agent instruction"
    assert backend.calls == [
        (
            "resource",
            "mafia://context/current/00000000-0000-4000-8000-000000000001/00000000-0000-4000-8000-000000000002",
        ),
        ("tool", "PASS"),
        ("prompt", "agent_instruction"),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["public", "me", "turn", "persona", "gm-guide"])
async def test_scoped_resource_preserves_actor_and_scope_for_backend(scope: str) -> None:
    backend = FakeBackend()
    server = create_fastmcp_server(backend)
    uri = (
        "mafia://context/scoped/00000000-0000-4000-8000-000000000001/"
        "00000000-0000-4000-8000-000000000002/00000000-0000-4000-8000-000000000003/"
        f"{scope}"
    )

    resource = await server.read_resource(uri)

    assert resource[0].mime_type == "application/json"
    assert json.loads(resource[0].content) == {"session_id": "fixture-session", "phase": "DAY"}
    assert backend.calls == [("resource", uri)]
