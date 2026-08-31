"""여러 Streamlit 페이지가 공유하는 기본 거부 방식의 권한 게이트."""

from __future__ import annotations

from auth.identity import is_external_user_logged_in

# 인증 화면 이외의 페이지도 같은 키를 사용해 로컬 계정 확인이 끝났는지 판정한다.
# 이 값은 편의를 위한 세션 플래그이며 OIDC 쿠키나 서버 측 권한 검사를 대체하지 않는다.
APPLICATION_ACCESS_SESSION_KEY = "application-access-granted"


def should_process_external_user(
    user: object,
    *,
    oidc_configuration_ready: bool,
) -> bool:
    """서버 설정과 외부 로그인 상태가 모두 유효할 때만 처리를 허용한다.

    브라우저에 이전 OIDC 쿠키가 남았더라도 현재 서버의 쿠키 비밀값이나 공급자
    설정을 검증할 수 없으면 ``False``를 반환한다. 조건을 AND로 묶는 순서 자체가
    설정 장애 시 인증을 열지 않는 기본 거부 정책이다.
    """

    return oidc_configuration_ready and is_external_user_logged_in(user)
