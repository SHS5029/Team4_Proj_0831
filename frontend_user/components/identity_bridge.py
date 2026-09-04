"""Streamlit과 브라우저 local storage 사이의 최소 UUID bridge."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import streamlit as st

from frontend_user.core.identity import STORAGE_KEY, new_user_id, parse_uuid_v4

ASSET_DIR = Path(__file__).with_name("browser_components") / "identity"
IDENTITY_HTML = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
IDENTITY_JS = (ASSET_DIR / "index.js").read_text(encoding="utf-8")
IDENTITY_COMPONENT = st.components.v2.component(
    name="ai_mafia_identity", html=IDENTITY_HTML, js=IDENTITY_JS
)
IDENTITY_COMPONENT_CHANGED_SESSION_KEY = "identity.bridge_changed"

# 팀 전달 사항: 이 component는 UUID 문자열과 LOCAL/SESSION_ONLY 상태만 반환한다.
# snapshot, 게임 목록, role, private event, API secret을 browser storage나 component
# state에 저장하지 않는다. 저장소가 차단되어도 화면을 중단하지 않고 session-only로
# 동작하되, 게임 복구가 보장되지 않는다는 경고를 사용자에게 표시한다.


def _mark_identity_changed() -> None:
    """브라우저 bridge가 실제 상태를 반환했음을 다음 Streamlit rerun에 전달한다."""

    st.session_state[IDENTITY_COMPONENT_CHANGED_SESSION_KEY] = True


def load_identity(*, scope_version: str = "1") -> tuple[UUID, str, str | None]:
    """bridge 결과를 읽고 실패 시 session-only identity로 안전하게 대체한다."""

    try:
        result = IDENTITY_COMPONENT(
            data={
                "schema_version": 1,
                "component_instance_id": "identity-main",
                "storage_key": STORAGE_KEY,
                "scope_version": scope_version,
            },
            default={"identity": None},
            on_identity_change=_mark_identity_changed,
            key="identity-bridge",
        )
        identity = getattr(result, "identity", None)
    except Exception:
        identity = None
    if not isinstance(identity, dict):
        return new_user_id(), "SESSION_ONLY", "STORAGE_BLOCKED"
    user_id = parse_uuid_v4(identity.get("user_id"))
    if user_id is None:
        return new_user_id(), "SESSION_ONLY", "INVALID_STORED_UUID"
    persistence = identity.get("persistence")
    if persistence not in {"LOCAL", "SESSION_ONLY"}:
        persistence = "SESSION_ONLY"
    return user_id, persistence, None
