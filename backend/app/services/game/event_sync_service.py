"""게임 event 조회와 Front 동기화 operation 변환을 담당하는 모듈."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError

def build_operation_batches(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """같은 Front sequence의 operation을 순서대로 묶는다."""

    batches: dict[int, dict[str, Any]] = {}
    for row in rows:
        operation_type = row["operation_type"]
        payload = row["payload"]
        if operation_type is None or not isinstance(payload, Mapping):
            continue
        front_sequence = int(row["front_sequence"])
        batch = batches.setdefault(
            front_sequence,
            {
                "front_sequence": front_sequence,
                "state_version": int(row["state_version"]),
                "operations": [],
            },
        )
        batch["operations"].append(
            {
                "operation_index": int(row["operation_index"]),
                "type": str(operation_type),
                "payload": _operation_payload(row, operation_type, payload),
            }
        )
    return [batches[key] for key in sorted(batches)]


def _operation_payload(
    row: Mapping[str, Any], operation_type: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """공개 event payload에 event 메타데이터를 결합한다."""

    if operation_type != "APPEND_PUBLIC_EVENT":
        return dict(payload)
    created_at = row["created_at"]
    return {
        "event_id": str(row["id"]),
        "event_type": str(row["event_type"]),
        "created_at": created_at.isoformat().replace("+00:00", "Z")
        if isinstance(created_at, datetime)
        else str(created_at),
        "data": dict(payload),
    }


def read_sync(
    reader: Any,
    owner_user_id: Any,
    game_id: Any,
    *,
    after_state_version: int,
    after_sequence: int,
) -> dict[str, Any]:
    """소유자 검증부터 PostgreSQL event batch envelope까지의 sync 흐름을 실행한다."""

    if after_state_version < 0 or after_sequence < 0:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="sync cursor가 올바르지 않습니다.")
    try:
        with reader._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                game = reader._games.get_owned_game(cursor, owner_user_id=owner_user_id, game_id=game_id)
                if game is None:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                current_state_version = int(game["state_version"])
                current_sequence = max(int(game["next_front_sequence"]) - 1, 0)
                if after_state_version > current_state_version or after_sequence > current_sequence:
                    needs_snapshot = True
                elif after_sequence == current_sequence and after_state_version != current_state_version:
                    needs_snapshot = True
                else:
                    needs_snapshot = False
                if not needs_snapshot:
                    rows = reader._events.list_front_events(
                        cursor, game_id=game_id, after_front_sequence=after_sequence
                    )
        if needs_snapshot:
            snapshot = reader.snapshot(owner_user_id, game_id)
            return {
                "game_id": str(game_id), "mode": "SNAPSHOT",
                "from_state_version": after_state_version,
                "state_version": current_state_version,
                "last_sequence": current_sequence, "operations": [], "snapshot": snapshot,
            }
        operations = build_operation_batches(rows)
        return {
            "game_id": str(game_id),
            "mode": "DELTA",
            "from_state_version": after_state_version,
            "state_version": current_state_version if operations else after_state_version,
            "last_sequence": operations[-1]["front_sequence"] if operations else after_sequence,
            "operations": operations,
            "snapshot": None,
        }
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="게임 동기화를 사용할 수 없습니다.",
            retryable=True,
        ) from exc
