import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from frontend_user.components import action_panel
from frontend_user.core.api_client import ApiUnavailableError
from frontend_user.core.commands import build_command, normalize_message


def _snapshot(*, legal_actions=None, message_window=None):
    return {
        "game": {"state_version": 12},
        "me": {"player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269", "alive": True},
        "legal_actions": legal_actions or ["SPEAK", "PASS"],
        "action_window": message_window or {
            "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
            "paused": False,
            "has_submitted": False,
            "turn_player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
            "legal_actions": ["SPEAK", "PASS"],
            "remaining_ms": None,
            "valid_targets": [],
        },
    }


@pytest.mark.parametrize("length", [0, 201])
def test_message_length_is_rejected(length: int) -> None:
    with pytest.raises(ValueError):
        normalize_message("가" * length)


def test_message_200_chars_is_accepted_after_whitespace_normalization() -> None:
    assert len(normalize_message("가" * 200)) == 200


def test_speak_command_contains_contract_fields() -> None:
    command = build_command(snapshot=_snapshot(), command_type="SPEAK", message="  안녕   하세요 ")
    assert command == {
        "type": "SPEAK",
        "expected_state_version": 12,
        "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
        "message": "안녕 하세요",
    }


def test_target_uuid_is_forwarded_for_backend_validation() -> None:
    # Front snapshot의 valid_targets는 stale될 수 있으므로 Backend가 최종 검증한다.
    window = {
        "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
        "paused": False,
        "has_submitted": False,
        "legal_actions": ["SUBMIT_VOTE"],
        "remaining_ms": 30000,
        "valid_targets": [{"player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08", "display_name": "플레이어 2"}],
    }
    snapshot = _snapshot(legal_actions=["SUBMIT_VOTE"], message_window=window)
    command = build_command(snapshot=snapshot, command_type="SUBMIT_VOTE", target_player_id="e15f18b6-ea20-477e-9d99-8a22dc6048f5")
    assert command["target_player_id"] == "e15f18b6-ea20-477e-9d99-8a22dc6048f5"


def test_stale_window_is_forwarded_for_backend_validation() -> None:
    window = _snapshot()["action_window"] | {"remaining_ms": 0}
    command = build_command(snapshot=_snapshot(message_window=window), command_type="SPEAK", message="발언")
    assert command["type"] == "SPEAK"


@pytest.mark.parametrize("command_type", ["SAVE_AND_EXIT", "RESUME", "FAST_FORWARD"])
def test_lifecycle_commands_do_not_send_window_id(command_type: str) -> None:
    """window과 무관한 lifecycle command가 불필요한 필드를 보내지 않는지 확인한다."""

    snapshot = _snapshot(legal_actions=[command_type])
    command = build_command(snapshot=snapshot, command_type=command_type)
    assert command == {"type": command_type, "expected_state_version": 12}


GAME = "00000000-0000-4000-8000-000000000201"
HUMAN = "0fa54b68-a42a-4d52-81dd-8a59e54eb269"
TARGET = "70d5bd5d-61da-4db4-b218-6d0ac41f2a08"
DEAD = "00000000-0000-4000-8000-000000000204"
OUTSIDER = "00000000-0000-4000-8000-000000000205"


def _action_snapshot(phase="DAY_VOTE"):
    """실제 시각·DB 없이 후보와 서버 마감 계약을 검증하는 합성 snapshot을 만든다."""

    snapshot = _snapshot()
    snapshot["game"].update(game_id=GAME, status="IN_PROGRESS", phase=phase)
    snapshot["me"]["role"] = "DOCTOR"
    snapshot["players"] = [
        {"player_id": HUMAN, "display_name": "나", "alive": True},
        {"player_id": TARGET, "display_name": "후보", "alive": True},
        {"player_id": DEAD, "display_name": "탈락자", "alive": False},
    ]
    command = "SUBMIT_NIGHT_ACTION" if phase == "NIGHT_ACTION" else "SUBMIT_VOTE"
    snapshot["legal_actions"] = [command]
    snapshot["action_window"].update(
        kind={"NIGHT_ACTION": "NIGHT", "REVOTE": "REVOTE", "FINAL_ACCUSATION": "FINAL_VOTE"}.get(phase, "VOTE"),
        server_time="2026-09-07T00:00:00Z",
        deadline_at="2026-09-07T00:00:30Z",
        remaining_ms=30000,
        legal_actions=[command],
        valid_targets=[{"player_id": HUMAN, "display_name": "나"},
                       {"player_id": TARGET, "display_name": "후보"}],
    )
    return snapshot


