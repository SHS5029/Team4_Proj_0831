"""관리자 게임 목록."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend_admin.core.models import ADMIN_PHASES, ADMIN_STATUSES


LIST_CSS = """
<style>
.admin-list-title { color:#152238; font-size:1.05rem; font-weight:800; }
.admin-list-meta { margin:.25rem 0 .7rem; color:#66758f; font-size:.83rem; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:#e1e7f0; border-radius:.8rem; background:#fff; }
</style>
"""


def render_filters() -> tuple[str | None, str | None]:
    """Backend 목록 API가 지원하는 상태·단계만 선택하게 한다."""

    columns = st.columns(2)
    status = columns[0].selectbox(
        "게임 상태", (None, *ADMIN_STATUSES), key="admin.filter.status",
        format_func=lambda value: value or "전체 상태",
    )
    phase = columns[1].selectbox(
        "게임 단계", (None, *ADMIN_PHASES), key="admin.filter.phase",
        format_func=lambda value: value or "전체 단계",
    )
    return status, phase


def render(items: list[dict]) -> str | None:
    """공개 관리자 요약 필드만 표시하고 선택한 game id를 반환한다."""

    st.markdown(LIST_CSS, unsafe_allow_html=True)
    st.subheader("최근 게임")
    st.caption("선택한 조건의 최근 20개 게임에서 공개 요약 정보만 표시됩니다.")
    if not items:
        st.info("조건에 맞는 게임이 없습니다.")
    selected = None
    for item in items:
        game_id = item.get("game_id")
        with st.container(border=True):
            title = escape(str(item.get("game_id", "게임")))
            status = escape(str(item.get("status", "-")))
            phase = escape(str(item.get("phase", "-")))
            count = escape(str(item.get("player_count", "-")))
            st.markdown(f"<div class=\"admin-list-title\">{title}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class=\"admin-list-meta\">{status} · {phase} · {count}명</div>", unsafe_allow_html=True)
            if isinstance(game_id, str) and st.button("상세 보기", key=f"admin.game.{game_id}"):
                selected = game_id
    return selected
