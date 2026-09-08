"""최소 Backend adapter가 고정 endpoint를 호출하는지 검증한다."""

from __future__ import annotations

import json
import traceback

import httpx
import pytest

from mafia_game.integrations.engine_http import (
    BackendContextError,
    MinimalBackendContextClient,
)

GAME_ID = "00000000-0000-4000-8000-000000000001"
USER_ID = "00000000-0000-4000-8000-000000000002"
PLAYER_ID = "00000000-0000-4000-8000-000000000003"


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
        await adapter.read_resource(f"mafia://context/current/{GAME_ID}/{USER_ID}")
    await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 409, 429, 503])
async def test_backend_http_status_precedes_body_parsing(status: int) -> None:
    """HTML 오류 본문도 상태 코드로 구분하고 본문의 비공개 문자열은 숨긴다."""

    marker = "SYNTHETIC_PRIVATE_HTTP_BODY"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text=f"<html>{marker}</html>")
        )
    ) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError) as captured:
            await adapter.read_resource(f"mafia://context/current/{GAME_ID}/{USER_ID}")

    assert captured.value.code == f"MCP_BACKEND_HTTP_{status}"
    assert str(captured.value) == captured.value.code
    assert marker not in "".join(traceback.format_exception(captured.value))


@pytest.mark.anyio
@pytest.mark.parametrize("error_type, code", [
    (httpx.ConnectTimeout, "MCP_BACKEND_TIMEOUT"),
    (httpx.ReadTimeout, "MCP_BACKEND_TIMEOUT"),
    (httpx.ConnectError, "MCP_BACKEND_CONNECTION_ERROR"),
    (httpx.RemoteProtocolError, "MCP_BACKEND_CONNECTION_ERROR"),
    (httpx.TooManyRedirects, "MCP_BACKEND_ERROR"),
    (ValueError, "MCP_BACKEND_ERROR"),
])
async def test_backend_transport_failure_hides_external_exception(error_type, code: str) -> None:
    """timeout과 연결 실패를 구분하면서 예외 체인의 URL·본문 노출을 차단한다."""

    marker = "SYNTHETIC_PRIVATE_TRANSPORT_DETAIL"

    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(f"{request.url}?private={marker}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError) as captured:
            await adapter.read_resource(f"mafia://context/current/{GAME_ID}/{USER_ID}")

    assert captured.value.code == code
    assert str(captured.value) == code
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(captured.value))
    assert marker not in rendered
    assert GAME_ID not in rendered


@pytest.mark.anyio
@pytest.mark.parametrize("body, code", [
    (b'{"private":"SYNTHETIC_PRIVATE_JSON"', "MCP_BACKEND_INVALID_JSON"),
    (b'["SYNTHETIC_PRIVATE_JSON"]', "MCP_BACKEND_INVALID_RESPONSE"),
])
async def test_backend_success_response_validation_is_redacted(body: bytes, code: str) -> None:
    """HTTP 성공 뒤의 JSON 문법 오류와 object 계약 오류를 별도 코드로 남긴다."""

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError) as captured:
            await adapter.read_resource(f"mafia://context/current/{GAME_ID}/{USER_ID}")

    assert captured.value.code == code
    assert str(captured.value) == code
    assert "SYNTHETIC_PRIVATE_JSON" not in "".join(traceback.format_exception(captured.value))


@pytest.mark.parametrize("code", [None, 403, "SYNTHETIC_PRIVATE_ERROR", "MCP_BACKEND_HTTP_403\nPRIVATE"])
def test_backend_error_accepts_only_fixed_safe_codes(code) -> None:
    """호출자가 실수로 외부 문구를 넘겨도 오류 메시지는 고정 allowlist만 사용한다."""

    error = BackendContextError(code)
    assert str(error) == error.code == "MCP_BACKEND_ERROR"


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["public", "me", "turn", "persona", "gm-guide"])
async def test_scoped_resource_forwards_query_without_reprojecting(scope: str) -> None:
    requests: list[httpx.Request] = []
    payload = {"scope": scope, "subject_id": PLAYER_ID, "data": {"fixture": scope}}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        result = await adapter.read_resource(
            f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/{scope}"
        )

    assert result == payload
    assert len(requests) == 1
    assert requests[0].url.path == "/internal/mcp/context"
    assert dict(requests[0].url.params) == {
        "game_id": GAME_ID, "user_id": USER_ID, "player_id": PLAYER_ID, "scope": scope,
    }


@pytest.mark.anyio
async def test_current_resource_requests_only_public_without_actor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {
            "game_id": GAME_ID, "user_id": USER_ID, "scope": "public",
        }
        return httpx.Response(200, json={"scope": "public"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        assert await adapter.read_resource(
            f"mafia://context/current/{GAME_ID}/{USER_ID}"
        ) == {"scope": "public"}


@pytest.mark.anyio
@pytest.mark.parametrize("uri", [
    f"mafia://context/current/invalid/{USER_ID}",
    f"mafia://context/current/{GAME_ID}/invalid",
    f"mafia://context/current/{GAME_ID.replace('-', '')}/{USER_ID}",
    f"mafia://context/scoped/invalid/{USER_ID}/{PLAYER_ID}/me",
    f"mafia://context/scoped/{GAME_ID}/invalid/{PLAYER_ID}/me",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/invalid/me",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/unknown",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/ME",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/%6de",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/me?scope=public",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/me#fragment",
    f"mafia://context/scoped/{GAME_ID}/{USER_ID}/{PLAYER_ID}/me/extra",
    f"mafia://context/current/{GAME_ID}/{USER_ID}?player_id={PLAYER_ID}",
    f"mafia://context/other/{GAME_ID}/{USER_ID}",
])
async def test_invalid_resource_is_rejected_before_http(uri: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError):
            await adapter.read_resource(uri)
    assert requests == []


@pytest.mark.anyio
@pytest.mark.parametrize("arguments, expected", [
    ({"game_id": "", "user_id": ""}, {}),
    ({"game_id": GAME_ID, "user_id": ""}, {"game_id": GAME_ID}),
    ({"game_id": "", "user_id": USER_ID}, {"user_id": USER_ID}),
    ({"game_id": GAME_ID, "user_id": USER_ID}, {"game_id": GAME_ID, "user_id": USER_ID}),
])
async def test_optional_prompt_empty_uuid_is_omitted(arguments, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == expected
        return httpx.Response(200, json={"prompt": "fixture instruction"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        assert await adapter.get_prompt("agent_instruction", arguments) == "fixture instruction"


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [
    {"accepted": False},
    {"accepted": "false"},
    {"accepted": "true"},
    {"accepted": 1},
    {"status": "accepted"},
    {"error": "Error executing tool submit_action"},
    {"accepted": True, "error": "synthetic failure"},
    "Error executing tool submit_action",
])
async def test_action_http_200_requires_explicit_acceptance(payload) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError):
            await adapter.submit_action(action="PASS")
