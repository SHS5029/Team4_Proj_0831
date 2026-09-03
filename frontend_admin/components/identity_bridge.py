"""관리자 origin의 UUID local storage bridge."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import streamlit as st

from frontend_admin.core.auth import ADMIN_STORAGE_KEY

ASSET_DIR = Path(__file__).with_name("browser_components") / "identity"
ADMIN_IDENTITY_COMPONENT = st.components.v2.component(
    name="ai_mafia_admin_identity",
    html=(ASSET_DIR / "index.html").read_text(encoding="utf-8"),
    js=(ASSET_DIR / "index.js").read_text(encoding="utf-8"),
)
ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY = "admin.identity.bridge_changed"


def _mark_identity_changed() -> None:
    """브라우저 bridge의 실제 UUID가 준비되었음을 다음 관리자 앱 rerun에 전달한다."""

    st.session_state[ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY] = True


def load_identity() -> UUID | None:
    """관리자 UUID만 반환하며 저장 실패 시 접근을 허용하지 않는다."""

    result = ADMIN_IDENTITY_COMPONENT(
        data={"storage_key": ADMIN_STORAGE_KEY},
        default={"user_id": None},
        on_user_id_change=_mark_identity_changed,
        key="admin-identity-bridge",
    )
    value = getattr(result, "user_id", None)
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.version == 4 else None
