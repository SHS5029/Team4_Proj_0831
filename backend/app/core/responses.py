"""모든 Backend 오류를 동일한 공개 응답 계약으로 직렬화한다."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.app.core.errors import ApiError


def request_trace_id(request: Request) -> str:
    """미들웨어가 지정한 추적 ID를 반환하고 없으면 안전한 UUID를 만든다."""

    trace_id = getattr(request.state, "trace_id", None)
    return trace_id if isinstance(trace_id, str) else str(uuid4())


def api_error_response(request: Request, error: ApiError) -> JSONResponse:
    """정본 문서의 ``{error: ...}`` 형식으로 오류를 반환한다.

    클라이언트가 오류를 처리하는 위치를 항상 고정하고, 내부 예외 원문은
    반환하지 않는 공통 보안 경계다.
    """

    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": request_trace_id(request),
                "retryable": error.retryable,
                "details": error.details,
            },
        },
    )
