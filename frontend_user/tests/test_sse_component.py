"""Streamlit Python을 점유하지 않는 browser SSE component 계약을 검증한다."""

from pathlib import Path

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from frontend_user.components import sync_bridge


def test_sse_component_uses_browser_fetch_and_abortable_lifecycle() -> None:
    """SSE 수신이 JS fetch와 AbortController 안에서 수행되는지 확인한다."""

    source = (
        Path(__file__).parents[1] / "components" / "browser_components" / "sync" / "index.js"
    ).read_text(encoding="utf-8")
    assert "fetch(url" in source
    assert "new AbortController()" in source
    assert 'setStateValue("status"' not in source
    assert '"Last-Event-ID": String(lastSequence)' in source
    assert "await wait(1000)" in source
    assert "hasOperations" in source
    assert "hasCursorAdvance" in source
    assert "controller.abort()" in source


@pytest.mark.parametrize("outcome", ["unchanged", "changed", "sync_error", "get_error", "gap", "saved", "other_game"])
def test_polling_refreshes_only_after_authoritative_change(monkeypatch, outcome) -> None:
    """SSE 없이도 변경을 복구하며 실패·무변경에는 입력 상태와 cursor를 보존한다."""

    snapshot = {"game": {"game_id": "game-test", "status": "IN_PROGRESS", "state_version": 1, "last_sequence": 0}}
    refreshed = deepcopy(snapshot)
    refreshed["game"].update(state_version=2, last_sequence=1)
    client = Mock()
    client.get_sync.return_value = {"game_id": "game-test", "mode": "SNAPSHOT", "snapshot": refreshed}
    client.get_game.return_value = {"data": refreshed}
    if outcome == "unchanged":
        client.get_sync.return_value = {"game_id": "game-test", "mode": "DELTA", "operations": [], "state_version": 1, "last_sequence": 0}
    elif outcome == "sync_error":
        client.get_sync.side_effect = RuntimeError("synthetic failure")
    elif outcome == "get_error":
        client.get_game.side_effect = RuntimeError("synthetic failure")
    elif outcome == "gap":
        client.get_sync.return_value = {"mode": "INVALID"}
    elif outcome == "saved":
        snapshot["game"]["status"] = "SAVED"
    state = {"game.latest_snapshot": snapshot, "game.client": client, "form.message": "작성 중"}
    ui = SimpleNamespace(session_state=state, rerun=Mock(), warning=Mock())
    monkeypatch.setattr(sync_bridge, "st", ui)
    game_id = "other-game" if outcome == "other_game" else "game-test"
    sync_bridge.poll_game_progress.__wrapped__(game_id=game_id)
    assert state["form.message"] == "작성 중"
    if outcome in {"changed", "gap"}:
        assert state["game.latest_snapshot"] == refreshed
        ui.rerun.assert_called_once()
    else:
        assert state["game.latest_snapshot"] is snapshot
        ui.rerun.assert_not_called()
    if outcome in {"sync_error", "get_error"}:
        ui.warning.assert_called_once()
        # 오류가 사라지면 사용자 클릭 없이 다음 타이머 호출에서 복구한다.
        client.get_sync.side_effect = None
        client.get_game.side_effect = None
        sync_bridge.poll_game_progress.__wrapped__(game_id=game_id)
        ui.rerun.assert_called_once()
    if outcome in {"saved", "other_game"}:
        client.get_sync.assert_not_called()


def test_other_speaker_is_not_reported_as_my_submission(monkeypatch) -> None:
    """다른 차례의 has_submitted=true를 내 발언 제출 완료로 표시하지 않는다."""

    from contextlib import nullcontext
    from frontend_user.components import action_panel

    ui = SimpleNamespace(container=lambda **kwargs: nullcontext(), info=Mock())
    monkeypatch.setattr(action_panel, "st", ui)
    monkeypatch.setattr(action_panel, "_pending_for_window", lambda **kwargs: None)
    monkeypatch.setattr(action_panel, "_render_turn_status", lambda **kwargs: None)
    monkeypatch.setattr(action_panel, "_render_pending_feedback", lambda **kwargs: None)
    monkeypatch.setattr(action_panel, "_current_speaker", lambda **kwargs: "플레이어 2")
    action_panel._render_discussion(game_id="game-test", snapshot={
        "me": {"player_id": "human"}, "legal_actions": [],
        "action_window": {"turn_player_id": "ai", "has_submitted": True},
    })
    ui.info.assert_called_once_with("현재 플레이어 2님의 발언 차례입니다.")
