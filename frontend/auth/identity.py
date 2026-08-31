"""Streamlit OIDC 사용자 클레임을 공급자 중립 모델로 안전하게 변환한다.

외부 공급자가 전달한 값은 인증된 세션 안에서도 화면·DB에 바로 사용할 수 있는
형식이라고 가정하지 않는다. 이 모듈은 필수 식별자 확인, 제어 문자 제거, 길이 제한,
URL 스킴 제한을 적용한 뒤 백엔드가 소유한 도메인 모델을 생성한다.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from backend.app.auth.models import ExternalIdentity

# 공급자 ID는 설정 키와 DB 식별자로 쓰이므로 예측 가능한 소문자 문자 집합으로 제한한다.
_PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TRUE_VALUES = {"1", "true", "yes", "on"}


class IdentityMappingError(ValueError):
    """필수 클레임을 로컬 신원으로 안전하게 변환할 수 없을 때 발생한다.

    오류 메시지에는 원본 클레임을 넣지 않아 사용자 정보가 로그나 UI로 새지 않는다.
    """


# 신원 데이터 계약의 소유자는 백엔드다. 프런트엔드 전용 데이터 클래스를 별도로
# 만들면 필드나 검증 규칙이 서서히 달라질 수 있으므로, UI 문맥에서 읽기 쉬운 이름만
# 별칭으로 제공하고 동일한 도메인 모델을 그대로 사용한다.
IdentityProfile = ExternalIdentity


def _read_claim(source: object, name: str) -> Any:
    """매핑형·속성형 OIDC 사용자 객체에서 클레임 하나를 예외 없이 읽는다.

    Streamlit 버전과 테스트 대역에 따라 ``st.user``가 제공하는 접근 방식이 다를 수
    있어 매핑, ``get``, 속성 순으로 시도한다. 읽기 실패는 클레임 부재로 정규화한다.
    """

    if isinstance(source, Mapping):
        return source.get(name)

    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            return getter(name)
        except (KeyError, TypeError, ValueError):
            pass

    try:
        return getattr(source, name)
    except (AttributeError, KeyError, TypeError):
        return None


def _clean_text(value: Any, *, limit: int) -> str:
    """외부 값을 한 줄 텍스트로 정규화하고 제어 문자와 과도한 길이를 제거한다.

    연속 공백을 하나로 합치고 Unicode 범주가 ``C``인 제어·서식 문자를 제거한다.
    이 함수는 HTML 이스케이프를 대신하지 않으므로 렌더링 계층은 문맥별 이스케이프를
    별도로 적용해야 한다.
    """

    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C")
    )
    return text[:limit]


def _as_bool(value: Any) -> bool:
    """공급자별 표현 차이를 제한된 참 값 집합으로 정규화한다."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return _clean_text(value, limit=12).casefold() in _TRUE_VALUES


def _safe_avatar_url(value: Any) -> str | None:
    """HTTPS 절대 주소인 아바타 URL만 반환하고 나머지는 이미지 없음으로 처리한다.

    ``javascript:``이나 평문 HTTP 같은 스킴이 브라우저 렌더링 경계로 넘어가지 않게
    한다. 최종 HTML 속성 이스케이프는 UI 계층에서 한 번 더 수행한다.
    """

    candidate = _clean_text(value, limit=2048)
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return candidate


def is_external_user_logged_in(user: object) -> bool:
    """OIDC 미설정 시 존재하지 않을 수 있는 Streamlit 로그인 플래그를 읽는다.

    동등 비교나 truthy 판정 대신 실제 불리언 ``True``만 허용해 임의 문자열이나 숫자가
    로그인 상태로 해석되지 않게 한다.
    """

    return _read_claim(user, "is_logged_in") is True


def map_external_identity(
    user: object,
    *,
    provider: str,
) -> IdentityProfile:
    """``st.user`` 클레임을 원문 노출 없이 내부 신원 모델로 변환한다.

    공급자와 ``sub``는 계정의 안정적인 외부 식별자로 사용하고, 이메일은 최소 구조만
    확인한다. 이메일 소유권 여부는 별도의 ``email_verified`` 필드로 보존한다. 표시명은
    전체 이름, 이름, 이메일 로컬 파트 순으로 대체해 필수 UI 값을 만든다.
    """

    normalized_provider = _clean_text(provider, limit=64).casefold()
    if not _PROVIDER_PATTERN.fullmatch(normalized_provider):
        raise IdentityMappingError("로그인 제공자 정보를 확인할 수 없습니다.")

    provider_subject = _clean_text(_read_claim(user, "sub"), limit=512)
    if not provider_subject:
        raise IdentityMappingError("로그인 계정 식별 정보를 확인할 수 없습니다.")

    email = _clean_text(_read_claim(user, "email"), limit=320).casefold()
    if not email or "@" not in email:
        raise IdentityMappingError("로그인 계정 이메일을 확인할 수 없습니다.")

    display_name = _clean_text(_read_claim(user, "name"), limit=120)
    if not display_name:
        # 일부 공급자는 전체 이름 없이 given_name만 제공한다.
        display_name = _clean_text(_read_claim(user, "given_name"), limit=120)
    if not display_name:
        # 마지막 대체값도 정규화된 이메일에서 만들며 최대 길이를 다시 제한한다.
        display_name = email.split("@", maxsplit=1)[0][:120] or "여행자"

    return IdentityProfile(
        provider=normalized_provider,
        provider_subject=provider_subject,
        email=email,
        email_verified=_as_bool(_read_claim(user, "email_verified")),
        display_name=display_name,
        avatar_url=_safe_avatar_url(_read_claim(user, "picture")),
    )
