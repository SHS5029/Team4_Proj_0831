"""`/mcp` 요청에 bootstrap·owner·고정 오류 정책을 적용하는 ASGI 경계다."""

from __future__ import annotations

import json
import secrets
from typing import Any

import anyio
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.types import (
    ClientNotification,
    ClientRequest,
    InitializeRequest,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
)
from pydantic import ValidationError
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mafia_game.core.security.errors import (
    AuthRequired,
    BootstrapDenied,
    EngineConsumeDenied,
    ReplayDetected,
)
from mafia_game.domain.session import SessionBinding, SessionRegistry
from mafia_game.services.bootstrap import BootstrapService

_AUTHORIZATION = b"authorization"
_CAPABILITY = b"x-agent-capability"
_SESSION_ID = b"mcp-session-id"
_MAX_INITIALIZE_BODY_BYTES = 4 * 1024 * 1024
_VALIDATION_MESSAGE = "요청 형식이 올바르지 않습니다."
_INTERNAL_MESSAGE = "내부 처리 중 오류가 발생했습니다."


class _BodyValidationError(Exception):
    """인증과 무관한 HTTP body 상한 위반을 protocol 오류로 분류한다."""


class _ClientDisconnected(Exception):
    """응답할 peer가 사라진 transport 종료를 내부 오류 노출 없이 전달한다."""


def _values(scope: Scope, name: bytes) -> list[str]:
    """중복 header를 합치지 않고 원본 개수를 보존한다."""

    return [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == name
    ]


def _single_header(scope: Scope, name: bytes) -> str | None:
    values = _values(scope, name)
    return values[0] if len(values) == 1 else None


def _bearer(scope: Scope) -> str:
    """공백 변형과 중복 Authorization을 허용하지 않는 bearer 원문을 반환한다."""

    value = _single_header(scope, _AUTHORIZATION)
    if value is None or not value.startswith("Bearer ") or value.count(" ") != 1:
        raise AuthRequired
    token = value[7:]
    if not token:
        raise AuthRequired
    return token


async def _body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise _ClientDisconnected
        chunk = message.get("body", b"")
        chunks.append(chunk)
        size += len(chunk)
        if size > _MAX_INITIALIZE_BODY_BYTES:
            raise _BodyValidationError
        if not message.get("more_body", False):
            return b"".join(chunks)


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


async def _fixed_http_error(
    scope: Scope, receive: Receive, send: Send, status: int, code: str
) -> None:
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    await Response(body, status_code=status, media_type="application/json")(scope, receive, send)


def _request_id(raw: Any) -> str | int:
    """오류 응답에는 검증된 scalar id만 반영하고 입력 객체는 노출하지 않는다."""

    if isinstance(raw, dict):
        value = raw.get("id")
        if isinstance(value, str) or isinstance(value, int) and not isinstance(value, bool):
            return value
    return "server-error"


async def _fixed_rpc_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    request_id: str | int,
    code: int,
    message: str,
) -> None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    await Response(body, status_code=400, media_type="application/json")(scope, receive, send)


def _parse_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError from error


def _validate_initialize(body: bytes) -> str | int:
    """Engine consume 전에 JSON-RPC envelope와 MCP InitializeRequest를 모두 검증한다."""

    raw = _parse_json(body)
    envelope = JSONRPCMessage.model_validate(raw).root
    if not isinstance(envelope, JSONRPCRequest):
        raise ValueError
    request = ClientRequest.model_validate(
        {"method": envelope.method, "params": envelope.params}
    ).root
    if not isinstance(request, InitializeRequest):
        raise ValueError
    return envelope.id


def _validate_existing(body: bytes) -> str | int:
    """기존 session의 POST도 SDK 전에 JSON-RPC와 알려진 MCP message를 검증한다."""

    raw = _parse_json(body)
    envelope = JSONRPCMessage.model_validate(raw).root
    payload = {"method": envelope.method, "params": envelope.params}
    if isinstance(envelope, JSONRPCRequest):
        ClientRequest.model_validate(payload)
        return envelope.id
    if isinstance(envelope, JSONRPCNotification):
        ClientNotification.model_validate(payload)
        return "server-error"
    raise ValueError


def _sdk_user(owner: str) -> AuthenticatedUser:
    """SDK tombstone에는 실제 job·subject·bearer 대신 session-local 난수만 전달한다."""

    return AuthenticatedUser(
        AccessToken(
            token=owner,
            client_id=owner,
            scopes=[],
            subject=owner,
            claims={"iss": "ai-mafia-mcp-session"},
        )
    )


