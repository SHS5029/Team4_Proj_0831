"""FastAPI Backend 생성, 공통 오류 처리, router 등록 진입점."""

from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from backend.app.core.errors import ApiError
from backend.app.core.logging import configure_logging
from backend.app.core.responses import api_error_response
from backend.app.routers.health_router import router as health_router
from backend.app.routers.identity_router import router as identity_router
from backend.app.routers.scaffold_game_router import router as scaffold_game_router
from backend.app.routers.scaffold_mcp_router import router as scaffold_mcp_router


def _trace_id_from_header(value: str | None) -> str:
    """정규 UUID request id만 추적 ID로 재사용하고 나머지는 새 UUID로 대체한다."""

    if value is not None:
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value.lower():
                return str(parsed)
    return str(uuid4())


def create_app() -> FastAPI:
    """서버별 router와 비밀정보 비노출 오류 계약을 가진 앱을 생성한다."""

    configure_logging()
    application = FastAPI(title="Team4 Backend", version="1.0.0")

    @application.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        """요청 전체에 상관관계 ID를 유지하고 응답 헤더에도 같은 값을 제공한다."""

        request.state.trace_id = _trace_id_from_header(
            request.headers.get("X-Internal-Request-Id")
        )
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError):
        """예상된 애플리케이션 오류를 공통 JSON 계약으로 변환한다."""

        return api_error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, error: RequestValidationError):
        """Pydantic 입력값을 되돌려주지 않고 실패 위치와 유형만 공개한다."""

        details = [
            {"location": list(item["loc"]), "type": item["type"]}
            for item in error.errors()
        ]
        return api_error_response(
            request,
            ApiError(
                status_code=422,
                code="INVALID_IDENTITY",
                message="identity 요청 형식이 올바르지 않습니다.",
                details=details,
            ),
        )

    application.include_router(health_router)
    application.include_router(identity_router)
    application.include_router(scaffold_mcp_router)
    application.include_router(scaffold_game_router)
    return application


app = create_app()
