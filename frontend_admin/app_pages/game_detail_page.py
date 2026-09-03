"""관리자 게임 상세."""

from __future__ import annotations

import streamlit as st


def render(detail: dict) -> None:
    """비밀정보가 제거된 상세만 read-only로 표시한다."""

    st.header("게임 상세")
    st.json(detail)
