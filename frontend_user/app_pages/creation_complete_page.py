"""게임 생성 직후 플레이어와 다음 행동을 안내하는 완료 화면."""

from __future__ import annotations

import streamlit as st


# MOCK ONLY: 실제 시나리오·player preset 연결 시 이 목록을 제거한다.
PLAYER_NAMES = ["민수", "철수", "영희", "태경", "지효", "성주", "환석", "유빈", "태웅", "지혜", "지토"]


def render(pending: dict[str, object]) -> None:
    """Backend 생성 성공 결과만 사용해 역할 공개 전 대기 화면을 표시한다."""

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] { background:linear-gradient(145deg,#f4f8ff,#eef4fb); }
        .complete-card { max-width:760px; margin:3rem auto 1rem; padding:2.2rem; border:1px solid #d7e3f5;
          border-radius:1.2rem; background:#fff; box-shadow:0 1rem 2.5rem rgba(42,79,145,.12); text-align:center; }
        .complete-icon { font-size:3.2rem; } .complete-card h1 { color:#152238; margin:.5rem 0; }
        .complete-card p { color:#66758f; } .complete-id { margin:1.2rem 0; padding:1rem; border-radius:.7rem;
          color:#244d91; background:#eef5ff; font-family:monospace; word-break:break-all; }
        .complete-players { display:flex; flex-wrap:wrap; justify-content:center; gap:.5rem; margin:1.2rem 0; }
        .complete-player { padding:.45rem .7rem; border-radius:999px; color:#315a9f; background:#f0f5ff; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    game_id = str(pending.get("game_id", "확인 중"))
    snapshot = pending.get("snapshot")
    game = snapshot.get("data", {}).get("game", {}) if isinstance(snapshot, dict) else {}
    player_count = game.get("player_count", pending.get("player_count", 6)) if isinstance(game, dict) else pending.get("player_count", 6)
    try:
        player_count = max(6, min(9, int(player_count)))
    except (TypeError, ValueError):
        player_count = 6
    names = PLAYER_NAMES[:player_count]

    st.markdown(
        f'<section class="complete-card"><div class="complete-icon">🎉</div>'
        f'<h1>게임이 만들어졌어요</h1><p>{player_count}명의 플레이어가 사건 현장에 모였습니다.</p>'
        f'<div class="complete-id">게임 식별자<br>{game_id}</div>'
        f'<div class="complete-players">{"".join(f"<span class=\"complete-player\">{name}</span>" for name in names)}</div>'
        f'<p>역할은 다음 화면에서 비공개로 공개됩니다.</p></section>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        if st.button("역할 공개 보기", type="primary", key="creation.complete.continue", width="stretch"):
            st.session_state["navigation.page"] = "game"
            st.rerun()
    with right:
        if st.button("홈으로 돌아가기", key="creation.complete.home", width="stretch"):
            st.session_state["navigation.page"] = "home"
            st.session_state.pop("game.game_id", None)
            st.rerun()
