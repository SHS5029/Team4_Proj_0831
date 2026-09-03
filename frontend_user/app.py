"""일반 사용자 앱의 UUID bootstrap과 화면 dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend_user.app_pages.game_create_page import render as render_create  # noqa: E402
from frontend_user.app_pages.feedback_page import render as render_feedback  # noqa: E402
from frontend_user.app_pages.game_page import render as render_game  # noqa: E402
from frontend_user.app_pages.home_page import load_games, render as render_home  # noqa: E402
from frontend_user.app_pages.role_reveal_page import render as render_role_reveal  # noqa: E402
from frontend_user.app_pages.result_page import render as render_result  # noqa: E402
from frontend_user.app_pages.settings_page import render as render_settings  # noqa: E402
from frontend_user.components.identity_bridge import (  # noqa: E402
    IDENTITY_COMPONENT_CHANGED_SESSION_KEY,
    load_identity,
)
from frontend_user.core.api_client import ApiClient  # noqa: E402
from frontend_user.core.session import (  # noqa: E402
    IDENTITY_WARNING_SESSION_KEY,
    get_identity,
    set_identity,
)


def main() -> None:
    """UUID를 한 번 bootstrap한 뒤 Backend 연동 준비 화면을 표시한다."""

    st.set_page_config(page_title="AI 마피아", page_icon="🕵️", layout="wide")
    if (
        get_identity(st.session_state) is None
        or st.session_state.get(IDENTITY_COMPONENT_CHANGED_SESSION_KEY) is True
    ):
        user_id, persistence, error_code = load_identity()
        set_identity(user_id=user_id, persistence=persistence, session_state=st.session_state)
        st.session_state.pop(IDENTITY_COMPONENT_CHANGED_SESSION_KEY, None)
        if error_code:
            st.session_state[IDENTITY_WARNING_SESSION_KEY] = True

    client = ApiClient(user_id=get_identity(st.session_state))
    st.session_state["game.client"] = client
    if st.session_state.get(IDENTITY_WARNING_SESSION_KEY):
        st.warning("브라우저 저장소를 사용할 수 없어 이번 세션에서만 게임을 복구할 수 있어요.")
    page = st.session_state.get("navigation.page", "home")
    if page == "feedback":
        render_feedback(client=client, feedback_type="GENERAL")
    elif page == "game_feedback":
        render_feedback(
            client=client,
            feedback_type="GAME",
            game_id=st.session_state.get("game.game_id"),
            snapshot=st.session_state.get("game.latest_snapshot"),
        )
    elif page == "create":
        render_create(client)
    elif page == "game":
        game_id = st.session_state.get("game.game_id")
        if not isinstance(game_id, str):
            st.session_state["navigation.page"] = "home"
            st.rerun()
        try:
            response = client.get_game(game_id)
            snapshot = response.get("data") if isinstance(response.get("data"), dict) else response
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("game"), dict):
                raise ValueError("INVALID_RESPONSE")
            st.session_state["game.latest_snapshot"] = snapshot
        except Exception:
            st.error("게임 상태를 불러오지 못했어요.")
            if st.button("홈으로 이동", key="game.load_home"):
                st.session_state["navigation.page"] = "home"
                st.session_state.pop("game.game_id", None)
                st.rerun()
        else:
            if snapshot["game"].get("status") in {"COMPLETED", "FAILED"}:
                render_result(snapshot)
            elif snapshot["game"].get("phase") == "ROLE_REVEAL":
                render_role_reveal(snapshot)
            else:
                render_game(snapshot)
    else:
        if "home.games" not in st.session_state and not st.session_state.get("home.games_loading"):
            st.session_state["home.games_loading"] = True
            st.rerun()
        if st.session_state.get("home.games_loading"):
            load_games(client)
            st.rerun()
        render_home(client)
    render_settings()


if __name__ == "__main__":
    main()
