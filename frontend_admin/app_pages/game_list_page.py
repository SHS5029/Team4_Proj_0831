"""관리자 게임 목록."""

from __future__ import annotations

import streamlit as st


def render(items: list[dict]) -> str | None:
    """공개 관리자 요약 필드만 표시하고 선택한 game id를 반환한다."""

    st.header("게임 목록")
    selected = None
    for item in items:
        game_id = item.get("game_id")
        with st.container(border=True):
            st.write(f"{item.get('status', '-')} · {item.get('phase', '-')} · {item.get('player_count', '-')}명")
            if isinstance(game_id, str) and st.button("상세 보기", key=f"admin.game.{game_id}"):
                selected = game_id
    return selected
