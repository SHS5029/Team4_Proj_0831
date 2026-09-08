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
SPECIAL_PLAYER_ID = "00000000-0000-4000-8000-000000000004"


def special_roles_payload() -> dict[str, object]:
    """본인과 다른 특수 직업 한 명만 포함한 합성 비공개 응답을 만든다."""

    return {
        "game_id": GAME_ID,
        "player_id": PLAYER_ID,
        "ability_id": "intel.special_roles.v1",
        "state_version": 8,
        "roles": [{
            "player_id": SPECIAL_PLAYER_ID,
            "display_name": "합성 탐정",
            "role": "DETECTIVE",
            "alive": True,
        }],
    }


@pytest.mark.anyio
async def test_special_roles_query_binds_owner_and_game_without_actor_argument() -> None:
    """소유자 UUID만 전달하고 생사와 관계없이 Backend가 허용한 특수 직업을 보존한다."""

    requests: list[httpx.Request] = []
    payload = special_roles_payload()
    payload["roles"].append({
        "player_id": "00000000-0000-4000-8000-000000000005",
        "display_name": "합성 의사",
        "role": "DOCTOR",
        "alive": False,
    })

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        for _ in range(2):
            assert await adapter.inspect_special_roles(user_id=USER_ID, game_id=GAME_ID) == payload

    assert len(requests) == 2
    assert all(request.method == "GET" for request in requests)
    assert all(request.url.path == "/internal/mcp/special-roles" for request in requests)
    assert all(dict(request.url.params) == {"user_id": USER_ID, "game_id": GAME_ID}
               for request in requests)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["user_id", "game_id"])
@pytest.mark.parametrize("invalid", [None, 1, "", "invalid", GAME_ID.replace("-", ""),
                                      f"{GAME_ID}?player_id={PLAYER_ID}"])
async def test_special_roles_invalid_uuid_never_calls_backend(field, invalid) -> None:
    """쿼리 조작과 비정규 UUID는 비공개 조회 HTTP 요청 전에 차단한다."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=special_roles_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        arguments = {"user_id": USER_ID, "game_id": GAME_ID, field: invalid}
        with pytest.raises(BackendContextError):
            await adapter.inspect_special_roles(**arguments)
    assert requests == []


@pytest.mark.anyio
@pytest.mark.parametrize("change", [
    {"game_id": SPECIAL_PLAYER_ID},
    {"player_id": "invalid"},
    {"ability_id": "night.investigate.v1"},
    {"state_version": True},
    {"state_version": 0},
    {"state_version": -1},
    {"roles": None},
    {"roles": {}},
    {"private_state": "SYNTHETIC_PRIVATE_EXTRA"},
])
async def test_special_roles_rejects_invalid_envelope_without_payload_in_error(change) -> None:
    """다른 게임 응답·비공개 추가 필드·원시 타입 위반을 오류 원문 없이 거부한다."""

    payload = {**special_roles_payload(), **change}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError) as captured:
            await adapter.inspect_special_roles(user_id=USER_ID, game_id=GAME_ID)

    assert captured.value.code == "MCP_BACKEND_INVALID_RESPONSE"
    rendered = "".join(traceback.format_exception(captured.value))
    assert "SYNTHETIC_PRIVATE_EXTRA" not in rendered
    assert GAME_ID not in rendered


@pytest.mark.anyio
@pytest.mark.parametrize("change", [
    {"player_id": PLAYER_ID},
    {"player_id": "invalid"},
    {"role": "MAFIA"},
    {"role": "CITIZEN"},
    {"role": "CUSTOM_ROLE"},
    {"role": []},
    {"display_name": ""},
    {"display_name": "\ud800"},
    {"alive": 1},
    {"alive": "true"},
    {"faction": "SYNTHETIC_PRIVATE_FACTION"},
])
async def test_special_roles_rejects_self_non_special_and_private_row_fields(change) -> None:
    """본인·기본 직업·숨겨진 부가 정보는 최종 Tool 출력으로 전달하지 않는다."""

    payload = special_roles_payload()
    payload["roles"][0].update(change)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=json.dumps(payload).encode("utf-8"))
        )
    ) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError) as captured:
            await adapter.inspect_special_roles(user_id=USER_ID, game_id=GAME_ID)

    assert captured.value.code == "MCP_BACKEND_INVALID_RESPONSE"
    assert "SYNTHETIC_PRIVATE_FACTION" not in "".join(traceback.format_exception(captured.value))


@pytest.mark.anyio
async def test_special_roles_rejects_duplicate_players() -> None:
    """같은 플레이어를 서로 다른 역할로 반복한 모순된 비공개 응답을 거부한다."""

    payload = special_roles_payload()
    payload["roles"].append({**payload["roles"][0], "role": "DOCTOR"})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError, match="MCP_BACKEND_INVALID_RESPONSE"):
            await adapter.inspect_special_roles(user_id=USER_ID, game_id=GAME_ID)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 404, 409])
async def test_special_roles_denial_hides_backend_private_body(status) -> None:
    """능력·소유권·첫 밤 거부 시 Backend의 비공개 오류 본문은 노출하지 않는다."""

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json={"error": "SYNTHETIC_PRIVATE_ROLE"})
    )) as client:
        adapter = MinimalBackendContextClient("http://127.0.0.1:8000", client=client)
        with pytest.raises(BackendContextError) as captured:
            await adapter.inspect_special_roles(user_id=USER_ID, game_id=GAME_ID)
    assert captured.value.code == f"MCP_BACKEND_HTTP_{status}"
    assert "SYNTHETIC_PRIVATE_ROLE" not in "".join(traceback.format_exception(captured.value))


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
