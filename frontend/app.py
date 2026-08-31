"""Streamlit entry point for the native Google OIDC login screen."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import streamlit as st

# ``streamlit run frontend/app.py`` puts ``frontend`` first on sys.path.  Add the
# repository root explicitly so the shared backend domain/repository can be used.
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
from ui import APP_CSS, hero_html, login_intro_html, profile_card_html  # noqa: E402

LOGGER = logging.getLogger(__name__)


def _load_oidc_status(provider: OAuthProvider) -> OidcConfigurationStatus:
    """Read only the shape of secrets and never surface their values."""

    try:
        secrets = st.secrets.to_dict()
    except Exception as exc:  # Streamlit uses different errors for absent sources.
        LOGGER.info("OIDC secrets are unavailable (%s)", type(exc).__name__)
        secrets = None
    return inspect_oidc_configuration(secrets, provider=provider.id)


def _persist_profile(profile: IdentityProfile) -> PersistenceResult:
    """Lazily cross the UI/backend boundary after OIDC authentication succeeds."""

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
        return PersistenceResult(
            state="blocked",
            user_message="비활성화된 계정입니다. 관리자에게 문의해 주세요.",
        )
    except Exception as exc:
        # Do not render exception strings: database drivers can include connection data.
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
    raw_key = f"{profile.provider}:{profile.provider_subject}".encode()
    return hashlib.sha256(raw_key).hexdigest()


def _render_login(
    provider: OAuthProvider,
    oidc_status: OidcConfigurationStatus,
) -> None:
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
                st.login(provider.id)
        except Exception as exc:
            LOGGER.warning("Native OIDC login could not start (%s)", type(exc).__name__)
            st.error(
                "Google 로그인 페이지를 열지 못했어요. 잠시 후 다시 시도해 주세요.",
                icon="⚠️",
            )


def _render_untrusted_session() -> None:
    """Refuse cookies signed under missing, weak, or placeholder OIDC settings."""

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
          <p class="auth-kicker">WELCOME BACK</p>
          <h2 class="auth-title" id="welcome-title">다시 만나<br>반가워요.</h2>
          <p class="auth-description">저장해 둔 여행과 새로운 영감을 이어서 만나보세요.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(profile_card_html(profile), unsafe_allow_html=True)

    cache_key = _profile_cache_key(profile)
    cached_result = st.session_state.get("identity-persistence-result")
    cached_key = st.session_state.get("identity-persistence-key")
    if should_refresh_persistence(
        cached_result,
        cached_identity_key=cached_key,
        current_identity_key=cache_key,
    ):
        with st.spinner("계정 정보를 안전하게 연결하고 있어요..."):
            cached_result = _persist_profile(profile)
        st.session_state["identity-persistence-key"] = cache_key
        st.session_state["identity-persistence-result"] = cached_result

    feedback = persistence_feedback(cached_result)
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
            st.session_state.pop("identity-persistence-result", None)
            st.rerun()

    with st.container(key="account-logout"):
        if st.button("로그아웃", key="logout-button", use_container_width=True):
            st.session_state.pop("identity-persistence-key", None)
            st.session_state.pop("identity-persistence-result", None)
            with st.spinner("안전하게 로그아웃하고 있어요..."):
                st.logout()


def main() -> None:
    st.set_page_config(
        page_title="여정 | Google 로그인",
        page_icon="✦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(APP_CSS, unsafe_allow_html=True)

    provider = get_provider("google")
    oidc_status = _load_oidc_status(provider)
    st.session_state[APPLICATION_ACCESS_SESSION_KEY] = False
    hero_column, auth_column = st.columns(
        [1.12, 0.88],
        gap="large",
        vertical_alignment="center",
    )
    with hero_column:
        st.markdown(hero_html(), unsafe_allow_html=True)

    with auth_column:
        with st.container(border=True, key="auth-card"):
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
