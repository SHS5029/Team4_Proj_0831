"""관리자 화면의 운영 분석·피드백·로그·운영 에이전트 계획 화면."""

from __future__ import annotations

import altair as alt
import streamlit as st
from frontend_admin.app_pages.agent_plan_page import render as render_agent_plan
from frontend_admin.core.api_client import AUDIT_EVENT_LABELS


ADMIN_DASHBOARD_CSS = """
<style>
[data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] { background: #f4f5fa; color: #172033; color-scheme: light; }
[data-testid="stMainBlockContainer"] { width: min(100%, 1240px); padding: 1.6rem 1.6rem 3rem; }
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 { color: #172033; }
[data-testid="stCaptionContainer"] p { color: #4f5b73 !important; opacity: 1 !important; }
[data-testid="stWidgetLabel"] p, [data-testid="stSelectbox"] label p, [data-testid="stTextInput"] label p { color: #172033 !important; font-weight: 700 !important; }
[data-baseweb="select"], [data-baseweb="input"], [data-testid="stTextInput"] input, textarea { color: #172033 !important; -webkit-text-fill-color: #172033 !important; background: #fff !important; }
[data-baseweb="select"] *, [data-baseweb="input"] input { color: #172033 !important; -webkit-text-fill-color: #172033 !important; }
[data-baseweb="select"] { border-color: #bcc4d6 !important; }
[data-testid="stAlert"] p, [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p { color: #172033 !important; }
[data-testid="stCode"] pre { color: #172033 !important; background: #f7f8fc !important; }
.admin-hero { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin-bottom:1.4rem; padding:1.35rem 1.5rem; border:1px solid #e5e2ef; border-radius:1rem; background:linear-gradient(135deg,#fff 0%,#f7f3ff 100%); box-shadow:0 12px 30px rgba(31,24,61,.07); }
.admin-eyebrow { color:#5f35c9; font-size:.74rem; font-weight:850; letter-spacing:.14em; text-transform:uppercase; }
.admin-hero h1 { margin:.35rem 0 0; color:#172033; letter-spacing:-.055em; font-size:2.1rem; }
.admin-hero p { margin:.4rem 0 0; color:#68738a; font-size:.95rem; }
.admin-hero-badge { flex:0 0 auto; padding:.42rem .7rem; border:1px solid #d8c9ff; border-radius:999px; color:#5f35c9; background:#f2edff; font-size:.72rem; font-weight:800; letter-spacing:.04em; }
[data-testid="stMetric"] { padding:1rem 1.1rem; border:1px solid #e1e4ed; border-radius:.85rem; background:#fff; box-shadow:0 10px 28px rgba(25,35,70,.06); }
[data-testid="stMetricLabel"] p { color:#68738a; font-weight:650; }
[data-testid="stMetricValue"] { color:#172033; }
[data-baseweb="tab-list"] { gap:.4rem; padding:.35rem; border:1px solid #e0e3ec; border-radius:.75rem; background:#eceef5; }
[data-baseweb="tab"] { min-height:2.55rem; padding:0 1rem; border-radius:.5rem; color:#5e697f; font-weight:750; }
[data-baseweb="tab"] p { color:inherit !important; }
[aria-selected="true"][data-baseweb="tab"] { color:#fff; background:#4b237a; box-shadow:0 4px 10px rgba(75,35,122,.2); }
[data-testid="stButton"] button { min-height:2.55rem; border:1px solid #4b237a !important; border-radius:.6rem !important; color:#fff !important; background:#4b237a !important; font-weight:750 !important; box-shadow:0 4px 10px rgba(75,35,122,.12); }
[data-testid="stButton"] button p, [data-testid="stButton"] button span { color:#fff !important; }
[data-testid="stButton"] button:hover:not(:disabled) { border-color:#65349c !important; background:#65349c !important; transform:translateY(-1px); }
[data-testid="stButton"] button:disabled { color:#9d96aa !important; background:#e9e7ee !important; border-color:#d8d4e0 !important; box-shadow:none; }
.admin-status-label { display:inline-flex; align-items:center; gap:.35rem; margin:.2rem 0 .75rem; color:#5f35c9; font-size:.8rem; font-weight:800; }
.admin-section-note { color:#68738a; font-size:.9rem; margin-bottom:1rem; }
.admin-divider { height:1px; margin:1.4rem 0; background:#e1e4ed; }
@media (max-width:768px) { [data-testid="stMainBlockContainer"] { padding:.8rem .8rem 2rem; } }
</style>
"""


