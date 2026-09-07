"""WU-SCC-03 최소 FastMCP Backend endpoint 계약 테스트."""

from fastapi.testclient import TestClient

from backend.app.main import create_app


USER_ID = "00000000-0000-4000-8000-000000000002"
GAME_ID = "00000000-0000-4000-8000-000000000001"
WINDOW_ID = "00000000-0000-4000-8000-000000000003"


class FakeMcpRuntime:
    """MCP endpoint의 HTTP 계약만 검증하기 위한 게임 runtime 대역이다."""

    def snapshot(self, user_id, game_id):
        """실제 게임 규칙 없이 요청된 식별자를 context에 반영한다."""

        return {"game": {"game_id": str(game_id)}, "me": {"player_id": str(user_id)}}

    def command(self, user_id, game_id, payload, idempotency_key):
        """Backend command 위임 인자를 확인할 수 있는 synthetic 결과를 반환한다."""

        return (
            {
                "type": payload.type,
                "user_id": str(user_id),
                "game_id": str(game_id),
                "idempotency_key": str(idempotency_key),
            },
            False,
        )


def _client() -> TestClient:
    """실제 게임 runtime과 분리된 MCP endpoint 테스트 앱을 만든다."""

    application = create_app(enable_background_worker=False)
    application.state.game_runtime = FakeMcpRuntime()
    return TestClient(application)


def test_mcp_context_prompt_and_action_endpoints_use_game_contract() -> None:
    """세 endpoint가 실제 runtime 위임에 필요한 입력을 전달하는지 확인한다."""

    client = _client()

    context = client.get(f"/internal/mcp/context?game_id={GAME_ID}&user_id={USER_ID}")
    assert context.status_code == 200
    assert context.json()["status"] == "ok"
    assert context.json()["context"]["game"]["game_id"] == GAME_ID

    prompt = client.get("/internal/mcp/prompts/agent_instruction")
    assert prompt.status_code == 200
    assert "게임 context" in prompt.json()["prompt"]

    action = client.post(
        "/internal/mcp/actions",
        json={
            "action": "PASS",
            "user_id": USER_ID,
            "game_id": GAME_ID,
            "expected_state_version": 2,
            "window_id": WINDOW_ID,
            "idempotency_key": "00000000-0000-4000-8000-000000000004",
        },
    )
    assert action.status_code == 200
    assert action.json()["accepted"] is True
    assert action.json()["result"]["type"] == "PASS"


def test_minimal_mcp_action_rejects_unknown_fields_with_common_error_envelope() -> None:
    """MCP가 추가 필드를 몰래 전달하지 못하고 Backend 검증 오류를 반환하는지 확인한다."""

    response = _client().post(
        "/internal/mcp/actions",
        json={"action": "PASS", "unexpected": "not-allowed"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "detail" not in response.json()["error"]


def test_minimal_mcp_unknown_prompt_returns_common_error_envelope() -> None:
    """등록되지 않은 Prompt가 framework 기본 detail 형식으로 노출되지 않는지 확인한다."""

    response = _client().get("/internal/mcp/prompts/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROMPT_NOT_FOUND"
    assert "detail" not in response.json()
