"""로그인 UI와 분리해 관리하는 OIDC 공급자별 표시 설정."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    """OIDC 공급자 하나의 설정 키와 사용자 표시 문구를 담는 불변 메타데이터.

    ``id``는 Streamlit 비밀 설정의 하위 키이자 ``st.login`` 인자로 사용되므로,
    사용자 입력에서 직접 만들지 않고 아래 등록소에 명시적으로 선언한다.
    """

    id: str
    display_name: str
    login_label: str
    unavailable_message: str


# 공급자를 확장할 때는 이 등록소에 메타데이터를 추가하고, Streamlit secrets의 같은
# ID 아래에 OIDC 설정을 제공한다. 공급자별 인증 로직을 UI 조건문으로 복제하지 않는다.
PROVIDERS: dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        id="google",
        display_name="Google",
        login_label="Google로 계속하기",
        unavailable_message="Google 로그인 설정이 아직 완료되지 않았어요.",
    ),
}


def get_provider(provider_id: str) -> OAuthProvider:
    """등록된 공급자 설정을 반환하고 지원하지 않는 ID는 즉시 거부한다.

    명시적 등록소 조회를 사용해 임의 공급자 ID가 ``st.login``이나 secrets 조회로
    전달되는 것을 막는다. 사용자에게는 내부 등록 키를 노출하지 않는 고정 오류를 준다.
    """

    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError("지원하지 않는 로그인 제공자입니다.") from exc
