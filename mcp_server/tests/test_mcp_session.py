"""실제 MCP SDK client와 ASGI transport로 WU-M2 session 경계를 검증한다."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from resource_fixtures import consume_payload
from test_bootstrap_token import CAPABILITY, NOW, SECRET, make_claims, sign

from mafia_game.core.security.errors import EngineConsumeDenied
from mafia_game.main import RuntimeSettings, create_app
from mafia_game.ports.engine_context import EnginePort


@dataclass
class FakeEngine(EnginePort):
    """실제 Backend 없이 consume 호출 횟수·입력과 거부 결과를 재현한다."""

    deny: bool = False
    after_consume: object | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    closed: bool = False
    consume_body: bytes = field(default_factory=consume_payload)

    async def consume(self, bootstrap_token: str, capability: str) -> bytes:
        self.calls.append((bootstrap_token, capability))
        if self.deny:
            raise EngineConsumeDenied
        if callable(self.after_consume):
            self.after_consume()
        return self.consume_body

    async def get_context(self, scope: str, capability: str) -> bytes:
        """WU-M2 테스트가 예상 밖 Resource 호출을 즉시 감지하게 한다."""

        raise AssertionError(f"unexpected context call: {scope}, {bool(capability)}")

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


def job_credential(index: int) -> tuple[str, str]:
    """같은 process에서 replay되지 않는 synthetic job token·capability 쌍을 만든다."""

    capability = base64.urlsafe_b64encode(
        f"synthetic-capability-value-{index:05d}".encode()
    ).decode().rstrip("=")
    claims = make_claims(
        nonce=f"00000000-0000-1000-8000-{index + 10:012d}",
        capability_hash=hashlib.sha256(capability.encode()).hexdigest(),
    )
    return sign(claims), capability


async def call_existing_asgi(
    app: object,
    token: str,
    session_id: str,
    body: bytes,
    send: Callable[[dict[str, object]], Awaitable[None]],
) -> None:
    """후속 요청의 응답 전송 실패를 직접 주입할 수 있는 최소 ASGI 호출을 만든다."""

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
            (b"mcp-session-id", session_id.encode()),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
        ],
        "client": None,
        "server": None,
    }
    await app(scope, receive, send)  # type: ignore[operator]


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
async def test_public_delete_stops_the_session_manager_run_context() -> None:
    """공개 DELETE 뒤 session 전용 manager run이 끝나 tombstone을 함께 폐기한다."""

    token = sign(make_claims())
    async with running_client(FakeEngine()) as (app, client):
        initial = await client.post(
            "/mcp",
            headers=mcp_headers(token, capability=CAPABILITY),
            json=initialize_body(),
        )
        session_id = initial.headers["Mcp-Session-Id"]
        pool = app.state.session_manager

        assert pool.candidate_count == 0
        assert pool.active_count == 1
        assert pool.running_count == 1

        deleted = await client.delete(
            "/mcp", headers={**mcp_headers(token), "Mcp-Session-Id": session_id}
        )

        assert deleted.status_code == 200
        with anyio.fail_after(1):
            await pool.wait_for_run_exits(1)
        assert pool.candidate_count == 0
        assert pool.active_count == 0
        assert pool.run_exit_count == 1


@pytest.mark.anyio
async def test_session_id_collision_discards_only_the_new_candidate() -> None:
    """registry·route 충돌에서 기존 runtime은 유지하고 새 candidate run만 끝낸다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware

    async def fixed_session(scope, receive, send):  # type: ignore[no-untyped-def]
        message = await receive()
        if scope["method"] == "DELETE":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        request_id = json.loads(message["body"])["id"]
        payload = {"jsonrpc": "2.0", "id": request_id, "result": {}}
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"fixed-collision")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(payload).encode()})

    middleware._app = fixed_session
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            first_token, first_capability = job_credential(20)
            first = await client.post(
                "/mcp",
                headers=mcp_headers(first_token, capability=first_capability),
                json=initialize_body(20),
            )
            second_token, second_capability = job_credential(21)
            second = await client.post(
                "/mcp",
                headers=mcp_headers(second_token, capability=second_capability),
                json=initialize_body(21),
            )

            assert first.status_code == 200
            assert second.status_code == 403
            with anyio.fail_after(1):
                await app.state.session_manager.wait_for_run_exits(1)
            assert app.state.session_registry.active_count == 1
            assert app.state.session_manager.candidate_count == 0
            assert app.state.session_manager.active_count == 1
            assert app.state.session_manager.run_exit_count == 1

            await client.delete(
                "/mcp",
                headers={
                    **mcp_headers(first_token),
                    "Mcp-Session-Id": "fixed-collision",
                },
            )


