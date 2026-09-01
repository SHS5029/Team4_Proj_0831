"""Frontend 서버가 보낸 identity 요청의 HMAC와 시간 범위를 검증한다."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import ApiError

_INVALID_SIGNATURE_MESSAGE = "내부 요청 인증을 확인할 수 없습니다."


def _unauthorized() -> ApiError:
    """검증 실패 원인을 구분해 공격자에게 힌트를 주지 않는 공통 오류를 만든다."""

    return ApiError(
        status_code=401,
        code="INVALID_INTERNAL_SIGNATURE",
        message=_INVALID_SIGNATURE_MESSAGE,
    )


def calculate_signature(
    *,
    secret: bytes,
    timestamp: str,
    request_id: str,
    body: bytes,
) -> str:
    """문서화된 canonical byte sequence의 HMAC-SHA256 hex 값을 계산한다."""

    canonical = timestamp.encode() + b"." + request_id.encode() + b"." + body
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


async def verify_internal_request(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    timestamp: str | None = Header(default=None, alias="X-Internal-Timestamp"),
    request_id: str | None = Header(default=None, alias="X-Internal-Request-Id"),
    signature: str | None = Header(default=None, alias="X-Internal-Signature"),
) -> None:
    """필수 헤더, UUID, 시간 오차, HMAC를 모두 통과한 요청만 허용한다.

    raw body를 그대로 서명하므로 JSON 재직렬화 방식 차이로 검증 경계가 흐려지지
    않는다. 실패 시 payload나 secret을 응답·로그에 포함하지 않으며 저장소 의존성은
    호출되지 않는다.
    """

    if timestamp is None or request_id is None or signature is None:
        raise _unauthorized()
    try:
        parsed_timestamp = int(timestamp)
        parsed_request_id = UUID(request_id)
    except (TypeError, ValueError) as exc:
        raise _unauthorized() from exc
    if str(parsed_request_id) != request_id.lower():
        raise _unauthorized()
    if abs(int(time.time()) - parsed_timestamp) > settings.internal_api_max_age_seconds:
        raise _unauthorized()

    try:
        secret = settings.validated_internal_api_secret
    except RuntimeError as exc:
        raise ApiError(
            status_code=503,
            code="INTERNAL_AUTH_UNAVAILABLE",
            message="내부 요청 인증 설정을 사용할 수 없습니다.",
        ) from exc

    expected = calculate_signature(
        secret=secret,
        timestamp=timestamp,
        request_id=request_id,
        body=await request.body(),
    )
    if not hmac.compare_digest(expected, signature.casefold()):
        raise _unauthorized()
