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
from frontend_admin.app_pages.game_detail_page import render as render_detail
from frontend_admin.app_pages.game_list_page import render as render_list
from frontend_admin.components.identity_bridge import (
    ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY,
    load_identity,
)
from frontend_admin.core.api_client import (
    AdminApiClient,
    AdminApiError,
    DemoAdminApiClient,
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
        client = DemoAdminApiClient()
        metrics = client.metrics().get("data")
        if not isinstance(metrics, dict):
            st.error("가상 관리자 데이터를 읽을 수 없습니다.")
            return
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = True
        render_dashboard(metrics, lambda: _render_games(client))
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
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = True
    except (AdminApiError, ValueError):
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        st.error("관리자 접근 권한을 확인할 수 없습니다.")
        st.caption("권한이 없거나 관리자 Backend에 연결할 수 없습니다.")
        return
    render_dashboard(metrics, lambda: _render_games(client))


def _render_games(client: AdminApiClient) -> None:
    """목록과 상세를 조회하되 private field 검증 실패 시 상세를 렌더링하지 않는다."""

    try:
        response = client.games()
        data = response.get("data")
        items = data.get("items", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise ValueError("INVALID_RESPONSE")
        items = reject_private_fields(items)
        selected = render_list(items)
        if selected:
            detail_response = client.game_detail(selected)
            detail = detail_response.get("data")
            if not isinstance(detail, dict):
                raise ValueError("INVALID_RESPONSE")
            render_detail(reject_private_fields(detail))
    except (AdminApiError, ValueError):
        st.error("관리자 게임 정보를 불러오지 못했습니다.")


if __name__ == "__main__":
    main()
