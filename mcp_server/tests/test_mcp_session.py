"""실제 MCP SDK client와 ASGI transport로 WU-M2 session 경계를 검증한다."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_bootstrap_token import CAPABILITY, NOW, SECRET, make_claims, sign

from mafia_game.core.security.errors import EngineConsumeDenied
from mafia_game.main import RuntimeSettings, create_app
from mafia_game.ports.engine_bootstrap import EngineBootstrapPort


@dataclass
class FakeEngine(EngineBootstrapPort):
    """실제 Backend 없이 consume 호출 횟수·입력과 거부 결과를 재현한다."""

    deny: bool = False
    after_consume: object | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    closed: bool = False

    async def consume(self, bootstrap_token: str, capability: str) -> None:
        self.calls.append((bootstrap_token, capability))
        if self.deny:
            raise EngineConsumeDenied
        if callable(self.after_consume):
            self.after_consume()

    async def aclose(self) -> None:
        """shutdown 순서 검증을 위해 client close 호출 여부만 기록한다."""

        self.closed = True


class InitialCapabilityAuth(httpx.Auth):
    """SDK의 첫 HTTP 요청에만 capability를 싣고 이후에는 bearer만 유지한다."""

    requires_request_body = True

    def __init__(self, token: str, capability: str) -> None:
        self.token = token
        self.capability = capability
        self.requests = 0

    def auth_flow(self, request: httpx.Request):  # type: ignore[no-untyped-def]
        request.headers["Authorization"] = f"Bearer {self.token}"
        if self.requests == 0:
            request.headers["X-Agent-Capability"] = self.capability
        self.requests += 1
        yield request


def settings() -> RuntimeSettings:
    return RuntimeSettings(
        mcp_server_auth_secret=SECRET,
        engine_internal_api_secret="synthetic-engine-hmac-secret-value",
        engine_api_url="https://engine.invalid",
    )


@asynccontextmanager
async def running_client(engine: FakeEngine) -> AsyncIterator[tuple[object, httpx.AsyncClient]]:
    app = create_app(settings(), engine=engine, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield app, client


@dataclass
class MutableClock:
    """만료 경계를 sleep 없이 이동시키는 테스트 전용 wall clock이다."""

    value: float = NOW

    def __call__(self) -> float:
        return self.value


@dataclass
class MutableMonotonic:
    """idle deadline을 실제 sleep 없이 경계 직후로 이동한다."""

    value: float = 100.0

    def __call__(self) -> float:
        return self.value


def initialize_body(request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1.0"},
        },
    }


def mcp_headers(token: str, *, capability: str | None = None) -> dict[str, str]:
    """직접 ASGI 요청도 MCP SDK와 동일한 content negotiation header를 사용한다."""

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    }
    if capability is not None:
        headers["X-Agent-Capability"] = capability
    return headers


def tamper_signature(token: str) -> str:
    """서명 표현은 canonical로 유지하면서 실제 HMAC byte 하나만 변경한다."""

    encoded_payload, encoded_signature = token.split(".")
    signature = bytearray(
        base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
    )
    signature[0] ^= 1
    changed = base64.urlsafe_b64encode(bytes(signature)).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{changed}"


@pytest.mark.anyio
async def test_sdk_initialize_consumes_once_and_delete_cleans_session() -> None:
    engine = FakeEngine()
    claims = make_claims()
    token = sign(claims)
    auth = InitialCapabilityAuth(token, CAPABILITY)

    async with running_client(engine) as (app, http_client):
        http_client.auth = auth
        async with streamable_http_client(
            "http://testserver/mcp", http_client=http_client
        ) as (read_stream, write_stream, session_id):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                assert result.serverInfo.name == "ai-mafia-mcp"
                assert session_id() is not None
                assert app.state.session_registry.active_count == 1

        assert app.state.session_registry.active_count == 0

    assert engine.calls == [(token, CAPABILITY)]
    assert auth.requests >= 3


@pytest.mark.anyio
async def test_distinct_jobs_receive_distinct_bootstrap_consumes_and_session_ids() -> None:
    """서로 다른 job의 nonce·capability·MCP session을 process 안에서 재사용하지 않는다."""

    engine = FakeEngine()
    first_claims = make_claims()
    second_capability = base64.urlsafe_b64encode(
        b"synthetic-capability-value-00002"
    ).decode().rstrip("=")
    second_claims = make_claims(
        nonce="00000000-0000-1000-8000-000000000005",
        capability_hash=hashlib.sha256(second_capability.encode()).hexdigest(),
    )
    first_token = sign(first_claims)
    second_token = sign(second_claims)

    async with running_client(engine) as (app, client):
        first = await client.post(
            "/mcp",
            headers=mcp_headers(first_token, capability=CAPABILITY),
            json=initialize_body(1),
        )
        second = await client.post(
            "/mcp",
            headers=mcp_headers(second_token, capability=second_capability),
            json=initialize_body(2),
        )

        assert first.status_code == second.status_code == 200
        assert first.headers["Mcp-Session-Id"] != second.headers["Mcp-Session-Id"]
        assert app.state.session_registry.active_count == 2

    assert engine.calls == [
        (first_token, CAPABILITY),
        (second_token, second_capability),
    ]


def test_runtime_uses_stateful_manager_with_fixed_idle_timeout() -> None:
    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)

    assert app.state.session_manager.stateless is False
    assert app.state.session_manager.session_idle_timeout == 30.0
    assert app.state.session_registry.idle_timeout_seconds == 30.0


def test_runtime_rejects_reused_directional_secrets() -> None:
    """Backend→MCP와 MCP→Engine의 서로 다른 신뢰 경계를 같은 key로 합치지 않는다."""

    with pytest.raises(ValueError, match="must be different"):
        RuntimeSettings(
            mcp_server_auth_secret=SECRET,
            engine_internal_api_secret=SECRET,
            engine_api_url="https://engine.invalid",
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({"X-Agent-Capability": CAPABILITY}, 401),
        ({"Authorization": "Basic invalid", "X-Agent-Capability": CAPABILITY}, 401),
        ({"Authorization": "Bearer malformed", "X-Agent-Capability": CAPABILITY}, 401),
        ({"Authorization": "Bearer valid.but.extra", "X-Agent-Capability": CAPABILITY}, 401),
        ({"Authorization": "Bearer placeholder"}, 401),
    ],
)
async def test_initialize_rejects_missing_or_malformed_auth(
    headers: dict[str, str], expected_status: int
) -> None:
    async with running_client(FakeEngine()) as (_, client):
        response = await client.post("/mcp", headers=headers, json=initialize_body())

    assert response.status_code == expected_status
    assert response.json() == {"error": "AUTH_REQUIRED"}


@pytest.mark.anyio
async def test_initialize_requires_capability_header_exactly_once() -> None:
    token = sign(make_claims())
    headers = [
        ("Authorization", f"Bearer {token}"),
        ("X-Agent-Capability", CAPABILITY),
        ("X-Agent-Capability", CAPABILITY),
        ("Accept", "application/json, text/event-stream"),
    ]
    async with running_client(FakeEngine()) as (_, client):
        response = await client.post("/mcp", headers=headers, json=initialize_body())

    assert response.status_code == 401
    assert response.json() == {"error": "AUTH_REQUIRED"}


@pytest.mark.anyio
async def test_initialize_rejects_tamper_expiry_hash_mismatch_replay_and_engine_deny() -> None:
    valid = sign(make_claims())
    cases: list[tuple[str, str, FakeEngine]] = [
        (tamper_signature(valid), CAPABILITY, FakeEngine()),
        (sign(make_claims(exp=NOW)), CAPABILITY, FakeEngine()),
        (valid, "wrong-capability", FakeEngine()),
        (sign(make_claims()), CAPABILITY, FakeEngine(deny=True)),
    ]
    for token, capability, engine in cases:
        async with running_client(engine) as (_, client):
            response = await client.post(
                "/mcp",
                headers=mcp_headers(token, capability=capability),
                json=initialize_body(),
            )
        assert response.status_code == 403
        assert response.json() == {"error": "BOOTSTRAP_DENIED"}

    engine = FakeEngine()
    token = sign(make_claims())
    async with running_client(engine) as (_, client):
        headers = mcp_headers(token, capability=CAPABILITY)
        first = await client.post("/mcp", headers=headers, json=initialize_body())
        second = await client.post("/mcp", headers=headers, json=initialize_body(2))
    assert first.status_code == 200
    assert second.status_code == 403
    assert engine.calls == [(token, CAPABILITY)]


@pytest.mark.anyio
async def test_followup_requires_same_bearer_and_forbids_capability_resend() -> None:
    token = sign(make_claims())
    async with running_client(FakeEngine()) as (app, client):
        initial = await client.post(
            "/mcp",
            headers=mcp_headers(token, capability=CAPABILITY),
            json=initialize_body(),
        )
        session_id = initial.headers["Mcp-Session-Id"]
        violation = await client.post(
            "/mcp",
            headers={**mcp_headers(token, capability=CAPABILITY), "Mcp-Session-Id": session_id},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        after_close = await client.delete(
            "/mcp",
            headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
        )

        assert violation.status_code == 403
        assert violation.json() == {"error": "BOOTSTRAP_DENIED"}
        assert after_close.status_code == 404
        assert after_close.json() == {"error": "SESSION_NOT_FOUND"}
        assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_followup_with_different_bearer_closes_session_without_reconsume() -> None:
    engine = FakeEngine()
    token = sign(make_claims())
    other_token = sign(make_claims())
    async with running_client(engine) as (app, client):
        initial = await client.post(
            "/mcp",
            headers=mcp_headers(token, capability=CAPABILITY),
            json=initialize_body(),
        )
        session_id = initial.headers["Mcp-Session-Id"]
        denied = await client.post(
            "/mcp",
            headers={**mcp_headers(other_token), "Mcp-Session-Id": session_id},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        assert denied.status_code == 403
        assert denied.json() == {"error": "BOOTSTRAP_DENIED"}
        assert app.state.session_registry.active_count == 0
    assert engine.calls == [(token, CAPABILITY)]


@pytest.mark.anyio
async def test_followup_with_non_ascii_bearer_is_fixed_denial_and_cleanup() -> None:
    """임의 header byte가 constant-time 비교 예외를 만들지 않고 session을 닫아야 한다."""

    token = sign(make_claims())
    async with running_client(FakeEngine()) as (app, client):
        initial = await client.post(
            "/mcp",
            headers=mcp_headers(token, capability=CAPABILITY),
            json=initialize_body(),
        )
        session_id = initial.headers["Mcp-Session-Id"]
        denied = await client.post(
            "/mcp",
            headers=[
                (b"authorization", b"Bearer \xff"),
                (b"mcp-session-id", session_id.encode()),
                (b"accept", b"application/json, text/event-stream"),
            ],
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        assert denied.status_code == 403
        assert denied.json() == {"error": "BOOTSTRAP_DENIED"}
        assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_delayed_consume_that_finishes_after_expiry_creates_no_session() -> None:
    clock = MutableClock()
    engine = FakeEngine(after_consume=lambda: setattr(clock, "value", NOW + 2))
    app = create_app(settings(), engine=engine, clock=clock)
    token = sign(make_claims(exp=NOW + 1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )

    assert response.status_code == 403
    assert response.json() == {"error": "BOOTSTRAP_DENIED"}
    assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_expiry_during_sdk_initialize_is_denied_before_session_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """consume 후 SDK 처리 중 만료된 bootstrap도 ACTIVE binding과 session ID를 노출하지 않는다."""

    clock = MutableClock()
    engine = FakeEngine()
    app = create_app(settings(), engine=engine, clock=clock)
    middleware = app.state.bootstrap_middleware
    terminated: list[str] = []

    async def downstream(_, receive, send):  # type: ignore[no-untyped-def]
        await receive()
        clock.value = NOW + 120
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"expired-during-initialize")],
            }
        )
        payload = {"jsonrpc": "2.0", "id": 1, "result": {}}
        await send({"type": "http.response.body", "body": json.dumps(payload).encode()})

    async def record_terminate(_, session_id, __):  # type: ignore[no-untyped-def]
        terminated.append(session_id)

    monkeypatch.setattr(middleware, "_app", downstream)
    monkeypatch.setattr(middleware, "_terminate_transport", record_terminate)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )

    assert response.status_code == 403
    assert response.json() == {"error": "BOOTSTRAP_DENIED"}
    assert engine.calls == [(token, CAPABILITY)]
    assert terminated == ["expired-during-initialize"]
    assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_expiry_reaper_cleans_before_thirty_second_idle_without_requests() -> None:
    now = int(time.time())
    token = sign(make_claims(iat=now, exp=now + 1))
    app = create_app(settings(), engine=FakeEngine(), clock=time.time)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            assert initial.status_code == 200
            assert app.state.session_registry.active_count == 1
            await __import__("anyio").sleep(1.1)
            assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("boundary", ["exp", "idle"])
async def test_followup_after_exp_or_idle_is_atomic_404(boundary: str) -> None:
    """reaper 실행 여부와 무관하게 middleware lookup 자체가 만료 binding을 제거한다."""

    wall = MutableClock()
    mono = MutableMonotonic()
    app = create_app(settings(), engine=FakeEngine(), clock=wall, monotonic=mono)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]
            if boundary == "exp":
                wall.value = NOW + 120
            else:
                mono.value += 30
            response = await client.post(
                "/mcp",
                headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            assert response.status_code == 404
            assert response.json() == {"error": "SESSION_NOT_FOUND"}
            assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_invalid_initialize_is_fixed_rpc_error_and_does_not_consume() -> None:
    engine = FakeEngine()
    token = sign(make_claims())
    async with running_client(engine) as (_, client):
        response = await client.post(
            "/mcp",
            headers=mcp_headers(token, capability=CAPABILITY),
            json={"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}},
        )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32602, "message": "요청 형식이 올바르지 않습니다."},
    }
    assert engine.calls == []


@pytest.mark.anyio
async def test_oversized_initialize_is_fixed_rpc_error_without_consume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """body 상한 위반은 인증 오류나 예외 원문이 아니라 protocol 오류로 수렴한다."""

    monkeypatch.setattr("mafia_game.api.bootstrap_auth._MAX_INITIALIZE_BODY_BYTES", 8)
    engine = FakeEngine()
    token = sign(make_claims())
    async with running_client(engine) as (_, client):
        response = await client.post(
            "/mcp",
            headers=mcp_headers(token, capability=CAPABILITY),
            content=b"123456789",
        )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": "server-error",
        "error": {"code": -32602, "message": "요청 형식이 올바르지 않습니다."},
    }
    assert engine.calls == []


@pytest.mark.anyio
async def test_oversized_existing_message_is_fixed_rpc_error_without_closing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검증 가능한 body 상한 위반만으로 정상 owner session을 불필요하게 닫지 않는다."""

    token = sign(make_claims())
    async with running_client(FakeEngine()) as (app, client):
        initial = await client.post(
            "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
        )
        session_id = initial.headers["Mcp-Session-Id"]
        monkeypatch.setattr("mafia_game.api.bootstrap_auth._MAX_INITIALIZE_BODY_BYTES", 8)

        response = await client.post(
            "/mcp",
            headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
            content=b"123456789",
        )

        assert response.status_code == 400
        assert response.json() == {
            "jsonrpc": "2.0",
            "id": "server-error",
            "error": {"code": -32602, "message": "요청 형식이 올바르지 않습니다."},
        }
        assert app.state.session_registry.active_count == 1


