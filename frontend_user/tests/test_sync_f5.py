import pytest

from copy import deepcopy

from frontend_user.core.sync import SyncEnvelopeError, apply_envelope


GAME_ID = "d9ae9b5d-1d17-4f80-8f1a-276bfe170412"


def _snapshot():
    return {"game": {"game_id": GAME_ID, "state_version": 12, "last_sequence": 42}, "players": [], "public_events": []}


def _envelope(operations):
    return {"data": {"game_id": GAME_ID, "mode": "DELTA", "from_state_version": 12, "state_version": 13, "last_sequence": 43, "operations": operations}}


def _operation(**changes):
    return {"schema_version": 1, "state_version": 13, "type": "APPEND_PUBLIC_EVENT",
            "front_sequence": 43, "operation_index": 0,
            "payload": {"event_id": "e", "event_type": "GAME_BEGAN", "message": "시작"}, **changes}


def test_delta_applies_complete_operation_batch_once() -> None:
    # 팀 전달 사항: Backend contract test도 한 visible transaction의 operation을
    # 동일 front_sequence와 0부터 연속인 operation_index로 반환해야 한다.
    envelope = _envelope([_operation()])
    updated, mode = apply_envelope(snapshot=_snapshot(), envelope=envelope)
    assert mode == "DELTA"
    assert updated["game"]["last_sequence"] == 43
    assert len(updated["public_events"]) == 1
    replayed, _ = apply_envelope(snapshot=updated, envelope=envelope)
    assert replayed == updated


def test_unknown_operation_and_sequence_gap_are_rejected_atomically() -> None:
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=_envelope([_operation(type="UNKNOWN")]))
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=_envelope([_operation(front_sequence=45)]))


def test_snapshot_mode_replaces_authoritative_state() -> None:
    replacement = {"game": {"game_id": GAME_ID, "state_version": 20, "last_sequence": 50}}
    updated, mode = apply_envelope(snapshot=_snapshot(), envelope={"data": {"game_id": GAME_ID, "mode": "SNAPSHOT", "snapshot": replacement}})
    assert mode == "SNAPSHOT"
    assert updated == replacement


def test_delayed_snapshot_cannot_reverse_latest_cursor():
    """오래된 SSE snapshot은 현재 상태를 덮기 전에 최신 GET으로 다시 확인한다."""

    replacement = {"game": {"game_id": GAME_ID, "state_version": 11, "last_sequence": 41}}
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope={"game_id": GAME_ID, "mode": "SNAPSHOT", "snapshot": replacement})


def test_nested_sequence_batches_apply_phase_transition_atomically() -> None:
    """Backend의 sequence별 중첩 operation이 최신 phase까지 반영되는지 확인한다."""

    envelope = {
        "data": {
            "game_id": GAME_ID,
            "mode": "DELTA",
            "from_state_version": 12,
            "state_version": 14,
            "last_sequence": 44,
            "operations": [{
                "schema_version": 1,
                "front_sequence": 43,
                "state_version": 13,
                "operations": [{
                    "operation_index": 0,
                    "type": "SET_GAME_STATE",
                    "payload": {
                        "phase": "NIGHT_ACTION",
                        "state_version": 13,
                    },
                }],
            }, {
                "schema_version": 1,
                "front_sequence": 44,
                "state_version": 14,
                "operations": [{
                    "operation_index": 0,
                    "type": "SET_ACTION_WINDOW",
                    "payload": {"kind": "NIGHT", "valid_targets": []},
                }],
            }],
        },
    }
    updated, mode = apply_envelope(snapshot=_snapshot(), envelope=envelope)

    assert mode == "DELTA"
    assert updated["game"]["phase"] == "NIGHT_ACTION"
    assert updated["game"]["last_sequence"] == 44
    assert updated["action_window"]["kind"] == "NIGHT"


