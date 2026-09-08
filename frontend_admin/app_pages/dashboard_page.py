"""관리자 화면의 운영 분석·피드백·로그 화면."""

from __future__ import annotations

import altair as alt
import streamlit as st
from frontend_admin.core.api_client import AUDIT_EVENT_LABELS


ADMIN_DASHBOARD_CSS = """
<style>
*, *::before, *::after { box-sizing: border-box; }
[data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] { background: #f4f5fa; color: #172033; color-scheme: light; }
[data-testid="stMainBlockContainer"] { width: 100%; max-width: 1240px; margin: 0 auto; padding: 1.6rem clamp(.8rem, 2.5vw, 1.6rem) 3rem; overflow-x: clip; }
[data-testid="stHorizontalBlock"] { max-width: 100%; }
[data-testid="stColumn"] { min-width: 0 !important; }
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
[data-testid="stMetric"] { min-width:0; overflow:hidden; padding:1rem 1.1rem; border:1px solid #e1e4ed; border-radius:.85rem; background:#fff; box-shadow:0 10px 28px rgba(25,35,70,.06); }
[data-testid="stMetricLabel"] p { color:#68738a; font-weight:650; }
[data-testid="stMetricValue"] { color:#172033; white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:anywhere; font-size:clamp(1.3rem, 2.4vw, 2rem); }
[data-baseweb="tab-list"] { gap:.4rem; padding:.35rem; border:1px solid #e0e3ec; border-radius:.75rem; background:#eceef5; }
[data-baseweb="tab"] { min-height:2.55rem; padding:0 1rem; border-radius:.5rem; color:#5e697f; font-weight:750; }
[data-baseweb="tab"] p { color:inherit !important; }
[aria-selected="true"][data-baseweb="tab"] { color:#fff; background:#4b237a; box-shadow:0 4px 10px rgba(75,35,122,.2); }
[data-testid="stButton"] button { min-height:2.55rem; border:1px solid #4b237a !important; border-radius:.6rem !important; color:#fff !important; background:#4b237a !important; font-weight:750 !important; box-shadow:0 4px 10px rgba(75,35,122,.12); }
[data-testid="stButton"] button p, [data-testid="stButton"] button span { color:#fff !important; }
[data-testid="stButton"] button:hover:not(:disabled) { border-color:#65349c !important; background:#65349c !important; transform:translateY(-1px); }
[data-testid="stButton"] button:disabled { color:#9d96aa !important; background:#e9e7ee !important; border-color:#d8d4e0 !important; box-shadow:none; }
[data-testid="stPopoverBody"] {
    width: min(680px, calc(100vw - 2rem)) !important;
    max-width: calc(100vw - 2rem) !important;
}
.admin-status-label { display:inline-flex; align-items:center; gap:.35rem; margin:.2rem 0 .75rem; color:#5f35c9; font-size:.8rem; font-weight:800; }
.admin-section-note { color:#68738a; font-size:.9rem; margin-bottom:1rem; }
.admin-live-chart-status { display:inline-flex; align-items:center; gap:.48rem; min-height:2.2rem; margin:.15rem 0 .8rem; padding:.38rem .7rem; border:1px solid #bfe8cf; border-radius:.65rem; color:#166534; background:#f0fdf4; font-size:.78rem; box-shadow:0 4px 12px rgba(22,101,52,.08); }
.admin-live-chart-status strong { color:#166534; font-weight:850; }
.admin-live-chart-status > span:not(.admin-live-chart-dot):not(.admin-live-chart-cycle) { color:#35624a; }
.admin-live-chart-dot { width:.58rem; height:.58rem; flex:0 0 auto; border-radius:50%; background:#16a34a; box-shadow:0 0 0 3px rgba(22,163,74,.13), 0 0 10px rgba(22,163,74,.38); animation:admin-live-pulse 1.8s ease-in-out infinite; }
.admin-live-chart-cycle { color:#15803d; font-weight:750; }
@keyframes admin-live-pulse { 0%, 100% { opacity:1; } 50% { opacity:.55; } }
.admin-divider { height:1px; margin:1.4rem 0; background:#e1e4ed; }
@media (max-width:1050px) {
    .st-key-admin-kpi-grid [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
    .st-key-admin-kpi-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { flex:1 1 calc(33.333% - .75rem) !important; }
}
@media (max-width:768px) {
    [data-testid="stMainBlockContainer"] { padding:.8rem .8rem 2rem; }
    .st-key-admin-kpi-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { flex-basis:calc(50% - .6rem) !important; }
}
@media (max-width:480px) {
    .st-key-admin-kpi-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { flex-basis:100% !important; }
}
</style>
"""


