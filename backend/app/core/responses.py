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
    """예외 원문 대신 공개가 허용된 필드만 JSON 오류 응답에 담는다."""

    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "trace_id": request_trace_id(request),
        },
    )