@pytest.mark.parametrize("changes", [
    {"schema_version": 2}, {"schema_version": None}, {"schema_version": True},
    {"front_sequence": True}, {"operation_index": True}, {"operation_index": 1},
    {"state_version": 12}, {"payload": []}, {"type": []},
])
def test_invalid_operation_never_partially_changes_snapshot(changes):
    """schema·cursor·payload 오류는 현재 화면을 변경하지 않고 GET 복구로 보낸다."""

    snapshot = _snapshot()
    original = deepcopy(snapshot)
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=snapshot, envelope=_envelope([_operation(**changes)]))
    assert snapshot == original


def test_missing_schema_and_nested_index_are_not_invented():
    """구형 응답에 schema나 index를 합성하면 손상 batch를 정상으로 오인할 수 있다."""

    operation = _operation()
    operation.pop("schema_version")
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=_envelope([operation]))
    operation.pop("operation_index")
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=_envelope([{
            "schema_version": 1, "front_sequence": 43, "state_version": 13,
            "operations": [operation],
        }]))


def test_backend_nested_operations_use_explicit_inner_schema():
    operation = _operation()
    operation.pop("front_sequence")
    operation.pop("state_version")
    envelope = _envelope([{"front_sequence": 43, "state_version": 13, "operations": [operation]}])
    updated, _ = apply_envelope(snapshot=_snapshot(), envelope=envelope)
    assert len(updated["public_events"]) == 1
    operation["front_sequence"] = 44
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=envelope)


@pytest.mark.parametrize("changes", [
    {"last_sequence": 44}, {"last_sequence": True}, {"state_version": 14},
    {"from_state_version": 13},
])
def test_envelope_cursor_must_match_complete_batch(changes):
    envelope = _envelope([_operation()])
    envelope["data"].update(changes)
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=envelope)


def test_replayed_batch_before_new_batch_is_skipped():
    first, _ = apply_envelope(snapshot=_snapshot(), envelope=_envelope([_operation()]))
    second = _envelope([_operation(), _operation(front_sequence=44, state_version=14)])
    second["data"].update(last_sequence=44, state_version=14)
    updated, _ = apply_envelope(snapshot=first, envelope=second)
    assert len(updated["public_events"]) == 2
    replayed, _ = apply_envelope(snapshot=updated, envelope=_envelope([_operation()]))
    assert replayed == updated


def test_duplicate_operation_in_current_batch_is_applied_once():
    updated, _ = apply_envelope(snapshot=_snapshot(), envelope=_envelope([_operation(), _operation()]))
    assert len(updated["public_events"]) == 1


def test_unknown_after_valid_operation_is_atomic_and_snapshot_game_is_checked():
    snapshot = _snapshot()
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=snapshot, envelope=_envelope([
            _operation(), _operation(operation_index=1, type="UNKNOWN"),
        ]))
    assert snapshot == _snapshot()
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=snapshot, envelope={"game_id": GAME_ID, "mode": "SNAPSHOT",
                       "snapshot": {"game": {"game_id": "another-game", "state_version": 20, "last_sequence": 50}}})


def test_noop_keeps_cursor_and_rejects_advanced_empty_delta():
    envelope = _envelope([])
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=envelope)
    envelope["data"].update(state_version=12, last_sequence=42)
    updated, _ = apply_envelope(snapshot=_snapshot(), envelope=envelope)
    assert updated == _snapshot()


