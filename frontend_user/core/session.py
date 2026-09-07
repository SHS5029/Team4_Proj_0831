"""Streamlit session state의 UUID와 사용자 scope 초기화 규칙."""

from __future__ import annotations

from uuid import UUID, uuid4

from frontend_user.core.identity import parse_uuid_v4

USER_ID_SESSION_KEY = "identity.user_id"
IDENTITY_PERSISTENCE_SESSION_KEY = "identity.persistence"
IDENTITY_WARNING_SESSION_KEY = "identity.storage_warning"
IDENTITY_SCOPE_SESSION_KEY = "identity.scope_version"
IDENTITY_WRITE_SESSION_KEY = "identity.write_request"


def set_identity(*, user_id: UUID, persistence: str, session_state: dict[str, object]) -> None:
    """검증된 UUID를 저장하고 실제 교체 때만 이전 사용자 화면 상태를 제거한다."""

    if parse_uuid_v4(user_id) is None or persistence not in {"LOCAL", "SESSION_ONLY"}:
        raise ValueError("유효한 UUID v4와 저장 상태가 필요합니다.")
    if session_state.get(USER_ID_SESSION_KEY) != str(user_id):
        reset_identity_scope(session_state)
    session_state[USER_ID_SESSION_KEY] = str(user_id)
    session_state[IDENTITY_PERSISTENCE_SESSION_KEY] = persistence
    session_state[IDENTITY_WARNING_SESSION_KEY] = persistence == "SESSION_ONLY"


def get_identity(session_state: dict[str, object]) -> UUID | None:
    """session mirror가 손상되었으면 사용하지 않고 None을 반환한다."""

    return parse_uuid_v4(session_state.get(USER_ID_SESSION_KEY))


def request_identity_write(
    *, user_id: UUID | None, session_state: dict[str, object]
) -> None:
    """교체 의도만 기록하고 브라우저 저장 응답 전에는 현재 사용자 scope를 유지한다."""

    if user_id is not None and parse_uuid_v4(user_id) is None:
        raise ValueError("UUID v4 형식만 사용할 수 있습니다.")
    # 동일 UUID를 연속 복구해도 이전 요청의 늦은 응답과 구분할 수 있어야 한다.
    session_state[IDENTITY_SCOPE_SESSION_KEY] = str(uuid4())
    session_state[IDENTITY_WRITE_SESSION_KEY] = {
        "user_id": str(user_id) if user_id is not None else None,
    }


def reset_identity_scope(session_state: dict[str, object]) -> None:
    """UUID 교체 시 이전 게임·private·cursor·form 상태를 제거한다."""

    for key in list(session_state):
        if str(key).startswith(("game.", "navigation.", "form.", "feedback.", "home.")):
            session_state.pop(key, None)
    session_state.pop(USER_ID_SESSION_KEY, None)
    session_state.pop(IDENTITY_PERSISTENCE_SESSION_KEY, None)
    session_state.pop(IDENTITY_WARNING_SESSION_KEY, None)
