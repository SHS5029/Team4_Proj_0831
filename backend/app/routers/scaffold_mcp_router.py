"""기존 MCP health와 B7 내부 Engine API를 함께 제공하는 router다."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.infrastructure.security.internal_request import (
    InternalRequestAuth,
    verify_engine_request,
)
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.mcp.game_client import GameMcpClient
from backend.app.repositories.agent_repository import PostgresAgentRepository
from backend.app.repositories.nonce_repository import PostgresNonceRepository
from backend.app.schemas.internal_schema import AgentProposalRequest, BootstrapConsumeRequest
from backend.app.services.internal_engine_service import InternalEngineService

router = APIRouter(prefix="/api/v1/mcp", tags=["scaffold-mcp"])
internal_router = APIRouter(prefix="/internal/v1", tags=["internal-engine"])


@dataclass(frozen=True, slots=True)
class InternalApiDependencies:
    """테스트와 실제 조립 코드가 내부 service를 주입할 수 있는 경계다."""

    service: InternalEngineService


def build_internal_api_dependencies(settings: Settings) -> InternalApiDependencies:
    """검증된 설정으로 nonce·capability PostgreSQL 저장소를 조립한다."""

    transaction_manager = TransactionManager(settings.effective_database_url)
    return InternalApiDependencies(
        service=InternalEngineService(
            settings=settings,
            nonce_repository=PostgresNonceRepository(transaction_manager),
            capability_repository=PostgresAgentRepository(transaction_manager),
        )
    )


def _service(request: Request) -> InternalEngineService:
    """앱 생성 시 등록한 단일 내부 service를 반환한다."""

    return request.app.state.internal_engine_service


def _dependency_error() -> ApiError:
    """DB·외부 adapter 원문을 숨기는 내부 dependency 오류를 만든다."""

    return ApiError(
        status_code=503,
        code="DEPENDENCY_UNAVAILABLE",
        message="내부 처리 의존성을 사용할 수 없습니다.",
        retryable=True,
    )


def _consume_engine_nonce(service: InternalEngineService, auth: InternalRequestAuth) -> None:
    """모든 내부 endpoint가 handler보다 먼저 Engine nonce를 소비하게 한다."""

    try:
        service.consume_engine_nonce(auth)
    except ApiError:
        raise
    except Exception as exc:
        raise _dependency_error() from exc


@router.get("/health")
async def mcp_health() -> JSONResponse:
    """연결 성공 여부만 노출하고 MCP 내부 오류는 외부에 공개하지 않는다."""

    try:
        await GameMcpClient().health()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "disconnected",
                "server": "game",
                "transport": "streamable-http",
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "status": "connected",
            "server": "game",
            "transport": "streamable-http",
        },
    )


@internal_router.get("/agent-context")
async def agent_context(
    request: Request,
    scope: str = Query(...),
    auth: InternalRequestAuth = Depends(verify_engine_request),  # noqa: B008
) -> JSONResponse:
    """capability가 허용한 하나의 audience context만 반환한다."""

    service = _service(request)
    _consume_engine_nonce(service, auth)
    try:
        result = service.get_context(capability=auth.capability, scope=scope)
    except ApiError:
        raise
    except Exception as exc:
        raise _dependency_error() from exc
    return JSONResponse(status_code=200, content=result)


@internal_router.post("/mcp-bootstrap/consume")
async def consume_mcp_bootstrap(
    request: Request,
    payload: BootstrapConsumeRequest,
    auth: InternalRequestAuth = Depends(verify_engine_request),  # noqa: B008
) -> JSONResponse:
    """signed bootstrap token을 검증하고 nonce를 한 번만 소비한다."""

    service = _service(request)
    _consume_engine_nonce(service, auth)
    try:
        result = service.consume_bootstrap(
            auth=auth,
            bootstrap_token=payload.bootstrap_token,
        )
    except ApiError:
        raise
    except Exception as exc:
        raise _dependency_error() from exc
    return JSONResponse(status_code=200, content=result)


@internal_router.post("/agent-proposals")
async def submit_agent_proposal(
    request: Request,
    payload: AgentProposalRequest,
    auth: InternalRequestAuth = Depends(verify_engine_request),  # noqa: B008
) -> JSONResponse:
    """Agent proposal을 다시 검증한 뒤 authoritative command handler에 위임한다."""

    service = _service(request)
    _consume_engine_nonce(service, auth)
    try:
        result = service.submit_proposal(capability=auth.capability, request=payload)
    except ApiError:
        raise
    except Exception as exc:
        raise _dependency_error() from exc
    return JSONResponse(status_code=200, content=result)
