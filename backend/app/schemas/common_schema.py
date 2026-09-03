"""여러 Backend endpoint가 공유하는 상태와 오류 응답 schema."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """프로세스 생존 여부만 노출하는 health 응답."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class ErrorDetail(BaseModel):
    """클라이언트가 오류를 이해하고 재시도 여부를 판단하는 정보."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: str
    retryable: bool
    details: Any = None


class ErrorResponse(BaseModel):
    """비밀값이나 내부 예외 문자열을 포함하지 않는 공통 오류 계약."""

    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail
