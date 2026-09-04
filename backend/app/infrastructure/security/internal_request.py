"""Backend 내부 Engine 요청의 HMAC·nonce 입력을 검증하는 보안 경계."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, quote
from uuid import UUID

from fastapi import Request

from backend.app.core.config import get_settings
from backend.app.core.errors import ApiError

_INVALID_SIGNATURE_MESSAGE = "내부 요청 인증을 확인할 수 없습니다."


@dataclass(frozen=True, slots=True)
class InternalRequestAuth:
    """HMAC 검증 뒤 내부 service가 사용할 최소 검증 결과다."""

    timestamp: int
    nonce: UUID
    request_hash: str
    capability: str


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


def canonical_query(raw_query: str) -> str:
    """RFC 3986 규칙으로 query를 정렬해 서명용 문자열로 만든다.

    query를 먼저 decode한 뒤 다시 같은 규칙으로 encode하므로 ``a=1``과
    ``a=%31``처럼 의미가 같은 입력은 같은 서명을 만들고, 중복 key는 그대로
    유지한다. 내부 API는 query 자체도 서명 대상이므로 임의 순서 변경을 허용하지
    않는다.
    """

    encoded = [
        (quote(key, safe="-._~"), quote(value, safe="-._~"))
        for key, value in parse_qsl(raw_query, keep_blank_values=True)
    ]
    encoded.sort()
    return "&".join(f"{key}={value}" for key, value in encoded)


def calculate_engine_signature(
    *,
    secret: bytes,
    method: str,
    path: str,
    query: str,
    body: bytes,
    timestamp: str,
    nonce: str,
) -> str:
    """정본의 줄바꿈 canonical 입력으로 padding 없는 base64url 서명을 만든다."""

    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        [method.upper(), path, canonical_query(query), body_hash, timestamp, nonce]
    ).encode("utf-8")
    digest = hmac.new(secret, canonical, hashlib.sha256).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _raw_path(request: Request) -> str:
    """percent decode하지 않은 HTTP path를 반환한다."""

    raw_path = request.scope.get("raw_path")
    if isinstance(raw_path, bytes):
        return raw_path.decode("ascii")
    return str(request.url.path)


async def verify_engine_request(request: Request) -> InternalRequestAuth:
    """Engine 내부 요청의 header·시간·UUID v4·HMAC를 검증한다.

    이 함수는 PostgreSQL nonce INSERT를 수행하지 않는다. 서명 검증과 nonce 원장
    기록을 분리해 route service가 짧은 transaction으로 원장을 먼저 기록하도록
    하며, DB 장애나 replay를 정상 요청으로 통과시키지 않는다.
    """

    timestamp_text = request.headers.get("X-Engine-Timestamp")
    nonce_text = request.headers.get("X-Engine-Nonce")
    signature = request.headers.get("X-Engine-Signature")
    capability = request.headers.get("X-Agent-Capability")
    if not timestamp_text or not nonce_text or not signature or not capability:
        raise _unauthorized()
    try:
        timestamp = int(timestamp_text)
        nonce = UUID(nonce_text)
    except (TypeError, ValueError) as exc:
        raise _unauthorized() from exc
    if nonce.version != 4 or str(nonce) != nonce_text.lower():
        raise _unauthorized()
    settings = getattr(request.app.state, "settings", None) or get_settings()
    if abs(int(time.time()) - timestamp) > settings.engine_internal_api_max_age_seconds:
        raise _unauthorized()
    try:
        secret = settings.validated_engine_internal_api_secret
    except RuntimeError as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="내부 인증 설정을 사용할 수 없습니다.",
            retryable=True,
        ) from exc
    body = await request.body()
    expected = calculate_engine_signature(
        secret=secret,
        method=request.method,
        path=_raw_path(request),
        query=request.scope.get("query_string", b"").decode("ascii"),
        body=body,
        timestamp=timestamp_text,
        nonce=nonce_text,
    )
    if not hmac.compare_digest(expected, signature):
        raise _unauthorized()
    return InternalRequestAuth(
        timestamp=timestamp,
        nonce=nonce,
        request_hash=hashlib.sha256(body).hexdigest(),
        capability=capability,
    )


def create_bootstrap_token(*, secret: bytes, claims: dict[str, Any]) -> str:
    """MCP가 Backend에 제시할 일회성 signed bootstrap token을 만든다."""

    encoded_payload = urlsafe_b64encode(
        json.dumps(claims, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        .encode("utf-8")
    ).rstrip(b"=")
    signature = urlsafe_b64encode(
        hmac.new(secret, encoded_payload, hashlib.sha256).digest()
    ).rstrip(b"=")
    return f"{encoded_payload.decode('ascii')}.{signature.decode('ascii')}"


def decode_bootstrap_token(*, secret: bytes, token: str, now: int | None = None) -> dict[str, Any]:
    """bootstrap token의 서명·필수 claim·유효기간을 확인해 claim만 반환한다."""

    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = urlsafe_b64encode(
            hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=")
        provided = encoded_signature.encode("ascii")
        if not hmac.compare_digest(expected, provided):
            raise ValueError("signature")
        padding = "=" * (-len(encoded_payload) % 4)
        payload = json.loads(urlsafe_b64decode((encoded_payload + padding).encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid bootstrap token") from exc
    if not isinstance(payload, dict) or payload.get("token_type") != "MCP_BOOTSTRAP":
        raise ValueError("invalid bootstrap claims")
    required = {
        "agent_job_id", "game_id", "subject_type", "subject_id", "capability_hash",
        "iat", "exp", "nonce",
    }
    if set(payload) != required | {"token_type"}:
        raise ValueError("invalid bootstrap claims")
    try:
        claim_nonce = UUID(str(payload["nonce"]))
        for key in ("agent_job_id", "game_id", "subject_id"):
            UUID(str(payload[key]))
        if claim_nonce.version != 4:
            raise ValueError("nonce")
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid bootstrap claims") from exc
    current = int(time.time()) if now is None else now
    if expires_at <= current or expires_at <= issued_at or expires_at - issued_at > 120:
        raise ValueError("expired bootstrap token")
    if not isinstance(payload["capability_hash"], str) or len(payload["capability_hash"]) != 64:
        raise ValueError("invalid capability hash")
    return payload


async def verify_internal_request(request: Request) -> None:
    """필수 헤더, UUID, 시간 오차, HMAC를 모두 통과한 요청만 허용한다.

    raw body를 그대로 서명하므로 JSON 재직렬화 방식 차이로 검증 경계가 흐려지지
    않는다. 실패 시 payload나 secret을 응답·로그에 포함하지 않으며 저장소 의존성은
    호출되지 않는다.
    """

    await verify_engine_request(request)
