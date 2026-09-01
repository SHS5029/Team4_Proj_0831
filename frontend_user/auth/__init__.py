"""Streamlit 로그인 화면이 사용하는 공개 인증 도우미 인터페이스.

호출부가 세부 모듈 구조에 결합되지 않도록 외부 신원 매핑에 필요한 최소 심볼만
재노출한다. 새 공개 API를 추가할 때는 ``__all__``에도 명시해 의도된 확장인지
확인할 수 있게 한다.
"""

from .identity import (
    IdentityMappingError,
    IdentityProfile,
    is_external_user_logged_in,
    map_external_identity,
)

__all__ = [
    "IdentityMappingError",
    "IdentityProfile",
    "is_external_user_logged_in",
    "map_external_identity",
]
