"""FastMCP scoped Resource와 실제 Tool 성공의 부정·왕복 경계를 검증한다."""

import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest

from backend.app.mcp.client import FastMcpGameContextClient, McpContextError, _json_object, _utc_time

GAME = UUID(int=1)
OWNER = UUID(int=2)
WINDOW = UUID(int=3)
ACTOR = UUID(int=4)


def context(scope):
    """서로 다른 scope를 같은 synthetic AI actor에 묶는 폐쇄형 입력이다."""

    data = {
        "public": {"game": {"game_id": str(GAME), "phase": "DAY_DISCUSSION", "state_version": 2},
                   "scenario": {}, "players": [], "public_events": []},
        "me": {"player_id": str(ACTOR), "role": "CITIZEN", "alive": True,
               "alibi": "합성 알리바이입니다.", "observation": "합성 관찰입니다.", "private_events": [],
               "agent_instruction": "합성 시민 지침"},
        "turn": {"window_id": str(WINDOW), "window_kind": "SPEECH", "cycle": 1,
                 "opened_state_version": 2,
                 "server_time": datetime(2026, 9, 7, microsecond=123456, tzinfo=timezone.utc).isoformat(),
                 "deadline_at": None,
                 "turn_player_id": str(ACTOR), "allowed_tools": ["propose_speech", "propose_pass"], "valid_targets": []},
        "persona": {"persona_id": "synthetic", "version": "v1", "display_name": "AI",
                    "speech_style": "차분함", "backstory": "합성 설정", "parameters": {},
                    "agent_instruction": "합성 말투 지침"},
    }[scope]
    return {"context_version": 1, "game_id": str(GAME), "subject_type": "AI_PLAYER", "subject_id": str(ACTOR),
            "phase": "DAY_DISCUSSION", "state_version": 2, "window_id": str(WINDOW), "scope": scope, "data": data}


def accepted():
    return {"status": "accepted", "source": "backend", "accepted": True, "replayed": False,
            "result": {"command_id": str(UUID(int=5)), "command_type": "PASS", "accepted_state_version": 2,
                       "result_state_version": 3, "sync_url": f"/api/v1/games/{GAME}/sync"}}