def _sdk_scope(scope: Scope, owner: str) -> Scope:
    """원본 인증 header를 제거하고 SDK 전용 난수 principal만 담은 scope를 만든다."""

    child_scope = dict(scope)
    child_scope["user"] = _sdk_user(owner)
    child_scope["headers"] = [
        (key, value)
        for key, value in scope.get("headers", [])
        if key.lower() not in {_AUTHORIZATION, _CAPABILITY}
    ]
    child_scope["headers"].append(
        (_AUTHORIZATION, f"Bearer {owner}".encode("latin-1"))
    )
    return child_scope


def _session_ids(messages: list[Message]) -> list[str]:
    values: list[str] = []
    for message in messages:
        if message["type"] == "http.response.start":
            for key, value in message.get("headers", []):
                if key.lower() == _SESSION_ID:
                    values.append(value.decode("latin-1"))
    return values


def _response_payload(messages: list[Message]) -> tuple[int, Any | None]:
    status = 500
    chunks: list[bytes] = []
    for message in messages:
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
    try:
        return status, json.loads(b"".join(chunks)) if chunks else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


async def _send_buffered(messages: list[Message], send: Send) -> None:
    for message in messages:
        await send(message)


def _valid_initialize_response(
    messages: list[Message], request_id: str | int
) -> tuple[bool, str | None]:
    """SDK initialize 성공을 HTTP·JSON-RPC·session header 전체 조건으로 판정한다."""

    starts = [message for message in messages if message["type"] == "http.response.start"]
    session_ids = _session_ids(messages)
    status, payload = _response_payload(messages)
    valid = (
        len(starts) == 1
        and status == 200
        and len(session_ids) == 1
        and bool(session_ids[0])
        and isinstance(payload, dict)
        and payload.get("jsonrpc") == "2.0"
        and payload.get("id") == request_id
        and "result" in payload
        and "error" not in payload
    )
    return valid, next((value for value in session_ids if value), None)


