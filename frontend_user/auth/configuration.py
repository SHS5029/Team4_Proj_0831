"""Streamlit 네이티브 OIDC 비밀 설정 구조를 검사하는 순수 검증 모듈.

검증 결과에는 필드 이름과 준비 상태만 담고 실제 자격 증명 값은 복사하지 않는다.
따라서 호출부는 결과를 화면이나 로그에 사용하더라도 client secret, cookie secret을
노출하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class OidcConfigurationStatus:
    """특정 공급자의 OIDC 설정 준비 상태를 나타내는 불변 값 객체.

    ``missing_fields``에는 누락되었거나 형식 검증에 실패한 필드의 경로만 들어간다.
    이름과 달리 실제 비밀값은 절대 포함하지 않는다.
    """

    provider_id: str
    ready: bool
    missing_fields: tuple[str, ...]
    user_message: str


def _mapping_value(source: object, key: str) -> Any:
    """일반 매핑과 Streamlit의 매핑 유사 설정 객체에서 값을 안전하게 읽는다."""

    if isinstance(source, Mapping):
        return source.get(key)
    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _text_value(value: Any) -> str:
    """문자열만 허용하고 앞뒤 공백을 제거하며, 다른 타입은 빈 값으로 본다."""

    return value.strip() if isinstance(value, str) else ""


def _is_real_value(value: Any, *, minimum_length: int = 1) -> bool:
    """빈 값·짧은 값·배포 전 자리표시자를 실제 설정값에서 제외한다.

    길이 검사는 최소 구성 오류를 찾기 위한 것이며 비밀값의 암호학적 강도를
    평가하는 검사는 아니다.
    """

    text = _text_value(value)
    return len(text) >= minimum_length and not text.upper().startswith("REPLACE_")


def _is_valid_redirect_uri(value: Any) -> bool:
    """Streamlit 콜백 경로와 허용된 전송 방식인지 리디렉션 URI를 검사한다.

    운영 환경은 HTTPS만 허용하고 로컬 개발의 ``localhost``에 한해 HTTP를 허용한다.
    사용자 정보, 쿼리, 프래그먼트가 붙은 URI는 콜백 대상을 모호하게 만들 수 있어
    거부하며 경로는 Streamlit 규약인 ``/oauth2callback``과 정확히 일치해야 한다.
    """

    candidate = _text_value(value)
    if not candidate:
        return False
    try:
        parsed = urlsplit(candidate)
        # 잘못된 포트 표기는 ``urlsplit`` 이후 ``port`` 접근 시 예외가 발생한다.
        port = parsed.port
    except ValueError:
        return False

    if not parsed.hostname or parsed.username or parsed.password:
        return False
    if port is not None and not 1 <= port <= 65_535:
        return False
    if parsed.path != "/oauth2callback" or parsed.query or parsed.fragment:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname == "localhost"


def _is_valid_metadata_url(value: Any) -> bool:
    """OIDC 메타데이터 URL이 자격 정보 없는 HTTPS 절대 주소인지 검사한다."""

    candidate = _text_value(value)
    if not candidate or candidate.upper().startswith("REPLACE_"):
        return False
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and (port is None or 1 <= port <= 65_535)
    )


def inspect_oidc_configuration(
    secrets: object | None,
    *,
    provider: str,
) -> OidcConfigurationStatus:
    """필수 OIDC 키를 검사하되 실제 비밀값을 반환하거나 표시하지 않는다.

    최상위 ``auth``와 공급자별 하위 설정을 각각 읽고 모든 조건이 통과한 경우에만
    ``ready=True``를 반환한다. 공급자 ID는 호출자가 선택한 등록 설정의 키로만
    사용되며, 검증 결과에는 안전한 필드 경로만 남는다.
    """

    auth = _mapping_value(secrets, "auth") if secrets is not None else None
    provider_config = _mapping_value(auth, provider)

    # cookie secret은 실수로 짧은 값을 배포하는 것을 막기 위해 최소 32자를 요구한다.
    # client ID/secret은 값의 존재와 자리표시자 여부만 확인하고 외부 요청은 하지 않는다.
    checks = (
        (
            "auth.redirect_uri",
            _is_valid_redirect_uri(_mapping_value(auth, "redirect_uri")),
        ),
        (
            "auth.cookie_secret",
            _is_real_value(_mapping_value(auth, "cookie_secret"), minimum_length=32),
        ),
        (
            f"auth.{provider}.client_id",
            _is_real_value(_mapping_value(provider_config, "client_id")),
        ),
        (
            f"auth.{provider}.client_secret",
            _is_real_value(_mapping_value(provider_config, "client_secret")),
        ),
        (
            f"auth.{provider}.server_metadata_url",
            _is_valid_metadata_url(
                _mapping_value(provider_config, "server_metadata_url")
            ),
        ),
    )
    missing_fields = tuple(name for name, is_valid in checks if not is_valid)

    if missing_fields:
        return OidcConfigurationStatus(
            provider_id=provider,
            ready=False,
            missing_fields=missing_fields,
            user_message="로그인 설정이 아직 완료되지 않았어요.",
        )

    return OidcConfigurationStatus(
        provider_id=provider,
        ready=True,
        missing_fields=(),
        user_message="안전한 Google 로그인을 사용할 수 있어요.",
    )
