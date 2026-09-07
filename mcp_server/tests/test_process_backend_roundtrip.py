"""실제 Backend process와 최소 FastMCP process의 HTTP 왕복을 검증한다."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from backend.app.core.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = PROJECT_ROOT / "mcp_server"
HEADERS = {"Accept": "application/json, text/event-stream"}


def _free_port() -> int:
    """운영 서비스와 충돌하지 않는 loopback 임시 포트를 얻는다."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http(url: str) -> None:
    """두 process가 listen할 때까지 짧게 기다린다."""

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=0.5) as client:
                client.get(url)
            return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise AssertionError(f"process did not start: {url}")


def _jsonrpc(
    client: httpx.Client,
    endpoint: str,
    session_id: str,
    request_id: str,
    method: str,
    params: dict[str, object],
) -> httpx.Response:
    """고정된 MCP session header로 하나의 JSON-RPC 요청을 보낸다."""

    return client.post(
        endpoint,
        headers={**HEADERS, "Mcp-Session-Id": session_id},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def test_real_backend_and_fastmcp_process_roundtrip() -> None:
    """실제 두 process가 PostgreSQL 게임 context와 command까지 왕복한다."""

    backend_port = _free_port()
    mcp_port = _free_port()
    backend = subprocess.Popen(  # noqa: S603 - 테스트가 직접 구성한 로컬 프로세스만 실행한다.
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
        ],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "LLM_PROVIDER": "dummy",
            "MCP_SERVER_URL": f"http://127.0.0.1:{mcp_port}",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    mcp = subprocess.Popen(  # noqa: S603 - 테스트가 직접 구성한 로컬 MCP만 실행한다.
        [sys.executable, "-m", "mafia_game"],
        cwd=MCP_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(MCP_ROOT),
            "BACKEND_API_URL": f"http://127.0.0.1:{backend_port}",
            "MCP_LISTEN_HOST": "127.0.0.1",
            "MCP_LISTEN_PORT": str(mcp_port),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    user_id = uuid4()
    game_id = None
    try:
        _wait_for_http(f"http://127.0.0.1:{backend_port}/health")
        _wait_for_http(f"http://127.0.0.1:{mcp_port}/mcp")
        with httpx.Client(
            base_url=f"http://127.0.0.1:{backend_port}", timeout=10
        ) as backend_client:
            common_headers = {"X-User-Id": str(user_id)}
            created = backend_client.post(
                "/api/v1/games",
                headers={**common_headers, "Idempotency-Key": str(uuid4())},
                json={
                    "player_count": 6,
                    "ruleset_version": "mystery-v1",
                    "scenario_version": "scenario-v1",
                },
            )
            assert created.status_code == 201, created.text
            game_id = created.json()["data"]["game_id"]
            begun = backend_client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**common_headers, "Idempotency-Key": str(uuid4())},
                json={"type": "BEGIN_GAME", "expected_state_version": 1},
            )
            assert begun.status_code == 200, begun.text
            snapshot = backend_client.get(f"/api/v1/games/{game_id}", headers=common_headers)
            assert snapshot.status_code == 200, snapshot.text
            game_data = snapshot.json()["data"]
            # 첫 인간 차례는 중앙 AI worker가 소비할 수 없으므로 PASS 승인 증거가
            # 다른 process의 AI 진행 속도에 따라 stale 거부로 바뀌지 않아야 한다.
            human_id = game_data["me"]["player_id"]
            assert game_data["action_window"]["turn_player_id"] == human_id
            state_version = game_data["game"]["state_version"]
            window_id = game_data["action_window"]["window_id"]
            action_key = str(uuid4())
        initialize_body = {
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "process-fixture", "version": "1.0"},
            },
        }
        with httpx.Client(
            base_url=f"http://127.0.0.1:{mcp_port}", timeout=10
        ) as client:
            initialized = client.post("/mcp", headers=HEADERS, json=initialize_body)
            assert initialized.status_code == 200
            session_id = initialized.headers["Mcp-Session-Id"]

            notification = client.post(
                "/mcp",
                headers={**HEADERS, "Mcp-Session-Id": session_id},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            assert notification.status_code == 202

            resource = _jsonrpc(
                client,
                "/mcp",
                session_id,
                "resource",
                "resources/read",
                {"uri": f"mafia://context/current/{game_id}/{user_id}"},
            )
            prompt = _jsonrpc(
                client,
                "/mcp",
                session_id,
                "prompt",
                "prompts/get",
                {
                    "name": "agent_instruction",
                    "arguments": {},
                },
            )
            action = _jsonrpc(
                client,
                "/mcp",
                session_id,
                "action",
                "tools/call",
                {
                    "name": "submit_action",
                    "arguments": {
                        "action": "PASS",
                        "user_id": str(user_id),
                        "game_id": game_id,
                        "expected_state_version": state_version,
                        "window_id": window_id,
                        "idempotency_key": action_key,
                    },
                },
            )

        assert resource.status_code == 200
        resource_payload = json.loads(resource.json()["result"]["contents"][0]["text"])
        assert resource_payload["game_id"] == game_id
        assert resource_payload["subject_type"] == "GM"
        assert resource_payload["subject_id"] == game_id
        assert resource_payload["scope"] == "public"
        assert resource_payload["state_version"] == state_version
        assert resource_payload["window_id"] == window_id
        assert "me" not in resource_payload["data"]
        assert prompt.status_code == 200
        assert "게임 context" in prompt.json()["result"]["messages"][0]["content"]["text"]
        assert action.status_code == 200
        action_result = action.json()["result"]
        assert action_result.get("isError") is False
        accepted = json.loads(action_result["content"][0]["text"])
        assert accepted["accepted"] is True
        assert accepted["replayed"] is False
        receipt = accepted["result"]
        assert receipt["command_id"] == action_key
        assert receipt["command_type"] == "PASS"
        assert receipt["accepted_state_version"] == state_version
        assert receipt["result_state_version"] == state_version + 1
        with httpx.Client(base_url=f"http://127.0.0.1:{backend_port}", timeout=10) as client:
            after = client.get(f"/api/v1/games/{game_id}", headers=common_headers)
        assert after.status_code == 200
        after_data = after.json()["data"]
        assert after_data["game"]["state_version"] >= receipt["result_state_version"]
        assert after_data["action_window"]["window_id"] != window_id
        assert any(
            event["event_type"] == "PLAYER_PASSED" and event["data"]["player_id"] == human_id
            for event in after_data["public_events"]
        )
    finally:
        for process in (mcp, backend):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if game_id is not None:
            with psycopg.connect(get_settings().effective_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM public.games WHERE id = %s", (game_id,))
                    cursor.execute("DELETE FROM public.users WHERE id = %s", (user_id,))
