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
from frontend_admin.app_pages.game_detail_page import render as render_detail
from frontend_admin.app_pages.game_list_page import render as render_list
from frontend_admin.app_pages.game_list_page import render_filters
from frontend_admin.components.identity_bridge import load_identity
from frontend_admin.core.api_client import AdminApiClient, AdminApiError
from frontend_admin.core.auth import (
    ADMIN_ACCESS_SESSION_KEY,
    ADMIN_USER_ID_SESSION_KEY,
    parse_admin_uuid,
)
from frontend_admin.core.models import reject_private_fields


def main() -> None:
    """metrics 200 응답을 관리자 접근 증거로 사용하고 나머지는 dashboard를 숨긴다."""

    # 팀 전달 사항: Backend는 X-User-Id가 ADMIN_USER_IDS allowlist에 정확히 있을
    # 때만 200을 반환한다. 빈 allowlist·잘못된 UUID·403에서는 partial data도 주지 않는다.
    st.set_page_config(page_title="관리자", page_icon="🛠️", layout="wide")
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
        client = AdminApiClient(user_id=user_id)
        metrics_response = client.metrics()
        metrics = metrics_response.get("data")
        if not isinstance(metrics, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        metrics = reject_private_fields(metrics)
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = True
    except AdminApiError as error:
        if error.status_code == 403:
            st.error("관리자 접근이 거부되었습니다.")
            st.caption("Backend allowlist에 등록된 UUID인지 확인하고 위에서 식별자를 교체해 주세요.")
        else:
            st.error("관리자 Backend에 연결하거나 응답을 확인하지 못했습니다.")
        st.button("접근 다시 확인", key="admin.access.retry")
        return
    except ValueError:
        st.error("관리자 응답을 안전하게 표시할 수 없습니다.")
        st.button("접근 다시 확인", key="admin.access.retry")
        return
    render_dashboard(metrics)
    _render_games(client)


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


def _render_games(client: AdminApiClient) -> None:
    """지원 필터를 목록 API에 보내고 상세 선택은 game_id 주소로 복원한다."""

    status, phase = render_filters()
    try:
        response = client.games(status=status, phase=phase)
        data = response.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("INVALID_RESPONSE")
        items = reject_private_fields(items)
        selected = render_list(items)
        if selected:
            st.query_params["game_id"] = str(UUID(selected))
    except (AdminApiError, ValueError):
        st.error("관리자 게임 정보를 불러오지 못했습니다.")

    with st.form("admin.game.lookup"):
        game_input = st.text_input("상세 조회할 게임 ID", key="admin.game.input")
        if st.form_submit_button("게임 ID로 상세 열기"):
            try:
                st.query_params["game_id"] = str(UUID(game_input.strip()))
            except ValueError:
                st.error("게임 ID는 UUID 형식으로 입력해 주세요.")
    selected = st.query_params.get("game_id")
    if not selected:
        return
    if st.button("상세 닫기", key="admin.game.close"):
        st.query_params.pop("game_id", None)
        st.rerun()
    try:
        # URL은 공개 game_id만 포함하며 UUID 형식 검사 후 Backend 권한 검사를 거친다.
        game_id = UUID(selected)
        detail_response = client.game_detail(game_id)
        detail = detail_response.get("data")
        if not isinstance(detail, dict):
            raise ValueError("INVALID_RESPONSE")
        render_detail(reject_private_fields(detail))
    except (AdminApiError, ValueError):
        st.error("게임 상세를 불러오지 못했습니다. 게임 ID와 접근 권한을 확인해 주세요.")


if __name__ == "__main__":
    main()