@pytest.fixture
def panel_state(monkeypatch):
    """시계·command queue 단위 검증에서는 실제 Streamlit 세션을 사용하지 않는다."""

    state = {}
    monkeypatch.setattr(action_panel.st, "session_state", state)
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1000.0)
    return state


@pytest.mark.parametrize("phase", ["DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"])
def test_vote_targets_exclude_self_and_invalid_candidates(phase):
    snapshot = _action_snapshot(phase)
    snapshot["action_window"]["valid_targets"] += [
        {"player_id": HUMAN.upper()}, {"player_id": TARGET.upper()},
        {"player_id": DEAD}, {"player_id": OUTSIDER}, {"player_id": "bad"},
        {"player_id": []}, {}, None,
    ]
    assert action_panel._valid_targets(snapshot=snapshot, command_type="SUBMIT_VOTE") == [
        {"player_id": TARGET, "display_name": "후보"},
    ]


@pytest.mark.parametrize("targets", [[], None, {}, [{"player_id": OUTSIDER}]])
def test_server_candidates_are_not_replaced_with_all_living_players(targets):
    snapshot = _action_snapshot("REVOTE")
    snapshot["action_window"]["valid_targets"] = targets
    assert action_panel._valid_targets(snapshot=snapshot, command_type="SUBMIT_VOTE") == []


@pytest.mark.parametrize("field,value", [("alive", False), ("alive", "true"), ("game_id", OUTSIDER)])
def test_invalid_target_metadata_is_rejected(field, value):
    snapshot = _action_snapshot()
    snapshot["action_window"]["valid_targets"] = [{"player_id": TARGET, field: value}]
    assert action_panel._valid_targets(snapshot=snapshot, command_type="SUBMIT_VOTE") == []


@pytest.mark.parametrize("field,value", [("alive", False), ("alive", "true"), ("game_id", OUTSIDER)])
def test_invalid_public_player_metadata_is_rejected(field, value):
    snapshot = _action_snapshot()
    snapshot["players"][1][field] = value
    assert action_panel._valid_targets(snapshot=snapshot, command_type="SUBMIT_VOTE") == []


def test_night_preserves_server_allowed_self_protection_and_order():
    snapshot = _action_snapshot("NIGHT_ACTION")
    assert [target["player_id"] for target in action_panel._valid_targets(
        snapshot=snapshot, command_type="SUBMIT_NIGHT_ACTION"
    )] == [HUMAN, TARGET]


@pytest.mark.parametrize("target,game_id", [(HUMAN, GAME), (DEAD, GAME), (OUTSIDER, GAME),
                                           ("bad", GAME), (TARGET, OUTSIDER)])
def test_invalid_selection_is_rejected_before_creating_a_pending_command(panel_state, monkeypatch, target, game_id):
    error, rerun = Mock(), Mock()
    monkeypatch.setattr(action_panel.st, "error", error)
    monkeypatch.setattr(action_panel.st, "rerun", rerun)
    action_panel._queue_command(game_id=game_id, snapshot=_action_snapshot(),
                                command_type="SUBMIT_VOTE", target_player_id=target)
    error.assert_called_once()
    rerun.assert_not_called()
    assert "game.command_pending" not in panel_state


def test_removed_selection_is_cleared_without_selecting_a_replacement(panel_state):
    panel_state["target"] = DEAD
    action_panel._clear_invalid_selection(key="target", options=[TARGET])
    assert panel_state["target"] is None


def test_countdown_advances_without_reanchoring_the_same_snapshot(panel_state, monkeypatch):
    snapshot = _action_snapshot()
    original = deepcopy(snapshot)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 30000
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1012.25)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=deepcopy(snapshot)) == 17750
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1100.0)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 0
    assert snapshot == original


