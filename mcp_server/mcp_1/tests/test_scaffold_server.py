"""게임 MCP smoke JSON-RPC 계약을 검증한다."""

import pytest

from fastapi.testclient import TestClient

mcp = pytest.importorskip("mcp")
from mcp_server.mcp_1.server import app  # noqa: E402


def test_mcp_initialize_tools_and_proposal() -> None:
    """initialize·tools/list·tools/call의 최소 왕복을 검증한다."""

    client = TestClient(app)
    initialized = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "ai-mafia-game"
    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {item["name"] for item in tools.json()["result"]["tools"]}
    assert names == {"game_ping", "game_get_context", "game_submit_proposal"}
    proposal = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "game_submit_proposal", "arguments": {"action": "PING", "expected_version": 1}}},
    )
    assert proposal.json()["result"]["content"][0]["text"]["accepted"] is True
