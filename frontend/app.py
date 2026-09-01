"""Streamlit 네이티브 Google OIDC 기본 로그인 화면의 진입점.

이 모듈은 화면 구성, OIDC 세션 확인, 외부 사용자 정보의 내부 모델 변환,
데이터베이스 계정 연결을 순서대로 조율한다. 인증 공급자의 원본 클레임과
비밀 설정은 신뢰 경계 밖의 값으로 취급하며, 화면에는 검증된 상태와 안전한
사용자 안내 문구만 전달한다.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import streamlit as st

# ``streamlit run frontend/app.py``로 실행하면 ``frontend``가 모듈 탐색 경로의
# 선두가 된다. 백엔드의 도메인 모델과 저장소 구현을 같은 계약으로 재사용할 수
# 있도록 저장소 루트를 명시적으로 추가한다. 이미 등록된 경우에는 순서를 바꾸지
# 않아 테스트나 다른 실행 환경의 import 동작을 불필요하게 건드리지 않는다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth.authorization import (  # noqa: E402
    APPLICATION_ACCESS_SESSION_KEY,
    should_process_external_user,
)
from auth.configuration import (  # noqa: E402
    OidcConfigurationStatus,
    inspect_oidc_configuration,
)
from auth.identity import (  # noqa: E402
    IdentityMappingError,
    IdentityProfile,
    is_external_user_logged_in,
    map_external_identity,
)
from auth.persistence import (  # noqa: E402
    PersistenceResult,
    persistence_feedback,
    should_refresh_persistence,
)
from auth.providers import OAuthProvider, get_provider  # noqa: E402
from ui import APP_CSS, login_intro_html, profile_card_html  # noqa: E402

LOGGER = logging.getLogger(__name__)


def _load_oidc_status(provider: OAuthProvider) -> OidcConfigurationStatus:
    """비밀 값 자체를 노출하지 않고 OIDC 설정의 사용 가능 여부만 반환한다.

    ``st.secrets``는 설정 파일이 없거나 형식이 잘못된 경우 Streamlit 버전에 따라
    서로 다른 예외를 낼 수 있다. 어느 경우든 로그인 기능을 활성화하지 않는 쪽으로
    처리하며, 로그에는 예외 타입만 남겨 자격 증명이나 파일 내용이 섞이지 않게 한다.
    """

    try:
        secrets = st.secrets.to_dict()
    # 설정 소스 부재를 나타내는 예외 종류가 Streamlit 버전마다 달라 넓게 잡는다.
    # 이후 순수 검증 함수가 ``None``을 미설정 상태로 판정하므로 기본 거부가 유지된다.
    except Exception as exc:
        LOGGER.info("OIDC secrets are unavailable (%s)", type(exc).__name__)
        secrets = None
    return inspect_oidc_configuration(secrets, provider=provider.id)


def _persist_profile(profile: IdentityProfile) -> PersistenceResult:
    """OIDC 인증 뒤에만 백엔드 경계를 넘어 로컬 계정을 연결한다.

    백엔드 import를 함수 안에서 수행해 로그인 전 화면은 저장 계층이 준비되지 않아도
    표시할 수 있게 한다. 반환값은 UI가 이해하는 제한된 상태로 변환하며, DB 드라이버의
    예외 문자열에는 접속 정보가 포함될 수 있으므로 사용자 화면이나 로그에 원문을
    출력하지 않는다.
    """

    try:
        from backend.app.auth.models import InactiveUserError
        from backend.app.core.config import get_settings
        from backend.app.db.users import PostgresUserRepository
    except (ImportError, ModuleNotFoundError) as exc:
        LOGGER.warning("Identity repository is unavailable (%s)", type(exc).__name__)
        return PersistenceResult(
            state="unavailable",
            user_message=(
                "로그인은 완료됐어요. 계정 저장 기능은 현재 준비 중이라 "
                "잠시 후 다시 확인해 주세요."
            ),
        )

    try:
        settings = get_settings()
        repository = PostgresUserRepository(settings.effective_database_url)
        repository.upsert_identity(profile)
    except InactiveUserError:
        # 비활성 계정은 일시 장애와 달리 재시도로 풀리지 않는 명시적 접근 거부다.
        return PersistenceResult(
            state="blocked",
            user_message="비활성화된 계정입니다. 관리자에게 문의해 주세요.",
        )
    except Exception as exc:
        # DB 드라이버 예외에는 호스트, 사용자명 등 연결 정보가 포함될 수 있다.
        # 진단에는 예외 타입만 쓰고 세부 메시지는 고정된 안전 문구로 치환한다.
        LOGGER.warning("Identity persistence failed (%s)", type(exc).__name__)
        return PersistenceResult(
            state="failed",
            user_message=(
                "로그인은 완료됐지만 계정 정보를 저장하지 못했어요. "
                "잠시 후 다시 시도해 주세요."
            ),
        )

    return PersistenceResult(
        state="saved",
        user_message="Google 로그인과 계정 연결이 완료됐어요.",
    )


def _profile_cache_key(profile: IdentityProfile) -> str:
    """세션 상태 비교용으로 공급자와 외부 식별자의 불투명 해시를 만든다.

    이 값은 인증 토큰이나 권한 증명이 아니라 동일 사용자 여부를 비교하는 키다.
    원본 ``sub``를 세션 상태와 디버그 화면에 그대로 남기지 않도록 해시한다.
    """

    raw_key = f"{profile.provider}:{profile.provider_subject}".encode()
    return hashlib.sha256(raw_key).hexdigest()


def _render_login(
    provider: OAuthProvider,
    oidc_status: OidcConfigurationStatus,
) -> None:
    """로그아웃 상태의 안내와 OIDC 로그인 시작 버튼을 그린다.

    서버 설정 검증이 실패하면 버튼 자체를 비활성화한다. 활성 버튼에서
    ``st.login``을 호출하면 Streamlit이 공급자 페이지로 리디렉션하고, 콜백을
    처리한 뒤 앱 스크립트가 다시 실행된다.
    """

    # ``login_intro_html``은 코드에 고정된 신뢰 가능한 마크업만 반환한다.
    st.markdown(login_intro_html(), unsafe_allow_html=True)

    if not oidc_status.ready:
        st.error(provider.unavailable_message, icon="⚙️")
        st.caption(
            "앱 관리자가 Streamlit OIDC 비밀 설정을 완료하면 로그인할 수 있어요."
        )

    with st.container(key="google-login"):
        login_clicked = st.button(
            provider.login_label,
            key="google-login-button",
            disabled=not oidc_status.ready,
            help=None if oidc_status.ready else provider.unavailable_message,
            use_container_width=True,
        )

    st.markdown(
        (
            '<p class="privacy-note">로그인하면 서비스 이용에 필요한 기본 프로필만 '
            "안전하게 연결돼요.</p>"
        ),
        unsafe_allow_html=True,
    )

    if login_clicked:
        try:
            with st.spinner("안전한 Google 로그인 페이지로 이동하고 있어요..."):
                # 공급자 ID는 등록된 ``OAuthProvider``에서만 가져오며 사용자 입력을
                # 그대로 전달하지 않는다. 리디렉션과 콜백 검증은 Streamlit이 담당한다.
                st.login(provider.id)
        except Exception as exc:
            LOGGER.warning("Native OIDC login could not start (%s)", type(exc).__name__)
            st.error(
                "Google 로그인 페이지를 열지 못했어요. 잠시 후 다시 시도해 주세요.",
                icon="⚠️",
            )


def _render_untrusted_session() -> None:
    """현재 서버 설정으로 신뢰할 수 없는 OIDC 쿠키의 사용을 거부한다.

    브라우저에 로그인 쿠키가 남아 있어도 서버의 쿠키 비밀값이나 공급자 설정이
    누락·약화·자리표시자 상태라면 인증 사용자로 처리하지 않는다. 로컬 접근 플래그를
    먼저 제거하고 Streamlit 로그아웃으로 쿠키 정리를 요청한다.
    """

    st.markdown(login_intro_html(), unsafe_allow_html=True)
    st.error(
        "로그인 보안 설정을 확인할 수 없어 현재 세션을 사용할 수 없어요.",
        icon="⛔",
    )
    st.caption("관리자가 설정을 수정한 뒤 안전하게 로그아웃하고 다시 시도해 주세요.")
    if st.button("안전하게 로그아웃", key="unsafe-session-logout", use_container_width=True):
        st.session_state.pop(APPLICATION_ACCESS_SESSION_KEY, None)
        st.logout()


def _render_authenticated(provider: OAuthProvider) -> None:
    """외부 클레임을 검증하고 로컬 계정 상태에 따라 인증 화면을 그린다.

    ``st.user``는 외부 공급자에서 온 입력이므로 먼저 내부 ``IdentityProfile``로
    정규화한다. 그 뒤 DB 계정 연결 결과를 UI 상태로 변환하고, 저장 성공이 확인된
    실행에서만 애플리케이션 접근 플래그를 연다.
    """

    try:
        profile = map_external_identity(st.user, provider=provider.id)
    except IdentityMappingError:
        st.error(
            "로그인은 완료됐지만 계정 정보를 확인할 수 없어요. 다시 로그인해 주세요.",
            icon="⚠️",
        )
        if st.button("로그아웃", key="invalid-account-logout", use_container_width=True):
            st.logout()
        return

    st.markdown(
        """
        <section class="auth-intro" aria-labelledby="welcome-title">
          <span class="auth-symbol auth-symbol-success" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"
              stroke-linecap="round" stroke-linejoin="round">
              <path d="m7 12 3 3 7-7"></path>
              <circle cx="12" cy="12" r="9"></circle>
            </svg>
          </span>
          <h1 class="auth-title" id="welcome-title">환영합니다</h1>
          <p class="auth-description">현재 Google 계정으로 로그인되어 있습니다.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    # 프로필 카드에는 사용자 값이 들어가므로 HTML 생성 함수가 모든 텍스트와 속성값을
    # 이스케이프한다. 이 책임을 우회해 여기서 문자열을 직접 조합하지 않는다.
    st.markdown(profile_card_html(profile), unsafe_allow_html=True)

    cache_key = _profile_cache_key(profile)
    cached_result = st.session_state.get("identity-persistence-result")
    cached_key = st.session_state.get("identity-persistence-key")
    if should_refresh_persistence(
        cached_result,
        cached_identity_key=cached_key,
        current_identity_key=cache_key,
    ):
        # Streamlit은 버튼 클릭 등 상호작용마다 스크립트를 처음부터 재실행한다.
        # 성공 결과도 매 실행마다 DB에서 다시 확인해, 실행 사이에 관리자가 계정을
        # 비활성화한 경우 이전 성공 캐시로 접근 권한이 계속 유지되지 않게 한다.
        # 반면 일시 실패는 사용자가 재시도를 선택할 때까지 캐시해 중복 요청을 막는다.
        with st.spinner("계정 정보를 안전하게 연결하고 있어요..."):
            cached_result = _persist_profile(profile)
        st.session_state["identity-persistence-key"] = cache_key
        st.session_state["identity-persistence-result"] = cached_result

    feedback = persistence_feedback(cached_result)
    # 화면 알림과 별개로, 실제 애플리케이션 접근 여부는 저장 계층의 판정에서만
    # 파생한다. 알 수 없는 상태나 장애에서는 항상 False가 되도록 매핑되어 있다.
    st.session_state[APPLICATION_ACCESS_SESSION_KEY] = feedback.access_granted
    if feedback.tone == "success":
        st.success(cached_result.user_message, icon="✅")
    elif feedback.tone == "info":
        st.info(cached_result.user_message, icon="ℹ️")
    elif feedback.tone == "error":
        st.error(cached_result.user_message, icon="⛔")
    else:
        st.warning(cached_result.user_message, icon="⚠️")

    if feedback.retry_allowed:
        if st.button("계정 연결 다시 시도", key="retry-persistence"):
            # 실패 결과만 제거하면 다음 전체 실행에서 동일 사용자를 다시 저장한다.
            # ``st.rerun`` 이후 현재 호출 스택은 이어지지 않는다는 점에 유의한다.
            st.session_state.pop("identity-persistence-result", None)
            st.rerun()

    with st.container(key="account-logout"):
        if st.button("로그아웃", key="logout-button", use_container_width=True):
            # 다른 Google 계정으로 다시 로그인할 때 이전 사용자의 연결 결과가
            # 재사용되지 않도록 식별 키와 결과를 함께 폐기한다.
            st.session_state.pop("identity-persistence-key", None)
            st.session_state.pop("identity-persistence-result", None)
            with st.spinner("안전하게 로그아웃하고 있어요..."):
                st.logout()