def test_bridge_scope_tick_and_envelope_delivery(monkeypatch):
    """동일 widget 상태 재수신은 중복 적용하지 않고 이전 UUID scope 응답은 폐기한다."""

    from types import SimpleNamespace
    from uuid import UUID
    from frontend_user.components import sync_bridge

    session = {}
    returned = SimpleNamespace(envelope=None, status_tick=None)
    calls = []
    monkeypatch.setattr(sync_bridge.st, "session_state", session)
    monkeypatch.setattr(sync_bridge, "SYNC_COMPONENT", lambda **kwargs: calls.append(kwargs) or returned)
    args = {"backend_url": "http://127.0.0.1:8000", "game_id": GAME_ID,
            "user_id": UUID("00000000-0000-4000-8000-000000000101"),
            "last_sequence": 42, "after_state_version": 12}
    assert sync_bridge.mount_sse(**args) is None
    data = calls[-1]["data"]
    assert data["after_sequence"] == 42
    assert data["after_state_version"] == 12
    assert data["policy"]["foreground_poll_ms"] == 2000
    scope = {key: data[key] for key in ("schema_version", "component_instance_id", "scope_version")}
    returned.envelope = {**scope, "type": "SYNC_ENVELOPE", "event_id": "delivery-1", "envelope": _envelope([_operation()])}
    returned.status_tick = {**scope, "type": "SYNC_STATUS", "tick": 1000, "status": "POLLING", "hidden": False}
    assert sync_bridge.mount_sse(**args) == returned.envelope["envelope"]
    assert session["game.sync_tick"] == 1000
    assert session["game.sync_status"] == "POLLING"
    assert sync_bridge.mount_sse(**args) is None
    returned.status_tick = {**returned.status_tick, "tick": 900, "status": "STALE"}
    assert sync_bridge.mount_sse(**args) is None
    assert session["game.sync_status"] == "POLLING"
    returned.envelope = {**returned.envelope, "event_id": "delivery-2", "envelope": None}
    assert sync_bridge.mount_sse(**args) == {}
    args["user_id"] = UUID("00000000-0000-4000-8000-000000000102")
    assert sync_bridge.mount_sse(**args) is None
    assert session["game.sync_tick"] == 0
    assert calls[-1]["data"]["scope_version"] != scope["scope_version"]
    assert calls[-1]["key"] != calls[0]["key"]