class BootstrapAuthMiddleware:
    """consume 성공 전 session 생성을 막고 이후 동일 bearer owner를 검증한다."""

    def __init__(
        self,
        app: ASGIApp,
        bootstrap_service: BootstrapService,
        session_registry: SessionRegistry,
    ) -> None:
        self._app = app
        self._bootstrap = bootstrap_service
        self._sessions = session_registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if scope.get("path") != "/mcp":
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return

        session_values = _values(scope, _SESSION_ID)
        if len(session_values) > 1:
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return
        if session_values:
            session_id = session_values[0]
            try:
                await self._existing(scope, receive, send, session_id)
            except anyio.get_cancelled_exc_class():
                # 개별 분기 사이 checkpoint에서 취소돼도 active binding을 남기지 않는다.
                with anyio.CancelScope(shield=True):
                    binding = await self._sessions.cleanup(session_id)
                    if binding is not None:
                        await self._safe_terminate(scope, session_id, binding)
                raise
            return
        await self._initialize(scope, receive, send)

    async def _initialize(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") != "POST":
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id="server-error",
                code=-32602,
                message=_VALIDATION_MESSAGE,
            )
            return
        try:
            token = _bearer(scope)
            capability_values = _values(scope, _CAPABILITY)
            if len(capability_values) != 1 or not capability_values[0]:
                raise AuthRequired
            capability = capability_values[0]
            self._bootstrap.verify(token, capability)
        except AuthRequired:
            await _fixed_http_error(scope, receive, send, 401, "AUTH_REQUIRED")
            return
        except BootstrapDenied:
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
            return

        try:
            body = await _body(receive)
        except _ClientDisconnected:
            return
        except _BodyValidationError:
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id="server-error",
                code=-32602,
                message=_VALIDATION_MESSAGE,
            )
            return
        try:
            request_id = _validate_initialize(body)
        except (ValueError, ValidationError):
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id=_request_id(_safe_json(body)),
                code=-32602,
                message=_VALIDATION_MESSAGE,
            )
            return
        try:
            claims = await self._bootstrap.consume(token, capability)
        except anyio.get_cancelled_exc_class():
            raise
        except (AuthRequired, BootstrapDenied, ReplayDetected, EngineConsumeDenied):
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
            return
        except Exception:
            # consume 성공을 입증할 수 없는 adapter 결함도 재사용 없이 동일하게 닫는다.
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
            return

        binding = SessionBinding(
            token=token,
            capability=capability,
            claims=claims,
            sdk_owner=secrets.token_urlsafe(32),
        )
        child_scope = _sdk_scope(scope, binding.sdk_owner)
        messages: list[Message] = []
        try:
            await self._call_buffered(
                child_scope,
                _replay_receive(body),
                messages=messages,
            )
        except anyio.get_cancelled_exc_class():
            session_id = next((value for value in _session_ids(messages) if value), None)
            if session_id is not None:
                await self._shielded_close(scope, session_id, binding)
            raise
        except Exception:
            session_id = next((value for value in _session_ids(messages) if value), None)
            if session_id is not None:
                await self._shielded_close(scope, session_id, binding)
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id=request_id,
                code=-32603,
                message=_INTERNAL_MESSAGE,
            )
            return
        succeeded, session_id = _valid_initialize_response(messages, request_id)
        if not succeeded or session_id is None:
            if session_id is not None:
                await self._shielded_close(scope, session_id, binding)
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id=request_id,
                code=-32603,
                message=_INTERNAL_MESSAGE,
            )
            return
        try:
            # consume 직후뿐 아니라 SDK 처리 뒤에도 exp가 남아 있어야 ACTIVE가 될 수 있다.
            self._bootstrap.verify(token, capability)
        except (AuthRequired, BootstrapDenied):
            await self._shielded_close(scope, session_id, binding)
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
            return
        try:
            # SDK transport가 이미 만들어졌으므로 add 자체도 상위 취소에 반쯤 끝나지 않게 한다.
            with anyio.CancelScope(shield=True):
                added = await self._sessions.add(session_id, binding)
            if not added:
                await self._shielded_close(scope, session_id, binding)
                await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
                return
            await _send_buffered(messages, send)
        except BaseException:
            await self._shielded_close(scope, session_id, binding)
            raise

    async def _existing(self, scope: Scope, receive: Receive, send: Send, session_id: str) -> None:
        lookup = await self._sessions.lookup_active(session_id)
        binding = lookup.active
        if binding is None:
            if lookup.expired is not None:
                await self._shielded_close(scope, session_id, lookup.expired)
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return
        try:
            token = _bearer(scope)
        except AuthRequired:
            await self._shielded_close(scope, session_id, binding)
            await _fixed_http_error(scope, receive, send, 401, "AUTH_REQUIRED")
            return
        try:
            if _values(scope, _CAPABILITY) or not self._sessions.token_matches(binding, token):
                raise BootstrapDenied
            self._bootstrap.verify(token, binding.capability)
        except (AuthRequired, BootstrapDenied):
            await self._shielded_close(scope, session_id, binding)
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
            return

        confirmation = await self._sessions.lookup_active(
            session_id, expected=binding, touch=True
        )
        if confirmation.active is None:
            await self._shielded_close(scope, session_id, binding)
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return

        child_scope = _sdk_scope(scope, binding.sdk_owner)
        if scope.get("method") == "DELETE":
            with anyio.CancelScope(shield=True):
                await self._sessions.cleanup(session_id)
            try:
                messages = await self._call_buffered(child_scope, receive)
            except anyio.get_cancelled_exc_class():
                await self._shielded_close(scope, session_id, binding)
                raise
            except Exception:
                await self._shielded_close(scope, session_id, binding)
                await _fixed_rpc_error(
                    scope,
                    receive,
                    send,
                    request_id="server-error",
                    code=-32603,
                    message=_INTERNAL_MESSAGE,
                )
                return
            try:
                await self._send_normalized(
                    scope, receive, send, messages, request_id="server-error"
                )
            except BaseException:
                await self._shielded_close(scope, session_id, binding)
                raise
            return
        if scope.get("method") == "POST":
            try:
                body = await _body(receive)
            except _ClientDisconnected:
                await self._shielded_close(scope, session_id, binding)
                return
            except _BodyValidationError:
                await _fixed_rpc_error(
                    scope,
                    receive,
                    send,
                    request_id="server-error",
                    code=-32602,
                    message=_VALIDATION_MESSAGE,
                )
                return
            except anyio.get_cancelled_exc_class():
                await self._shielded_close(scope, session_id, binding)
                raise
            except Exception:
                await self._shielded_close(scope, session_id, binding)
                raise
            try:
                request_id = _validate_existing(body)
            except (ValueError, ValidationError):
                await _fixed_rpc_error(
                    scope,
                    receive,
                    send,
                    request_id=_request_id(_safe_json(body)),
                    code=-32602,
                    message=_VALIDATION_MESSAGE,
                )
                return
            confirmation = await self._sessions.lookup_active(
                session_id, expected=binding, touch=True
            )
            if confirmation.active is None:
                await self._shielded_close(scope, session_id, binding)
                await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
                return
            try:
                messages = await self._call_buffered(child_scope, _replay_receive(body))
            except anyio.get_cancelled_exc_class():
                await self._shielded_close(scope, session_id, binding)
                raise
            except Exception:
                await self._shielded_close(scope, session_id, binding)
                await _fixed_rpc_error(
                    scope,
                    receive,
                    send,
                    request_id=request_id,
                    code=-32603,
                    message=_INTERNAL_MESSAGE,
                )
                return
            try:
                await self._send_normalized(scope, receive, send, messages, request_id)
            except BaseException:
                await self._shielded_close(scope, session_id, binding)
                raise
            return
        try:
            await self._call_stream_normalized(child_scope, receive, send)
        except anyio.get_cancelled_exc_class():
            await self._shielded_close(scope, session_id, binding)
            raise
        except Exception:
            await self._shielded_close(scope, session_id, binding)
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id="server-error",
                code=-32603,
                message=_INTERNAL_MESSAGE,
            )

    async def _call_buffered(
        self,
        scope: Scope,
        receive: Receive,
        *,
        messages: list[Message] | None = None,
    ) -> list[Message]:
        """SDK message를 모으되 예외를 삼키지 않아 호출자가 lifecycle을 정리하게 한다."""

        captured = messages if messages is not None else []

        async def capture(message: Message) -> None:
            captured.append(message)

        await self._app(scope, receive, capture)
        return captured

    async def _send_normalized(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        messages: list[Message],
        request_id: str | int,
    ) -> None:
        status, payload = _response_payload(messages)
        if status == 404:
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            code = payload["error"].get("code")
            mapped_code = -32602 if code == -32602 else -32603
            mapped_message = _VALIDATION_MESSAGE if mapped_code == -32602 else _INTERNAL_MESSAGE
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id=request_id,
                code=mapped_code,
                message=mapped_message,
            )
            return
        valid_success = 200 <= status < 300 and (
            request_id == "server-error"
            or isinstance(payload, dict)
            and payload.get("jsonrpc") == "2.0"
            and payload.get("id") == request_id
            and "result" in payload
            and "error" not in payload
        )
        if not messages or not valid_success:
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id=request_id,
                code=-32603,
                message=_INTERNAL_MESSAGE,
            )
            return
        await _send_buffered(messages, send)

    async def _call_stream_normalized(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """성공 stream만 즉시 전달하고 SDK HTTP 오류는 고정 payload로 대체한다."""

        status: int | None = None
        suppressed: list[Message] = []
        emitted = False

        async def normalized_send(message: Message) -> None:
            nonlocal status, emitted
            if message["type"] == "http.response.start":
                status = message["status"]
            if status is not None and not 200 <= status < 300:
                suppressed.append(message)
                if message["type"] == "http.response.body" and not message.get(
                    "more_body", False
                ):
                    emitted = True
                    await self._send_normalized(
                        scope, receive, send, suppressed, request_id="server-error"
                    )
                return
            await send(message)

        await self._app(scope, receive, normalized_send)
        if suppressed and not emitted:
            await self._send_normalized(
                scope, receive, send, suppressed, request_id="server-error"
            )

    async def _close(self, scope: Scope, session_id: str, binding: SessionBinding) -> None:
        await self._sessions.cleanup(session_id)
        await self._safe_terminate(scope, session_id, binding)

    async def _shielded_close(
        self, scope: Scope, session_id: str, binding: SessionBinding
    ) -> None:
        """상위 취소보다 raw binding 제거와 opaque transport 종료를 먼저 완료한다."""

        with anyio.CancelScope(shield=True):
            await self._close(scope, session_id, binding)

    async def _safe_terminate(
        self, scope: Scope, session_id: str, binding: SessionBinding
    ) -> None:
        try:
            await self._terminate_transport(scope, session_id, binding)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            return

    async def _terminate_transport(
        self, scope: Scope, session_id: str, binding: SessionBinding
    ) -> None:
        """공개 DELETE 경로에 실제 자격 대신 session-local SDK owner만 전달한다."""

        terminate_scope = _sdk_scope(scope, binding.sdk_owner)
        terminate_scope["method"] = "DELETE"
        terminate_scope["headers"] = [
            (key, value)
            for key, value in terminate_scope["headers"]
            if key.lower() != _SESSION_ID
        ]
        terminate_scope["headers"].append((_SESSION_ID, session_id.encode("latin-1")))

        async def empty_receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def discard_send(_: Message) -> None:
            return None

        await self._app(terminate_scope, empty_receive, discard_send)

    async def run_reaper(self) -> None:
        """만료 binding을 먼저 제거하고 개별 transport 실패와 무관하게 계속 돈다."""

        interval = min(0.1, self._sessions.idle_timeout_seconds / 2)
        while True:
            await anyio.sleep(interval)
            for session_id, binding in await self._sessions.pop_expired():
                scope = _delete_scope()
                await self._safe_terminate(scope, session_id, binding)


def _safe_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _delete_scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "DELETE",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": None,
        "server": None,
    }