def transport(requests, *, mutate=None, tool=None):
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "synthetic-session"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "resources/read":
            uri = body["params"]["uri"]
            payload = context(uri.rsplit("/", 1)[-1])
            if mutate:
                mutate(payload)
            result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(payload)}]}
        else:
            assert method == "tools/call"
            result = tool if tool is not None else {"content": [{"text": json.dumps(accepted())}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
    return httpx.MockTransport(handler)


def client(http_client, *, phase="DAY_DISCUSSION"):
    return FastMcpGameContextClient("http://127.0.0.1:8100", user_id=OWNER, game_id=GAME,
                                   player_id=ACTOR, phase=phase, state_version=2, window_id=WINDOW,
                                   client=http_client)


@pytest.mark.anyio
@pytest.mark.parametrize("utc_suffix", ["+00:00", "Z"])
async def test_fastmcp_agent_client_reads_distinct_scopes_and_accepts_tool_receipt(utc_suffix):
    """실제 projection의 UTC 직렬화와 Z 표기 모두 persona·Tool 단계까지 도달한다."""

    def mutate(payload):
        if payload["scope"] == "turn":
            payload["data"]["server_time"] = (
                payload["data"]["server_time"].removesuffix("+00:00") + utc_suffix
            )

    requests = []
    async with httpx.AsyncClient(transport=transport(requests, mutate=mutate)) as http_client:
        adapter = client(http_client)
        read = await adapter.read_context(game_id=GAME, player_id=ACTOR)
        result = await adapter.submit_action(game_id=GAME, player_id=ACTOR, action={"type": "PASS"})
    assert result == accepted()
    assert list(read) == ["public", "me", "turn", "persona"]
    assert read["me"]["data"]["player_id"] == str(ACTOR)
    assert [body["params"]["uri"] for body in requests if body["method"] == "resources/read"] == [
        f"mafia://context/scoped/{GAME}/{OWNER}/{ACTOR}/{scope}" for scope in read]
    args = requests[-1]["params"]["arguments"]
    assert args["expected_state_version"] == 2 and args["window_id"] == str(WINDOW)


@pytest.mark.parametrize("fraction", ["", ".123456"])
def test_context_utc_time_equates_zero_offset_and_z(fraction):
    """초·마이크로초 정밀도에서 두 UTC 표기가 같은 aware 시각을 보존한다."""

    value = f"2026-09-07T00:00:00{fraction}"
    parsed = _utc_time(value + "+00:00")
    assert parsed == _utc_time(value + "Z")
    assert parsed.tzinfo == timezone.utc
    assert parsed.microsecond == (123456 if fraction else 0)


@pytest.mark.parametrize("value", [
    None, 0, "", "invalid", "2026-09-07T00:00:00", "2026-09-07T00:00:00+09:00",
    "2026-09-07T00:00:00-01:00", "2026-09-07T00:00:00-00:00",
    "2026-09-07T00:00:00+09:00Z", "2026-09-07T00:00:00+00:00Z",
    "2026-09-07T00:00:00+00:00:01", "2026-09-07 00:00:00+00:00",
    "20260907T000000Z", "2026-09-07T00:00Z", "2026-09-07T00:00:00,123Z",
    "2026-09-07T00:00:00Z\n", "2026-02-30T00:00:00Z", "2026-09-07T24:00:00+00:00",
])
def test_context_utc_time_rejects_naive_non_utc_and_malformed_values(value):
    """미지정·비UTC offset과 fromisoformat이 허용하는 비정본 입력을 거부한다."""

    with pytest.raises(ValueError):
        _utc_time(value)


@pytest.mark.anyio
@pytest.mark.parametrize("server_time,deadline_at,valid", [
    ("2026-09-07T00:00:00+00:00", "2026-09-07T00:00:20+00:00", True),
    ("2026-09-07T00:00:00Z", "2026-09-07T00:00:20+00:00", True),
    ("2026-09-07T00:00:00+00:00", "2026-09-07T00:00:20Z", True),
    ("2026-09-07T00:00:00Z", "2026-09-07T00:00:00+00:00", False),
    ("2026-09-07T00:00:01+00:00", "2026-09-07T00:00:00Z", False),
    ("2026-09-07T00:00:00", "2026-09-07T00:00:20+00:00", False),
    ("2026-09-07T00:00:00Z", "2026-09-07T00:00:20+09:00", False),
    ("2026-09-07T00:00:00Z", "invalid", False),
])
async def test_turn_context_preserves_deadline_validation(server_time, deadline_at, valid):
    """UTC 표기가 섞여도 투표 deadline의 미래 시각 조건과 거부 경계를 유지한다."""

    def mutate(payload):
        payload["phase"] = "DAY_VOTE"
        payload["data"].update(
            window_kind="VOTE", turn_player_id=None, allowed_tools=["propose_vote"],
            valid_targets=[{"player_id": str(UUID(int=6)), "display_name": "합성 후보"}],
            server_time=server_time, deadline_at=deadline_at,
        )

    async with httpx.AsyncClient(transport=transport([], mutate=mutate)) as http_client:
        adapter = client(http_client, phase="DAY_VOTE")
        if valid:
            result = await adapter.get_context(capability="", scope="turn")
            assert result["data"]["deadline_at"] == deadline_at
        else:
            with pytest.raises(RuntimeError, match="contract"):
                await adapter.get_context(capability="", scope="turn")
            assert adapter._last_context is None


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [
    ("game_id", str(UUID(int=90))), ("subject_id", str(OWNER)), ("subject_type", "GM"),
    ("window_id", str(UUID(int=91))), ("state_version", 3), ("state_version", True),
    ("phase", "NIGHT_ACTION"), ("scope", "me"), ("context_version", True), ("extra", "secret"),
])
async def test_context_rejects_cross_actor_stale_unknown_and_coerced_envelopes(field, value):
    requests = []
    async with httpx.AsyncClient(transport=transport(requests, mutate=lambda data: data.update({field: value}))) as http_client:
        with pytest.raises(RuntimeError, match="contract"):
            await client(http_client).get_context(capability="synthetic", scope="public")


@pytest.mark.anyio
async def test_client_rejects_unknown_scope_and_actor_without_network():
    requests = []
    async with httpx.AsyncClient(transport=transport(requests)) as http_client:
        adapter = client(http_client)
        with pytest.raises(ValueError):
            await adapter.get_context(capability="", scope="gm-guide")
        with pytest.raises(ValueError):
            await adapter.read_context(game_id=GAME, player_id=OWNER)
    assert requests == []


@pytest.mark.anyio
@pytest.mark.parametrize("tool", [
    {"isError": True, "content": [{"text": json.dumps(accepted())}]},
    {"content": [{"text": json.dumps({"accepted": True})}]},
    {"content": [{"text": json.dumps({**accepted(), "accepted": False})}]},
    {"content": [{"text": json.dumps({**accepted(), "result": {**accepted()["result"], "result_state_version": 2}})}]},
])
async def test_tool_error_or_incomplete_success_never_becomes_accepted(tool):
    async with httpx.AsyncClient(transport=transport([], tool=tool)) as http_client:
        adapter = client(http_client)
        await adapter.get_context(capability="", scope="turn")
        with pytest.raises(RuntimeError):
            await adapter.submit_action(game_id=GAME, player_id=ACTOR, action={"type": "PASS"})


def test_duplicate_json_members_are_rejected():
    with pytest.raises(ValueError):
        _json_object('{"state_version":2,"state_version":3}')


@pytest.mark.anyio
async def test_unknown_data_field_never_reaches_provider():
    def mutate(payload):
        payload["data"]["agent_activity"] = [{"summary": "synthetic"}]
    async with httpx.AsyncClient(transport=transport([], mutate=mutate)) as http_client:
        with pytest.raises(RuntimeError):
            await client(http_client).get_context(capability="", scope="public")


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["me", "persona"])
@pytest.mark.parametrize("value", [None, 42, "가" * 2401])
async def test_mcp_instruction_rejects_missing_invalid_and_oversized_values(scope, value):
    """구버전 MCP나 잘못된 지침을 조용히 모델에 전달하지 않는다."""

    def mutate(payload):
        if value is None:
            payload["data"].pop("agent_instruction")
        else:
            payload["data"]["agent_instruction"] = value

    async with httpx.AsyncClient(transport=transport([], mutate=mutate)) as http_client:
        with pytest.raises(RuntimeError, match="contract"):
            await client(http_client).get_context(capability="", scope=scope)


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["me", "persona"])
async def test_only_persona_instruction_may_be_empty(scope):
    """말투 생략은 허용하되 역할 전략 없는 me는 거부한다."""

    def mutate(payload):
        payload["data"]["agent_instruction"] = ""

    async with httpx.AsyncClient(transport=transport([], mutate=mutate)) as http_client:
        adapter = client(http_client)
        if scope == "persona":
            assert (await adapter.get_context(capability="", scope=scope))["data"]["agent_instruction"] == ""
        else:
            with pytest.raises(RuntimeError, match="contract"):
                await adapter.get_context(capability="", scope=scope)