def test_browser_sync_transport_lifecycle_with_mock_fetch():
    """실제 JS에 가상 시계·stream을 주입해 네트워크 없이 장애·복귀·cleanup을 검증한다."""

    import json
    import shutil
    import subprocess
    from dataclasses import asdict
    from pathlib import Path
    from frontend_user.core.sync_policy import DEFAULT_SYNC_POLICY

    node = shutil.which("node")
    if node is None:
        pytest.skip("브라우저 sync JS 검증에는 Node.js가 필요합니다.")
    source = (Path(__file__).parents[1] / "components/browser_components/sync/index.js").read_text()
    script = r"""
import assert from 'node:assert/strict';
const {default: render} = await import('data:text/javascript;base64,' + Buffer.from(SOURCE_TEXT).toString('base64'));
let now = 0, nextTimer = 1;
const timers = new Map();
globalThis.setTimeout = (fn, delay = 0) => { const id = nextTimer++; timers.set(id, {fn, at: now + delay}); return id; };
globalThis.clearTimeout = id => timers.delete(id);
Date.now = () => 100000 + now;
Math.random = () => 0.5;
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
async function advance(delay) {
  const until = now + delay;
  await flush();
  let steps = 0;
  while (true) {
    const next = [...timers.entries()].filter(([, timer]) => timer.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
    if (!next) break;
    assert.ok(++steps < 1000, '타이머가 무한 반복되면 안 된다');
    now = next[1].at;
    timers.delete(next[0]);
    next[1].fn();
    await flush();
  }
  now = until;
  await flush();
}
function eventTarget(extra = {}) {
  const listeners = new Map();
  return {...extra, listeners,
    addEventListener: (type, fn) => { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(fn); },
    removeEventListener: (type, fn) => listeners.get(type)?.delete(fn),
    fire(type) { for (const fn of [...(listeners.get(type) || [])]) fn(); },
  };
}
globalThis.document = eventTarget({visibilityState: 'visible'});
globalThis.window = eventTarget();
Object.defineProperty(globalThis, 'navigator', {value: {onLine: true}, configurable: true});
let sseHealthy = false, pollingHealthy = true, pendingPoll = false;
const requests = [], streams = [], outputs = [];
const noOp = (gameId, sequence, version) => ({game_id: gameId, mode: 'DELTA', from_state_version: version,
  state_version: version, last_sequence: sequence, operations: [], snapshot: null});
globalThis.fetch = async (url, options) => {
  const request = {url, options, at: now};
  requests.push(request);
  if (url.includes('/sync?')) {
    if (pendingPoll) return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(Error('중단'))));
    if (!pollingHealthy) throw Error('목 장애');
    const parsed = new URL(url);
    return {ok: true, json: async () => ({data: noOp(parsed.pathname.split('/')[4],
      Number(parsed.searchParams.get('after_sequence')), Number(parsed.searchParams.get('after_state_version')))})};
  }
  if (!sseHealthy) return {ok: false};
  const stream = {request};
  const body = new ReadableStream({
    start(controller) {
      stream.controller = controller;
      controller.enqueue(new TextEncoder().encode(': heartbeat\n\n'));
      options.signal.addEventListener('abort', () => { try { controller.error(Error('중단')); } catch (_) {} });
    },
    cancel() { stream.cancelled = true; },
  });
  streams.push(stream);
  return {ok: true, body};
};
const props = {backend_url: 'http://127.0.0.1:8000', game_id: 'game-one', user_id: 'user-one',
  component_instance_id: 'component-one', scope_version: 'scope-one', schema_version: 1,
  last_sequence: 42, after_sequence: 42, after_state_version: 12, policy: POLICY_VALUE};
const root = {};
let cleanup;
function run(data = props) {
  cleanup = render({data, parentElement: root, setStateValue: (key, value) => outputs.push({key, value, at: now})});
}
const polls = () => requests.filter(request => request.url.includes('/sync?'));
const sse = () => requests.filter(request => request.url.endsWith('/events'));
const ticks = () => outputs.filter(output => output.key === 'status_tick');
const envelopes = () => outputs.filter(output => output.key === 'envelope');
run();
await advance(5000);
assert.deepEqual(polls().map(request => request.at), [0, 2000, 4000]);
assert.deepEqual(sse().map(request => request.at), [0, 1000, 3000]);
assert.equal(envelopes().length, 0);
assert.equal(ticks().length, 2);
assert.equal(ticks().at(-1).value.status, 'POLLING');
assert.ok(requests.every(request => request.options.headers['X-User-Id'] === 'user-one'));
assert.ok(requests.every(request => !request.url.includes('user-one')));
assert.ok(requests.every(request => request.options.headers['X-Request-Id']));

// SSE가 복구되면 polling을 멈추고 no-op heartbeat에도 2초 상태 tick은 유지한다.
sseHealthy = true;
await advance(3000);
assert.equal(ticks().at(-1).value.status, 'LIVE');
const count = polls().length;
await advance(2000);
assert.equal(polls().length, count);
const liveRequest = streams.at(-1).request;
cleanup();
run();
await advance(0);
assert.equal(liveRequest.options.signal.aborted, false);
assert.equal(sse().length, 4);

// frame 조각·다중 data line은 완성 뒤 한 번만 전달하고 수신 cursor를 독자 전진시키지 않는다.
const event = {...noOp('game-one', 43, 13), from_state_version: 12,
  operations: [{schema_version: 1, state_version: 13, front_sequence: 43, operation_index: 0,
    type: 'CLEAR_ACTION_WINDOW', payload: {window_id: null}}]};
const frame = 'id: 43\r\nevent: game_sync\r\ndata: ' + JSON.stringify(event).replace(',"operations"', ',\r\ndata: "operations"') + '\r\n\r\n';
streams.at(-1).controller.enqueue(new TextEncoder().encode(frame.slice(0, 35)));
await flush();
assert.equal(envelopes().length, 0);
streams.at(-1).controller.enqueue(new TextEncoder().encode(frame.slice(35)));
await flush();
assert.equal(envelopes().length, 1);
const beforeDisconnect = polls().length;
streams.at(-1).controller.close();
await flush();
await advance(0);
assert.equal(polls().length, beforeDisconnect + 1);
await advance(1000);
assert.equal(sse().at(-1).options.headers['Last-Event-ID'], '42');
const accepted = {...props, last_sequence: 43, after_sequence: 43, after_state_version: 13};
cleanup();
run(accepted);
await advance(0);
window.fire('online');
await flush();
assert.match(polls().at(-1).url, /after_sequence=43/);

// background에서는 tick을 늦추고 foreground 복귀 순간 polling·상태 확인을 수행한다.
document.visibilityState = 'hidden';
document.fire('visibilitychange');
const hiddenCount = ticks().length;
await advance(9999);
assert.equal(ticks().length, hiddenCount);
await advance(1);
assert.equal(ticks().length, hiddenCount + 1);
const pollBeforeWake = polls().length;
document.visibilityState = 'visible';
document.fire('visibilitychange');
await flush();
assert.equal(polls().length, pollBeforeWake + 1);
assert.equal(ticks().at(-1).value.hidden, false);

// 서버가 잘못된 SSE id를 보내면 cursor를 넘기지 않고 Python snapshot 복구를 요청한다.
streams.at(-1).controller.enqueue(new TextEncoder().encode('id: 999\nevent: game_sync\ndata: ' + JSON.stringify(event) + '\n\n'));
await flush();
assert.deepEqual(envelopes().at(-1).value.envelope, {});
await advance(1000);
assert.equal(sse().at(-1).options.headers['Last-Event-ID'], '43');

// 새 게임·UUID scope로 교체하면 이전 stream과 모든 listener를 정리한다.
const previousRequest = streams.at(-1).request;
const nextProps = {...props, game_id: 'game-two', user_id: 'user-two', scope_version: 'scope-two'};
cleanup();
run(nextProps);
await advance(0);
assert.equal(previousRequest.options.signal.aborted, true);
assert.equal(streams.at(-1).request.options.headers['X-User-Id'], 'user-two');
assert.equal(document.listeners.get('visibilitychange').size, 1);
const activeRequest = streams.at(-1).request;
cleanup();
await advance(0);
assert.equal(activeRequest.options.signal.aborted, true);
assert.equal(document.listeners.get('visibilitychange').size, 0);
assert.equal(window.listeners.get('online').size, 0);
const outputCount = outputs.length, requestCount = requests.length;
await advance(60000);
assert.equal(outputs.length, outputCount);
assert.equal(requests.length, requestCount);
assert.equal(timers.size, 0);

// 연속 polling 장애는 2·4·8·16·30초로 늦추며 5회 실패 후 STALE이 된다.
sseHealthy = false;
pollingHealthy = false;
const failureStart = now;
run(nextProps);
await advance(32000);
const failedPolls = polls().filter(request => request.at >= failureStart).map(request => request.at - failureStart);
assert.deepEqual(failedPolls, [0, 2000, 6000, 14000, 30000]);
assert.equal(ticks().at(-1).value.status, 'STALE');
pollingHealthy = true;
window.fire('online');
await flush();
await advance(2000);
assert.equal(ticks().at(-1).value.status, 'POLLING');

// 종료 시 대기 중인 polling도 중단해 새 scope의 화면에 응답하지 못하게 한다.
pendingPoll = true;
window.fire('online');
await flush();
const pendingRequest = polls().at(-1);
cleanup();
await advance(0);
assert.equal(pendingRequest.options.signal.aborted, true);
assert.equal(timers.size, 0);
console.log('sync browser lifecycle passed');
""".replace("SOURCE_TEXT", json.dumps(source)).replace("POLICY_VALUE", json.dumps(asdict(DEFAULT_SYNC_POLICY)))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sync browser lifecycle passed" in result.stdout