@pytest.mark.anyio
async def test_existing_malformed_rpc_is_fixed_error_without_closing_session() -> None:
    token = sign(make_claims())
    async with running_client(FakeEngine()) as (app, client):
        initial = await client.post(
            "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
        )
        session_id = initial.headers["Mcp-Session-Id"]
        response = await client.post(
            "/mcp",
            headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
            content=b'{"jsonrpc":"2.0","id":8,"method":"ping","params":"bad"}',
        )

        assert response.status_code == 400
        assert response.json() == {
            "jsonrpc": "2.0",
            "id": 8,
            "error": {"code": -32602, "message": "요청 형식이 올바르지 않습니다."},
        }
        assert "data" not in response.json()["error"]
        assert "bad" not in response.text
        assert app.state.session_registry.active_count == 1


@pytest.mark.anyio
async def test_missing_followup_bearer_returns_401_and_cleans_session() -> None:
    token = sign(make_claims())
    async with running_client(FakeEngine()) as (app, client):
        initial = await client.post(
            "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
        )
        session_id = initial.headers["Mcp-Session-Id"]
        response = await client.post(
            "/mcp",
            headers={"Mcp-Session-Id": session_id},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        assert response.status_code == 401
        assert response.json() == {"error": "AUTH_REQUIRED"}
        assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_registry_is_bound_before_initialize_response_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    original_add = app.state.session_registry.add
    added = False

    async def recording_add(session_id: str, binding: object) -> bool:
        nonlocal added
        result = await original_add(session_id, binding)
        added = True
        return result

    monkeypatch.setattr(app.state.session_registry, "add", recording_add)
    token = sign(make_claims())
    body = json.dumps(initialize_body(), separators=(",", ":")).encode()
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            assert added

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-agent-capability", CAPABILITY.encode()),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
        ],
        "client": None,
        "server": None,
    }
    async with app.router.lifespan_context(app):
        await app(scope, receive, send)


