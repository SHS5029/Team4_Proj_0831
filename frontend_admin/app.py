"""관리자 read-only dashboard의 UUID bootstrap과 fail-closed 진입점."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # Streamlit은 실행 스크립트 디렉터리만 import 경로에 넣을 수 있으므로,
    # 패키지 절대 import가 실행 위치와 무관하게 동작하도록 저장소 루트를 등록한다.
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend_admin.app_pages.dashboard_page import render as render_dashboard
from frontend_admin.components.identity_bridge import (
    ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY,
    load_identity,
)
from frontend_admin.core.api_client import (
    AdminApiClient,
    AdminApiError,
    DemoAdminApiClient,
    DEMO_API_KEY,
    AUDIT_EVENT_LABELS,
    is_demo_mode,
)
from frontend_admin.core.auth import ADMIN_ACCESS_SESSION_KEY, ADMIN_USER_ID_SESSION_KEY
from frontend_admin.core.models import reject_private_fields


def main() -> None:
    """실제 관리자 API 또는 명시된 로컬 가상 API로 화면을 시작한다."""

    # 팀 전달 사항: Backend는 X-User-Id가 ADMIN_USER_IDS allowlist에 정확히 있을
    # 때만 200을 반환한다. 빈 allowlist·잘못된 UUID·403에서는 partial data도 주지 않는다.
    st.set_page_config(page_title="관리자", page_icon="🛠️", layout="wide")
    if is_demo_mode():
        # 가상 모드는 외부 API 없이 화면을 확인하기 위한 명시적 개발 옵션이다.
        # 환경변수가 없으면 아래 실제 UUID allowlist 흐름만 실행된다.
        st.warning("개발용 가상 메타데이터 모드입니다. 실제 운영 데이터가 아닙니다.")
        with st.expander("데모 API 연결 설정"):
            st.caption("이 키는 공개 테스트 값입니다. 외부 API나 실제 관리자 인증에는 사용할 수 없습니다.")
            st.code(DEMO_API_KEY, language=None)
            with st.form("admin.demo.connection"):
                demo_key = st.text_input("데모 API 키", value=DEMO_API_KEY)
                connect = st.form_submit_button("연결 확인", type="primary")
            if connect:
                st.session_state["admin.demo.key"] = demo_key
        try:
            client = DemoAdminApiClient(api_key=st.session_state.get("admin.demo.key", DEMO_API_KEY))
        except AdminApiError:
            st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
            st.error("데모 키가 일치하지 않습니다. 연결 설정에서 위의 예시 키를 다시 입력해 주세요.")
            return
        metrics = client.metrics().get("data")
        if not isinstance(metrics, dict):
            st.error("가상 관리자 데이터를 읽을 수 없습니다.")
            return
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        try:
            insights, records = _dashboard_inputs(client, metrics)
        except (AdminApiError, ValueError, KeyError, TypeError):
            st.error("관리자 예시 데이터를 읽을 수 없습니다.")
            return
        render_dashboard(metrics, insights=insights, records=records, synthetic=True, client=client)
        return

    if (
        ADMIN_USER_ID_SESSION_KEY not in st.session_state
        or st.session_state.get(ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY) is True
    ):
        user_id = load_identity()
        st.session_state.pop(ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY, None)
        if user_id is None:
            st.error("관리자 식별자를 확인할 수 없어 접근을 차단했습니다.")
            return
        st.session_state[ADMIN_USER_ID_SESSION_KEY] = str(user_id)
    try:
        client = AdminApiClient(user_id=st.session_state[ADMIN_USER_ID_SESSION_KEY])
        metrics_response = client.metrics()
        metrics = metrics_response.get("data")
        if not isinstance(metrics, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        metrics = reject_private_fields(metrics)
        insights, records = _dashboard_inputs(client, metrics)
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = True
    except (AdminApiError, ValueError, KeyError, TypeError):
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        st.error("관리자 접근 권한을 확인할 수 없습니다.")
        st.caption("권한이 없거나 관리자 Backend에 연결할 수 없습니다.")
        return
    render_dashboard(metrics, insights=insights, records=records, client=client)


def _dashboard_inputs(client, metrics: dict) -> tuple[dict, dict]:
    """모든 탭의 API 응답을 렌더링 전에 읽어 권한 오류 시 부분 노출을 막는다."""

    def data(response):
        value = response.get("data")
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise ValueError("INVALID_RESPONSE")
        return reject_private_fields(value)

    personas = data(client.persona_win_rates())["items"]
    insights = {
        "personas": [{"페르소나": row["persona_name"],
                      "성격": row["personality_summary"],
                      "참여 수": row["participations"], "승리 수": row["wins"],
                      "승률 (%)": round(float(row["win_rate"]) * 100, 1)}
                     for row in personas],
        "daily": [{"날짜": row["date"], "생성 게임": row["games_created"]}
                  for row in metrics.get("daily_games", [])],
    }
    feedback_type = {"전체": None, "일반": "GENERAL", "게임": "GAME"}[
        st.session_state.get("admin.feedback.type", "전체")]
    rating_label = st.session_state.get("admin.feedback.rating", "전체")
    rating = None if rating_label == "전체" else int(rating_label)
    event_type = AUDIT_EVENT_LABELS[st.session_state.get("admin.logs.type", "전체")]

    def cursor(name, filters):
        # 식별자 또는 필터가 바뀌면 이전 조건에서 받은 커서를 재사용하지 않는다.
        signature = (str(getattr(client, "user_id", "demo")), *filters)
        if st.session_state.get(name + ".signature") != signature:
            st.session_state[name + ".signature"] = signature
            st.session_state[name + ".cursors"] = [None]
        return st.session_state[name + ".cursors"][-1]

    feedback_cursor = cursor("admin.feedback", (feedback_type, rating))
    logs_cursor = cursor("admin.logs", (event_type,))
    records = {
        "feedback": data(client.feedback(feedback_type=feedback_type, rating=rating,
                                         cursor=feedback_cursor)),
        "logs": data(client.audit_logs(event_type=event_type, cursor=logs_cursor)),
    }
    return insights, records

if __name__ == "__main__":
    main()