def render(metrics: dict, *, insights: dict, records: dict,
           synthetic: bool = False, client=None) -> None:
    """중복을 제거한 통합 운영 분석과 읽기 전용 기록 화면을 표시한다.

    운영 현황과 통계 분석은 같은 KPI를 반복하지 않도록 하나의 화면으로 합친다.
    게임 목록은 관리자 요약 화면에서 제외하고, 피드백·로그만 별도 화면에서
    페이지 단위로 확인한다. 합성 모드 여부는 수치와 별개로 안내 문구에 반영한다.
    """

    st.markdown(ADMIN_DASHBOARD_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="admin-hero"><div><div class="admin-eyebrow">AI MAFIA · INSIGHTS</div>'
        '<h1>관리자 센터</h1><p>핵심 KPI와 페르소나 성과를 한 화면에서 확인합니다.</p></div>'
        '<div class="admin-hero-badge">READ ONLY · ADMIN</div></div>',
        unsafe_allow_html=True,
    )
    analysis_tab, feedback_tab, logs_tab, agent_plan_tab = st.tabs(
        ["운영 분석", "사용자 피드백", "관리자 로그", "운영 에이전트 계획"]
    )
    with analysis_tab:
        _render_operations_analysis(metrics, insights=insights, synthetic=synthetic)
    with feedback_tab:
        _render_feedback(metrics, records=records, synthetic=synthetic)
    with logs_tab:
        _render_logs(records=records, synthetic=synthetic)
    with agent_plan_tab:
        render_agent_plan(synthetic=synthetic, client=client)