def main() -> None:
    """페이지 전역 설정을 적용하고 현재 인증 상태에 맞는 화면을 선택한다."""

    # 페이지 설정은 첫 Streamlit UI 명령이어야 하므로 다른 렌더링보다 먼저 호출한다.
    st.set_page_config(
        page_title="로그인",
        page_icon="🔐",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    st.markdown(APP_CSS, unsafe_allow_html=True)

    provider = get_provider("google")
    oidc_status = _load_oidc_status(provider)
    # Streamlit 재실행 시작 시 접근 권한을 닫아 둔 뒤, 아래 인증·DB 검사가 모두
    # 성공한 경로에서만 다시 연다. 이전 실행의 True가 판단 전에 남는 것을 막는다.
    st.session_state[APPLICATION_ACCESS_SESSION_KEY] = False
    with st.container(border=True, key="auth-card"):
        # 순서가 보안 정책이다. 유효한 서버 설정과 로그인 세션을 모두 만족해야 인증
        # 경로로 들어가며, 쿠키만 남은 경우에는 별도의 안전 로그아웃 화면을 보여 준다.
        # 어느 조건도 아니면 일반 로그인 화면으로 돌아간다.
        if should_process_external_user(
            st.user,
            oidc_configuration_ready=oidc_status.ready,
        ):
            _render_authenticated(provider)
        elif is_external_user_logged_in(st.user):
            _render_untrusted_session()
        else:
            _render_login(provider, oidc_status)


if __name__ == "__main__":
    main()