@pytest.mark.anyio
async def test_registry_add_collision_rolls_back_published_route_and_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """route publish 뒤 registry add가 거부돼도 외부 응답 전에 candidate 전체를 닫는다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)

    async def reject_add(*_: object) -> bool:
        return False

    monkeypatch.setattr(app.state.session_registry, "add", reject_add)
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp",
                headers=mcp_headers(token, capability=CAPABILITY),
                json=initialize_body(),
            )

            assert response.status_code == 403
            assert response.json() == {"error": "BOOTSTRAP_DENIED"}
            assert app.state.session_registry.active_count == 0
            assert app.state.session_manager.candidate_count == 0
            assert app.state.session_manager.active_count == 0
            assert app.state.session_manager.running_count == 0
            assert app.state.session_manager.run_exit_count == 1


@pytest.mark.anyio
async def test_late_old_retire_does_not_close_reused_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """detach된 old owner의 늦은 종료가 같은 ID로 publish된 new runtime을 건드리지 않는다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware

    async def fixed_session(scope, receive, send):  # type: ignore[no-untyped-def]
        message = await receive()
        headers = []
        if scope["method"] == "DELETE":
            body = b""
        else:
            request_id = json.loads(message["body"])["id"]
            body = json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "result": {}}
            ).encode()
            headers = [(b"mcp-session-id", b"reused-session")]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    middleware._app = fixed_session
    original_terminate = middleware._terminate_transport
    old_detached = anyio.Event()
    release_old = anyio.Event()
    old_owner: str | None = None

    async def delayed_old(scope, session_id, binding):  # type: ignore[no-untyped-def]
        if binding.sdk_owner == old_owner:
            old_detached.set()
            await release_old.wait()
        return await original_terminate(scope, session_id, binding)

    monkeypatch.setattr(middleware, "_terminate_transport", delayed_old)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            old_token, old_capability = job_credential(30)
            opened = await client.post(
                "/mcp",
                headers=mcp_headers(old_token, capability=old_capability),
                json=initialize_body(30),
            )
            old_binding = await app.state.session_registry.lookup_bound("reused-session")
            assert old_binding is not None
            old_owner = old_binding.sdk_owner

            delete_response: httpx.Response | None = None

            async def delete_old() -> None:
                nonlocal delete_response
                delete_response = await client.delete(
                    "/mcp",
                    headers={
                        **mcp_headers(old_token),
                        "Mcp-Session-Id": opened.headers["Mcp-Session-Id"],
                    },
                )

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(delete_old)
                await old_detached.wait()
                new_token, new_capability = job_credential(31)
                replacement = await client.post(
                    "/mcp",
                    headers=mcp_headers(new_token, capability=new_capability),
                    json=initialize_body(31),
                )
                assert replacement.status_code == 200
                new_binding = await app.state.session_registry.lookup_bound(
                    "reused-session"
                )
                assert new_binding is not None and new_binding is not old_binding
                release_old.set()

            assert delete_response is not None and delete_response.status_code == 200
            assert app.state.session_registry.active_count == 1
            assert app.state.session_manager.active_count == 1
            assert app.state.session_manager.running_count == 1


