"""서명된 identity 요청을 Backend로 보내는 단일 Frontend API 경계."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from backend.app.models.identity import ExternalIdentity

HttpTransport = Callable[[Request, float], tuple[int, bytes]]


class ApiClientConfigurationError(RuntimeError):
    """Backend 주소나 내부 서명 비밀값을 안전하게 사용할 수 없을 때 발생한다."""


class IdentityApiUnavailable(RuntimeError):
    """Backend에 연결할 수 없거나 안전한 응답 계약을 읽을 수 없을 때 발생한다."""


class IdentityApiResponseError(RuntimeError):
    """Backend가 고정된 오류 code와 함께 요청을 거부했음을 나타낸다."""

    def __init__(self, *, status_code: int, code: str) -> None:
        super().__init__(f"Identity API request failed with {code}")
        self.status_code = status_code
        self.code = code


class InactiveIdentityError(IdentityApiResponseError):
    """재시도로 해제되지 않는 비활성 사용자 접근 거부."""


@dataclass(frozen=True, slots=True)
class BackendApiConfig:
    """Frontend 서버에서만 보관하는 Backend 주소와 내부 서명 설정."""

    api_url: str
    internal_api_secret: str = field(repr=False)
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        """운영 HTTPS와 로컬 loopback HTTP만 허용하고 secret 강도를 검사한다."""

        candidate = self.api_url.strip().rstrip("/")
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise ApiClientConfigurationError("Backend API URL is invalid") from exc
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (parsed.scheme != "https" and not local_http)
            or (port is not None and not 1 <= port <= 65_535)
        ):
            raise ApiClientConfigurationError("Backend API URL is unsafe")
        secret = self.internal_api_secret.strip()
        if len(secret) < 32 or secret.upper().startswith("REPLACE_"):
            raise ApiClientConfigurationError("Internal API signing is not configured")
        if not 0 < self.timeout_seconds <= 30:
            raise ApiClientConfigurationError("Backend API timeout is invalid")
        object.__setattr__(self, "api_url", candidate)
        object.__setattr__(self, "internal_api_secret", secret)

    @classmethod
    def from_secrets(cls, secrets: object) -> BackendApiConfig:
        """Streamlit secrets에서 실제 값을 복사해 출력하지 않고 설정을 만든다."""

        backend = _mapping_value(secrets, "backend")
        api_url = _mapping_value(backend, "api_url")
        internal_secret = _mapping_value(backend, "internal_api_secret")
        if not isinstance(api_url, str) or not isinstance(internal_secret, str):
            raise ApiClientConfigurationError("Backend API settings are missing")
        return cls(api_url=api_url, internal_api_secret=internal_secret)


@dataclass(frozen=True, slots=True)
class ProvisionedUser:
    """Backend 성공 응답에서 검증해 보존하는 최소 내부 사용자 정보."""

    user_id: UUID
    email: str | None
    display_name: str | None
    avatar_url: str | None
    is_active: bool


class IdentityApiClient:
    """body와 서명에 같은 bytes를 사용해 identity provision API를 호출한다."""

    def __init__(
        self,
        config: BackendApiConfig,
        *,
        transport: HttpTransport | None = None,
        clock: Callable[[], float] = time.time,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._config = config
        self._transport = transport or _send
        self._clock = clock
        self._request_id_factory = request_id_factory

    def provision_identity(self, identity: ExternalIdentity) -> ProvisionedUser:
        """정규화한 identity를 JSON으로 직렬화하고 HMAC 헤더와 함께 전송한다."""

        identity.validate_for_login()
        body = json.dumps(
            {
                "provider": identity.normalized_provider,
                "provider_subject": identity.provider_subject.strip(),
                "email": identity.email,
                "email_verified": identity.email_verified,
                "display_name": identity.display_name,
                "avatar_url": identity.avatar_url,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(self._clock()))
        request_id = str(self._request_id_factory())
        signature = _calculate_signature(
            secret=self._config.internal_api_secret.encode(),
            timestamp=timestamp,
            request_id=request_id,
            body=body,
        )
        request = Request(  # noqa: S310 - 설정 검증이 HTTPS 또는 loopback HTTP만 허용한다.
            f"{self._config.api_url}/api/v1/identity/provision",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Internal-Timestamp": timestamp,
                "X-Internal-Request-Id": request_id,
                "X-Internal-Signature": signature,
            },
        )
        status_code, response_body = self._transport(
            request,
            self._config.timeout_seconds,
        )
        payload = _decode_response(response_body)
        if status_code != 200:
            code = payload.get("code")
            safe_code = code if isinstance(code, str) else "UNKNOWN_BACKEND_ERROR"
            error_type = (
                InactiveIdentityError if safe_code == "INACTIVE_USER" else IdentityApiResponseError
            )
            raise error_type(status_code=status_code, code=safe_code)
        return _parse_user(payload)


def _mapping_value(source: object, key: str) -> Any:
    """일반 매핑과 Streamlit secrets 매핑 유사 객체에서 값을 안전하게 읽는다."""

    if isinstance(source, Mapping):
        return source.get(key)
    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _calculate_signature(
    *,
    secret: bytes,
    timestamp: str,
    request_id: str,
    body: bytes,
) -> str:
    """Backend와 같은 canonical byte sequence의 HMAC-SHA256 값을 만든다."""

    canonical = timestamp.encode() + b"." + request_id.encode() + b"." + body
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def _send(request: Request, timeout: float) -> tuple[int, bytes]:
    """urllib의 네트워크 오류를 자격 정보 없는 고정 예외로 변환한다."""

    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status), response.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except (OSError, TimeoutError, URLError) as exc:
        raise IdentityApiUnavailable("Backend API is unavailable") from exc


def _decode_response(body: bytes) -> dict[str, Any]:
    """응답 크기를 제한하고 JSON 객체만 허용해 예기치 않은 payload를 거부한다."""

    if len(body) > 64 * 1024:
        raise IdentityApiUnavailable("Backend API response is too large")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IdentityApiUnavailable("Backend API returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise IdentityApiUnavailable("Backend API returned an invalid response")
    return payload


def _parse_user(payload: dict[str, Any]) -> ProvisionedUser:
    """성공 응답의 타입과 활성 상태를 다시 검증해 기본 거부를 유지한다."""

    try:
        user_id = UUID(str(payload["user_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise IdentityApiUnavailable("Backend API returned an invalid user") from exc
    is_active = payload.get("is_active")
    if is_active is not True:
        raise IdentityApiUnavailable("Backend API returned an inactive user")
    optional_fields: dict[str, str | None] = {}
    for field_name in ("email", "display_name", "avatar_url"):
        value = payload.get(field_name)
        if value is not None and not isinstance(value, str):
            raise IdentityApiUnavailable("Backend API returned an invalid user")
        optional_fields[field_name] = value
    return ProvisionedUser(
        user_id=user_id,
        email=optional_fields["email"],
        display_name=optional_fields["display_name"],
        avatar_url=optional_fields["avatar_url"],
        is_active=True,
    )
