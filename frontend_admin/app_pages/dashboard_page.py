"""관리자 metrics dashboard."""

from __future__ import annotations

import streamlit as st


def render(metrics: dict) -> None:
    """검증된 metrics만 표시한다."""

    st.header("관리자 대시보드")
    columns = st.columns(5)
    for column, (key, label) in zip(columns, (("games_created", "생성 게임"), ("games_completed", "완료 게임"), ("games_saved", "저장 게임"), ("completion_rate", "완료율"), ("feedback_average", "평균 피드백")), strict=True):
        column.metric(label, metrics.get(key, "-"))