@pytest.mark.anyio
@pytest.mark.parametrize("failure,code,status", [
    ("timeout", "MCP_TIMEOUT", None),
    ("connect", "MCP_CONNECTION_ERROR", None),
    ("http", "MCP_HTTP_ERROR", 503),
    ("json", "MCP_INVALID_JSON", None),
    ("rpc", "MCP_RPC_ERROR", None),
])
async def test_context_failure_diagnostics_do_not_expose_remote_url_or_body(failure, code, status):
    """연결·응답 오류는 원문 대신 고정 코드와 필요한 HTTP 상태만 전달한다."""

    marker = "synthetic-private-response-marker"
    secret_url = f"https://synthetic.invalid/private?token={marker}"
    requests = []
    healthy = transport(requests)

    def handler(request):
        body = json.loads(request.content)
        if body["method"] != "resources/read":
            return healthy.handle_request(request)
        requests.append(body)
        if failure == "timeout":
            raise httpx.ReadTimeout(secret_url, request=request)
        if failure == "connect":
            raise httpx.ConnectError(secret_url, request=request)
        if failure == "http":
            return httpx.Response(503, text=secret_url)
        if failure == "json":
            return httpx.Response(200, text=f"{{invalid-json: {secret_url}")
        return httpx.Response(200, json={"jsonrpc": "1.0", "id": body["id"], "result": {"private": secret_url}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        adapter = client(http_client)
        with pytest.raises(McpContextError) as captured:
            await adapter.get_context(capability="", scope="public")
    assert captured.value.code == code
    assert captured.value.http_status == status
    assert marker not in str(captured.value)
    assert "synthetic.invalid" not in str(captured.value)
    assert adapter._last_context is None


@pytest.mark.anyio
@pytest.mark.parametrize("message,code,status", [
    ("Error reading resource synthetic-private-uri: MCP_BACKEND_HTTP_403", "MCP_BACKEND_HTTP_403", 403),
    ("Error reading resource synthetic-private-uri: MCP_BACKEND_TIMEOUT", "MCP_BACKEND_TIMEOUT", None),
    ("MCP_BACKEND_CONNECTION_ERROR", "MCP_BACKEND_CONNECTION_ERROR", None),
    ("MCP_BACKEND_INVALID_JSON", "MCP_BACKEND_INVALID_JSON", None),
    ("MCP_BACKEND_INVALID_RESPONSE", "MCP_BACKEND_INVALID_RESPONSE", None),
    ("MCP_BACKEND_ERROR", "MCP_BACKEND_ERROR", None),
    ("MCP_BACKEND_HTTP_999", "MCP_RPC_ERROR", None),
    ("MCP_BACKEND_HTTP_403\n", "MCP_RPC_ERROR", None),
    ("MCP_BACKEND_HTTP_403 synthetic-private-uri", "MCP_RPC_ERROR", None),
    ("synthetic-private-uri-MCP_BACKEND_HTTP_403", "MCP_RPC_ERROR", None),
    ("MCP_BACKEND_PRIVATE_synthetic-private-uri", "MCP_RPC_ERROR", None),
    ({"secret": "synthetic-private-uri"}, "MCP_RPC_ERROR", None),
])
async def test_rpc_error_accepts_only_fixed_backend_diagnostic_suffix(message, code, status):
    """FastMCP의 예외 포장에서도 허용한 마지막 코드만 추출하고 URI는 버린다."""

    healthy = transport([])

    def handler(request):
        body = json.loads(request.content)
        if body["method"] != "resources/read":
            return healthy.handle_request(request)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "error": {"code": -32603, "message": message, "data": "synthetic-private-uri"},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(McpContextError) as captured:
            await client(http_client).get_context(capability="", scope="persona")
    assert captured.value.code == code
    assert captured.value.http_status == status
    assert "synthetic-private-uri" not in str(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [
    {"id": True},
    {"id": 999},
    {"jsonrpc": "1.0"},
    {"result": None},
    {"error": "synthetic-private-rpc-error"},
    {"error": {"code": -32603}},
])
async def test_malformed_rpc_envelope_never_becomes_backend_diagnostic(changes):
    """RPC 연결 정보가 잘못되거나 오류 메시지가 없으면 외부 문자열을 사용하지 않는다."""

    healthy = transport([])

    def handler(request):
        body = json.loads(request.content)
        if body["method"] != "resources/read":
            return healthy.handle_request(request)
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": {}}
        payload.update(changes)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(McpContextError) as captured:
            await client(http_client).get_context(capability="", scope="public")
    assert captured.value.code == "MCP_RPC_ERROR"
    assert captured.value.http_status is None
    assert "synthetic-private-rpc-error" not in str(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize("failed_method", ["initialize", "notifications/initialized"])
async def test_failed_handshake_does_not_read_resource_or_mark_initialized(failed_method):
    """초기화 알림 거부를 무시하면 무효 세션으로 Resource를 읽으므로 즉시 중단한다."""

    requests = []
    healthy = transport(requests)
    fail = True

    def handler(request):
        body = json.loads(request.content)
        if fail and body["method"] == failed_method:
            requests.append(body)
            return httpx.Response(403, text="synthetic-private-handshake-body")
        return healthy.handle_request(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        adapter = client(http_client)
        with pytest.raises(McpContextError) as captured:
            await adapter.get_context(capability="", scope="public")
        assert captured.value.code == "MCP_HTTP_ERROR"
        assert captured.value.http_status == 403
        assert "synthetic-private-handshake-body" not in str(captured.value)
        assert not adapter._initialized
        assert "resources/read" not in [body["method"] for body in requests]

        fail = False
        result = await adapter.get_context(capability="", scope="public")
    assert result["scope"] == "public"
    assert adapter._initialized
    assert [body["method"] for body in requests].count("initialize") == 2
    assert [body["method"] for body in requests].count("resources/read") == 1


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["me", "persona"])
async def test_old_mcp_without_instruction_has_distinct_diagnostic(scope):
    """구형 MCP 계약 누락을 네트워크 장애와 구별하되 잘못된 응답은 계속 거부한다."""

    def mutate(payload):
        payload["data"].pop("agent_instruction")

    async with httpx.AsyncClient(transport=transport([], mutate=mutate)) as http_client:
        with pytest.raises(McpContextError, match="contract") as captured:
            await client(http_client).get_context(capability="", scope=scope)
    assert captured.value.code == "MCP_INSTRUCTION_MISSING"
    assert captured.value.http_status is None


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [
    ("phase", "NIGHT_ACTION"),
    ("state_version", 3),
    ("window_id", str(UUID(int=90))),
])
async def test_valid_but_outdated_context_binding_has_distinct_diagnostic(field, value):
    """다른 요청이 게임을 진행한 경우를 응답 형식 오류와 나눠 진단한다."""

    async with httpx.AsyncClient(transport=transport([], mutate=lambda payload: payload.update({field: value}))) as http_client:
        adapter = client(http_client)
        with pytest.raises(McpContextError, match="contract") as captured:
            await adapter.get_context(capability="", scope="turn")
    assert captured.value.code == "MCP_CONTEXT_STALE"
    assert captured.value.http_status is None
    assert adapter._last_context is None


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [("state_version", True), ("context_version", True), ("extra", "synthetic-private-field")])
async def test_invalid_context_shape_remains_contract_failure(field, value):
    """타입 강제 변환이나 미승인 필드 수용 없이 형식 오류를 고정 코드로 남긴다."""

    async with httpx.AsyncClient(transport=transport([], mutate=lambda payload: payload.update({field: value}))) as http_client:
        with pytest.raises(McpContextError, match="contract") as captured:
            await client(http_client).get_context(capability="", scope="public")
    assert captured.value.code == "MCP_CONTEXT_CONTRACT"
    assert captured.value.http_status is None
    assert "synthetic-private-field" not in str(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("backend_status,reasoning_skill", [(200, 0.6), (200, 0.75), (200, 0.8), (403, 0.8)])
async def test_actual_fastmcp_context_roundtrip_preserves_persona_or_safe_backend_failure(
    backend_status, reasoning_skill, anyio_backend,
):
    """실제 FastMCP 세션·오류 포장을 왕복하며 persona 전달과 403 진단 경계를 확인한다.

    Backend HTTP만 합성해 공유 DB나 유료 모델 없이 네 scope의 실제 등록부와 소비
    클라이언트를 연결한다. persona 단계의 거부는 본문을 버린 고정 코드로만 돌아온다.
    """

    from mafia_game.api.prompts.instructions import persona_instruction, role_instruction
    from mafia_game.integrations.engine_http import MinimalBackendContextClient
    from mafia_game.main import create_fastmcp_server

    scopes = []
    parameters = {"reasoning_skill": reasoning_skill, "sociability": 0.25}
    marker = "synthetic-secret-backend-persona-response"

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/internal/mcp/context"
        assert request.url.params["game_id"] == str(GAME)
        assert request.url.params["user_id"] == str(OWNER)
        assert request.url.params["player_id"] == str(ACTOR)
        scope = request.url.params["scope"]
        scopes.append(scope)
        if scope == "persona" and backend_status != 200:
            return httpx.Response(backend_status, text=marker)
        payload = context(scope)
        payload["data"].pop("agent_instruction", None)
        if scope == "persona":
            payload["data"]["parameters"] = parameters.copy()
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend_http:
        backend = MinimalBackendContextClient("http://127.0.0.1:18000", client=backend_http)
        server = create_fastmcp_server(backend)
        app = server.streamable_http_app()
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as mcp_http:
                adapter = client(mcp_http)
                if backend_status == 200:
                    result = await adapter.read_context(game_id=GAME, player_id=ACTOR)
                    assert list(result) == ["public", "me", "turn", "persona"]
                    assert result["persona"]["data"]["parameters"] == parameters
                    assert result["persona"]["data"]["agent_instruction"] == persona_instruction(parameters, "DAY_DISCUSSION")
                    assert result["me"]["data"]["agent_instruction"] == role_instruction("CITIZEN", "DAY_DISCUSSION")
                    assert result["public"]["data"]["rules"]
                    assert "alibi" not in result["me"]["data"]
                else:
                    with pytest.raises(McpContextError) as captured:
                        await adapter.read_context(game_id=GAME, player_id=ACTOR)
                    assert captured.value.code == "MCP_BACKEND_HTTP_403"
                    assert captured.value.http_status == 403
                    assert marker not in str(captured.value)
                    assert "mafia://" not in str(captured.value)
    assert scopes == ["public", "me", "turn", "persona"]