def test_countdown_uses_server_deadline_and_new_server_observations(panel_state, monkeypatch):
    snapshot = _action_snapshot()
    snapshot["action_window"]["remaining_ms"] = 999999
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 30000
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1002.0)
    snapshot["action_window"]["server_time"] = "2026-09-07T00:00:10Z"
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 20000
    snapshot["action_window"]["server_time"] = "2026-09-07T00:00:00Z"
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1003.0)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 19000


@pytest.mark.parametrize("saved", [True, False])
def test_saved_or_paused_countdown_is_frozen_until_new_resume_deadline(panel_state, monkeypatch, saved):
    snapshot = _action_snapshot()
    action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot)
    snapshot["game"]["status"] = "SAVED" if saved else "IN_PROGRESS"
    snapshot["action_window"].update(paused=not saved, deadline_at=None, remaining_ms=17500)
    monkeypatch.setattr(action_panel, "monotonic", lambda: 2000.0)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 17500
    assert not action_panel._timer_is_running(snapshot)
    assert action_panel._countdown_text(snapshot) == "00:18 · 일시 정지"
    snapshot["game"]["status"] = "IN_PROGRESS"
    snapshot["action_window"].update(paused=False, server_time="2026-09-07T01:00:00Z",
                                      deadline_at="2026-09-07T01:00:17.500Z")
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 17500
    monkeypatch.setattr(action_panel, "monotonic", lambda: 2001.0)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) == 16500


@pytest.mark.parametrize("server_time", [None, "bad", "2026-09-07T00:00:00", {}])
def test_invalid_server_clock_does_not_fall_back_to_local_wall_time(panel_state, server_time):
    snapshot = _action_snapshot()
    snapshot["action_window"]["server_time"] = server_time
    assert not action_panel._timer_is_running(snapshot)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) is None


def test_untimed_window_has_no_clock_and_is_not_expired(panel_state):
    snapshot = _action_snapshot("DAY_DISCUSSION")
    snapshot["action_window"].update(kind="SPEECH", deadline_at=None, remaining_ms=None)
    assert action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot) is None
    assert action_panel._countdown_text(snapshot) == "시간 제한 없음"
    assert not action_panel._is_locked(window=snapshot["action_window"], pending=None)
    snapshot["action_window"]["paused"] = True
    assert action_panel._countdown_text(snapshot) == "일시 정지 · 시간 제한 없음"


def _action_app(snapshot, client):
    import streamlit as st
    from unittest.mock import patch
    from frontend_user.components import action_panel

    current = st.session_state.setdefault("test.snapshot", snapshot)
    # AppTest는 v2 component registry를 초기화하지 않으므로 브라우저 focus bridge만
    # 대체한다. 행동 패널·countdown·live region은 실제 Python 렌더 경로를 사용한다.
    with patch.object(action_panel, "ACTION_ATTENTION_COMPONENT"):
        action_panel.render(client=client, game_id=current["game"]["game_id"], snapshot=current)


