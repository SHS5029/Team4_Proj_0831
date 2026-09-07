"""`/mcp` 요청에 bootstrap·owner·고정 오류 정책을 적용하는 ASGI 경계다."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
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

from mafia_game.api.streamable_session_pool import (
    StreamableSessionPool,
    mark_active,
    mark_candidate,
    mark_retiring,
)
from mafia_game.core.audit import (
    AUDIT_SPAN_SCOPE_KEY,
    AuditError,
    AuditOperation,
    AuditRecorder,
    AuditSpan,
    AuditStatus,
)
from mafia_game.core.security.errors import (
    AuthRequired,
    BootstrapDenied,
    EngineConsumeDenied,
    ReplayDetected,
)
from mafia_game.domain.resource import URI_TO_SCOPE
from mafia_game.domain.session import SessionBinding, SessionRegistry
from mafia_game.schemas.common import WireContractError, strict_json_object
from mafia_game.services.bootstrap import BootstrapService

_AUTHORIZATION = b"authorization"
_CAPABILITY = b"x-agent-capability"
_SESSION_ID = b"mcp-session-id"
_MAX_INITIALIZE_BODY_BYTES = 4 * 1024 * 1024
_SHUTDOWN_GRACE_SECONDS = 0.1
_VALIDATION_MESSAGE = "요청 형식이 올바르지 않습니다."
_INTERNAL_MESSAGE = "내부 처리 중 오류가 발생했습니다."
_RESOURCE_MESSAGES = {
    -32002: "요청한 리소스에 접근할 수 없습니다.",
    -32003: "게임 컨텍스트를 불러올 수 없습니다.",
    -32004: "게임 컨텍스트 응답 형식이 올바르지 않습니다.",
}
_AUDIT_REQUEST = "mafia.audit_request"
_AUDIT_RPC_ERRORS = {
    -32602: AuditError.VALIDATION_ERROR,
    -32603: AuditError.INTERNAL_ERROR,
    -32001: AuditError.SESSION_NOT_ACTIVE,
    -32002: AuditError.CAPABILITY_DENIED,
    -32003: AuditError.DEPENDENCY_UNAVAILABLE,
    -32004: AuditError.UPSTREAM_CONTRACT_VIOLATION,
}


@dataclass(slots=True)
class _AuditRequest:
    """HTTP 송신 결과를 원문 payload 없이 폐쇄형 로그 분류로만 유지한다."""

    span: AuditSpan
    status: AuditStatus = AuditStatus.FAILED
    error_class: AuditError | None = AuditError.INTERNAL_ERROR


def _audit_error(scope: Scope, error: AuditError) -> None:
    """실제 전송되는 고정 오류 분류만 기록하고 입력·SDK exception은 받지 않는다."""

    audit = scope.get(_AUDIT_REQUEST)
    if isinstance(audit, _AuditRequest):
        audit.error_class = error
        audit.status = (
            AuditStatus.FAILED
            if error in {
                AuditError.INTERNAL_ERROR, AuditError.DEPENDENCY_UNAVAILABLE,
                AuditError.UPSTREAM_CONTRACT_VIOLATION,
            }
            else AuditStatus.REJECTED
        )


def _audit_operation(scope: Scope, body: bytes) -> None:
    """raw method 문자열 전체를 남기지 않고 구현된 두 Resource operation만 선택한다."""

    audit = scope.get(_AUDIT_REQUEST)
    raw = _safe_json(body)
    if not isinstance(audit, _AuditRequest) or not isinstance(raw, dict):
        return
    method = raw.get("method")
    if method == "resources/list":
        audit.span.set_operation(AuditOperation.RESOURCE_LIST)
    elif method == "resources/read":
        audit.span.set_operation(AuditOperation.RESOURCE_READ)


class _BodyValidationError(Exception):
    """인증과 무관한 HTTP body 상한 위반을 protocol 오류로 분류한다."""


class _ClientDisconnected(Exception):
    """응답할 peer가 사라진 transport 종료를 내부 오류 노출 없이 전달한다."""


class _ResourceAccessDenied(Exception):
    """SDK 정규화 전 raw URI가 canonical registry 밖임을 나타낸다."""


@dataclass(frozen=True, slots=True)
class _ExistingRequest:
    """검증된 request ID와 raw URI에서 확정한 선택적 scope만 전달한다."""

    request_id: str | int
    resource_scope: str | None = None
    is_resource: bool = False


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
    _audit_error(scope, {
        "AUTH_REQUIRED": AuditError.AUTH_REQUIRED,
        "BOOTSTRAP_DENIED": AuditError.BOOTSTRAP_DENIED,
        "SESSION_NOT_FOUND": AuditError.SESSION_NOT_FOUND,
    }.get(code, AuditError.INTERNAL_ERROR))
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
    _audit_error(scope, _AUDIT_RPC_ERRORS.get(code, AuditError.INTERNAL_ERROR))
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
        return strict_json_object(body)
    except WireContractError as error:
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


def _validate_existing(body: bytes) -> _ExistingRequest:
    """SDK 전에 duplicate·list cursor·Resource raw URI를 순서대로 검증한다."""

    raw = _parse_json(body)
    envelope = JSONRPCMessage.model_validate(raw).root
    payload = {"method": envelope.method, "params": envelope.params}
    if isinstance(envelope, JSONRPCRequest):
        if envelope.method == "resources/list":
            params = raw.get("params")
            if isinstance(params, dict) and "cursor" in params:
                raise ValueError
            ClientRequest.model_validate(payload)
            return _ExistingRequest(envelope.id, is_resource=True)
        if envelope.method == "resources/read":
            params = raw.get("params")
            raw_uri = params.get("uri") if isinstance(params, dict) else None
            if isinstance(raw_uri, str) and raw_uri not in URI_TO_SCOPE:
                raise _ResourceAccessDenied
            ClientRequest.model_validate(payload)
            return _ExistingRequest(
                envelope.id, URI_TO_SCOPE.get(raw_uri), is_resource=True
            )
        ClientRequest.model_validate(payload)
        return _ExistingRequest(envelope.id)
    if isinstance(envelope, JSONRPCNotification):
        ClientNotification.model_validate(payload)
        return _ExistingRequest("server-error")
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


def _is_capability_denied_response(messages: list[Message]) -> bool:
    """서버가 생성한 고정 Resource 거부만 terminal capability 신호로 인정한다."""

    _, payload = _response_payload(messages)
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return False
    error = payload["error"]
    return error.get("code") == -32002 and error.get("message") == _RESOURCE_MESSAGES[-32002]


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
        session_pool: StreamableSessionPool,
        bootstrap_service: BootstrapService,
        session_registry: SessionRegistry,
        *,
        audit: AuditRecorder | None = None,
    ) -> None:
        self._pool = session_pool
        self._app: ASGIApp = session_pool.handle_request
        self._bootstrap = bootstrap_service
        self._sessions = session_registry
        self._reaper_inflight: set[str] = set()
        self._audit = audit or AuditRecorder()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """HTTP 종료 시점의 결과만 기록하며 취소·송신 실패도 같은 범위를 정리한다."""

        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        with self._audit.context():
            outcome = _AuditRequest(self._audit.start(AuditOperation.PROTOCOL_REQUEST))
            audited_scope = dict(scope)
            audited_scope[_AUDIT_REQUEST] = outcome
            audited_scope[AUDIT_SPAN_SCOPE_KEY] = outcome.span

            async def audited_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    # 오류 분류는 고정 응답 helper가 맡고, 여기서는 성공 status만 본다.
                    if 200 <= message["status"] < 300:
                        outcome.status = AuditStatus.SUCCEEDED
                        outcome.error_class = None
                await send(message)

            try:
                await self._dispatch(audited_scope, receive, audited_send)
            except anyio.get_cancelled_exc_class():
                outcome.status = AuditStatus.CANCELLED
                outcome.error_class = AuditError.CANCELLED
                raise
            except BaseException:
                outcome.status = AuditStatus.FAILED
                outcome.error_class = AuditError.INTERNAL_ERROR
                raise
            finally:
                outcome.span.finish(outcome.status, error_class=outcome.error_class)

    async def _dispatch(self, scope: Scope, receive: Receive, send: Send) -> None:
        """로그 전달 실패가 기존 인증·lifecycle 분기와 섞이지 않게 실행 경계를 분리한다."""

        if scope.get("path") != "/mcp":
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return

        session_values = _values(scope, _SESSION_ID)
        if len(session_values) > 1:
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return
        if session_values:
            session_id = session_values[0]
            expected_binding: SessionBinding | None = None
            try:
                # lookup checkpoint 뒤 생기는 송신·검증·transport 예외가 어느 분기에서
                # 발생해도 같은 binding identity로만 cleanup하도록 대상을 먼저 고정한다.
                with anyio.CancelScope(shield=True):
                    expected_binding = await self._sessions.lookup_bound(session_id)
                await self._existing(scope, receive, send, session_id)
            except BaseException:
                # 기존 분기가 이미 닫았으면 expected cleanup은 no-op이므로 SDK DELETE가
                # 중복되지 않고, 처음부터 없는 session ID에는 종료를 시도하지 않는다.
                if expected_binding is not None:
                    await self._shielded_close(scope, session_id, expected_binding)
                raise
            return
        await self._initialize(scope, receive, send)

    async def _initialize(self, scope: Scope, receive: Receive, send: Send) -> None:
        audit = scope.get(_AUDIT_REQUEST)
        if isinstance(audit, _AuditRequest):
            audit.span.set_operation(AuditOperation.INITIALIZE)
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
            result = await self._bootstrap.consume(token, capability)
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
            claims=result.claims,
            issuance=result.issuance,
            sdk_owner=secrets.token_urlsafe(32),
        )
        try:
            await self._pool.start_candidate(binding.sdk_owner)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            await _fixed_rpc_error(
                scope,
                receive,
                send,
                request_id=request_id,
                code=-32603,
                message=_INTERNAL_MESSAGE,
            )
            return
        child_scope = _sdk_scope(scope, binding.sdk_owner)
        mark_candidate(child_scope, binding.sdk_owner)
        messages: list[Message] = []
        try:
            await self._call_buffered(
                child_scope,
                _replay_receive(body),
                messages=messages,
            )
        except anyio.get_cancelled_exc_class():
            session_id = next((value for value in _session_ids(messages) if value), None)
            await self._shielded_discard_transport(scope, session_id, binding)
            raise
        except Exception:
            session_id = next((value for value in _session_ids(messages) if value), None)
            await self._discard_transport(scope, session_id, binding)
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
            await self._discard_transport(scope, session_id, binding)
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
            await self._discard_transport(scope, session_id, binding)
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
            return
        try:
            claimed_after_add_failure = False
            commit_started = False
            # route publish와 registry add는 외부 응답 전에 짧은 ownership 전이로
            # 묶는다. transport I/O는 이 shield와 session gate 밖에서만 수행한다.
            with anyio.CancelScope(shield=True):
                async with binding.terminal_gate:
                    published = self._pool.publish(session_id, binding.sdk_owner)
                    added = published and await self._sessions.add(session_id, binding)
                    if published and not added:
                        claimed_after_add_failure = self._pool.begin_retirement(
                            session_id, binding.sdk_owner
                        )
                    elif added:
                        binding.commits_drained = anyio.Event()
                        binding.active_commits += 1
                        commit_started = True
            if not added:
                if claimed_after_add_failure:
                    await self._safe_terminate(scope, session_id, binding)
                else:
                    await self._discard_transport(scope, session_id, binding)
                await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
                return
            try:
                await _send_buffered(messages, send)
            finally:
                if commit_started:
                    await self._finish_commit(binding)
        except anyio.get_cancelled_exc_class():
            await self._shielded_close(scope, session_id, binding)
            raise
        except BaseException:
            await self._close(scope, session_id, binding)
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

        async with binding.terminal_gate:
            terminal_pending = binding.terminal_pending
            confirmation = (
                None
                if terminal_pending
                else await self._sessions.lookup_active(
                    session_id, expected=binding, touch=True
                )
            )
        if terminal_pending or confirmation is None or confirmation.active is None:
            await self._shielded_close(scope, session_id, binding)
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
            return

        child_scope = _sdk_scope(scope, binding.sdk_owner)
        mark_active(child_scope, binding.sdk_owner, binding)
        if scope.get("method") == "DELETE":
            try:
                claimed = await self._claim_close(session_id, binding)
                messages = (
                    await self._terminate_transport(scope, session_id, binding)
                    if claimed
                    else None
                )
            except anyio.get_cancelled_exc_class():
                raise
            except Exception:
                await _fixed_rpc_error(
                    scope,
                    receive,
                    send,
                    request_id="server-error",
                    code=-32603,
                    message=_INTERNAL_MESSAGE,
                )
                return
            if not claimed:
                await _fixed_http_error(
                    scope, receive, send, 404, "SESSION_NOT_FOUND"
                )
                return
            try:
                if messages is None:
                    await Response(status_code=200)(scope, receive, send)
                else:
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
                _audit_operation(scope, body)
                request = _validate_existing(body)
                request_id = request.request_id
                if (
                    request.resource_scope is not None
                    and request.resource_scope not in binding.issuance.allowed_resource_scopes
                ):
                    raise _ResourceAccessDenied
            except _ResourceAccessDenied:
                await _fixed_rpc_error(
                    scope,
                    receive,
                    send,
                    request_id=_request_id(_safe_json(body)),
                    code=-32002,
                    message=_RESOURCE_MESSAGES[-32002],
                )
                return
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
            async with binding.terminal_gate:
                terminal_pending = binding.terminal_pending
                confirmation = (
                    None
                    if terminal_pending
                    else await self._sessions.lookup_active(
                        session_id, expected=binding, touch=True
                    )
                )
            if terminal_pending or confirmation is None or confirmation.active is None:
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
                if request.is_resource:
                    await self._commit_resource_response(
                        scope,
                        receive,
                        send,
                        session_id=session_id,
                        binding=binding,
                        token=token,
                        messages=messages,
                        request_id=request_id,
                    )
                else:
                    await self._send_normalized(
                        scope, receive, send, messages, request_id
                    )
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
            message = payload["error"].get("message")
            if code == -32602:
                mapped_code = -32602
                mapped_message = _VALIDATION_MESSAGE
            elif code in _RESOURCE_MESSAGES and message == _RESOURCE_MESSAGES[code]:
                mapped_code = code
                mapped_message = _RESOURCE_MESSAGES[code]
            else:
                mapped_code = -32603
                mapped_message = _INTERNAL_MESSAGE
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

    async def _commit_resource_response(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        session_id: str,
        binding: SessionBinding,
        token: str,
        messages: list[Message],
        request_id: str | int,
    ) -> None:
        """성공 commit 소유권만 gate에서 정하고 실제 ASGI 송신은 gate 밖에서 수행한다."""

        response_kind = "success"
        commit_started = False
        async with binding.terminal_gate:
            confirmation = (
                None
                if binding.terminal_pending
                else await self._sessions.lookup_active(
                    session_id, expected=binding, touch=True
                )
            )
            bearer_valid = True
            try:
                if not self._sessions.token_matches(binding, token):
                    raise BootstrapDenied
                self._bootstrap.verify(token, binding.capability)
            except (AuthRequired, BootstrapDenied):
                bearer_valid = False

            if confirmation is None or confirmation.active is None or not bearer_valid:
                response_kind = "missing" if bearer_valid else "expired"
            elif _is_capability_denied_response(messages):
                response_kind = "capability-denied"
            else:
                if binding.active_commits == 0:
                    binding.commits_drained = anyio.Event()
                binding.active_commits += 1
                commit_started = True

        if commit_started:
            try:
                await self._send_normalized(
                    scope, receive, send, messages, request_id
                )
            finally:
                await self._finish_commit(binding)
            return

        await self._close(scope, session_id, binding)

        if response_kind == "missing":
            await _fixed_http_error(scope, receive, send, 404, "SESSION_NOT_FOUND")
        elif response_kind == "expired":
            await _fixed_http_error(scope, receive, send, 403, "BOOTSTRAP_DENIED")
        else:
            await self._send_normalized(scope, receive, send, messages, request_id)

    async def _finish_commit(self, binding: SessionBinding) -> None:
        """송신 결과와 무관하게 commit waiter를 깨우는 짧은 memory 전이만 shield한다."""

        # 취소된 send도 ownership 전이는 끝내야 terminal waiter가 gate 밖에서
        # 깨어난다. transport I/O는 이 shield에 포함하지 않는다.
        with anyio.CancelScope(shield=True):
            async with binding.terminal_gate:
                binding.active_commits -= 1
                if binding.active_commits == 0:
                    binding.commits_drained.set()

    async def _claim_close(
        self,
        session_id: str,
        binding: SessionBinding,
        *,
        expired_only: bool = False,
    ) -> bool:
        """성공 commit을 gate 밖에서 기다린 뒤 route-first 종료 소유권만 확정한다."""

        while True:
            wait_for_commits: anyio.Event | None = None
            async with binding.terminal_gate:
                if expired_only:
                    confirmation = await self._sessions.lookup_active(
                        session_id, expected=binding
                    )
                    if confirmation.expired is not binding:
                        return False
                binding.terminal_pending = True
                if binding.active_commits:
                    wait_for_commits = binding.commits_drained
                else:
                    # route detach와 registry remove만 짧게 shield해 두 저장소 중 하나만
                    # 바뀐 상태를 막는다. SDK DELETE 같은 transport I/O는 포함하지 않는다.
                    with anyio.CancelScope(shield=True):
                        claimed = self._pool.begin_retirement(
                            session_id, binding.sdk_owner
                        )
                        if not claimed:
                            return False
                        if expired_only:
                            removed = await self._sessions.cleanup_expired(
                                session_id, expected=binding
                            )
                        else:
                            removed = await self._sessions.cleanup(
                                session_id, expected=binding
                            )
                        if removed is None:
                            self._pool.restore(session_id, binding.sdk_owner)
                            binding.terminal_pending = False
                            return False
                        return True
            if wait_for_commits is not None:
                await wait_for_commits.wait()

    async def _close(self, scope: Scope, session_id: str, binding: SessionBinding) -> bool:
        claimed = await self._claim_close(session_id, binding)
        if claimed:
            await self._safe_terminate(scope, session_id, binding)
        return claimed

    async def _shielded_close(
        self, scope: Scope, session_id: str, binding: SessionBinding
    ) -> None:
        """취소된 request 대신 pool lifespan에 gate-aware teardown을 독립 위임한다."""

        with anyio.CancelScope(shield=True):
            claimed = False
            async with binding.terminal_gate:
                binding.terminal_pending = True
                if binding.active_commits:
                    self._pool.start_soon(
                        self._close_in_background, scope, session_id, binding
                    )
                else:
                    claimed = self._pool.begin_retirement(
                        session_id, binding.sdk_owner
                    )
                    if claimed:
                        removed = await self._sessions.cleanup(
                            session_id, expected=binding
                        )
                        if removed is None:
                            self._pool.restore(session_id, binding.sdk_owner)
                            claimed = False
            if claimed:
                self._pool.start_soon(
                    self._safe_terminate, scope, session_id, binding
                )
            await anyio.lowlevel.checkpoint()

    async def _close_in_background(
        self, scope: Scope, session_id: str, binding: SessionBinding
    ) -> None:
        """보상 cleanup 실패가 pool의 다른 session task를 취소하지 않게 격리한다."""

        try:
            await self._close(scope, session_id, binding)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            return

    async def _shielded_discard_transport(
        self, scope: Scope, session_id: str | None, binding: SessionBinding
    ) -> None:
        """등록 전 candidate를 짧게 detach하고 실제 teardown은 별도 task에 맡긴다."""

        with anyio.CancelScope(shield=True):
            claimed = self._pool.begin_retirement(session_id, binding.sdk_owner)
            if claimed:
                self._pool.start_soon(
                    self._safe_terminate, scope, session_id, binding
                )
                await anyio.lowlevel.checkpoint()

    async def _discard_transport(
        self, scope: Scope, session_id: str | None, binding: SessionBinding
    ) -> None:
        """일반 initialize 실패는 candidate run 종료까지 기다린 뒤 오류를 응답한다."""

        claimed = self._pool.begin_retirement(session_id, binding.sdk_owner)
        if claimed:
            await self._safe_terminate(scope, session_id, binding)

    async def _safe_terminate(
        self, scope: Scope, session_id: str | None, binding: SessionBinding
    ) -> None:
        try:
            await self._terminate_transport(scope, session_id, binding)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            return

    async def _terminate_transport(
        self, scope: Scope, session_id: str | None, binding: SessionBinding
    ) -> list[Message] | None:
        """공개 DELETE와 manager run 종료를 같은 session runtime에만 적용한다."""

        span = self._audit.start(AuditOperation.SESSION_TEARDOWN)
        try:
            result = await self._retire_transport(scope, session_id, binding)
        except anyio.get_cancelled_exc_class():
            span.finish(AuditStatus.CANCELLED, error_class=AuditError.CANCELLED)
            raise
        except Exception:
            span.finish(AuditStatus.FAILED, error_class=AuditError.INTERNAL_ERROR)
            raise
        failed_response = result is not None and any(
            message["type"] == "http.response.start" and not 200 <= message["status"] < 300
            for message in result
        )
        if failed_response:
            span.finish(AuditStatus.FAILED, error_class=AuditError.INTERNAL_ERROR)
        else:
            span.finish(AuditStatus.SUCCEEDED)
        return result

    async def _retire_transport(
        self, scope: Scope, session_id: str | None, binding: SessionBinding
    ) -> list[Message] | None:
        """로그에 session 식별자를 넘기지 않고 기존 pool 소유권 종료만 실행한다."""

        if session_id is None:
            return await self._pool.retire(binding.sdk_owner, None)

        terminate_scope = _sdk_scope(scope, binding.sdk_owner)
        terminate_scope["method"] = "DELETE"
        terminate_scope["headers"] = [
            (key, value)
            for key, value in terminate_scope["headers"]
            if key.lower() != _SESSION_ID
        ]
        terminate_scope["headers"].append((_SESSION_ID, session_id.encode("latin-1")))
        mark_retiring(terminate_scope, binding.sdk_owner)

        async def request() -> list[Message]:
            async def empty_receive() -> Message:
                return {"type": "http.request", "body": b"", "more_body": False}

            return await self._call_buffered(terminate_scope, empty_receive)

        return await self._pool.retire(binding.sdk_owner, request)

    async def run_reaper(self) -> None:
        """만료 후보별 teardown을 독립 task로 보내 한 session의 지연을 격리한다."""

        interval = min(0.1, self._sessions.idle_timeout_seconds / 2)
        async with anyio.create_task_group() as cleanups:
            while True:
                await anyio.sleep(interval)
                for session_id, binding in await self._sessions.expired_candidates():
                    if binding.sdk_owner in self._reaper_inflight:
                        continue
                    self._reaper_inflight.add(binding.sdk_owner)
                    cleanups.start_soon(self._reap_one, session_id, binding)

    async def _reap_one(self, session_id: str, binding: SessionBinding) -> None:
        """한 binding의 만료 재확인과 teardown을 다른 binding과 직렬화하지 않는다."""

        try:
            claimed = await self._claim_close(
                session_id, binding, expired_only=True
            )
            if claimed:
                await self._safe_terminate(_delete_scope(), session_id, binding)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            return
        finally:
            self._reaper_inflight.discard(binding.sdk_owner)

    async def shutdown(self, bindings: list[tuple[str, SessionBinding]]) -> None:
        """shutdown의 active runtime을 병렬 종료하고 취소 가능한 유예로 상한을 둔다."""

        async def retire_one(session_id: str, binding: SessionBinding) -> None:
            while True:
                wait_for_commits: anyio.Event | None = None
                async with binding.terminal_gate:
                    binding.terminal_pending = True
                    if binding.active_commits:
                        wait_for_commits = binding.commits_drained
                    else:
                        claimed = self._pool.begin_retirement(
                            session_id, binding.sdk_owner
                        )
                        break
                if wait_for_commits is not None:
                    await wait_for_commits.wait()
            if claimed:
                await self._safe_terminate(_delete_scope(), session_id, binding)

        # 외부 await가 취소를 무시하는 경우의 절대 종료는 보장하지 않는다. 정상적인
        # cancellation point를 지키는 teardown 하나가 전체 shutdown을 무기한 막지 않게 한다.
        with anyio.move_on_after(_SHUTDOWN_GRACE_SECONDS):
            async with anyio.create_task_group() as cleanups:
                for session_id, binding in bindings:
                    cleanups.start_soon(retire_one, session_id, binding)


def _safe_json(body: bytes) -> Any:
    try:
        return strict_json_object(body)
    except WireContractError:
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