@pytest.mark.anyio
async def test_sdk_scopes_never_receive_raw_credentials() -> None:
    """초기·후속·종료 SDK scope에는 session-local owner만 남아야 한다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware
    captured: list[dict[str, object]] = []

    async def downstream(scope, receive, send):  # type: ignore[no-untyped-def]
        captured.append(dict(scope))
        if scope["method"] == "POST" and not any(
            key.lower() == b"mcp-session-id" for key, _ in scope["headers"]
        ):
            await receive()
            payload = {"jsonrpc": "2.0", "id": 1, "result": {}}
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"mcp-session-id", b"opaque-session")],
                }
            )
            await send({"type": "http.response.body", "body": json.dumps(payload).encode()})
            return
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware._app = downstream
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]
            await client.post(
                "/mcp",
                headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            await client.delete(
                "/mcp", headers={**mcp_headers(token), "Mcp-Session-Id": session_id}
            )

    assert len(captured) == 3
    for scope in captured:
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        assert headers["authorization"] != f"Bearer {token}"
        assert headers["authorization"].startswith("Bearer ")
        assert "x-agent-capability" not in headers
        user = scope["user"]
        assert user.access_token.token == headers["authorization"][7:]
        assert user.access_token.subject == headers["authorization"][7:]


@pytest.mark.anyio
async def test_shutdown_cleans_active_registry_before_closing_engine() -> None:
    """active session이 남은 shutdown도 cancellation보다 먼저 자격과 client를 정리한다."""

    engine = FakeEngine()
    app = create_app(settings(), engine=engine, clock=lambda: NOW)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            assert response.status_code == 200
            assert app.state.session_registry.active_count == 1

    assert app.state.session_registry.active_count == 0
    assert engine.closed


@pytest.mark.anyio
async def test_initial_send_failure_cleans_binding_and_terminates_with_opaque_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """consume 뒤 응답 전달 실패가 나도 raw binding을 먼저 지우고 원래 예외를 전파한다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    terminated: list[tuple[str, str]] = []

    async def record_terminate(scope, session_id, binding):  # type: ignore[no-untyped-def]
        terminated.append((session_id, binding.sdk_owner))

    monkeypatch.setattr(app.state.bootstrap_middleware, "_terminate_transport", record_terminate)
    token = sign(make_claims())
    body = json.dumps(initialize_body(), separators=(",", ":")).encode()
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def failing_send(_: dict[str, object]) -> None:
        raise RuntimeError("client transport closed")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-agent-capability", CAPABILITY.encode()),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
        ],
        "client": None,
        "server": None,
    }
    async with app.router.lifespan_context(app):
        with pytest.raises(RuntimeError, match="client transport closed"):
            await app(scope, receive, failing_send)
        assert app.state.session_registry.active_count == 0

    assert len(terminated) == 1
    assert terminated[0][1] not in {token, CAPABILITY}


