"""FastMCP scoped Resource와 실제 Tool 성공의 부정·왕복 경계를 검증한다."""

import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest

from backend.app.mcp.client import FastMcpGameContextClient, _json_object, _utc_time

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
               "alibi": "합성 알리바이입니다.", "observation": "합성 관찰입니다.", "private_events": []},
        "turn": {"window_id": str(WINDOW), "window_kind": "SPEECH", "cycle": 1,
                 "opened_state_version": 2,
                 "server_time": datetime(2026, 9, 7, microsecond=123456, tzinfo=timezone.utc).isoformat(),
                 "deadline_at": None,
                 "turn_player_id": str(ACTOR), "allowed_tools": ["propose_speech", "propose_pass"], "valid_targets": []},
        "persona": {"persona_id": "synthetic", "version": "v1", "display_name": "AI",
                    "speech_style": "차분함", "backstory": "합성 설정", "parameters": {}},
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