@pytest.mark.anyio
async def test_shutdown_cancels_blocked_teardown_without_delaying_other_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A의 취소 가능한 종료 지연 중에도 B teardown 시작과 전체 shutdown을 완료한다."""

    engine = FakeEngine()
    app = create_app(settings(), engine=engine, clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware
    pool = app.state.session_manager
    original_terminate = middleware._terminate_transport
    blocked_owner: str | None = None
    second_started = anyio.Event()
    never_release = anyio.Event()

    async def blocked_first(scope, session_id, binding):  # type: ignore[no-untyped-def]
        if binding.sdk_owner == blocked_owner:
            await never_release.wait()
        else:
            second_started.set()
        return await original_terminate(scope, session_id, binding)

    monkeypatch.setattr(middleware, "_terminate_transport", blocked_first)
    with anyio.fail_after(0.75):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                session_ids: list[str] = []
                for index in (40, 41):
                    token, capability = job_credential(index)
                    response = await client.post(
                        "/mcp",
                        headers=mcp_headers(token, capability=capability),
                        json=initialize_body(index),
                    )
                    session_ids.append(response.headers["Mcp-Session-Id"])
                binding = await app.state.session_registry.lookup_bound(session_ids[0])
                assert binding is not None
                blocked_owner = binding.sdk_owner

    assert second_started.is_set()
    assert app.state.session_registry.active_count == 0
    assert pool.active_count == pool.candidate_count == pool.running_count == 0
    assert pool.run_exit_count == 2
    assert engine.closed


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


def test_runtime_assigns_fixed_idle_timeout_only_to_gate_aware_registry() -> None:
    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)

    assert app.state.session_manager.stateless is False
    assert app.state.session_manager.event_store is None
    assert app.state.session_manager.json_response is True
    assert app.state.session_manager.session_idle_timeout is None
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
            assert app.state.session_manager.candidate_count == 0
            assert app.state.session_manager.active_count == 0
            assert app.state.session_manager.running_count == 0

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
    original_terminate = middleware._terminate_transport
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

    async def record_terminate(scope, session_id, binding):  # type: ignore[no-untyped-def]
        terminated.append(session_id)
        return await original_terminate(scope, session_id, binding)

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
async def test_reaper_teardowns_are_session_independent_across_sweeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """멎은 A 종료가 같은 sweep의 B와 이후 sweep의 C 소유권 전이를 막지 않는다."""

    monotonic = MutableMonotonic()
    app = create_app(
        settings(), engine=FakeEngine(), clock=lambda: NOW, monotonic=monotonic
    )
    middleware = app.state.bootstrap_middleware
    original_terminate = middleware._terminate_transport
    release_first = anyio.Event()
    second_started = anyio.Event()
    third_started = anyio.Event()
    started: list[str] = []
    first_session_id: str | None = None
    second_session_id: str | None = None
    third_session_id: str | None = None

    async def controlled_terminate(scope, session_id, binding):  # type: ignore[no-untyped-def]
        started.append(session_id)
        if session_id == first_session_id:
            await release_first.wait()
        elif session_id == second_session_id:
            second_started.set()
        elif session_id == third_session_id:
            third_started.set()
        await original_terminate(scope, session_id, binding)

    monkeypatch.setattr(middleware, "_terminate_transport", controlled_terminate)

    second_progressed = False
    third_progressed = False
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            opened: list[str] = []
            for index in (1, 2):
                token, capability = job_credential(index)
                response = await client.post(
                    "/mcp",
                    headers=mcp_headers(token, capability=capability),
                    json=initialize_body(index),
                )
                opened.append(response.headers["Mcp-Session-Id"])
            first_session_id, second_session_id = opened

            monotonic.value += 30.0
            with anyio.move_on_after(0.5) as second_wait:
                await second_started.wait()
            second_progressed = not second_wait.cancel_called
            if second_progressed:
                assert app.state.session_registry.active_count == 0
                assert app.state.session_manager.active_count == 0

            if second_progressed:
                token, capability = job_credential(3)
                third = await client.post(
                    "/mcp",
                    headers=mcp_headers(token, capability=capability),
                    json=initialize_body(3),
                )
                third_session_id = third.headers["Mcp-Session-Id"]
                monotonic.value += 30.0
                with anyio.move_on_after(0.5) as third_wait:
                    await third_started.wait()
                third_progressed = not third_wait.cancel_called
                if third_progressed:
                    assert app.state.session_registry.active_count == 0
                    assert app.state.session_manager.active_count == 0

            release_first.set()

    assert second_progressed
    assert third_progressed
    assert first_session_id is not None
    assert started.count(first_session_id) == 1


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
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            b'{"jsonrpc":"2.0","id":81,"method":"resources/read",'
            b'"params":{"uri":"mafia://session/public/"}}',
            id="unknown-raw-uri",
        ),
        pytest.param(
            b'{"jsonrpc":"2.0","id":82,"method":"ping","params":"PRIVATE-MARKER"}',
            id="validation",
        ),
    ],
)
async def test_existing_fixed_error_send_failure_closes_expected_binding_once(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    """raw URI·validation 고정 응답 전송 실패도 원예외 전파 전 session을 한 번 닫는다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    token = sign(make_claims())
    terminated: list[str] = []

    async def record_terminate(_: object, session_id: str, __: object) -> None:
        terminated.append(session_id)

    async def failing_send(_: dict[str, object]) -> None:
        raise OSError("synthetic response transport failure")

    monkeypatch.setattr(
        app.state.bootstrap_middleware, "_terminate_transport", record_terminate
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]

            with pytest.raises(OSError, match="synthetic response transport failure"):
                await call_existing_asgi(app, token, session_id, body, failing_send)

            assert app.state.session_registry.active_count == 0
            assert terminated == [session_id]


