"""관리자 read-only dashboard의 UUID bootstrap과 fail-closed 진입점."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # Streamlit은 실행 스크립트 디렉터리만 import 경로에 넣을 수 있으므로,
    # 패키지 절대 import가 실행 위치와 무관하게 동작하도록 저장소 루트를 등록한다.
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend_admin.app_pages.dashboard_page import render as render_dashboard
from frontend_admin.components.identity_bridge import (
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
from frontend_admin.core.auth import ADMIN_ACCESS_SESSION_KEY, ADMIN_USER_ID_SESSION_KEY, parse_admin_uuid
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

    replacement = parse_admin_uuid(st.session_state.get("admin.identity.write"))
    # bridge를 매 rerun에 같은 key로 유지해야 브라우저 응답과 입력 widget이 사라지지 않는다.
    user_id, identity_error = load_identity(
        scope_version=str(st.session_state.get("admin.identity.scope", 1)),
        replacement=replacement,
    )
    if user_id is not None:
        st.session_state[ADMIN_USER_ID_SESSION_KEY] = str(user_id)
        if replacement is not None:
            st.session_state.pop("admin.identity.write", None)
            st.session_state.pop("admin.identity.input", None)
    st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
    _render_identity(user_id)
    if user_id is None:
        messages = {
            "MISSING_UUID": "Backend에 등록된 관리자 UUID를 입력해 주세요.",
            "INVALID_STORED_UUID": "저장된 식별자 형식이 올바르지 않습니다. 관리자 UUID를 다시 입력해 주세요.",
            "STORAGE_BLOCKED": "브라우저 저장소를 사용할 수 없습니다. 저장소 설정을 확인한 뒤 다시 시도해 주세요.",
        }
        if identity_error is None:
            st.info("브라우저의 관리자 식별자를 확인하고 있습니다.")
        else:
            st.warning(messages.get(identity_error, "관리자 식별자를 읽지 못했습니다. 다시 시도해 주세요."))
        if st.button("식별자 다시 확인", key="admin.identity.retry"):
            st.session_state["admin.identity.scope"] = st.session_state.get("admin.identity.scope", 1) + 1
            st.rerun()
        return
    try:
        client = AdminApiClient(user_id=st.session_state[ADMIN_USER_ID_SESSION_KEY])
        metrics_response = client.metrics()
        metrics = metrics_response.get("data")
        if not isinstance(metrics, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        metrics = reject_private_fields(metrics)
        insights, records = _dashboard_inputs(client, metrics)
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = True
    except AdminApiError as error:
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        if error.status_code == 403:
            st.error("관리자 접근이 거부되었습니다. Backend에 등록된 UUID를 입력해 주세요.")
        else:
            st.error("관리자 Backend 연결 또는 응답 오류입니다. BACKEND_API_URL과 서버 상태를 확인해 주세요.")
        st.button("접근 다시 확인", key="admin.access.retry")
        return
    except (ValueError, KeyError, TypeError):
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        st.error("관리자 응답을 안전하게 표시할 수 없습니다.")
        st.button("접근 다시 확인", key="admin.access.retry")
        return
    render_dashboard(metrics, insights=insights, records=records, client=client)


def _render_identity(user_id: UUID | None) -> None:
    """접근 거부 상태에서도 식별자를 확인·교체할 수 있게 입력 경로를 유지한다."""

    with st.expander("관리자 식별자", expanded=user_id is None):
        current = parse_admin_uuid(st.session_state.get(ADMIN_USER_ID_SESSION_KEY))
        if current is not None:
            st.caption("현재 브라우저의 관리자 UUID")
            st.code(str(current), language=None)
        st.caption("이 UUID는 비밀번호가 아닙니다. 관리자 화면은 loopback 또는 사설망에서만 사용합니다.")
        candidate = st.text_input("관리자 UUID v4", key="admin.identity.input")
        if st.button("입력값 확인", key="admin.identity.apply"):
            parsed = parse_admin_uuid(candidate)
            if parsed is None:
                st.error("UUID v4 형식의 식별자를 입력해 주세요.")
            else:
                st.session_state["admin.identity.pending"] = str(parsed)
    pending = parse_admin_uuid(st.session_state.get("admin.identity.pending"))
    if pending is not None:
        _confirm_identity(pending)


@st.dialog("관리자 UUID 적용 확인", dismissible=False)
def _confirm_identity(candidate: UUID) -> None:
    """명시적으로 확인한 UUID만 저장 요청으로 넘기며 이전 조회 선택을 비운다."""

    st.code(str(candidate), language=None)
    st.warning("이 식별자는 비밀번호가 아니며, 아는 사람은 같은 관리자 정보를 볼 수 있습니다.")
    st.caption("현재 식별자를 교체하고 Backend에서 권한을 다시 확인합니다. allowlist는 변경하지 않습니다.")
    if st.button("확인하고 적용", key="admin.identity.confirm"):
        st.session_state["admin.identity.write"] = str(candidate)
        st.session_state["admin.identity.scope"] = st.session_state.get("admin.identity.scope", 1) + 1
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        st.session_state.pop("admin.identity.pending", None)
        st.query_params.pop("game_id", None)
        st.rerun()
    if st.button("취소", key="admin.identity.cancel"):
        st.session_state.pop("admin.identity.pending", None)
        st.rerun()



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
