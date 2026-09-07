"""SDK 공개 Resource handler를 session binding과 연결한다."""

from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl
from starlette.requests import Request

from mafia_game.api.streamable_session_pool import (
    SESSION_POOL_BINDING_SCOPE_KEY,
    SESSION_POOL_OWNER_SCOPE_KEY,
)
from mafia_game.core.audit import AUDIT_SPAN_SCOPE_KEY, AuditSpan
from mafia_game.core.security.errors import (
    CapabilityDenied,
    DependencyUnavailable,
    UpstreamContractViolation,
)
from mafia_game.domain.resource import RESOURCE_URIS, URI_TO_SCOPE
from mafia_game.domain.session import SessionBinding, SessionRegistry
from mafia_game.services.resources import ResourceService

_MESSAGES = {
    -32002: "요청한 리소스에 접근할 수 없습니다.",
    -32003: "게임 컨텍스트를 불러올 수 없습니다.",
    -32004: "게임 컨텍스트 응답 형식이 올바르지 않습니다.",
}


def _mcp_error(code: int) -> McpError:
    """Resource 오류에 upstream 원문이나 data가 들어갈 여지를 없앤다."""

    return McpError(types.ErrorData(code=code, message=_MESSAGES[code]))


async def _binding(
    server: Server[Any], registry: SessionRegistry
) -> SessionBinding:
    """공개 HTTP Request에 고정된 owner·identity와 같은 session memory만 반환한다."""

    request = server.request_context.request
    if not isinstance(request, Request):
        raise RuntimeError("request context unavailable")
    expected_owner = request.scope.get(SESSION_POOL_OWNER_SCOPE_KEY)
    expected_binding = request.scope.get(SESSION_POOL_BINDING_SCOPE_KEY)
    if (
        not isinstance(expected_owner, str)
        or not isinstance(expected_binding, SessionBinding)
        or expected_binding.sdk_owner != expected_owner
    ):
        raise RuntimeError("request binding unavailable")
    session_id = request.headers.get("Mcp-Session-Id")
    if not session_id:
        raise RuntimeError("session context unavailable")
    binding = await registry.lookup_bound(session_id)
    if binding is not expected_binding or binding.sdk_owner != expected_owner:
        raise RuntimeError("session binding unavailable")
    return binding


def register_resource_handlers(
    server: Server[Any],
    registry: SessionRegistry,
    service: ResourceService,
) -> None:
    """template·subscription 없이 list/read 두 공개 SDK handler만 등록한다."""

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        binding = await _binding(server, registry)
        return [
            types.Resource(
                uri=RESOURCE_URIS[scope],
                name=scope,
                mimeType="application/json",
            )
            for scope in binding.issuance.allowed_resource_scopes
        ]

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        binding = await _binding(server, registry)
        scope = URI_TO_SCOPE.get(uri.encoded_string())
        if scope is None or scope not in binding.issuance.allowed_resource_scopes:
            raise _mcp_error(-32002)
        try:
            request = server.request_context.request
            span = request.scope.get(AUDIT_SPAN_SCOPE_KEY) if isinstance(request, Request) else None
            if isinstance(span, AuditSpan):
                # SDK worker는 initialize 시점의 context를 상속하므로 현재 HTTP scope의
                # 검증된 UUID만 복원한다. Resource·인증 payload는 로그 context에 넣지 않는다.
                with span.context():
                    text = await service.read(binding, scope)
            else:
                text = await service.read(binding, scope)
        except CapabilityDenied as error:
            raise _mcp_error(-32002) from error
        except DependencyUnavailable as error:
            raise _mcp_error(-32003) from error
        except UpstreamContractViolation as error:
            raise _mcp_error(-32004) from error
        return [ReadResourceContents(content=text, mime_type="application/json")]
