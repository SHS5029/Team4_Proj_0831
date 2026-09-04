"""fetch 기반 SSE bridge와 Python polling fallback 연결부."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import streamlit as st

from frontend_user.core.sync import SyncEnvelopeError, apply_envelope

ASSET_DIR = Path(__file__).with_name("browser_components") / "sync"
SYNC_COMPONENT = st.components.v2.component(
    name="ai_mafia_sync", html=(ASSET_DIR / "index.html").read_text(encoding="utf-8"),
    js=(ASSET_DIR / "index.js").read_text(encoding="utf-8"),
)


def mount_sse(*, backend_url: str, game_id: str, user_id: UUID, last_sequence: int) -> dict[str, Any] | None:
    """SSE component에서 완전한 game_sync envelope만 받는다."""

    # 팀 전달 사항: /events는 native EventSource가 아니라 fetch streaming으로 연결한다.
    # Backend CORS/proxy는 X-User-Id, X-Request-Id, Last-Event-ID를 허용해야 하며,
    # game_id·UUID를 query parameter에 넣어서는 안 된다.

    try:
        result = SYNC_COMPONENT(
            data={"backend_url": backend_url, "game_id": game_id, "user_id": str(user_id), "last_sequence": last_sequence},
            default={"envelope": None}, on_envelope_change=lambda: None,
            key=f"sync-{game_id}",
        )
        envelope = getattr(result, "envelope", None)
        return envelope if isinstance(envelope, dict) else None
    except Exception:
        return None


def apply_sync(*, snapshot: dict[str, Any], envelope: dict[str, Any] | None) -> dict[str, Any]:
    """잘못된 batch는 버리고 caller가 authoritative GET을 수행하도록 예외를 고정한다."""

    # 팀 전달 사항: envelope 검증 실패 시 Backend GET snapshot으로 복구한다. Front는
    # 실패한 batch를 추정해 이어 붙이거나 deadline·phase를 자체 계산하지 않는다.

    if envelope is None:
        return snapshot
    updated, _ = apply_envelope(snapshot=snapshot, envelope=envelope)
    if updated is None:
        raise SyncEnvelopeError("SYNC_EMPTY")
    return updated