@pytest.mark.anyio
async def test_unknown_session_send_failure_never_terminates_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """registry에 없는 ID의 응답 실패는 임의 SDK transport 종료로 확대하지 않는다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    terminated: list[str] = []

    async def record_terminate(_: object, session_id: str, __: object) -> None:
        terminated.append(session_id)

    async def failing_send(_: dict[str, object]) -> None:
        raise OSError("synthetic missing-session transport failure")

    monkeypatch.setattr(
        app.state.bootstrap_middleware, "_terminate_transport", record_terminate
    )
    async with app.router.lifespan_context(app):
        with pytest.raises(OSError, match="synthetic missing-session transport failure"):
            await call_existing_asgi(
                app,
                "synthetic-owner-token",
                "unknown-session-id",
                b'{"jsonrpc":"2.0","id":83,"method":"ping"}',
                failing_send,
            )

        assert app.state.session_registry.active_count == 0
        assert terminated == []


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
async def test_initialize_response_commit_precedes_concurrent_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """초기 response-start 뒤 DELETE가 와도 body commit 후에만 manager를 종료한다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware
    original_terminate = middleware._terminate_transport
    response_started = anyio.Event()
    allow_response_body = anyio.Event()
    terminate_started = anyio.Event()
    session_id: str | None = None
    sent_messages: list[dict[str, object]] = []

    async def observed_terminate(scope, requested_id, binding):  # type: ignore[no-untyped-def]
        terminate_started.set()
        return await original_terminate(scope, requested_id, binding)

    monkeypatch.setattr(middleware, "_terminate_transport", observed_terminate)
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
        nonlocal session_id
        sent_messages.append(message)
        if message["type"] == "http.response.start":
            headers = {
                key.decode().lower(): value.decode()
                for key, value in message.get("headers", [])
            }
            session_id = headers["mcp-session-id"]
            response_started.set()
            await allow_response_body.wait()

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
    delete_response: httpx.Response | None = None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:

            async def delete_after_start() -> None:
                nonlocal delete_response
                assert session_id is not None
                delete_response = await client.delete(
                    "/mcp",
                    headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                )

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(app, scope, receive, send)
                await response_started.wait()
                tasks.start_soon(delete_after_start)
                with anyio.move_on_after(0.05) as early_terminate:
                    await terminate_started.wait()
                assert early_terminate.cancel_called
                allow_response_body.set()

            assert delete_response is not None and delete_response.status_code == 200
            assert terminate_started.is_set()
            assert [message["type"] for message in sent_messages] == [
                "http.response.start",
                "http.response.body",
            ]


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
    middleware = app.state.bootstrap_middleware
    original_terminate = middleware._terminate_transport
    terminated: list[tuple[str, str]] = []

    async def record_terminate(scope, session_id, binding):  # type: ignore[no-untyped-def]
        terminated.append((session_id, binding.sdk_owner))
        return await original_terminate(scope, session_id, binding)

    monkeypatch.setattr(middleware, "_terminate_transport", record_terminate)
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
        assert app.state.session_manager.active_count == 0
        assert app.state.session_manager.running_count == 0

    assert len(terminated) == 1
    assert terminated[0][1] not in {token, CAPABILITY}


