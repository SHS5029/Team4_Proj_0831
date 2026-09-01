"""Backend HTTP 경계에서 사용하는 안전한 애플리케이션 오류 타입."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """내부 예외나 비밀값을 노출하지 않는 고정 API 오류를 표현한다."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
