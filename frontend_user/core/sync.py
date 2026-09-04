"""SSE·polling 공통 sync envelope 검증과 원자적 operation 적용."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

ALLOWED_OPERATION_TYPES = {
    "SET_GAME_STATE", "REPLACE_PLAYERS", "SET_PRIVATE_STATE", "SET_ACTION_WINDOW",
    "CLEAR_ACTION_WINDOW", "APPEND_PUBLIC_EVENT", "APPEND_PRIVATE_EVENT", "SET_RESULT",
}


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    """정본에 정의된 polling·실패 전환 timing을 한 곳에서 관리한다."""

    foreground_poll_ms: int = 2_000
    background_poll_ms: int = 10_000
    stale_after_failures: int = 5
    sse_retry_ms: int = 1_000


class SyncEnvelopeError(ValueError):
    """부분 적용 없이 snapshot 복구가 필요한 sync 계약 오류."""


def apply_envelope(*, snapshot: dict[str, Any], envelope: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """DELTA를 검증한 뒤 전부 적용하고, SNAPSHOT은 authoritative snapshot으로 교체한다."""

    # 팀 전달 사항: Backend의 /sync와 /events는 동일한 game_id·front_sequence·
    # operation_index를 사용해야 한다. sequence/index gap이나 unknown operation이
    # 있으면 부분 batch가 아니라 mode=SNAPSHOT으로 복구할 수 있는 응답을 제공한다.

    data = envelope.get("data", envelope)
    if not isinstance(data, dict) or data.get("mode") not in {"DELTA", "SNAPSHOT"}:
        raise SyncEnvelopeError("SYNC_INVALID")
    current_game = snapshot.get("game")
    if not isinstance(current_game, dict) or data.get("game_id") != current_game.get("game_id"):
        raise SyncEnvelopeError("SYNC_GAME_MISMATCH")
    if data["mode"] == "SNAPSHOT":
        replacement = data.get("snapshot")
        if not isinstance(replacement, dict) or not isinstance(replacement.get("game"), dict):
            raise SyncEnvelopeError("SYNC_SNAPSHOT_INVALID")
        return deepcopy(replacement), "SNAPSHOT"
    operations = data.get("operations")
    if not isinstance(operations, list):
        raise SyncEnvelopeError("SYNC_OPERATIONS_INVALID")
    expected_sequence = int(current_game.get("last_sequence", 0))
    expected_index = -1
    candidate = deepcopy(snapshot)
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("type") not in ALLOWED_OPERATION_TYPES:
            raise SyncEnvelopeError("SYNC_UNKNOWN_OPERATION")
        sequence = operation.get("front_sequence")
        index = operation.get("operation_index")
        if not isinstance(sequence, int) or not isinstance(index, int):
            raise SyncEnvelopeError("SYNC_OPERATION_ID_INVALID")
        if sequence < expected_sequence or (sequence == expected_sequence and index <= expected_index):
            continue
        if sequence == expected_sequence:
            if index != expected_index + 1:
                raise SyncEnvelopeError("SYNC_BATCH_INDEX_GAP")
        elif sequence == expected_sequence + 1 and index == 0:
            expected_index = -1
        else:
            raise SyncEnvelopeError("SYNC_SEQUENCE_GAP")
        expected_sequence = sequence
        expected_index = index
        _apply_operation(candidate, operation)
    state_version = data.get("state_version")
    last_sequence = data.get("last_sequence")
    if not isinstance(state_version, int) or not isinstance(last_sequence, int):
        raise SyncEnvelopeError("SYNC_CURSOR_INVALID")
    if last_sequence < int(current_game.get("last_sequence", 0)) or state_version < int(current_game.get("state_version", 0)):
        raise SyncEnvelopeError("SYNC_CURSOR_REVERSED")
    if not operations and (last_sequence != current_game.get("last_sequence") or state_version != current_game.get("state_version")):
        raise SyncEnvelopeError("SYNC_EMPTY_ADVANCED")
    candidate["game"]["last_sequence"] = last_sequence
    candidate["game"]["state_version"] = state_version
    return candidate, "DELTA"


def _apply_operation(snapshot: dict[str, Any], operation: dict[str, Any]) -> None:
    """허용된 operation만 projection의 해당 영역에 적용한다."""

    # 팀 전달 사항: 아래 operation type과 payload는 API 정본의 폐쇄형 union이다.
    # 다른 AI의 private event, capability, prompt, 개별 투표는 Front operation으로
    # 전달하지 않는다.

    payload = operation.get("payload")
    if not isinstance(payload, dict):
        raise SyncEnvelopeError("SYNC_PAYLOAD_INVALID")
    operation_type = operation["type"]
    if operation_type == "SET_GAME_STATE":
        snapshot["game"].update({key: payload[key] for key in ("status", "phase", "round", "day_number", "state_version", "fast_forward_enabled") if key in payload})
    elif operation_type == "REPLACE_PLAYERS":
        snapshot["players"] = deepcopy(payload.get("players", []))
    elif operation_type == "SET_PRIVATE_STATE":
        snapshot["me"] = deepcopy(payload.get("me", {}))
    elif operation_type == "SET_ACTION_WINDOW":
        snapshot["action_window"] = deepcopy(payload)
    elif operation_type == "CLEAR_ACTION_WINDOW":
        snapshot["action_window"] = None
    elif operation_type == "APPEND_PUBLIC_EVENT":
        snapshot.setdefault("public_events", []).append(deepcopy(payload))
    elif operation_type == "APPEND_PRIVATE_EVENT":
        snapshot.setdefault("me", {}).setdefault("private_events", []).append(deepcopy(payload))
    elif operation_type == "SET_RESULT":
        snapshot["result"] = deepcopy(payload)
