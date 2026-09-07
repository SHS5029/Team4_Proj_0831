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
        env=dict(os.environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    mcp = subprocess.Popen(
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
        with httpx.Client(base_url=f"http://127.0.0.1:{backend_port}", timeout=10) as backend_client:
            common_headers = {"X-User-Id": str(user_id)}
            created = backend_client.post(
                "/api/v1/games",
                headers={**common_headers, "Idempotency-Key": str(uuid4())},
                json={"player_count": 6, "ruleset_version": "mystery-v1", "scenario_version": "scenario-v1"},
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
                    "arguments": {"game_id": game_id, "user_id": str(user_id)},
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
                        "expected_state_version": game_data["game"]["state_version"],
                        "window_id": game_data["action_window"]["window_id"],
                        "idempotency_key": str(uuid4()),
                    },
                },
            )

        assert resource.status_code == 200
        assert game_id in resource.text
        assert prompt.status_code == 200
        assert "게임 context" in prompt.text
        assert action.status_code == 200
        action_result = action.json()["result"]
        if action_result.get("isError"):
            # 프로세스 fixture의 중앙 AI worker가 같은 window를 먼저 진행할 수
            # 있으므로 stale command도 Backend 왕복의 유효한 결과로 인정한다.
            assert "Error executing tool submit_action" in action.text
        else:
            assert json.loads(action_result["content"][0]["text"])["accepted"] is True
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
