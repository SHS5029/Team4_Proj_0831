"""관리자 화면의 운영 현황·통계·피드백 탭."""

from __future__ import annotations

import streamlit as st


ADMIN_DASHBOARD_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #f7f7fb; color: #172033; }
[data-testid="stMainBlockContainer"] { width: min(100%, 1240px); padding: 1.5rem 1.5rem 3rem; }
.admin-eyebrow { color:#6d4aff; font-size:.78rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.admin-hero h1 { margin:.3rem 0 0; color:#172033; letter-spacing:-.05em; }
.admin-hero p { margin:.4rem 0 0; color:#68738a; }
[data-testid="stMetric"] { padding:1rem 1.1rem; border:1px solid #e4e7ef; border-radius:.85rem; background:#fff; box-shadow:0 10px 28px rgba(25,35,70,.06); }
[data-testid="stMetricLabel"] p { color:#68738a; font-weight:650; }
[data-testid="stMetricValue"] { color:#172033; }
[data-baseweb="tab-list"] { gap:.35rem; border-bottom:1px solid #e4e7ef; }
[data-baseweb="tab"] { color:#68738a; font-weight:700; }
[aria-selected="true"][data-baseweb="tab"] { color:#5b39d6; }
.admin-section-note { color:#68738a; font-size:.9rem; margin-bottom:1rem; }
@media (max-width:768px) { [data-testid="stMainBlockContainer"] { padding:.8rem .8rem 2rem; } }
</style>
"""


def render(metrics: dict, render_games) -> None:
    """검증된 공개 지표만 세 개의 읽기 전용 관리자 화면으로 표시한다.

    게임 목록은 기존 목록 컴포넌트를 운영 현황 탭에 배치한다. Backend에 아직
    직업별 승률·피드백 목록·감사 로그 조회 계약이 없으므로 임의의 샘플 데이터는
    표시하지 않고, 연결 준비 상태를 명시해 관리자 화면의 수치를 오해하지 않게 한다.
    """

    st.markdown(ADMIN_DASHBOARD_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="admin-hero"><div><div class="admin-eyebrow">AI MAFIA · INSIGHTS</div>'
        '<h1>관리자 센터</h1><p>운영 현황과 게임 분석을 한 곳에서 확인합니다.</p></div></div>',
        unsafe_allow_html=True,
    )
    overview_tab, analysis_tab, feedback_tab = st.tabs(
        ["운영 현황", "통계 분석", "피드백 · 로그"]
    )
    with overview_tab:
        _render_overview(metrics)
        render_games()
    with analysis_tab:
        _render_analysis(metrics)
    with feedback_tab:
        _render_feedback_and_logs(metrics)


def _render_overview(metrics: dict) -> None:
    """운영자가 가장 먼저 확인할 핵심 KPI와 종료율을 표시한다."""

    st.subheader("운영 현황")
    st.markdown(
        '<div class="admin-section-note">현재 Backend에 저장된 공개 집계 기준입니다.</div>',
        unsafe_allow_html=True,
    )
    wins = metrics.get("wins_by_faction", {})
    wins = wins if isinstance(wins, dict) else {}
    citizen_wins = int(wins.get("CITIZEN", 0) or 0)
    mafia_wins = int(wins.get("MAFIA", 0) or 0)
    total_wins = citizen_wins + mafia_wins
    citizen_rate = citizen_wins / total_wins if total_wins else 0
    mafia_rate = mafia_wins / total_wins if total_wins else 0
    columns = st.columns(5)
    completion_rate = metrics.get("completion_rate", 0.0)
    if isinstance(completion_rate, (int, float)):
        completion_rate = f"{completion_rate * 100:.1f}%"
    for column, (key, label) in zip(
        columns,
        (("games_created", "전체 게임"), ("games_completed", "종료 게임"),
         ("completion_rate", "종료율"), ("citizen_rate", "시민 승률"),
         ("mafia_rate", "마피아 승률")),
        strict=True,
    ):
        value = {
            "completion_rate": completion_rate,
            "citizen_rate": f"{citizen_rate * 100:.1f}%",
            "mafia_rate": f"{mafia_rate * 100:.1f}%",
        }.get(key, metrics.get(key, 0))
        column.metric(label, value)


def _render_analysis(metrics: dict) -> None:
    """시민·마피아 결과 그래프와 직업별 분석의 계약 상태를 표시한다."""

    st.subheader("통계 분석")
    st.markdown(
        '<div class="admin-section-note">종료된 게임의 진영별 결과를 분석합니다.</div>',
        unsafe_allow_html=True,
    )
    completed = int(metrics.get("games_completed", 0) or 0)
    if completed == 0:
        st.info("아직 종료된 게임이 없어 분석할 통계가 없습니다. 게임이 끝나면 이곳에 집계됩니다.")
        return
    wins = metrics.get("wins_by_faction", {})
    wins = wins if isinstance(wins, dict) else {}
    chart_data = {
        "시민": int(wins.get("CITIZEN", 0) or 0),
        "마피아": int(wins.get("MAFIA", 0) or 0),
    }
    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### 진영별 승리 횟수")
        st.bar_chart(chart_data, height=260, color="#6d4aff")
    with right:
        st.markdown("#### 운영 지표")
        st.metric("평균 진행 라운드", metrics.get("average_rounds", 0))
        st.metric("자동 행동", metrics.get("auto_action_count", 0))
        st.info("마피아·탐정·의사·시민 등 에이전트 직업별 승률은 Backend 집계 API가 준비되면 표시됩니다.")


def _render_feedback_and_logs(metrics: dict) -> None:
    """현재 제공되는 평균 피드백과 향후 목록·로그 영역을 구분해 표시한다."""

    st.subheader("피드백 · 로그")
    st.markdown(
        '<div class="admin-section-note">사용자 의견과 관리자 감사 기록을 읽기 전용으로 확인합니다.</div>',
        unsafe_allow_html=True,
    )
    feedback_average = metrics.get("feedback_average")
    feedback_value = "-" if feedback_average is None else f"{float(feedback_average):.2f} / 5"
    st.metric("평균 피드백 점수", feedback_value)
    feedback_col, log_col = st.columns(2)
    with feedback_col:
        with st.container(border=True):
            st.markdown("#### 사용자 피드백")
            st.info("피드백 목록 조회 API가 연결되면 최근 의견과 평점을 표시합니다.")
    with log_col:
        with st.container(border=True):
            st.markdown("#### 관리자 로그")
            st.info("감사 로그 조회 API가 연결되면 관리자 접근·조회 기록을 표시합니다.")