def render(metrics: dict, *, insights: dict, records: dict,
           synthetic: bool = False, refreshed_at: str | None = None) -> None:
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
    analysis_tab, feedback_tab, logs_tab = st.tabs(
        ["운영 분석", "사용자 피드백", "관리자 로그"]
    )
    with analysis_tab:
        _render_operations_analysis(
            metrics,
            insights=insights,
            synthetic=synthetic,
            refreshed_at=refreshed_at,
        )
    with feedback_tab:
        _render_feedback(metrics, records=records, synthetic=synthetic)
    with logs_tab:
        _render_logs(records=records, synthetic=synthetic)


def _render_operations_analysis(metrics: dict, *, insights: dict,
                                synthetic: bool = False,
                                refreshed_at: str | None = None) -> None:
    """운영 KPI·진영 결과·페르소나 승률을 한눈에 비교하도록 배치한다."""

    st.subheader("운영 분석")
    st.markdown('<div class="admin-status-label">● 핵심 운영 지표</div>', unsafe_allow_html=True)
    st.caption(
        f"가상 데이터 {metrics.get('games_created', 0):,}건 기준 · 실제 운영 수치가 아닙니다."
        if synthetic else "현재 Backend에 저장된 공개 집계 기준입니다."
    )
    _render_live_chart_status(refreshed_at, synthetic=synthetic)
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
    average_rounds = metrics.get("average_rounds", 0)
    try:
        average_rounds_value = f"{float(average_rounds):.2f} ROUND"
    except (TypeError, ValueError):
        average_rounds_value = "0.00 ROUND"
    with st.container(key="admin-kpi-grid"):
        columns = st.columns(6)
        for column, (key, label) in zip(
            columns,
            (("users_total", "전체 사용자"), ("games_created", "누적 게임"),
             ("completion_rate", "완료율"), ("average_rounds", "평균 경기 라운드"),
             ("citizen_rate", "시민 승률"), ("mafia_rate", "마피아 승률")),
            strict=True,
        ):
            value = {
                "completion_rate": completion_rate,
                "average_rounds": average_rounds_value,
                "citizen_rate": f"{citizen_rate * 100:.1f}%",
                "mafia_rate": f"{mafia_rate * 100:.1f}%",
            }.get(key, metrics.get(key, 0))
            column.metric(label, value)

    chart_data = {"시민": citizen_wins, "마피아": mafia_wins}
    total = sum(chart_data.values())
    st.markdown('<div class="admin-section-note">완료된 경기의 결과와 AI 페르소나 성과를 함께 비교합니다.</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        with st.container(border=True):
            with st.container(
                horizontal=True,
                height=44,
                border=False,
                vertical_alignment="center",
            ):
                st.markdown("#### 진영별 승리 확률")
            st.caption("완료된 경기 기준 · 도넛 안쪽은 전체 승리 횟수입니다.")
            if total:
                rows = [{"진영": faction, "승리 횟수": count, "비율": count / total}
                        for faction, count in chart_data.items()]
                chart = alt.Chart(alt.Data(values=rows)).mark_arc(
                    innerRadius=78,
                    outerRadius=116,
                    padAngle=0.008,
                    cornerRadius=0,
                    stroke="#10131a",
                    strokeWidth=2,
                ).encode(
                    theta=alt.Theta("승리 횟수:Q", stack=True),
                    color=alt.Color("진영:N", scale=alt.Scale(
                        domain=["시민", "마피아"], range=["#3b82f6", "#dc2626"]),
                        legend=alt.Legend(orient="bottom", title=None)),
                    tooltip=[alt.Tooltip("진영:N"), alt.Tooltip("승리 횟수:Q", format=","),
                             alt.Tooltip("비율:Q", format=".1%")],
                ).properties(height=260)
                center = alt.Chart(alt.Data(values=[{"표시": f"총 {total:,}승"}])).mark_text(
                    fontSize=23, fontWeight="bold", color="#f8fafc",
                ).encode(text="표시:N")
                donut_chart = (chart + center).properties(
                    height=300,
                    padding={"top": 24, "bottom": 24, "left": 8, "right": 8},
                ).configure(
                    background="#10131a",
                ).configure_view(
                    stroke=None,
                ).configure_legend(
                    labelColor="#f1f5f9",
                    titleColor="#f1f5f9",
                )
                st.altair_chart(donut_chart, width="stretch")
                st.caption(" · ".join(f"{name} {count:,}승 ({count / total:.1%})"
                                      for name, count in chart_data.items()))
                if citizen_wins == mafia_wins:
                    st.caption("현재 완료 경기에서는 두 진영의 승리 확률이 같습니다.")
                else:
                    leading_faction = "시민" if citizen_wins > mafia_wins else "마피아"
                    st.caption(f"현재 완료 경기에서는 {leading_faction} 진영의 승리 확률이 더 높습니다.")
            else:
                st.info("진영별 승리 기록이 없습니다.")
    with right:
        with st.container(border=True):
            with st.container(
                horizontal=True,
                height=44,
                border=False,
                wrap=False,
                horizontal_alignment="distribute",
                vertical_alignment="center",
            ):
                st.markdown("#### 페르소나별 승률")
                persona_details = st.popover(
                    "상세 정보", icon=":material/table_chart:"
                )
            st.caption("AI 참여 기록 기준 · 높은 승률 순으로 정렬하며 막대 끝에 수치를 표시합니다.")
            personas = insights.get("personas", [])
            if not personas:
                st.info("페르소나별 통계는 아직 제공되지 않습니다.")
            else:
                with persona_details:
                    st.caption("페르소나별 참여·승리 횟수와 계산된 승률입니다.")
                    st.dataframe(personas, hide_index=True, height=220, width="stretch")
                persona_data = alt.Data(values=personas)
                persona_sort = alt.SortField(field="승률 (%)", order="descending")
                persona_chart = alt.Chart(persona_data).mark_bar(
                    size=14, cornerRadiusEnd=4, color="#6d4aff"
                ).encode(
                    x=alt.X("승률 (%):Q", title="승률 (%)", scale=alt.Scale(domain=[0, 110]),
                            axis=alt.Axis(values=[0, 25, 50, 75, 100])),
                    y=alt.Y(
                        "페르소나:N",
                        title=None,
                        sort=persona_sort,
                        axis=alt.Axis(labelPadding=14, labelLimit=150),
                    ),
                    tooltip=[alt.Tooltip("페르소나:N"), alt.Tooltip("성격:N"),
                             alt.Tooltip("참여 수:Q", format=","),
                             alt.Tooltip("승리 수:Q", format=","),
                             alt.Tooltip("승률 (%):Q", format=".1f")],
                ).properties(height=300)
                labels = alt.Chart(persona_data).mark_text(
                    align="left", baseline="middle", dx=6, color="#f8fafc", fontWeight="bold"
                ).encode(
                    x=alt.X("승률 (%):Q", scale=alt.Scale(domain=[0, 110])),
                    y=alt.Y(
                        "페르소나:N",
                        sort=persona_sort,
                        axis=alt.Axis(labelPadding=14, labelLimit=150),
                    ),
                    text=alt.Text("승률 (%):Q", format=".1f"),
                )
                persona_visual = (persona_chart + labels).properties(
                    height=300,
                    padding={"top": 24, "bottom": 24, "left": 8, "right": 8},
                ).configure(
                    background="#10131a",
                ).configure_view(
                    stroke=None,
                ).configure_axis(
                    labelColor="#dbe4f0",
                    titleColor="#dbe4f0",
                    gridColor="#384152",
                    domainColor="#697586",
                )
                st.altair_chart(persona_visual, width="stretch")

    daily = insights.get("daily", [])
    if daily:
        daily_rows = []
        for row in daily:
            try:
                created_games = int(row.get("생성 게임", 0) or 0)
            except (TypeError, ValueError):
                created_games = 0
            daily_rows.append({
                "날짜": str(row.get("날짜", "")),
                "생성 게임": created_games,
            })
        if daily_rows:
            peak_row = max(daily_rows, key=lambda item: item["생성 게임"])
            peak_count = peak_row["생성 게임"]
            for row in daily_rows:
                row["최다 생성일"] = row is peak_row
                # 날짜를 시간축으로 두면 0건 날짜가 공간을 차지하지 않아 마지막
                # 급증일만 화면 끝에 붙어 보인다. 화면용 표시는 범주형 축으로
                # 고정해 최근 30일의 날짜 간격을 항상 동일하게 유지한다.
                row["날짜 표시"] = row["날짜"][5:10].replace("-", "/")
            period_total = sum(row["생성 게임"] for row in daily_rows)
            period_average = period_total / len(daily_rows)
            peak_date = peak_row["날짜"][:10] or "-"
        else:
            peak_count = 0
            period_total = 0
            period_average = 0.0
            peak_date = "-"
        with st.container(border=True):
            st.markdown("#### 일별 게임 생성 · 가상 예시" if synthetic else "#### 일별 게임 생성")
            st.caption("최근 30일 생성 건수 · 모든 날짜를 같은 간격으로 표시하고 최다 생성일은 노란색으로 강조합니다.")
            with st.container(horizontal=True):
                st.metric("최근 30일 총 게임", f"{period_total:,}건", f"{period_total:,}건")
                st.metric("일평균 생성", f"{period_average:.1f}건", f"{period_average:.1f}건")
                st.metric("최다 생성일", peak_date, f"{peak_count:,}건")
            daily_data = alt.Data(values=daily_rows)
            daily_base = alt.Chart(daily_data)
            date_order = [row["날짜 표시"] for row in daily_rows]
            date_axis = alt.Axis(
                title="날짜",
                labelAngle=-45,
                labelOverlap=False,
                labelPadding=8,
                tickSize=4,
            )
            daily_bars = daily_base.mark_bar(size=22, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X(
                    "날짜 표시:N",
                    sort=date_order,
                    axis=date_axis,
                ),
                y=alt.Y("생성 게임:Q", title="게임 수", scale=alt.Scale(zero=True)),
                color=alt.Color(
                    "최다 생성일:N",
                    scale=alt.Scale(domain=[True, False], range=["#facc15", "#fbbf24"]),
                    legend=None,
                ),
                tooltip=[alt.Tooltip("날짜:N", title="날짜"),
                         alt.Tooltip("생성 게임:Q", title="생성 게임", format=",")],
            )
            peak_label = daily_base.transform_filter(
                alt.datum["최다 생성일"] == True
            ).mark_text(
                dy=-14, color="#f8fafc", fontWeight="bold"
            ).encode(
                x=alt.X("날짜 표시:N", sort=date_order),
                y="생성 게임:Q",
                text=alt.Text("생성 게임:Q", format=",")
            )
            daily_chart = (daily_bars + peak_label).properties(
                height=290,
                padding={"top": 24, "bottom": 34, "left": 24, "right": 18},
            ).configure(
                background="#10131a",
            ).configure_view(
                stroke=None,
            ).configure_axis(
                labelColor="#dbe4f0",
                titleColor="#dbe4f0",
                gridColor="#384152",
                domainColor="#697586",
            )
            st.altair_chart(daily_chart, width="stretch")


def _render_live_chart_status(refreshed_at: str | None, *, synthetic: bool) -> None:
    """그래프가 어느 시점의 데이터를 표시하는지와 갱신 방식을 눈에 보이게 한다."""

    mode_label = "가상 데이터" if synthetic else "실시간 API"
    refreshed_label = refreshed_at or "조회 시각 확인 중"
    with st.container(
        horizontal=True,
        wrap=False,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    ):
        st.markdown(
            '<div class="admin-live-chart-status">'
            '<span class="admin-live-chart-dot" aria-hidden="true"></span>'
            f'<strong>{mode_label}</strong>'
            f'<span>마지막 조회 {refreshed_label}</span>'
            '<span class="admin-live-chart-cycle">30초 자동 갱신</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("지금 새로고침", key="admin.dashboard.refresh", icon=":material/refresh:"):
            # 수동 갱신은 전체 인증 흐름을 다시 거쳐 최신 권한과 데이터를 함께 확인한다.
            st.rerun()


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
    """피드백과 감사 로그에 같은 한 줄 페이지 이동 컨트롤을 표시한다.

    이전·다음 버튼은 기존 세션 커서 구조를 그대로 사용해 필터 변경과 한 번의
    클릭으로 다음 페이지를 읽는 동작을 보존한다. 화면에서는 두 버튼과 현재
    페이지 정보를 하나의 가로 행으로 묶어 서로 다른 탭에서도 같은 위치와
    간격으로 보이게 한다.
    """

    stack = st.session_state[name + ".cursors"]
    with st.container(
        horizontal=True,
        wrap=False,
        horizontal_alignment="center",
        vertical_alignment="center",
        gap="small",
    ):
        st.button(
            "← 이전",
            key=name + ".previous",
            disabled=len(stack) == 1,
            on_click=lambda: st.session_state[name + ".cursors"].pop(),
        )
        st.caption(f"{len(stack)} 페이지 · {len(data['items'])}건 표시")
        st.button(
            "다음 →",
            key=name + ".next",
            disabled=data.get("next_cursor") is None,
            on_click=lambda: st.session_state[name + ".cursors"].append(data["next_cursor"]),
        )
