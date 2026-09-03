from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from backend.app.infrastructure.redis.cache import RedisPublicCache
from backend.app.infrastructure.redis.lock import RedisGameLock
from backend.app.infrastructure.redis.streams import RedisEventStream
from backend.app.infrastructure.transaction import (
    TransactionManager,
    advisory_lock_key,
    lock_game,
    lock_idempotency,
)
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.repositories.game_repository import PostgresGameRepository
from backend.app.repositories.outbox_repository import PostgresOutboxRepository
from backend.app.repositories.receipt_repository import PostgresReceiptRepository
from backend.app.repositories.snapshot_repository import PostgresSnapshotRepository

GAME_ID = UUID("00000000-0000-4000-8000-000000000001")
USER_ID = UUID("00000000-0000-4000-8000-000000000002")
EVENT_ID = UUID("00000000-0000-4000-8000-000000000003")
IDEMPOTENCY_KEY = UUID("00000000-0000-4000-8000-000000000004")
HASH = "a" * 64


class FakeCursor:
    """SQL과 bound parameter를 기록하는 테스트용 커서."""

    def __init__(
        self,
        *,
        one_rows: list[Mapping[str, Any] | None] | None = None,
        all_rows: list[list[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.statements: list[tuple[str, object]] = []
        self.one_rows = list(one_rows or [])
        self.all_rows = list(all_rows or [])

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        self.statements.append((str(sql), params))
        return self

    def fetchone(self) -> Mapping[str, Any] | None:
        return self.one_rows.pop(0) if self.one_rows else None

    def fetchall(self) -> list[Mapping[str, Any]]:
        return self.all_rows.pop(0) if self.all_rows else []


class FakeConnection:
    """정상 context는 commit, 예외 context는 rollback으로 기록한다."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class FakeRedis:
    """Redis 명령의 핵심 결과만 재현하는 외부 서비스 대역."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.xadd_calls: list[tuple[str, dict[str, str]]] = []
        self.published: list[tuple[str, str]] = []

    def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script: str, key_count: int, key: str, token: str) -> int:
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.xadd_calls.append((key, fields))
        return "1-0"

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


def test_transaction_commits_and_rolls_back() -> None:
    """DB context 정상 종료와 예외 종료가 서로 다른 결과를 남기는지 확인한다."""

    connection = FakeConnection()
    manager = TransactionManager("postgresql://synthetic", connection_factory=lambda _: connection)
    with manager.transaction():
        pass
    assert connection.committed
    assert not connection.rolled_back

    failed_connection = FakeConnection()
    failed_manager = TransactionManager(
        "postgresql://synthetic",
        connection_factory=lambda _: failed_connection,
    )
    with pytest.raises(RuntimeError):
        with failed_manager.transaction():
            raise RuntimeError("synthetic failure")
    assert failed_connection.rolled_back
    assert not failed_connection.committed


def test_advisory_lock_key_is_stable_and_bound() -> None:
    """동일 작업은 같은 lock key를 쓰고 값은 SQL에 직접 삽입하지 않는다."""

    cursor = FakeCursor()
    lock_idempotency(cursor, "USER", USER_ID, IDEMPOTENCY_KEY)
    lock_game(cursor, GAME_ID)

    assert advisory_lock_key("USER", USER_ID, IDEMPOTENCY_KEY) == advisory_lock_key(
        "USER", USER_ID, IDEMPOTENCY_KEY
    )
    assert len(cursor.statements) == 2
    assert all("pg_advisory_xact_lock" in sql for sql, _ in cursor.statements)
    assert str(USER_ID) not in cursor.statements[0][0]


def test_game_repository_locks_row_and_allocates_both_sequences() -> None:
    """게임 행 잠금과 event/front sequence 증가 SQL을 확인한다."""

    cursor = FakeCursor(
        one_rows=[
            {"id": GAME_ID},
            {"sequence": 3},
            {"front_sequence": 2},
        ]
    )
    repository = PostgresGameRepository()

    assert repository.lock_game(cursor, GAME_ID) == {"id": GAME_ID}
    assert repository.next_event_sequence(cursor, GAME_ID) == 3
    assert repository.next_front_sequence(cursor, GAME_ID) == 2
    assert "for update" in cursor.statements[0][0].lower()
    assert "next_event_sequence = next_event_sequence + 1" in cursor.statements[1][0]
    assert "next_front_sequence = next_front_sequence + 1" in cursor.statements[2][0]


def test_receipt_event_outbox_and_snapshot_use_canonical_columns() -> None:
    """B3 핵심 저장소가 payload 복사와 비밀값 저장 없이 정본 컬럼을 쓰는지 확인한다."""

    receipt_cursor = FakeCursor(one_rows=[{"id": IDEMPOTENCY_KEY}])
    receipt = PostgresReceiptRepository()
    receipt.insert(
        receipt_cursor,
        principal_type="USER",
        principal_id=USER_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        route_scope=f"POST /api/v1/games/{GAME_ID}/commands",
        game_id=GAME_ID,
        request_hash=HASH,
        result_state_version=2,
        http_status=202,
        result_body={"operation_id": str(EVENT_ID)},
    )
    assert "command_receipts" in receipt_cursor.statements[0][0]
    assert str(GAME_ID) not in receipt_cursor.statements[0][0]

    event_cursor = FakeCursor(one_rows=[{"sequence": 1}, {"id": EVENT_ID}])
    event = PostgresEventRepository()
    event.append(
        event_cursor,
        game_id=GAME_ID,
        state_version=2,
        event_type="PLAYER_SPOKE",
        audience="PUBLIC",
        payload={"text": "synthetic"},
    )
    assert "game_events" in event_cursor.statements[1][0]
    assert "sequence" in event_cursor.statements[0][0]

    outbox_cursor = FakeCursor(one_rows=[{"id": 1, "game_event_id": EVENT_ID}])
    outbox = PostgresOutboxRepository()
    outbox.enqueue(outbox_cursor, EVENT_ID)
    assert "event_outbox" in outbox_cursor.statements[0][0]
    assert "payload" not in outbox_cursor.statements[0][0].lower()

    snapshot_cursor = FakeCursor(one_rows=[{"id": EVENT_ID}])
    snapshot = PostgresSnapshotRepository()
    snapshot.save(
        snapshot_cursor,
        game_id=GAME_ID,
        state_version=2,
        last_front_sequence=1,
        schema_version=1,
        state_ciphertext=b"ciphertext",
        nonce=b"nonce",
        key_id="development-key-v1",
        checksum=HASH,
    )
    assert "game_snapshots" in snapshot_cursor.statements[0][0]


def test_repositories_reject_invalid_hash_and_event_audience() -> None:
    """DB CHECK 전에 Backend도 명백한 hash·audience 오류를 차단한다."""

    with pytest.raises(ValueError):
        PostgresReceiptRepository().insert(
            FakeCursor(),
            principal_type="USER",
            principal_id=USER_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            route_scope="POST /api/v1/games",
            game_id=None,
            request_hash="not-a-hash",
            result_state_version=None,
            http_status=201,
            result_body={"game_id": str(GAME_ID)},
        )

    with pytest.raises(ValueError):
        PostgresEventRepository().append(
            FakeCursor(one_rows=[{"sequence": 1}]),
            game_id=GAME_ID,
            state_version=1,
            event_type="PLAYER_SPOKE",
            audience="PLAYER",
            payload={"text": "synthetic"},
        )


def test_redis_lock_cache_and_stream_follow_canonical_keys() -> None:
    """Redis는 lock·공개 cache·event fan-out만 맡고 정본 key를 사용한다."""

    client = FakeRedis()
    lock = RedisGameLock(client, ttl_seconds=15)
    first = lock.acquire(str(GAME_ID))
    assert first is not None
    assert lock.acquire(str(GAME_ID)) is None
    assert not lock.release(type(first)(str(GAME_ID), "wrong-token"))
    assert lock.release(first)
    assert RedisGameLock.key(str(GAME_ID)) == f"mafia:v1:lock:game:{GAME_ID}"

    cache = RedisPublicCache(client, ttl_seconds=60)
    cache.set(str(GAME_ID), 2, {"phase": "DAY_DISCUSSION"})
    assert cache.get(str(GAME_ID), 2) == {"phase": "DAY_DISCUSSION"}
    assert RedisPublicCache.key(str(GAME_ID), 2) == f"mafia:v1:public:{GAME_ID}:2"

    stream = RedisEventStream(client, max_length=100)
    stream_id = stream.publish_batch(str(GAME_ID), 2, [str(EVENT_ID)])
    stream.publish_outbox_wakeup(7)
    assert stream_id == "1-0"
    assert client.xadd_calls[0][0] == f"mafia:v1:events:{GAME_ID}"
    assert client.published == [("mafia:v1:outbox:wakeup", "7")]
