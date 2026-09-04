"""Streamlit session state의 UUID와 사용자 scope 초기화 규칙."""

from __future__ import annotations

from uuid import UUID

USER_ID_SESSION_KEY = "identity.user_id"
IDENTITY_PERSISTENCE_SESSION_KEY = "identity.persistence"
IDENTITY_WARNING_SESSION_KEY = "identity.storage_warning"


def set_identity(*, user_id: UUID, persistence: str, session_state: dict[str, object]) -> None:
    """검증된 UUID만 session mirror에 저장한다."""

    session_state[USER_ID_SESSION_KEY] = str(user_id)
    session_state[IDENTITY_PERSISTENCE_SESSION_KEY] = persistence
    session_state[IDENTITY_WARNING_SESSION_KEY] = persistence == "SESSION_ONLY"


def get_identity(session_state: dict[str, object]) -> UUID | None:
    """session mirror가 손상되었으면 사용하지 않고 None을 반환한다."""

    value = session_state.get(USER_ID_SESSION_KEY)
    try:
        return UUID(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def reset_identity_scope(session_state: dict[str, object]) -> None:
    """UUID 교체 시 이전 게임·private·cursor·form 상태를 제거한다."""

    for key in list(session_state):
        if str(key).startswith(("game.", "navigation.", "form.", "feedback.")):
            session_state.pop(key, None)
    session_state.pop(USER_ID_SESSION_KEY, None)
    session_state.pop(IDENTITY_PERSISTENCE_SESSION_KEY, None)
    session_state.pop(IDENTITY_WARNING_SESSION_KEY, None)
