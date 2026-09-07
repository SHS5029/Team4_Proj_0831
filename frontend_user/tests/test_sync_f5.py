import pytest

from frontend_user.core.sync import SyncEnvelopeError, apply_envelope


GAME_ID = "d9ae9b5d-1d17-4f80-8f1a-276bfe170412"


def _snapshot():
    return {"game": {"game_id": GAME_ID, "state_version": 12, "last_sequence": 42}, "players": [], "public_events": []}


def _envelope(operations):
    return {"data": {"game_id": GAME_ID, "mode": "DELTA", "state_version": 13, "last_sequence": 43, "operations": operations}}


def test_delta_applies_complete_operation_batch_once() -> None:
    # 팀 전달 사항: Backend contract test도 한 visible transaction의 operation을
    # 동일 front_sequence와 0부터 연속인 operation_index로 반환해야 한다.
    updated, mode = apply_envelope(snapshot=_snapshot(), envelope=_envelope([{
        "type": "APPEND_PUBLIC_EVENT", "front_sequence": 43, "operation_index": 0,
        "payload": {"event_id": "e", "event_type": "GAME_BEGAN", "message": "시작"},
    }]))
    assert mode == "DELTA"
    assert updated["game"]["last_sequence"] == 43
    assert len(updated["public_events"]) == 1


def test_unknown_operation_and_sequence_gap_are_rejected_atomically() -> None:
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=_envelope([{"type": "UNKNOWN", "front_sequence": 43, "operation_index": 0, "payload": {}}]))
    with pytest.raises(SyncEnvelopeError):
        apply_envelope(snapshot=_snapshot(), envelope=_envelope([{"type": "CLEAR_ACTION_WINDOW", "front_sequence": 45, "operation_index": 0, "payload": {}}]))


def test_snapshot_mode_replaces_authoritative_state() -> None:
    replacement = {"game": {"game_id": GAME_ID, "state_version": 20, "last_sequence": 50}}
    updated, mode = apply_envelope(snapshot=_snapshot(), envelope={"data": {"game_id": GAME_ID, "mode": "SNAPSHOT", "snapshot": replacement}})
    assert mode == "SNAPSHOT"
    assert updated == replacement


def test_nested_sequence_batches_apply_phase_transition_atomically() -> None:
    """Backend의 sequence별 중첩 operation이 최신 phase까지 반영되는지 확인한다."""

    envelope = {
        "data": {
            "game_id": GAME_ID,
            "mode": "DELTA",
            "state_version": 14,
            "last_sequence": 44,
            "operations": [{
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
