"""게임 MCP smoke JSON-RPC 계약을 검증한다."""

import json
import pytest

from starlette.testclient import TestClient

mcp = pytest.importorskip("mcp")
from mcp_server.mcp_1.server import streamable_http_app  # noqa: E402


def test_mcp_initialize_tools_and_proposal() -> None:
    """initialize·tools/list·tools/call의 최소 왕복을 검증한다."""

    with TestClient(streamable_http_app) as client:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        initialized = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}})
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == "ai-mafia-game"
        tools = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {item["name"] for item in tools.json()["result"]["tools"]}
        assert names == {"game_ping", "game_get_context", "game_submit_proposal"}
        proposal = client.post(
            "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "game_submit_proposal", "arguments": {"action": "PING", "expected_version": 1}}},
        )
        payload = json.loads(proposal.json()["result"]["content"][0]["text"])
        assert payload["accepted"] is True
