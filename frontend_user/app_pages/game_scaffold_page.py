"""로그인 기능과 독립적으로 연결 뼈대를 확인하는 Streamlit 화면이다."""

import streamlit as st

from frontend_user.core.game_api_client import GameApiClient, GameApiError


def main() -> None:
    """사용자 UUID로 dummy game 생성·조회·PING을 실행한다."""

    st.title("AI 마피아 연결 뼈대")
    user_id = st.text_input("개발용 User UUID", value="00000000-0000-4000-8000-000000000001")
    if st.button("게임 생성"):
        try:
            client = GameApiClient(user_id=user_id)
            game = client.create_game()
            st.session_state["scaffold_game"] = game
            st.success(f"게임 생성 완료: {game['game_id']}")
        except (ValueError, GameApiError) as error:
            st.error(f"연결 실패: {error}")
    game = st.session_state.get("scaffold_game")
    if game:
        st.json(game)
        if st.button("PING command", key="scaffold-ping"):
            try:
                st.json(GameApiClient(user_id=user_id).ping(game["game_id"], game["state_version"]))
            except GameApiError as error:
                st.error(f"command 실패: {error.code}")
