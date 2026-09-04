"""관리자 metrics dashboard."""

from __future__ import annotations

import streamlit as st


ADMIN_DASHBOARD_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #f5f7fb; color: #152238; }
[data-testid="stMainBlockContainer"] { width: min(100%, 1240px); padding: 1.5rem 1.5rem 3rem; }
.admin-eyebrow { color:#3568f2; font-size:.78rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.admin-hero h1 { margin:.3rem 0 0; color:#152238; letter-spacing:-.05em; }
.admin-hero p { margin:.4rem 0 0; color:#66758f; }
[data-testid="stMetric"] { padding:1rem 1.1rem; border:1px solid #e1e7f0; border-radius:.85rem; background:#fff; box-shadow:0 10px 28px rgba(25,45,86,.06); }
[data-testid="stMetricLabel"] p { color:#66758f; font-weight:650; }
[data-testid="stMetricValue"] { color:#152238; }
@media (max-width:768px) { [data-testid="stMainBlockContainer"] { padding:.8rem .8rem 2rem; } }
</style>
"""


def render(metrics: dict) -> None:
    """검증된 metrics만 표시한다."""

    st.markdown(ADMIN_DASHBOARD_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="admin-hero"><div><div class="admin-eyebrow">AI MAFIA · INSIGHTS</div>'
        '<h1>게임 통계</h1><p>종료된 게임의 결과와 플레이 흐름을 확인합니다.</p></div></div>',
        unsafe_allow_html=True,
    )
    columns = st.columns(5)
    completion_rate = metrics.get("completion_rate", 0.0)
    if isinstance(completion_rate, (int, float)):
        completion_rate = f"{completion_rate * 100:.1f}%"
    for column, (key, label) in zip(
        columns,
        (("games_created", "전체 게임"), ("games_completed", "종료 게임"),
         ("games_saved", "저장 게임"), ("completion_rate", "종료율"),
         ("feedback_average", "평균 피드백")),
        strict=True,
    ):
        value = completion_rate if key == "completion_rate" else metrics.get(key, 0)
        column.metric(label, value)

    st.markdown("### 종료 게임 분석")
    completed = int(metrics.get("games_completed", 0) or 0)
    if completed == 0:
        st.info("아직 종료된 게임이 없어 분석할 통계가 없습니다. 게임이 끝나면 이곳에 집계됩니다.")
        return
    analysis_columns = st.columns(4)
    analysis_columns[0].metric("평균 진행 라운드", metrics.get("average_rounds", 0))
    wins = metrics.get("wins_by_faction", {})
    wins = wins if isinstance(wins, dict) else {}
    analysis_columns[1].metric("시민 승리", wins.get("CITIZEN", 0))
    analysis_columns[2].metric("마피아 승리", wins.get("MAFIA", 0))
    analysis_columns[3].metric("자동 행동", metrics.get("auto_action_count", 0))