def test_countdown_ui_updates_warnings_and_locks_without_network_or_submission(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(action_panel, "monotonic", lambda: now[0])
    client = Mock()
    app = AppTest.from_function(_action_app, args=(_action_snapshot(), client)).run()
    assert not app.exception
    assert app.radio[0].options == ["🤖 후보"]
    app.radio[0].set_value(TARGET).run()
    assert not app.button(key="action.SUBMIT_VOTE").disabled
    for elapsed, remaining, warning in [(16, "00:14", "15초"), (26, "00:04", "5초"), (31, "00:00", None)]:
        now[0] = 1000.0 + elapsed
        app.run()
        assert not app.exception
        assert any(remaining in item.value for item in app.markdown)
        if warning:
            assert any(warning in item.value for item in app.warning)
    assert app.button(key="action.SUBMIT_VOTE").disabled
    assert app.radio[0].disabled
    assert app.session_state["test.snapshot"]["action_window"]["remaining_ms"] == 30000
    client.submit_command.assert_not_called()
    client.get_game.assert_not_called()


@pytest.mark.parametrize(
    ("phase", "remaining", "expected_label", "expected_warning"),
    [
        ("NIGHT_ACTION", 9_000, "보호 대상을 선택하세요", "밤 행동 마감까지 10초 이하 남았습니다."),
        ("DAY_VOTE", 14_000, "투표 대상을 선택하세요", "투표 마감까지 15초 이하 남았습니다."),
        ("REVOTE", 4_000, "투표 대상을 선택하세요", "투표 마감까지 5초 이하 남았습니다."),
        ("FINAL_ACCUSATION", 30_000, "최종 판정 대상을 지목하세요", None),
    ],
)
def test_current_action_status_exposes_action_and_threshold_without_auto_target(
    panel_state, phase, remaining, expected_label, expected_warning
):
    snapshot = _action_snapshot(phase)
    snapshot["action_window"]["remaining_ms"] = remaining
    status = action_panel._action_status(snapshot)
    assert status == (expected_label, action_panel._remaining_text(remaining), expected_warning)
    assert "game.command_pending" not in panel_state


def test_attention_payload_separates_visual_second_tick_from_live_announcement(panel_state):
    snapshot = _action_snapshot()
    snapshot["action_window"]["remaining_ms"] = 30_000
    payload = action_panel._attention_payload(snapshot)
    assert payload == {
        "active": True,
        "window_id": snapshot["action_window"]["window_id"],
        "announcement": "새 행동: 투표 대상을 선택하세요.",
    }
    snapshot["action_window"]["remaining_ms"] = 14_000
    assert action_panel._attention_payload(snapshot)["announcement"].endswith(
        "투표 마감까지 15초 이하 남았습니다."
    )
    html = (
        Path(__file__).parents[1]
        / "components/browser_components/action_attention/index.html"
    ).read_text(encoding="utf-8")
    assert 'role="status"' in html and 'aria-live="polite"' in html
    assert "00:30" not in html


def test_final_accusation_uses_decisive_copy_and_distinct_submit_label(monkeypatch):
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1000.0)
    snapshot = _action_snapshot("FINAL_ACCUSATION")
    app = AppTest.from_function(_action_app, args=(snapshot, Mock())).run()
    assert not app.exception
    assert "최종 판정할 플레이어를 지목해 주세요" in [item.value for item in app.subheader]
    assert any("시민을 선택하면 마피아가 승리" in item.value for item in app.warning)
    assert any("재투표하지 않으며" in item.value for item in app.caption)
    assert app.button(key="action.SUBMIT_VOTE").label == "최종 지목 제출  →"


def test_browser_attention_focuses_each_action_window_once():
    """실제 bridge JS가 countdown rerender마다 focus를 빼앗지 않는지 합성 DOM으로 확인한다."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("행동 focus bridge JS 검증에는 Node.js가 필요합니다.")
    source = (
        Path(__file__).parents[1]
        / "components/browser_components/action_attention/index.js"
    ).read_text(encoding="utf-8")
    script = r"""