@pytest.mark.anyio
async def test_initial_send_cancellation_cleans_before_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """response send 취소 중에도 shielded cleanup이 끝난 뒤 취소가 상위로 돌아간다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    terminated = False

    async def record_terminate(*_: object) -> None:
        nonlocal terminated
        terminated = True

    monkeypatch.setattr(app.state.bootstrap_middleware, "_terminate_transport", record_terminate)
    token = sign(make_claims())
    body = json.dumps(initialize_body(), separators=(",", ":")).encode()
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-agent-capability", CAPABILITY.encode()),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
        ],
        "client": None,
        "server": None,
    }
    async with app.router.lifespan_context(app):
        with anyio.CancelScope() as cancel_scope:

            async def cancelling_send(_: dict[str, object]) -> None:
                cancel_scope.cancel()
                await anyio.lowlevel.checkpoint()

            await app(scope, receive, cancelling_send)
        assert cancel_scope.cancel_called
        assert app.state.session_registry.active_count == 0
        assert terminated


@pytest.mark.anyio
async def test_initial_sdk_cancellation_terminates_created_transport_before_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK가 session header 생성 뒤 취소돼도 opaque transport를 정리하고 취소를 전파한다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware
    terminated: list[str] = []

    async def cancelled_after_session(_, receive, send):  # type: ignore[no-untyped-def]
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"cancelled-initialize")],
            }
        )
        raise anyio.get_cancelled_exc_class()

    async def record_terminate(_, session_id, __):  # type: ignore[no-untyped-def]
        terminated.append(session_id)

    monkeypatch.setattr(middleware, "_app", cancelled_after_session)
    monkeypatch.setattr(middleware, "_terminate_transport", record_terminate)
    token = sign(make_claims())
    body = json.dumps(initialize_body(), separators=(",", ":")).encode()
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(_: dict[str, object]) -> None:
        raise AssertionError("취소된 initialize 응답을 client에 보내면 안 된다")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-agent-capability", CAPABILITY.encode()),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
        ],
        "client": None,
        "server": None,
    }
    async with app.router.lifespan_context(app):
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await app(scope, receive, send)

    assert terminated == ["cancelled-initialize"]
    assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["POST", "GET"])
async def test_existing_handler_cancellation_cleans_session_and_propagates(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """후속 POST·GET 취소는 protocol 오류로 바꾸지 않고 session을 즉시 닫는다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]

            async def cancelled(*_: object) -> None:
                raise anyio.get_cancelled_exc_class()

            monkeypatch.setattr(app.state.bootstrap_middleware, "_app", cancelled)
            with pytest.raises(anyio.get_cancelled_exc_class()):
                headers = {**mcp_headers(token), "Mcp-Session-Id": session_id}
                if method == "POST":
                    await client.post(
                        "/mcp",
                        headers=headers,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    )
                else:
                    await client.get("/mcp", headers=headers)
            assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_sessionless_non_post_does_not_consume() -> None:
    engine = FakeEngine()
    token = sign(make_claims())
    async with running_client(engine) as (_, client):
        response = await client.put(
            "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
        )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": "server-error",
        "error": {"code": -32602, "message": "요청 형식이 올바르지 않습니다."},
    }
    assert engine.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (502, b"upstream exception detail"),
        (500, b'{"broken"'),
        (400, b'{"error":{"code":-32099,"message":"raw sdk text","data":"secret"}}'),
    ],
)
async def test_existing_downstream_errors_are_fixed_and_redacted(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes
) -> None:
    """SDK의 HTTP status와 임의 body는 고정된 내부 오류 외형으로만 공개한다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]

            async def downstream(_, receive, send):  # type: ignore[no-untyped-def]
                await receive()
                await send({"type": "http.response.start", "status": status, "headers": []})
                await send({"type": "http.response.body", "body": body})

            monkeypatch.setattr(app.state.bootstrap_middleware, "_app", downstream)
            response = await client.post(
                "/mcp",
                headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                json={"jsonrpc": "2.0", "id": 9, "method": "ping"},
            )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 9,
        "error": {"code": -32603, "message": "내부 처리 중 오류가 발생했습니다."},
    }
    assert "upstream" not in response.text
    assert "raw sdk" not in response.text
    assert "secret" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("payload", "session_headers"),
    [
        ({"jsonrpc": "2.0", "id": 2, "result": {}}, [(b"mcp-session-id", b"strict")]),
        (
            {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}},
            [(b"mcp-session-id", b"strict")],
        ),
        ({"id": 1, "result": {}}, [(b"mcp-session-id", b"strict")]),
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, []),
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, [(b"mcp-session-id", b"")]),
        (
            {"jsonrpc": "2.0", "id": 1, "result": {}},
            [(b"mcp-session-id", b"strict"), (b"mcp-session-id", b"strict")],
        ),
    ],
)
async def test_initialize_requires_exact_jsonrpc_success(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    session_headers: list[tuple[bytes, bytes]],
) -> None:
    """consume 뒤 SDK 응답이 strict success가 아니면 session을 열지 않는다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware

    async def downstream(_, receive, send):  # type: ignore[no-untyped-def]
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": session_headers,
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(payload).encode()})

    middleware._app = downstream
    terminated = False

    async def record_terminate(*_: object) -> None:
        nonlocal terminated
        terminated = True

    monkeypatch.setattr(middleware, "_terminate_transport", record_terminate)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": -32603,
        "message": "내부 처리 중 오류가 발생했습니다.",
    }
    assert terminated is any(value for _, value in session_headers)
    assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_teardown_failure_cleans_raw_binding_and_reaper_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = sign(make_claims())
    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]

            async def failing_terminate(*_: object) -> None:
                raise RuntimeError("upstream transport detail")

            monkeypatch.setattr(
                app.state.bootstrap_middleware, "_terminate_transport", failing_terminate
            )
            response = await client.post(
                "/mcp",
                headers={**mcp_headers(token, capability=CAPABILITY), "Mcp-Session-Id": session_id},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            assert response.status_code == 403
            assert response.json() == {"error": "BOOTSTRAP_DENIED"}
            assert "upstream" not in response.text
            assert app.state.session_registry.active_count == 0
            assert not app.state.reaper_task_finished()