def _render_operations_analysis(metrics: dict, *, insights: dict,
                                synthetic: bool = False) -> None:
    """운영 KPI·진영 결과·페르소나 승률을 한눈에 비교하도록 배치한다."""

    st.subheader("운영 분석")
    st.markdown('<div class="admin-status-label">● 핵심 운영 지표</div>', unsafe_allow_html=True)
    st.caption(
        f"가상 데이터 {metrics.get('games_created', 0):,}건 기준 · 실제 운영 수치가 아닙니다."
        if synthetic else "현재 Backend에 저장된 공개 집계 기준입니다."
    )
    wins = metrics.get("wins_by_faction", {})
    wins = wins if isinstance(wins, dict) else {}
    citizen_wins = int(wins.get("CITIZEN", 0) or 0)
    mafia_wins = int(wins.get("MAFIA", 0) or 0)
    total_wins = citizen_wins + mafia_wins
    citizen_rate = citizen_wins / total_wins if total_wins else 0
    mafia_rate = mafia_wins / total_wins if total_wins else 0
    completion_rate = metrics.get("completion_rate", 0.0)
    if isinstance(completion_rate, (int, float)):
        completion_rate = f"{completion_rate * 100:.1f}%"
    columns = st.columns(5)
    for column, (key, label) in zip(
        columns,
        (("users_total", "전체 사용자"), ("games_created", "누적 게임"),
         ("completion_rate", "완료율"), ("citizen_rate", "시민 승률"),
         ("mafia_rate", "마피아 승률")),
        strict=True,
    ):
        value = {
            "completion_rate": completion_rate,
            "citizen_rate": f"{citizen_rate * 100:.1f}%",
            "mafia_rate": f"{mafia_rate * 100:.1f}%",
        }.get(key, metrics.get(key, 0))
        column.metric(label, value)

    chart_data = {"시민": citizen_wins, "마피아": mafia_wins}
    total = sum(chart_data.values())
    st.markdown('<div class="admin-section-note">완료된 경기의 결과와 AI 페르소나 성과를 함께 비교합니다.</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### 진영별 승리 횟수")
        if total:
            rows = [{"진영": faction, "승리 횟수": count, "비율": count / total}
                    for faction, count in chart_data.items()]
            chart = alt.Chart(alt.Data(values=rows)).mark_arc(innerRadius=75).encode(
                theta=alt.Theta("승리 횟수:Q", stack=True),
                color=alt.Color("진영:N", scale=alt.Scale(
                    domain=["시민", "마피아"], range=["#3979c6", "#572585"]),
                    legend=alt.Legend(orient="bottom")),
                tooltip=[alt.Tooltip("진영:N"), alt.Tooltip("승리 횟수:Q", format=","),
                         alt.Tooltip("비율:Q", format=".1%")],
            ).properties(height=290)
            center = alt.Chart(alt.Data(values=[{"표시": f"총 {total:,}승"}])).mark_text(
                fontSize=23, fontWeight="bold", color="#172033",
            ).encode(text="표시:N")
            st.altair_chart(chart + center, width="stretch")
            st.caption(" · ".join(f"{name} {count:,}승 ({count / total:.1%})"
                                  for name, count in chart_data.items()))
        else:
            st.info("진영별 승리 기록이 없습니다.")
    with right:
        st.markdown("#### 에이전트 페르소나별 승률")
        st.caption("AI 참여 기록 기준 · 페르소나의 소속 진영이 승리한 비율입니다.")
        personas = insights.get("personas", [])
        if not personas:
            st.info("페르소나별 통계는 아직 제공되지 않습니다.")
        else:
            persona_chart = alt.Chart(alt.Data(values=personas)).mark_bar(
                size=12, cornerRadiusEnd=4, color="#6d4aff"
            ).encode(
                x=alt.X("승률 (%):Q", title="승률 (%)", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("페르소나:N", title=None, sort="-x"),
                tooltip=[alt.Tooltip("페르소나:N"), alt.Tooltip("성격:N"),
                         alt.Tooltip("참여 수:Q", format=","),
                         alt.Tooltip("승리 수:Q", format=","), alt.Tooltip("승률 (%):Q", format=".1f")],
            ).properties(height=max(170, len(personas) * 32))
            labels = alt.Chart(alt.Data(values=personas)).mark_text(
                align="left", baseline="middle", dx=6, color="#172033", fontWeight="bold"
            ).encode(x=alt.X("승률 (%):Q"), y=alt.Y("페르소나:N", sort="-x"),
                     text=alt.Text("승률 (%):Q", format=".1f")
            )
            st.altair_chart(persona_chart + labels, width="stretch")
            with st.expander("페르소나 상세 수치", expanded=False):
                st.dataframe(personas, hide_index=True)

    ops_left, ops_right = st.columns(2)
    ops_left.metric("평균 라운드", metrics.get("average_rounds", 0))
    ops_right.metric("자동 행동", metrics.get("auto_action_count", 0))
    daily = insights.get("daily", [])
    if daily:
        st.markdown("#### 일별 게임 생성 · 가상 예시" if synthetic else "#### 일별 게임 생성")
        st.caption("최근 30일 생성 건수")
        st.line_chart(daily, x="날짜", y="생성 게임", color="#6d4aff", height=180)


def _render_feedback(metrics: dict, *, records: dict, synthetic: bool = False) -> None:
    """사용자 피드백만 별도 화면에 표시해 개선 대상을 빠르게 찾는다."""

    st.subheader("사용자 피드백")
    st.markdown('<div class="admin-status-label">● 서비스 개선 의견</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="admin-section-note">평점과 의견을 확인해 사용자 경험과 게임 규칙 개선에 반영합니다.</div>',
        unsafe_allow_html=True,
    )
    feedback_average = metrics.get("feedback_average")
    feedback_value = "-" if feedback_average is None else f"{float(feedback_average):.2f} / 5"
    st.metric("평균 피드백 점수", feedback_value)
    with st.container(border=True):
        st.selectbox("피드백 종류", ["전체", "일반", "게임"], key="admin.feedback.type")
        st.selectbox("평점", ["전체", "1", "2", "3", "4", "5"], key="admin.feedback.rating")
        rows = records["feedback"]["items"]
        st.caption("가상 의견 · 실제 사용자 의견이 아닙니다." if synthetic else "사용자가 제출한 의견입니다.")
        if rows:
            st.dataframe([{"작성일": r["created_at"], "종류": r["feedback_type"],
                           "평점": r["rating"], "의견": r["comment"],
                           "사용자 UUID": r["user_id"], "게임 UUID": r["game_id"],
                           "피드백 UUID": r["feedback_id"]} for r in rows], hide_index=True)
        else:
            st.info("조건에 맞는 피드백이 없습니다.")
        _record_navigation("admin.feedback", records["feedback"])


def _render_logs(*, records: dict, synthetic: bool = False) -> None:
    """관리자 감사 로그만 별도 화면에 표시해 운영 이력을 추적한다."""

    st.subheader("관리자 로그")
    st.markdown('<div class="admin-status-label">● 감사 기록</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="admin-section-note">관리자 API 조회 이력을 읽기 전용으로 확인합니다. 서버 원문 로그는 노출하지 않습니다.</div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.selectbox("조회 유형", list(AUDIT_EVENT_LABELS), key="admin.logs.type")
        rows = records["logs"]["items"]
        st.caption("가상 감사 이력입니다." if synthetic else "관리자 조회 이력입니다.")
        labels = {value: key for key, value in AUDIT_EVENT_LABELS.items()}
        if rows:
            st.dataframe([{"시각": r["created_at"], "조회 유형": labels.get(r["event_type"], r["event_type"]),
                           "관리자 UUID": r["admin_user_id"], "대상 게임": r["target_game_id"],
                           "요청 ID": r["request_id"], "감사 ID": r["audit_id"]}
                          for r in rows], hide_index=True)
        else:
            st.info("조건에 맞는 감사 기록이 없습니다.")
        _record_navigation("admin.logs", records["logs"])


def _record_navigation(name: str, data: dict) -> None:
    """콜백에서 커서를 바꿔 한 번 클릭하면 다음 실행에서 해당 페이지를 읽는다."""

    stack = st.session_state[name + ".cursors"]
    previous, following = st.columns(2)
    previous.button("이전", key=name + ".previous", disabled=len(stack) == 1,
                    on_click=lambda: st.session_state[name + ".cursors"].pop())
    following.button("다음", key=name + ".next", disabled=data.get("next_cursor") is None,
                     on_click=lambda: st.session_state[name + ".cursors"].append(data["next_cursor"]))
    st.caption(f"{len(stack)} 페이지 · {len(data['items'])}건 표시")