import assert from 'node:assert/strict';
const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(SOURCE).toString('base64');
const {default: render} = await import(moduleUrl);
let scrolls = 0;
let focuses = 0;
let announcements = 0;
globalThis.requestAnimationFrame = callback => callback();
globalThis.setTimeout = callback => callback();
globalThis.window = {matchMedia: () => ({matches: true})};
const input = {focus: options => {
  assert.deepEqual(options, {preventScroll: true});
  focuses += 1;
}};
let liveText = '';
const liveRegion = {};
Object.defineProperty(liveRegion, 'textContent', {
  get: () => liveText,
  set: value => { liveText = value; announcements += 1; },
});
const region = {
  scrollIntoView: options => {
    assert.deepEqual(options, {block: 'start', behavior: 'auto'});
    scrolls += 1;
  },
  querySelector: () => input,
  setAttribute: () => { throw Error('input이 있으므로 region 자체를 focus하면 안 됩니다.'); },
};
const parentElement = {
  ownerDocument: {querySelector: () => region},
  querySelector: () => liveRegion,
};
const firstWindow = '00000000-0000-4000-8000-000000000001';
const secondWindow = '00000000-0000-4000-8000-000000000002';
render({data: {active: true, window_id: firstWindow, announcement: '새 행동'}, parentElement});
render({data: {active: true, window_id: firstWindow, announcement: '새 행동'}, parentElement});
assert.equal(scrolls, 1);
assert.equal(focuses, 1);
assert.equal(announcements, 1);
render({data: {active: true, window_id: firstWindow, announcement: '15초 경고'}, parentElement});
assert.equal(announcements, 2);
assert.equal(liveText, '15초 경고');
render({data: {active: true, window_id: secondWindow, announcement: '15초 경고'}, parentElement});
assert.equal(scrolls, 2);
assert.equal(focuses, 2);
render({data: {active: false, window_id: secondWindow, announcement: '마감'}, parentElement});
assert.equal(scrolls, 2);
assert.equal(announcements, 3);
""".replace("SOURCE", json.dumps(source))
    # 실행 파일은 PATH에서 찾은 고정 Node.js이고, shell을 거치지 않는다.
    completed = subprocess.run(  # noqa: S603
        [node, "--input-type=module", "--eval", script],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_action_retry_preserves_exact_body_and_idempotency_key(monkeypatch):
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1000.0)
    snapshot = _action_snapshot()
    client = Mock()
    client.submit_command.side_effect = [
        ApiUnavailableError(status_code=503, code="DEPENDENCY_UNAVAILABLE", request_id="synthetic"),
        {"data": {"command_type": "SUBMIT_VOTE"}},
    ]
    client.get_game.return_value = {"data": snapshot}
    app = AppTest.from_function(_action_app, args=(snapshot, client)).run()
    app.radio[0].set_value(TARGET).run()
    app.button(key="action.SUBMIT_VOTE").click().run()
    assert not app.exception
    assert app.session_state["game.command_pending"]["status"] == "RETRYABLE_UNKNOWN"
    assert client.submit_command.call_count == 1
    original = client.submit_command.call_args
    app.run()
    assert client.submit_command.call_count == 1
    app.button(key="action.retry_pending").click().run()
    assert not app.exception
    assert client.submit_command.call_count == 2
    assert client.submit_command.call_args == original
    assert app.session_state["game.command_pending"]["status"] == "SUCCEEDED"
    client.get_game.assert_called_once_with(GAME)


@pytest.mark.parametrize("mode,interval", [("active", 1), ("paused", None), ("saved", None),
                                          ("untimed", None), ("expired", None)])
def test_fragment_schedules_only_the_active_clock_and_never_reprocesses_pending(panel_state, monkeypatch, mode, interval):
    snapshot = _action_snapshot()
    if mode == "paused":
        snapshot["action_window"]["paused"] = True
    elif mode == "saved":
        snapshot["game"]["status"] = "SAVED"
    elif mode == "untimed":
        snapshot["action_window"].update(deadline_at=None, remaining_ms=None)
    elif mode == "expired":
        snapshot["action_window"]["remaining_ms"] = 0
    pending, panel = Mock(), Mock()
    fragment = Mock(side_effect=lambda *, run_every: lambda function: function)
    monkeypatch.setattr(action_panel.st, "fragment", fragment)
    monkeypatch.setattr(action_panel.st, "markdown", Mock())
    monkeypatch.setattr(action_panel, "_process_pending", pending)
    monkeypatch.setattr(action_panel, "_render_vote_action", panel)
    client = Mock()
    action_panel.render(client=client, game_id=GAME, snapshot=snapshot)
    fragment.assert_called_once_with(run_every=interval)
    pending.assert_called_once()
    if mode == "active":
        monkeypatch.setattr(action_panel, "monotonic", lambda: 1001.0)
        action_panel._render_actions(game_id=GAME, snapshot=snapshot)
        assert panel.call_args.kwargs["snapshot"]["action_window"]["remaining_ms"] == 29000
        assert snapshot["action_window"]["remaining_ms"] == 30000
        pending.assert_called_once()
    assert client.mock_calls == []


@pytest.mark.parametrize("change", ["game", "window"])
def test_new_game_or_window_does_not_reuse_previous_clock(panel_state, monkeypatch, change):
    snapshot = _action_snapshot()
    action_panel._countdown_remaining_ms(game_id=GAME, snapshot=snapshot)
    monkeypatch.setattr(action_panel, "monotonic", lambda: 1010.0)
    if change == "window":
        snapshot["action_window"]["window_id"] = OUTSIDER
    game_id = OUTSIDER if change == "game" else GAME
    assert action_panel._countdown_remaining_ms(game_id=game_id, snapshot=snapshot) == 30000