@pytest.mark.anyio
async def test_initial_send_cancellation_cleans_before_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """response send 취소 중에도 shielded cleanup이 끝난 뒤 취소가 상위로 돌아간다."""

    app = create_app(settings(), engine=FakeEngine(), clock=lambda: NOW)
    middleware = app.state.bootstrap_middleware
    original_terminate = middleware._terminate_transport
    terminated = False

    async def record_terminate(scope, session_id, binding):  # type: ignore[no-untyped-def]
        nonlocal terminated
        terminated = True
        return await original_terminate(scope, session_id, binding)

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
        with anyio.fail_after(1):
            await app.state.session_manager.wait_for_run_exits(1)
        assert app.state.session_manager.running_count == 0


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
async def test_concurrent_delete_only_registry_winner_calls_sdk_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 binding을 본 동시 DELETE도 cleanup 승자 하나만 SDK DELETE를 호출한다."""

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
            middleware = app.state.bootstrap_middleware
            registry = app.state.session_registry
            original_lookup = registry.lookup_active
            original_app = middleware._app
            both_confirmed = anyio.Event()
            release_confirmation = anyio.Event()
            count_lock = anyio.Lock()
            confirmations = 0
            sdk_delete_calls = 0

            async def synchronized_lookup(
                requested_id: str, *, expected: object | None = None, touch: bool = False
            ) -> object:
                nonlocal confirmations
                result = await original_lookup(requested_id, expected=expected, touch=touch)
                if expected is None and not touch:
                    async with count_lock:
                        confirmations += 1
                        if confirmations == 2:
                            both_confirmed.set()
                    await release_confirmation.wait()
                return result

            async def counted_app(scope, receive, send):  # type: ignore[no-untyped-def]
                nonlocal sdk_delete_calls
                if scope.get("method") == "DELETE":
                    sdk_delete_calls += 1
                await original_app(scope, receive, send)

            monkeypatch.setattr(registry, "lookup_active", synchronized_lookup)
            monkeypatch.setattr(middleware, "_app", counted_app)
            responses: list[httpx.Response] = []

            async def delete_once() -> None:
                responses.append(
                    await client.delete(
                        "/mcp",
                        headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                    )
                )

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(delete_once)
                tasks.start_soon(delete_once)
                await both_confirmed.wait()
                release_confirmation.set()

            assert sorted(response.status_code for response in responses) == [200, 404]
            assert [response.json() for response in responses if response.status_code == 404] == [
                {"error": "SESSION_NOT_FOUND"}
            ]
            assert sdk_delete_calls == 1
            assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_delete_losing_to_reaper_does_not_repeat_sdk_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE 확인 뒤 idle reaper가 먼저 소유권을 얻어도 패자는 SDK를 다시 닫지 않는다."""

    monotonic = MutableMonotonic()
    app = create_app(
        settings(), engine=FakeEngine(), clock=lambda: NOW, monotonic=monotonic
    )
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            initial = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            session_id = initial.headers["Mcp-Session-Id"]
            middleware = app.state.bootstrap_middleware
            registry = app.state.session_registry
            original_lookup = registry.lookup_active
            original_app = middleware._app
            delete_confirmed = anyio.Event()
            release_delete = anyio.Event()
            sdk_delete_called = anyio.Event()
            sdk_delete_calls = 0

            async def blocked_confirmation(
                requested_id: str, *, expected: object | None = None, touch: bool = False
            ) -> object:
                result = await original_lookup(requested_id, expected=expected, touch=touch)
                if expected is None and not touch:
                    delete_confirmed.set()
                    await release_delete.wait()
                return result

            async def counted_app(scope, receive, send):  # type: ignore[no-untyped-def]
                nonlocal sdk_delete_calls
                if scope.get("method") == "DELETE":
                    sdk_delete_calls += 1
                    sdk_delete_called.set()
                await original_app(scope, receive, send)

            monkeypatch.setattr(registry, "lookup_active", blocked_confirmation)
            monkeypatch.setattr(middleware, "_app", counted_app)
            response: httpx.Response | None = None

            async def delete_once() -> None:
                nonlocal response
                response = await client.delete(
                    "/mcp",
                    headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                )

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(delete_once)
                await delete_confirmed.wait()
                monotonic.value += 30.0
                with anyio.fail_after(1):
                    await sdk_delete_called.wait()
                release_delete.set()

            assert response is not None
            assert response.status_code == 404
            assert response.json() == {"error": "SESSION_NOT_FOUND"}
            assert sdk_delete_calls == 1
            assert app.state.session_registry.active_count == 0


@pytest.mark.anyio
async def test_cancelled_delete_does_not_retry_sdk_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE 소유자의 취소도 shielded 단일 호출로 끝나며 보상 DELETE를 중복하지 않는다."""

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
            middleware = app.state.bootstrap_middleware
            original_app = middleware._app
            delete_entered = anyio.Event()
            allow_delete = anyio.Event()
            cancel_scope_ready = anyio.Event()
            request_scope: list[anyio.CancelScope] = []
            sdk_delete_calls = 0

            async def slow_first_delete(scope, receive, send):  # type: ignore[no-untyped-def]
                nonlocal sdk_delete_calls
                if scope.get("method") == "DELETE":
                    sdk_delete_calls += 1
                    if sdk_delete_calls == 1:
                        delete_entered.set()
                        await allow_delete.wait()
                await original_app(scope, receive, send)

            monkeypatch.setattr(middleware, "_app", slow_first_delete)

            async def delete_once() -> None:
                with anyio.CancelScope() as cancel_scope:
                    request_scope.append(cancel_scope)
                    cancel_scope_ready.set()
                    await client.delete(
                        "/mcp",
                        headers={**mcp_headers(token), "Mcp-Session-Id": session_id},
                    )

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(delete_once)
                await cancel_scope_ready.wait()
                await delete_entered.wait()
                request_scope[0].cancel()
                await anyio.lowlevel.checkpoint()
                allow_delete.set()

            assert sdk_delete_calls == 1
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
        (
            400,
            b'{"error":{"code":-32002,"message":"wrong message","data":"secret"}}',
        ),
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
    token = sign(make_claims())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp", headers=mcp_headers(token, capability=CAPABILITY), json=initialize_body()
            )
            with anyio.fail_after(1):
                await app.state.session_manager.wait_for_run_exits(1)
            assert app.state.session_manager.candidate_count == 0
            assert app.state.session_manager.active_count == 0

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": -32603,
        "message": "내부 처리 중 오류가 발생했습니다.",
    }
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
