from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.game_engine.engine import GameEngine
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.infrastructure.redis.cache import RedisConversationHistory, RedisPublicCache
from backend.app.infrastructure.redis.lock import RedisGameLock
from backend.app.infrastructure.redis.streams import RedisEventStream
from backend.app.infrastructure.transaction import (
    TransactionManager,
    advisory_lock_key,
    lock_game,
    lock_idempotency,
)
from backend.app.main import create_app
from backend.app.models.enums import PlayerKind
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.repositories.agent_repository import PostgresAgentRepository
from backend.app.repositories.game_repository import (
    EncryptedGameSeed,
    GameStateKeyring,
    PostgresGameRepository,
)
from backend.app.repositories.outbox_repository import PostgresOutboxRepository
from backend.app.repositories.action_repository import (
    ActionSubmissionInsert,
    ActionWindowInsert,
    PostgresActionRepository,
)
from backend.app.repositories.player_repository import (
    PlayerInsert,
    PostgresPlayerRepository,
    ScenarioFactInsert,
)
from backend.app.repositories.receipt_repository import PostgresReceiptRepository
from backend.app.repositories.scenario_repository import PostgresScenarioRepository
from backend.app.repositories.snapshot_repository import PostgresSnapshotRepository
from backend.app.routers import health_router as health_router_module
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.constants import INTRO_MESSAGE
from backend.app.services.game_service import (
    PostgresBeginGameService,
    PostgresDiscussionCommandService,
    PostgresGameCreationService,
    PostgresGameReadService,
    PostgresGameResumeService,
    PostgresGameSaveService,
    uuid5_for_window,
)

GAME_ID = UUID("00000000-0000-4000-8000-000000000001")
USER_ID = UUID("00000000-0000-4000-8000-000000000002")
EVENT_ID = UUID("00000000-0000-4000-8000-000000000003")
IDEMPOTENCY_KEY = UUID("00000000-0000-4000-8000-000000000004")
HASH = "a" * 64


def _write_synthetic_keyring(path: Path, *, key_id: str = "test-key-v1") -> None:
    """실제 운영 키 대신 테스트에서만 쓰는 고정 32-byte 키 파일을 만든다."""

    encoded_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")
    path.write_text(
        json.dumps({"version": 1, "keys": {key_id: encoded_key}}),
        encoding="utf-8",
    )
    # POSIX 테스트 환경에서는 운영 규칙과 같은 소유자 전용 권한을 적용한다.
    if os.name != "nt":
        path.chmod(0o600)


def _readiness_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    postgresql: bool,
    redis: bool,
) -> TestClient:
    """실제 외부 서버를 호출하지 않고 readiness의 성공·실패 조합을 만든다.

    연결 함수 자체는 운영에서 실제 PostgreSQL과 Redis를 호출한다. 자동 테스트에서는
    팀 공용 DB에 영향을 주지 않도록 결과만 바꾸는 fake를 사용한다.
    """

    monkeypatch.setattr(
        health_router_module,
        "_postgresql_ready",
        lambda _: postgresql,
    )
    monkeypatch.setattr(
        health_router_module,
        "_redis_ready",
        lambda _: redis,
    )
    settings = Settings(
        database_url="postgresql://test:synthetic@localhost/test_db",
        database_name="test_db",
        redis_url="redis://localhost:6379/0",
    )
    return TestClient(create_app(settings=settings))


def test_ready_returns_200_only_when_postgresql_and_redis_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 필수 저장소가 모두 정상일 때만 요청 처리 준비 완료로 판단한다."""

    client = _readiness_client(monkeypatch, postgresql=True, redis=True)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgresql": "ok", "redis": "ok"},
    }


def test_ready_returns_safe_503_without_exposing_connection_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 저장소라도 실패하면 비밀 없는 고정 상태만 반환한다."""

    client = _readiness_client(monkeypatch, postgresql=True, redis=False)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"postgresql": "ok", "redis": "error"},
    }


def test_game_state_keyring_encrypts_and_decrypts_seed_with_fresh_nonce(
    tmp_path: Path,
) -> None:
    """같은 seed도 매번 다른 암호문이 되고 원래 값으로만 복원되는지 확인한다."""

    keyring_path = tmp_path / "game-state-keyring.json"
    _write_synthetic_keyring(keyring_path)
    settings = Settings(
        database_url="postgresql://test:synthetic@localhost/test_db",
        database_name="test_db",
        game_state_keyring_file=str(keyring_path),
        game_state_active_key_id="test-key-v1",
    )
    keyring = GameStateKeyring.from_settings(settings)

    first = keyring.encrypt_seed(b"fixed-game-seed")
    second = keyring.encrypt_seed(b"fixed-game-seed")

    assert first.key_id == "test-key-v1"
    assert len(first.nonce) == 12
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert b"fixed-game-seed" not in first.ciphertext
    assert (
        keyring.decrypt_seed(
            ciphertext=first.ciphertext,
            nonce=first.nonce,
            key_id=first.key_id,
        )
        == b"fixed-game-seed"
    )


def test_game_state_keyring_fails_closed_for_missing_or_tampered_data(
    tmp_path: Path,
) -> None:
    """키 누락과 암호문 위변조를 평문 처리나 재추첨으로 우회하지 않는지 확인한다."""

    unconfigured = Settings(
        database_url="postgresql://test:synthetic@localhost/test_db",
        database_name="test_db",
    )
    with pytest.raises(RuntimeError, match="not configured"):
        GameStateKeyring.from_settings(unconfigured)

    keyring_path = tmp_path / "game-state-keyring.json"
    _write_synthetic_keyring(keyring_path)
    settings = Settings(
        database_url="postgresql://test:synthetic@localhost/test_db",
        database_name="test_db",
        game_state_keyring_file=str(keyring_path),
        game_state_active_key_id="test-key-v1",
    )
    keyring = GameStateKeyring.from_settings(settings)
    encrypted = keyring.encrypt_seed(b"fixed-game-seed")
    tampered = encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1])

    with pytest.raises(RuntimeError, match="authentication failed"):
        keyring.decrypt_seed(
            ciphertext=tampered,
            nonce=encrypted.nonce,
            key_id=encrypted.key_id,
        )


def test_game_state_keyring_rejects_wrong_key_length(tmp_path: Path) -> None:
    """AES-256이 아닌 길이의 키는 게임 저장 전에 거부하는지 확인한다."""

    keyring_path = tmp_path / "game-state-keyring.json"
    encoded_key = base64.urlsafe_b64encode(bytes(range(31))).decode("ascii").rstrip("=")
    keyring_path.write_text(
        json.dumps({"version": 1, "keys": {"test-key-v1": encoded_key}}),
        encoding="utf-8",
    )
    if os.name != "nt":
        keyring_path.chmod(0o600)
    settings = Settings(
        database_url="postgresql://test:synthetic@localhost/test_db",
        database_name="test_db",
        game_state_keyring_file=str(keyring_path),
        game_state_active_key_id="test-key-v1",
    )

    with pytest.raises(RuntimeError, match="invalid key"):
        GameStateKeyring.from_settings(settings)


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

    def __enter__(self) -> "FakeCursor":
        """실제 psycopg cursor와 같은 with 문 사용을 지원한다."""

        return self

    def __exit__(self, *args: object) -> bool:
        """가짜 cursor는 별도 자원이 없으므로 예외를 그대로 전달한다."""

        return False

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        self.statements.append((str(sql), params))
        return self

    def fetchone(self) -> Mapping[str, Any] | None:
        return self.one_rows.pop(0) if self.one_rows else None

    def fetchall(self) -> list[Mapping[str, Any]]:
        return self.all_rows.pop(0) if self.all_rows else []


class FakeConnection:
    """정상 context는 commit, 예외 context는 rollback으로 기록한다."""

    def __init__(self, cursor: FakeCursor | None = None) -> None:
        self.committed = False
        self.rolled_back = False
        self._cursor = cursor or FakeCursor()

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False

    def cursor(self, *args: object, **kwargs: object) -> FakeCursor:
        """row_factory 인자는 기록하지 않고 같은 가짜 cursor를 반환한다."""

        del args, kwargs
        return self._cursor


def _last_user_action_flags(cursor: FakeCursor) -> list[bool]:
    """게임 상태 UPDATE에 전달된 사용자 동작 표지만 테스트용으로 추출한다."""

    return [
        params[-3]
        for sql, params in cursor.statements
        if "last_user_action_at" in sql and isinstance(params, tuple)
    ]


class _DirectContext:
    """저장소의 수동 context 종료 호출을 검증하는 얇은 대역이다."""

    def __init__(self, value: object) -> None:
        self.value = value
        self.exit_args: tuple[object, ...] | None = None

    def __exit__(self, *args: object) -> bool:
        self.exit_args = args
        if hasattr(self.value, "__exit__"):
            return bool(self.value.__exit__(*args))
        return False


def test_agent_repository_closes_successful_transaction_without_none_type_error() -> None:
    """Agent 저장소의 정상 종료가 NoneType을 예외로 전달하지 않는지 검증한다."""

    connection = FakeConnection()
    cursor = connection.cursor()
    connection_context = _DirectContext(connection)
    cursor_context = _DirectContext(cursor)

    PostgresAgentRepository._close_connection_cursor(
        (connection_context, cursor_context, cursor)
    )

    assert connection.committed is True
    assert connection.rolled_back is False


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


def test_game_repository_deletes_only_locked_stale_in_progress_batch() -> None:
    """15분 경계를 포함하고 잠기지 않은 최대 100개 진행 게임만 삭제한다."""

    second_game_id = UUID("00000000-0000-4000-8000-000000000005")
    cursor = FakeCursor(all_rows=[[{"id": GAME_ID}, {"id": second_game_id}]])

    deleted = PostgresGameRepository().delete_stale_in_progress(cursor, limit=100)

    assert deleted == [GAME_ID, second_game_id]
    sql, params = cursor.statements[0]
    normalized = " ".join(sql.lower().split())
    assert normalized.count("game.status = 'in_progress'") == 1
    assert "where status = 'in_progress'" in normalized
    assert normalized.count("<= current_timestamp - interval '15 minutes'") == 2
    assert "for update skip locked" in normalized
    assert "delete from public.games" in normalized
    assert params == (100,)


@pytest.mark.parametrize("limit", [0, 101, True])
def test_game_repository_rejects_unbounded_cleanup_batch(limit: object) -> None:
    """잘못된 batch 크기는 삭제 SQL을 실행하기 전에 거부한다."""

    cursor = FakeCursor()
    with pytest.raises(ValueError, match="batch"):
        PostgresGameRepository().delete_stale_in_progress(
            cursor, limit=limit,  # type: ignore[arg-type]
        )
    assert cursor.statements == []


def test_runtime_commits_stale_game_deletion_before_cache_invalidation() -> None:
    """Redis 정리는 권위 DB commit 뒤 실행하며 삭제 건수를 그대로 반환한다."""

    from types import SimpleNamespace

    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    second_game_id = UUID("00000000-0000-4000-8000-000000000005")
    connection = FakeConnection()
    deleted: list[str] = []

    class History:
        def delete(self, game_id: str) -> bool:
            assert connection.committed
            deleted.append(game_id)
            return True

    runtime = object.__new__(PostgresGameRuntime)
    runtime._transactions = TransactionManager(
        "postgresql://synthetic", connection_factory=lambda _: connection,
    )
    runtime._games = SimpleNamespace(
        delete_stale_in_progress=lambda cursor, *, limit: [GAME_ID, second_game_id],
    )
    runtime._conversation_history = History()

    assert runtime.cleanup_stale_games() == 2
    assert deleted == [str(GAME_ID), str(second_game_id)]


@pytest.mark.parametrize("case,code", [
    ("missing", "GAME_NOT_FOUND"), ("other_owner", "GAME_NOT_FOUND"),
    ("stale", "STALE_STATE_VERSION"), ("completed", "INVALID_GAME_STATUS"),
    ("failed", "INVALID_GAME_STATUS"), ("write_failure", "DEPENDENCY_UNAVAILABLE"),
    ("success", None), ("saved", None),
])
def test_manual_delete_checks_owner_version_status_and_rolls_back(case, code) -> None:
    """게임 행 잠금 뒤 모든 거부 조건을 확인하며 삭제 실패도 transaction을 되돌린다."""

    from types import SimpleNamespace
    from backend.app.services.game.lifecycle_service import delete_game

    row = {"id": GAME_ID, "owner_user_id": USER_ID, "state_version": 12, "status": "IN_PROGRESS"}
    if case == "other_owner":
        row["owner_user_id"] = GAME_ID
    elif case == "stale":
        row["state_version"] = 13
    elif case in {"completed", "failed", "saved"}:
        row["status"] = case.upper()
    cursor = FakeCursor(one_rows=[None if case == "missing" else row,
                                  None if case == "write_failure" else {"id": GAME_ID}])
    connection = FakeConnection(cursor)
    service = SimpleNamespace(
        _transactions=TransactionManager("postgresql://synthetic", connection_factory=lambda _: connection),
        _games=PostgresGameRepository(),
    )
    if code:
        with pytest.raises(ApiError) as error:
            delete_game(service, USER_ID, GAME_ID, expected_state_version=12)
        assert error.value.code == code
        assert connection.rolled_back and not connection.committed
        if case != "write_failure":
            assert len(cursor.statements) == 1
    else:
        assert delete_game(service, USER_ID, GAME_ID, expected_state_version=12) == {
            "game_id": str(GAME_ID), "deleted": True,
        }
        assert connection.committed
        assert cursor.statements[-1][1] == (GAME_ID, USER_ID, 12)
    assert "FOR UPDATE" in cursor.statements[0][0]


def test_manual_delete_commits_before_cache_and_tolerates_cache_failure() -> None:
    """Redis 실패로 이미 확정된 DB 삭제를 실패 응답으로 바꾸지 않는다."""

    from types import SimpleNamespace
    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    cursor = FakeCursor(one_rows=[
        {"owner_user_id": USER_ID, "state_version": 12, "status": "IN_PROGRESS"}, {"id": GAME_ID},
    ])
    connection = FakeConnection(cursor)

    def fail_cache(game_id):
        assert game_id == str(GAME_ID) and connection.committed
        raise RuntimeError("합성 Redis 장애")

    runtime = object.__new__(PostgresGameRuntime)
    runtime._transactions = TransactionManager("postgresql://synthetic", connection_factory=lambda _: connection)
    runtime._games = PostgresGameRepository()
    runtime._conversation_history = SimpleNamespace(delete=fail_cache)
    assert runtime.delete_game(USER_ID, GAME_ID, expected_state_version=12)["deleted"] is True


def test_game_creation_repositories_use_canonical_tables_and_bound_values() -> None:
    """게임 생성용 조회·INSERT가 정본 테이블과 bound parameter를 쓰는지 확인한다."""

    scenario_cursor = FakeCursor(
        one_rows=[{"scenario_id": "BLACKOUT_STUDIO"}],
        all_rows=[
            [{"id": "BLACKOUT_STUDIO", "content_hash": HASH}],
            [
                {
                    "id": EVENT_ID,
                    "template_kind": "ALIBI",
                    "template_key": "alibi-01",
                }
            ],
        ],
    )
    scenarios = PostgresScenarioRepository()
    assert scenarios.list_active(
        scenario_cursor, scenario_version="scenario-v1"
    )[0]["id"] == "BLACKOUT_STUDIO"
    assert (
        scenarios.last_created_scenario_id(
            scenario_cursor,
            owner_user_id=USER_ID,
            scenario_version="scenario-v1",
        )
        == "BLACKOUT_STUDIO"
    )
    assert scenarios.list_active_templates(
        scenario_cursor, scenario_id="BLACKOUT_STUDIO"
    )[0]["template_kind"] == "ALIBI"
    assert "scenario_catalog" in scenario_cursor.statements[0][0]
    assert "scenario_templates" in scenario_cursor.statements[2][0]
    assert str(USER_ID) not in scenario_cursor.statements[1][0]

    state = GameEngine.new_game(
        [
            (
                UUID(int=index + 1),
                PlayerKind.HUMAN if index == 0 else PlayerKind.AI,
            )
            for index in range(6)
        ],
        seed=b"repository-test-seed",
        game_id=GAME_ID,
    )
    game_cursor = FakeCursor(one_rows=[{"id": GAME_ID}])
    created = PostgresGameRepository().insert_initial_game(
        game_cursor,
        state=state,
        owner_user_id=USER_ID,
        scenario_version="scenario-v1",
        scenario_id="BLACKOUT_STUDIO",
        scenario_content_hash=HASH,
        encrypted_seed=EncryptedGameSeed(
            ciphertext=b"ciphertext",
            nonce=b"123456789012",
            key_id="test-key-v1",
        ),
    )
    assert created["id"] == GAME_ID
    assert "public.games" in game_cursor.statements[0][0]
    assert str(GAME_ID) not in game_cursor.statements[0][0]

    player_rows = [
        PlayerInsert(
            player_id=player.player_id,
            user_id=USER_ID if player.kind is PlayerKind.HUMAN else None,
            kind=player.kind.value,
            seat=player.seat,
            display_name=f"플레이어 {player.seat}",
            role=player.role.value,
            faction=player.faction.value,
            persona_id=None if player.kind is PlayerKind.HUMAN else "CAUTIOUS_ANALYST",
        )
        for player in state.players
    ]
    player_cursor = FakeCursor()
    players = PostgresPlayerRepository()
    players.insert_players(player_cursor, game_id=GAME_ID, players=player_rows)

    fact_rows: list[ScenarioFactInsert] = []
    for player in state.players:
        for fact_kind in ("ALIBI", "OBSERVATION"):
            index = len(fact_rows)
            fact_rows.append(
                ScenarioFactInsert(
                    fact_id=UUID(int=100 + index),
                    player_id=player.player_id,
                    fact_kind=fact_kind,
                    template_id=UUID(int=200 + index),
                    rendered_text=f"좌석 {player.seat}의 테스트 단서",
                )
            )
    players.insert_facts(
        player_cursor,
        game_id=GAME_ID,
        facts=fact_rows,
    )
    assert len(player_cursor.statements) == 18
    assert all("public.game_players" in sql for sql, _ in player_cursor.statements[:6])
    assert all(
        "public.player_scenario_facts" in sql for sql, _ in player_cursor.statements[6:]
    )


def _creation_templates() -> list[dict[str, object]]:
    """6인 게임 생성에 필요한 합성 ALIBI·OBSERVATION template을 만든다."""

    templates: list[dict[str, object]] = []
    for index in range(6):
        templates.append(
            {
                "id": UUID(int=500 + index),
                "template_kind": "ALIBI",
                "template_key": f"ALIBI_{index:02}",
                "text_template": "좌석 {{seat}}은 테스트 장소에 있었다.",
                "subject_mode": "NONE",
            }
        )
        templates.append(
            {
                "id": UUID(int=600 + index),
                "template_kind": "OBSERVATION",
                "template_key": f"OBSERVATION_{index:02}",
                "text_template": "좌석 {{seat}}은 누군가를 보았다.",
                "subject_mode": "SEAT",
            }
        )
    return templates


def _postgres_creation_service(cursor: FakeCursor) -> PostgresGameCreationService:
    """실제 DB 대신 한 가짜 transaction을 쓰는 게임 생성 서비스를 조립한다."""

    connection = FakeConnection(cursor)
    transactions = TransactionManager(
        "postgresql://synthetic",
        connection_factory=lambda _: connection,
    )
    service = PostgresGameCreationService(
        transactions=transactions,
        keyring=GameStateKeyring(
            active_key_id="test-key-v1",
            keys={"test-key-v1": bytes(range(32))},
        ),
    )
    # 테스트가 commit 또는 rollback을 확인할 수 있도록 가짜 연결을 함께 보관한다.
    service._test_connection = connection  # type: ignore[attr-defined]
    return service


def test_postgres_game_creation_commits_all_canonical_rows_in_one_transaction() -> None:
    """게임 생성의 모든 DB 행이 한 transaction 안에서 순서대로 기록되는지 확인한다."""

    now = datetime.now(UTC)
    cursor = FakeCursor(
        one_rows=[
            None,
            {"id": USER_ID, "created_at": now, "last_seen_at": now},
            None,
            {"id": GAME_ID},
            {"sequence": 1},
            {"id": EVENT_ID},
            {"id": 1, "game_event_id": EVENT_ID},
            {"id": IDEMPOTENCY_KEY},
        ],
        all_rows=[
            [
                {
                    "id": "BLACKOUT_STUDIO",
                    "version": "scenario-v1",
                    "content_hash": HASH,
                }
            ],
            [{"id": "CAUTIOUS_ANALYST", "version": "agent-config-v1"}],
            _creation_templates(),
        ],
    )
    service = _postgres_creation_service(cursor)

    result, replayed = service.create(
        USER_ID,
        CreateGameRequest(
            player_count=6,
            ruleset_version="mystery-v1",
            scenario_version="scenario-v1",
        ),
        IDEMPOTENCY_KEY,
    )

    assert not replayed
    assert result["status"] == "IN_PROGRESS"
    assert result["phase"] == "ROLE_REVEAL"
    assert result["state_version"] == 1
    assert service._test_connection.committed  # type: ignore[attr-defined]
    statements = "\n".join(sql for sql, _ in cursor.statements).lower()
    for table_name in (
        "users",
        "scenario_catalog",
        "agent_personas",
        "scenario_templates",
        "games",
        "game_players",
        "player_scenario_facts",
        "game_events",
        "event_outbox",
        "command_receipts",
    ):
        assert table_name in statements


def test_postgres_game_creation_rolls_back_when_player_storage_fails() -> None:
    """중간 INSERT 실패가 users·games만 남기는 부분 저장으로 이어지지 않는지 확인한다."""

    class FailingPlayerRepository(PostgresPlayerRepository):
        """DB 오류 대신 의도적으로 실패해 transaction rollback을 검증한다."""

        def insert_players(self, cursor: Any, *, game_id: UUID, players: list[PlayerInsert]) -> None:
            del cursor, game_id, players
            raise RuntimeError("synthetic player insert failure")

    now = datetime.now(UTC)
    cursor = FakeCursor(
        one_rows=[
            None,
            {"id": USER_ID, "created_at": now, "last_seen_at": now},
            None,
            {"id": GAME_ID},
        ],
        all_rows=[
            [{"id": "BLACKOUT_STUDIO", "version": "scenario-v1", "content_hash": HASH}],
            [{"id": "CAUTIOUS_ANALYST", "version": "agent-config-v1"}],
            _creation_templates(),
        ],
    )
    service = _postgres_creation_service(cursor)
    service._players = FailingPlayerRepository()  # type: ignore[attr-defined]

    with pytest.raises(ApiError, match="게임 저장소") as error:
        service.create(
            USER_ID,
            CreateGameRequest(
                player_count=6,
                ruleset_version="mystery-v1",
                scenario_version="scenario-v1",
            ),
            IDEMPOTENCY_KEY,
        )

    assert error.value.status_code == 503
    assert service._test_connection.rolled_back  # type: ignore[attr-defined]


def _snapshot_reader(
    events: list[Mapping[str, Any]] | None = None,
    *,
    game_changes: Mapping[str, Any] | None = None,
) -> tuple[PostgresGameReadService, FakeCursor, FakeConnection]:
    """DB 없이 동일한 저장 이력을 두 번 재조회할 수 있는 snapshot 대역을 구성한다."""

    seed = b"database-read-seed"
    players = GameEngine.new_game(
        [(UUID(int=index + 700), PlayerKind.HUMAN if index == 0 else PlayerKind.AI) for index in range(6)],
        game_id=GAME_ID,
        seed=seed,
    ).players
    keyring = GameStateKeyring(
        active_key_id="test-key-v1",
        keys={"test-key-v1": bytes(range(32))},
    )
    encrypted_seed = keyring.encrypt_seed(seed)
    now = datetime.now(UTC)
    game_row = {
        "id": GAME_ID,
        "owner_user_id": USER_ID,
        "status": "IN_PROGRESS",
        "phase": "ROLE_REVEAL",
        "round": 0,
        "day_number": 1,
        "state_version": 1,
        "next_front_sequence": 1,
        "next_event_sequence": 1,
        "player_count": 6,
        "mafia_count": 1,
        "scenario_version": "scenario-v1",
        "scenario_id": "BLACKOUT_STUDIO",
        "scenario_content_hash": HASH,
        "seed_ciphertext": encrypted_seed.ciphertext,
        "seed_nonce": encrypted_seed.nonce,
        "seed_key_id": encrypted_seed.key_id,
        "winner": None,
        "win_reason": None,
        "updated_at": now,
        "scenario_title": "정전된 방송국",
        "scenario_background": "테스트 사건 배경",
        "scenario_victim": "테스트 피해자",
        "scenario_locations": ["스튜디오", "조정실", "분장실", "대기실"],
    }
    player_rows = [
        {
            "id": player.player_id,
            "game_id": GAME_ID,
            "user_id": USER_ID if player.kind is PlayerKind.HUMAN else None,
            "kind": player.kind.value,
            "seat": player.seat,
            "display_name": f"플레이어 {player.seat}",
            "role": player.role.value,
            "faction": player.faction.value,
            "alive": True,
            "persona_id": None if player.kind is PlayerKind.HUMAN else "CAUTIOUS_ANALYST",
            "eliminated_phase": None,
            "eliminated_round": None,
        }
        for player in players
    ]
    game_row.update(game_changes or {})
    cursor = FakeCursor(
        one_rows=[game_row, None, game_row, None],
        all_rows=[
            player_rows,
            [
                {
                    "fact_kind": "ALIBI",
                    "rendered_text": "좌석 1은 스튜디오에 있었다.",
                },
                {
                    "fact_kind": "OBSERVATION",
                    "rendered_text": "좌석 1은 조정실 쪽을 보았다.",
                },
            ],
            events or [],
            [],
            [],
        ] * 2,
    )
    connection = FakeConnection(cursor)
    reader = PostgresGameReadService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=keyring,
    )
    return reader, cursor, connection


def test_postgres_game_reader_projects_owned_initial_snapshot_without_role_leak() -> None:
    """DB game·player·fact 행에서 인간 본인 정보만 포함한 최초 snapshot을 복원한다."""

    reader, _, connection = _snapshot_reader()

    snapshot = reader.snapshot(USER_ID, GAME_ID)

    assert snapshot["game"]["game_id"] == str(GAME_ID)
    assert snapshot["game"]["phase"] == "ROLE_REVEAL"
    assert len(snapshot["players"]) == 6
    assert all("role" not in player for player in snapshot["players"])
    assert snapshot["me"]["role"] in {"MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN"}
    assert snapshot["me"]["alibi"] == "좌석 1은 스튜디오에 있었다."
    assert snapshot["me"]["observation"] == "좌석 1은 조정실 쪽을 보았다."
    assert snapshot["public_events"] == []
    assert connection.committed


def _public_event_row(
    sequence: int,
    event_type: str = "PLAYER_PASSED",
    payload: Any = None,
    **changes: Any,
) -> dict[str, Any]:
    """실제 append 저장 형식에 맞는 synthetic 이벤트를 만들고 손상 조건을 주입한다."""

    return {
        "id": UUID(int=10_000 + sequence),
        "game_id": GAME_ID,
        "sequence": sequence,
        "front_sequence": 1,
        "operation_index": sequence,
        "state_version": 2,
        "event_type": event_type,
        "audience": "PUBLIC",
        "audience_player_id": None,
        "schema_version": 1,
        "operation_type": "APPEND_PUBLIC_EVENT",
        "payload": {"player_id": str(UUID(int=700))} if payload is None else payload,
        "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        **changes,
    }


HISTORY_GAME_CHANGES = {
    "phase": "DAY_DISCUSSION", "state_version": 10,
    "next_front_sequence": 11, "next_event_sequence": 2001,
}


@pytest.mark.parametrize("status, phase", [
    ("IN_PROGRESS", "DAY_DISCUSSION"), ("SAVED", "DAY_DISCUSSION"), ("COMPLETED", "ENDED"),
])
def test_snapshot_restores_public_history_in_sequence_order_on_each_read(
    status: str, phase: str,
) -> None:
    """동일 시각·batch의 시작/인간/AI 발언과 PASS를 재조회해도 DB 순서대로 복원한다."""

    rows = [
        _public_event_row(1, "GAME_BEGAN", {"message": INTRO_MESSAGE}),
        _public_event_row(3, "PLAYER_SPOKE", {
            "player_id": str(UUID(int=700)), "message": "  함께\n 확인합시다. ",
            "target_player_id": str(UUID(int=702)), "role": "MAFIA",
        }),
        _public_event_row(4, "PLAYER_SPOKE", {
            "player_id": str(UUID(int=701)), "message": "동의합니다.",
        }),
        _public_event_row(6),
    ]
    reader, cursor, _ = _snapshot_reader(list(reversed(rows)), game_changes={
        **HISTORY_GAME_CHANGES, "status": status, "phase": phase,
    })

    first = reader.snapshot(USER_ID, GAME_ID)

    assert [event["event_id"] for event in first["public_events"]] == [
        str(row["id"]) for row in rows
    ]
    second = reader.snapshot(USER_ID, GAME_ID)
    assert first["public_events"] == second["public_events"]
    assert first["public_events"][1]["data"] == {
        "player_id": str(UUID(int=700)), "message": "함께 확인합시다.",
    }
    assert first["me"]["private_events"] == []
    assert all(set(event) == {"event_id", "event_type", "created_at", "data"}
               for event in first["public_events"])
    assert all(event["created_at"] == "2026-01-02T03:04:05Z"
               for event in first["public_events"])
    queries = [(sql, params) for sql, params in cursor.statements if "FROM public.game_events" in sql and "audience = 'PUBLIC'" in sql]
    assert len(queries) == 2
    assert all(params == (GAME_ID, 2000, 10, 10) for _, params in queries)


@pytest.mark.parametrize("changes", [
    {"audience": "PLAYER", "audience_player_id": UUID(int=700)},
    {"audience": "INTERNAL"}, {"audience": "ADMIN"},
    {"audience": "unknown"}, {"audience_player_id": UUID(int=701)},
    {"game_id": UUID(int=999)}, {"state_version": 11},
    {"front_sequence": 11}, {"sequence": 2001},
    {"front_sequence": None}, {"front_sequence": 0},
    {"sequence": 0}, {"state_version": 0}, {"operation_index": -1},
    {"operation_type": "SET_ACTION_WINDOW", "event_type": "TURN_OPENED"},
    {"operation_type": "APPEND_PRIVATE_EVENT"}, {"schema_version": 2},
    {"schema_version": True}, {"state_version": True}, {"sequence": "1"},
    {"event_type": "ACTION_RESOLVED", "payload": {"target_player_id": str(UUID(int=701))}},
    {"event_type": "VOTE_RESOLVED", "payload": {
        "round": 1, "phase": "DAY_VOTE", "counts": [], "tied": False,
        "needs_revote": False, "ballots": ["synthetic-private"],
    }},
    {"event_type": "UNRECOGNIZED"}, {"payload": ["synthetic-private"]},
    {"payload": {}}, {"payload": {"player_id": str(UUID(int=999))}},
    {"payload": {"player_id": "not-a-uuid"}},
    {"event_type": "PLAYER_SPOKE", "payload": {"player_id": str(UUID(int=700)), "message": " "}},
    {"event_type": "PLAYER_SPOKE", "payload": {"player_id": str(UUID(int=700)), "message": "x" * 201}},
    {"event_type": "PLAYER_SPOKE", "payload": {"player_id": str(UUID(int=700)), "message": {"role": "MAFIA"}}},
    {"event_type": "GAME_BEGAN", "payload": {"message": "미승인 시작 안내"}},
    {"id": "not-an-event-id"}, {"created_at": "synthetic-invalid"},
    {"created_at": datetime(2026, 1, 2)},
])
def test_snapshot_discards_unapproved_or_malformed_events(changes: dict[str, Any]) -> None:
    """저장소가 잘못된 행을 반환해도 타인 정보와 snapshot 이후 이벤트를 공개하지 않는다."""

    invalid = _public_event_row(1)
    invalid.update(changes)
    valid = _public_event_row(2)
    reader, _, _ = _snapshot_reader([invalid, valid], game_changes=HISTORY_GAME_CHANGES)

    snapshot = reader.snapshot(USER_ID, GAME_ID)

    assert [event["event_id"] for event in snapshot["public_events"]] == [str(valid["id"])]


@pytest.mark.parametrize("event_type, data", [
    ("TURN_OPENED", {"player_id": str(UUID(int=701)), "cycle": 1, "prompt": None}),
    ("NIGHT_RESOLVED", {"round": 1, "killed_player_id": str(UUID(int=701))}),
    ("NIGHT_RESOLVED", {"round": 5, "killed_player_id": None}),
    ("PLAYER_EXECUTED", {"player_id": str(UUID(int=701)), "revealed_role": "CITIZEN"}),
    ("FAST_FORWARD_ENABLED", {"enabled": True}),
    ("GAME_SAVED", {"phase": "ROLE_REVEAL", "round": 0}),
    ("GAME_RESUMED", {"phase": "FINAL_DISCUSSION", "round": 5}),
    ("GAME_ENDED", {"winner": "MAFIA", "win_reason": "MAFIA_PARITY"}),
])
def test_snapshot_supports_existing_approved_event_fields_only(
    event_type: str, data: dict[str, Any],
) -> None:
    """기존 정본 이벤트도 허용한 필드만 복사하고 비공개·미승인 확장 내용은 버린다."""

    row = _public_event_row(1, event_type, {
        **data, "target_player_id": str(UUID(int=702)),
        "private": {"role": "MAFIA", "ballots": ["synthetic"]},
    })
    reader, _, _ = _snapshot_reader([row], game_changes=HISTORY_GAME_CHANGES)

    events = reader.snapshot(USER_ID, GAME_ID)["public_events"]

    assert len(events) == 1
    assert events[0]["data"] == data


@pytest.mark.parametrize("event_type, data", [
    ("TURN_OPENED", {"player_id": str(UUID(int=701)), "cycle": 2, "prompt": None}),
    ("TURN_OPENED", {"player_id": str(UUID(int=701)), "cycle": True, "prompt": None}),
    ("TURN_OPENED", {"player_id": str(UUID(int=701)), "cycle": 1, "prompt": "synthetic-private"}),
    ("TURN_OPENED", {"player_id": str(UUID(int=701)), "cycle": 1}),
    ("NIGHT_RESOLVED", {"round": 0, "killed_player_id": None}),
    ("NIGHT_RESOLVED", {"round": 6, "killed_player_id": None}),
    ("NIGHT_RESOLVED", {"round": 1, "killed_player_id": str(UUID(int=999))}),
    ("NIGHT_RESOLVED", {"round": 1}),
    ("PLAYER_EXECUTED", {"player_id": str(UUID(int=999)), "revealed_role": "MAFIA"}),
    ("PLAYER_EXECUTED", {"player_id": str(UUID(int=701)), "revealed_role": "UNKNOWN"}),
    ("FAST_FORWARD_ENABLED", {"enabled": False}),
    ("FAST_FORWARD_ENABLED", {"enabled": 1}),
    ("GAME_SAVED", {"phase": "INTERNAL", "round": 0}),
    ("GAME_RESUMED", {"phase": "DAY_DISCUSSION", "round": 6}),
    ("GAME_ENDED", {"winner": "UNKNOWN", "win_reason": "MAFIA_PARITY"}),
    ("GAME_ENDED", {"winner": "MAFIA", "win_reason": "UNKNOWN"}),
])
def test_snapshot_discards_invalid_approved_event_data(
    event_type: str, data: dict[str, Any],
) -> None:
    """알려진 event 이름이라도 필수 필드·enum·nullable·정수 계약을 어기면 제외한다."""

    reader, _, _ = _snapshot_reader(
        [_public_event_row(1, event_type, data)], game_changes=HISTORY_GAME_CHANGES,
    )

    assert reader.snapshot(USER_ID, GAME_ID)["public_events"] == []


def test_snapshot_restores_more_than_500_events_without_truncation() -> None:
    """sync의 페이지 크기로 snapshot 이력을 잘라 뒤쪽 발언을 잃지 않는지 확인한다."""

    rows = [_public_event_row(index) for index in range(1, 602)]
    reader, cursor, _ = _snapshot_reader(rows, game_changes=HISTORY_GAME_CHANGES)

    events = reader.snapshot(USER_ID, GAME_ID)["public_events"]

    assert [event["event_id"] for event in events] == [str(row["id"]) for row in rows]
    query = next(sql for sql, _ in cursor.statements if "FROM public.game_events" in sql)
    assert "LIMIT" not in query.upper()
    assert "ORDER BY sequence" in query
    assert "audience = 'PUBLIC'" in query
    assert "operation_type = 'APPEND_PUBLIC_EVENT'" in query
    assert "state_version <= %s" in query and "front_sequence <= %s" in query
    assert "sequence <= %s" in query


def test_snapshot_checks_ownership_before_reading_public_history() -> None:
    """비소유자에게 404를 반환할 때 이벤트와 player 테이블을 조회하지 않는다."""

    reader, cursor, connection = _snapshot_reader()
    cursor.one_rows = [None]

    with pytest.raises(ApiError) as error:
        reader.snapshot(UUID(int=999), GAME_ID)

    assert error.value.code == "GAME_NOT_FOUND"
    assert error.value.status_code == 404
    assert len(cursor.statements) == 1
    assert cursor.statements[0][1] == (GAME_ID, UUID(int=999))
    assert connection.rolled_back


def test_snapshot_event_read_failure_returns_safe_dependency_error() -> None:
    """이력 조회 장애를 빈 성공으로 숨기거나 DB 오류의 비공개 내용을 반환하지 않는다."""

    class FailingEvents:
        """조회 실패만 주입해 기존 API 오류 경계를 검사하는 저장소 대역."""

        def list_snapshot_public_events(self, *args: Any, **kwargs: Any) -> list[Any]:
            """오류 내용이 공개 응답으로 복사되지 않는지 확인한다."""

            raise RuntimeError("synthetic-private-storage-detail")

    reader, _, connection = _snapshot_reader(game_changes=HISTORY_GAME_CHANGES)
    reader._events = FailingEvents()

    with pytest.raises(ApiError) as error:
        reader.snapshot(USER_ID, GAME_ID)

    assert error.value.code == "DEPENDENCY_UNAVAILABLE"
    assert error.value.status_code == 503
    assert "synthetic-private" not in str(error.value)
    assert connection.rolled_back


def test_postgres_game_reader_lists_only_public_game_summary() -> None:
    """목록 조회는 복호화나 사용자 생성 없이 공개 요약만 반환하는지 확인한다."""

    now = datetime.now(UTC)
    cursor = FakeCursor(
        all_rows=[
            [
                {
                    "id": GAME_ID,
                    "status": "IN_PROGRESS",
                    "phase": "ROLE_REVEAL",
                    "round": 0,
                    "day_number": 1,
                    "state_version": 1,
                    "player_count": 6,
                    "winner": None,
                    "updated_at": now,
                    "scenario_title": "정전된 방송국",
                    "human_alive": True,
                }
            ]
        ]
    )
    connection = FakeConnection(cursor)
    reader = PostgresGameReadService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=GameStateKeyring(
            active_key_id="test-key-v1",
            keys={"test-key-v1": bytes(range(32))},
        ),
    )

    items = reader.list_games(USER_ID, status=None, limit=20)

    assert items == [
        {
            "game_id": str(GAME_ID),
            "status": "IN_PROGRESS",
            "phase": "ROLE_REVEAL",
            "round": 0,
            "day_number": 1,
            "state_version": 1,
            "scenario_title": "정전된 방송국",
            "player_count": 6,
            "human_alive": True,
            "winner": None,
            "can_resume": False,
            "updated_at": now.isoformat(),
        }
    ]
    assert "seed" not in cursor.statements[0][0].lower()
    assert connection.committed


def test_action_repository_preserves_window_and_submission_constraints() -> None:
    """행동 window와 첫 제출이 정본 테이블·제약에 맞는 SQL로 저장되는지 확인한다."""

    window_id = UUID("00000000-0000-4000-8000-000000000050")
    actor_id = UUID("00000000-0000-4000-8000-000000000051")
    target_id = UUID("00000000-0000-4000-8000-000000000052")
    deadline = datetime.now(UTC) + timedelta(seconds=30)
    cursor = FakeCursor(
        one_rows=[
            {"id": window_id, "status": "OPEN"},
            {"id": UUID("00000000-0000-4000-8000-000000000053")},
            {"id": window_id, "status": "PAUSED", "remaining_ms_on_save": 12_000},
            {"id": window_id, "status": "OPEN", "deadline_at": deadline},
        ]
    )
    repository = PostgresActionRepository()

    repository.cancel_current_window(cursor, game_id=GAME_ID)
    opened = repository.open_window(
        cursor,
        ActionWindowInsert(
            window_id=window_id,
            game_id=GAME_ID,
            window_kind="VOTE",
            phase="DAY_VOTE",
            round=1,
            cycle=1,
            turn_player_id=None,
            opened_state_version=3,
            deadline_at=deadline,
        ),
    )
    submitted = repository.insert_submission(
        cursor,
        ActionSubmissionInsert(
            game_id=GAME_ID,
            window_id=window_id,
            actor_player_id=actor_id,
            action_type="VOTE",
            target_player_id=target_id,
            message=None,
            source="HUMAN",
            observed_state_version=3,
        ),
    )
    paused = repository.pause_window(cursor, window_id=window_id, remaining_ms=12_000)
    resumed = repository.resume_window(cursor, window_id=window_id, deadline_at=deadline)

    assert opened["status"] == "OPEN"
    assert submitted["id"] == UUID("00000000-0000-4000-8000-000000000053")
    assert paused["status"] == "PAUSED"
    assert resumed["status"] == "OPEN"
    statements = "\n".join(sql for sql, _ in cursor.statements).lower()
    assert "public.action_windows" in statements
    assert "public.action_submissions" in statements
    assert str(window_id) not in statements

    with pytest.raises(ValueError, match="Speech submission"):
        repository.insert_submission(
            FakeCursor(),
            ActionSubmissionInsert(
                game_id=GAME_ID,
                window_id=window_id,
                actor_player_id=actor_id,
                action_type="SPEAK",
                target_player_id=target_id,
                message="잘못된 조합",
                source="HUMAN",
                observed_state_version=3,
            ),
        )


def test_begin_game_transaction_persists_state_window_events_outbox_and_receipt() -> None:
    """BEGIN_GAME은 하나의 commit에서 상태·window·operation·receipt를 모두 남긴다."""

    seed = b"begin-game-seed"
    state = GameEngine.new_game(
        [(UUID(int=index + 800), PlayerKind.HUMAN if index == 0 else PlayerKind.AI) for index in range(6)],
        game_id=GAME_ID,
        seed=seed,
    )
    keyring = GameStateKeyring(
        active_key_id="test-key-v1",
        keys={"test-key-v1": bytes(range(32))},
    )
    encrypted_seed = keyring.encrypt_seed(seed)
    now = datetime.now(UTC)
    game_row = {
        "id": GAME_ID,
        "owner_user_id": USER_ID,
        "status": "IN_PROGRESS",
        "phase": "ROLE_REVEAL",
        "round": 0,
        "day_number": 1,
        "state_version": 1,
        "player_count": 6,
        "seed_ciphertext": encrypted_seed.ciphertext,
        "seed_nonce": encrypted_seed.nonce,
        "seed_key_id": encrypted_seed.key_id,
        "updated_at": now,
    }
    player_rows = [
        {
            "id": player.player_id,
            "user_id": USER_ID if player.kind is PlayerKind.HUMAN else None,
            "kind": player.kind.value,
            "seat": player.seat,
            "display_name": f"플레이어 {player.seat}",
            "role": player.role.value,
            "alive": True,
        }
        for player in state.players
    ]
    second_event_id = UUID("00000000-0000-4000-8000-000000000061")
    cursor = FakeCursor(
        one_rows=[
            game_row,
            None,
            None,
            {"id": GAME_ID, "state_version": 2},
            {"front_sequence": 1},
            {"id": UUID("00000000-0000-4000-8000-000000000060"), "status": "OPEN"},
            {"sequence": 2},
            {"id": EVENT_ID},
            {"sequence": 3},
            {"id": second_event_id},
            {"id": 1, "game_event_id": EVENT_ID},
            {"id": 2, "game_event_id": second_event_id},
            {"id": IDEMPOTENCY_KEY},
        ],
        all_rows=[player_rows],
    )
    connection = FakeConnection(cursor)
    service = PostgresBeginGameService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=keyring,
    )

    result, replayed = service.begin(
        USER_ID,
        GAME_ID,
        GameCommandRequest(type="BEGIN_GAME", expected_state_version=1),
        IDEMPOTENCY_KEY,
    )

    assert not replayed
    assert result["accepted_state_version"] == 1
    assert result["result_state_version"] == 2
    assert connection.committed
    assert _last_user_action_flags(cursor) == [True]
    statements = "\n".join(sql for sql, _ in cursor.statements).lower()
    for table_name in (
        "games",
        "game_players",
        "action_windows",
        "game_events",
        "event_outbox",
        "command_receipts",
    ):
        assert table_name in statements


@pytest.mark.parametrize("observed_version", [1, 2, 99])
def test_save_game_transaction_pauses_window_and_persists_result(observed_version, monkeypatch) -> None:
    """SAVE_AND_EXIT은 열린 window를 멈추고 저장 결과 전체를 한 commit에 남긴다.

    실제 공용 DB를 변경하지 않기 위해 SQL 반환 순서만 재현한다. 이 검증은 게임
    상태가 SAVED인데 window가 OPEN으로 남는, 재개 시 시간이 잘못 흐를 수 있는
    불일치가 transaction 안에서 방지되는지를 확인한다.
    """

    seed = b"save-game-seed"
    state = GameEngine.new_game(
        [(UUID(int=index + 900), PlayerKind.HUMAN if index == 0 else PlayerKind.AI) for index in range(6)],
        game_id=GAME_ID,
        seed=seed,
    )
    GameEngine().begin_game(state)
    keyring = GameStateKeyring(
        active_key_id="test-key-v1",
        keys={"test-key-v1": bytes(range(32))},
    )
    encrypted_seed = keyring.encrypt_seed(seed)
    now = datetime.now(UTC)
    window_id = UUID("00000000-0000-4000-8000-000000000070")
    game_row = {
        "id": GAME_ID,
        "owner_user_id": USER_ID,
        "status": "IN_PROGRESS",
        "phase": state.phase.value,
        "round": state.round,
        "day_number": state.day_number,
        "state_version": state.state_version,
        "player_count": 6,
        "seed_ciphertext": encrypted_seed.ciphertext,
        "seed_nonce": encrypted_seed.nonce,
        "seed_key_id": encrypted_seed.key_id,
        "updated_at": now,
    }
    player_rows = [
        {
            "id": player.player_id,
            "user_id": USER_ID if player.kind is PlayerKind.HUMAN else None,
            "kind": player.kind.value,
            "seat": player.seat,
            "display_name": f"플레이어 {player.seat}",
            "role": player.role.value,
            "alive": True,
        }
        for player in state.players
    ]
    saved_event_id = UUID("00000000-0000-4000-8000-000000000071")
    cursor = FakeCursor(
        one_rows=[
            game_row,
            None,
            {"id": window_id, "window_kind": "SPEECH", "status": "OPEN"},
            {"id": GAME_ID, "state_version": 3},
            {"id": window_id, "status": "PAUSED", "remaining_ms_on_save": None},
            {"front_sequence": 2},
            {"sequence": 4},
            {"id": EVENT_ID},
            {"sequence": 5},
            {"id": saved_event_id},
            {"id": 3, "game_event_id": EVENT_ID},
            {"id": 4, "game_event_id": saved_event_id},
            {"id": IDEMPOTENCY_KEY},
        ],
        all_rows=[player_rows],
    )
    connection = FakeConnection(cursor)
    service = PostgresGameSaveService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=keyring,
    )

    from backend.app.services.game import lifecycle_service

    window_read = False
    original_current_window = service._actions.current_window

    def read_window(*args, **kwargs):
        nonlocal window_read
        window = original_current_window(*args, **kwargs)
        window_read = True
        return window

    class SaveClock(datetime):
        """게임과 window 잠금 뒤에만 저장 시각을 읽는지 검증하는 합성 시계다."""

        @classmethod
        def now(cls, tz=None):
            assert window_read
            return now

    monkeypatch.setattr(service._actions, "current_window", read_window)
    monkeypatch.setattr(lifecycle_service, "datetime", SaveClock)

    result, replayed = service.save(
        USER_ID,
        GAME_ID,
        GameCommandRequest(type="SAVE_AND_EXIT", expected_state_version=observed_version),
        IDEMPOTENCY_KEY,
    )

    assert not replayed
    assert result["accepted_state_version"] == 2
    assert result["result_state_version"] == 3
    assert connection.committed
    assert _last_user_action_flags(cursor) == [True]
    statements = "\n".join(sql for sql, _ in cursor.statements).lower()
    for table_name in (
        "games",
        "game_players",
        "action_windows",
        "game_events",
        "event_outbox",
        "command_receipts",
    ):
        assert table_name in statements
    # SPEECH는 별도 deadline이 없으므로 남은 시간을 만들지 않고 NULL을 유지한다.
    assert any(params == (None, window_id) for _, params in cursor.statements)


def test_resume_game_transaction_restores_timed_window_and_persists_result() -> None:
    """RESUME은 저장된 timed window에만 새 deadline을 만들고 한 commit에 기록한다."""

    seed = b"resume-game-seed"
    state = GameEngine.new_game(
        [(UUID(int=index + 1000), PlayerKind.HUMAN if index == 0 else PlayerKind.AI) for index in range(6)],
        game_id=GAME_ID,
        seed=seed,
    )
    keyring = GameStateKeyring(
        active_key_id="test-key-v1",
        keys={"test-key-v1": bytes(range(32))},
    )
    encrypted_seed = keyring.encrypt_seed(seed)
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    window_id = UUID("00000000-0000-4000-8000-000000000080")
    game_row = {
        "id": GAME_ID,
        "owner_user_id": USER_ID,
        "status": "SAVED",
        "phase": "DAY_VOTE",
        "round": 1,
        "day_number": 2,
        "state_version": 3,
        "player_count": 6,
        "seed_ciphertext": encrypted_seed.ciphertext,
        "seed_nonce": encrypted_seed.nonce,
        "seed_key_id": encrypted_seed.key_id,
        "updated_at": now,
    }
    player_rows = [
        {
            "id": player.player_id,
            "user_id": USER_ID if player.kind is PlayerKind.HUMAN else None,
            "kind": player.kind.value,
            "seat": player.seat,
            "display_name": f"플레이어 {player.seat}",
            "role": player.role.value,
            "alive": True,
        }
        for player in state.players
    ]
    resumed_event_id = UUID("00000000-0000-4000-8000-000000000081")
    cursor = FakeCursor(
        one_rows=[
            game_row,
            None,
            {
                "id": window_id,
                "window_kind": "VOTE",
                "status": "PAUSED",
                "remaining_ms_on_save": 20_000,
            },
            {"id": GAME_ID, "state_version": 4},
            {"id": window_id, "status": "OPEN"},
            {"front_sequence": 3},
            {"sequence": 6},
            {"id": EVENT_ID},
            {"sequence": 7},
            {"id": resumed_event_id},
            {"id": 5, "game_event_id": EVENT_ID},
            {"id": 6, "game_event_id": resumed_event_id},
            {"id": IDEMPOTENCY_KEY},
        ],
        all_rows=[player_rows],
    )
    connection = FakeConnection(cursor)
    service = PostgresGameResumeService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=keyring,
    )

    result, replayed = service.resume(
        USER_ID,
        GAME_ID,
        GameCommandRequest(type="RESUME", expected_state_version=3),
        IDEMPOTENCY_KEY,
        now=now,
    )

    assert not replayed
    assert result["accepted_state_version"] == 3
    assert result["result_state_version"] == 4
    assert connection.committed
    assert _last_user_action_flags(cursor) == [True]
    statements = "\n".join(sql for sql, _ in cursor.statements).lower()
    for table_name in (
        "games",
        "game_players",
        "action_windows",
        "game_events",
        "event_outbox",
        "command_receipts",
    ):
        assert table_name in statements
    assert any(
        params == (now + timedelta(milliseconds=20_000), window_id)
        for _, params in cursor.statements
    )


def test_discussion_speak_persists_submission_and_opens_next_turn() -> None:
    """SPEAK은 원장에 발언을 남기고 다음 좌석의 발언 window를 함께 연다."""

    seed = b"discussion-speak-seed"
    state = GameEngine.new_game(
        [(UUID(int=index + 1100), PlayerKind.HUMAN if index == 0 else PlayerKind.AI) for index in range(6)],
        game_id=GAME_ID,
        seed=seed,
    )
    GameEngine().begin_game(state)
    keyring = GameStateKeyring(
        active_key_id="test-key-v1",
        keys={"test-key-v1": bytes(range(32))},
    )
    encrypted_seed = keyring.encrypt_seed(seed)
    now = datetime(2026, 1, 3, 3, 4, 5, tzinfo=UTC)
    window_id = UUID("00000000-0000-4000-8000-000000000090")
    game_row = {
        "id": GAME_ID,
        "owner_user_id": USER_ID,
        "status": "IN_PROGRESS",
        "phase": "DAY_DISCUSSION",
        "round": 0,
        "day_number": 1,
        "state_version": 2,
        "player_count": 6,
        "seed_ciphertext": encrypted_seed.ciphertext,
        "seed_nonce": encrypted_seed.nonce,
        "seed_key_id": encrypted_seed.key_id,
        "updated_at": now,
    }
    player_rows = [
        {
            "id": player.player_id,
            "user_id": USER_ID if player.kind is PlayerKind.HUMAN else None,
            "kind": player.kind.value,
            "seat": player.seat,
            "display_name": f"플레이어 {player.seat}",
            "role": player.role.value,
            "alive": True,
        }
        for player in state.players
    ]
    next_window_id = uuid5_for_window(GAME_ID, 3)
    spoke_event_id = UUID("00000000-0000-4000-8000-000000000091")
    turn_event_id = UUID("00000000-0000-4000-8000-000000000092")
    cursor = FakeCursor(
        one_rows=[
            game_row,
            None,
            {
                "id": window_id,
                "window_kind": "SPEECH",
                "phase": "DAY_DISCUSSION",
                "cycle": 1,
                "status": "OPEN",
                "turn_player_id": state.players[0].player_id,
            },
            {"id": UUID("00000000-0000-4000-8000-000000000093")},
            {"id": GAME_ID, "state_version": 3},
            {"id": next_window_id, "status": "OPEN"},
            {"front_sequence": 4},
            {"sequence": 8},
            {"id": EVENT_ID},
            {"sequence": 9},
            {"id": spoke_event_id},
            {"sequence": 10},
            {"id": turn_event_id},
            {"id": 7, "game_event_id": EVENT_ID},
            {"id": 8, "game_event_id": spoke_event_id},
            {"id": 9, "game_event_id": turn_event_id},
            {"id": IDEMPOTENCY_KEY},
        ],
        all_rows=[player_rows, []],
    )
    connection = FakeConnection(cursor)
    service = PostgresDiscussionCommandService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=keyring,
    )

    result, replayed = service.submit(
        USER_ID,
        GAME_ID,
        GameCommandRequest(
            type="SPEAK",
            expected_state_version=2,
            window_id=window_id,
            message="  조정실   확인이 필요합니다.  ",
        ),
        IDEMPOTENCY_KEY,
        now=now,
    )

    assert not replayed
    assert result["command_type"] == "SPEAK"
    assert result["accepted_state_version"] == 2
    assert result["result_state_version"] == 3
    assert connection.committed
    assert _last_user_action_flags(cursor) == [True]
    statements = "\n".join(sql for sql, _ in cursor.statements).lower()
    for table_name in (
        "games",
        "game_players",
        "action_windows",
        "action_submissions",
        "game_events",
        "event_outbox",
        "command_receipts",
    ):
        assert table_name in statements
    # DB 원장에는 사용자가 보낸 원문이 아니라 엔진이 공백을 정규화한 발언만 남긴다.
    assert any(
        isinstance(params, tuple) and "조정실 확인이 필요합니다." in params
        for _, params in cursor.statements
    )
    assert any(
        isinstance(params, tuple) and next_window_id in params
        for _, params in cursor.statements
    )


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

    history = RedisConversationHistory(client, namespace="synthetic")
    history_key = history.key(str(GAME_ID))
    client.values[history_key] = "synthetic-public-history"
    assert history.delete(str(GAME_ID))
    assert history_key not in client.values

    stream = RedisEventStream(client, max_length=100)
    stream_id = stream.publish_batch(str(GAME_ID), 2, [str(EVENT_ID)])
    stream.publish_outbox_wakeup(7)
    assert stream_id == "1-0"
    assert client.xadd_calls[0][0] == f"mafia:v1:events:{GAME_ID}"
    assert client.published == [("mafia:v1:outbox:wakeup", "7")]


def _b5_action_service(*, phase="NIGHT_ACTION", human_role="DETECTIVE", roles=None,
                       submissions=None, deadline_offset=20, status="IN_PROGRESS", human_alive=True,
                       resolutions=None, round_number=1):
    """유료 API와 DB 없이 잠금·commit·원장 호출을 확인하는 B5 서비스 대역을 만든다."""

    from unittest.mock import Mock
    from backend.app.services.game.action_command import PostgresActionCommandService

    now = datetime(2026, 9, 7, tzinfo=UTC)
    roles = roles or [human_role, "MAFIA", "MAFIA", "DOCTOR", "CITIZEN", "CITIZEN", "CITIZEN"]
    players = [{"id": UUID(int=7100 + index), "seat": index + 1, "display_name": f"플레이어 {index + 1}",
                "kind": "HUMAN" if index == 0 else "AI", "user_id": USER_ID if index == 0 else None,
                "alive": human_alive if index == 0 else True, "role": role}
               for index, role in enumerate(roles)]
    window = {"id": UUID(int=7200), "window_kind": {"NIGHT_ACTION": "NIGHT", "DAY_VOTE": "VOTE", "REVOTE": "REVOTE", "FINAL_ACCUSATION": "FINAL_VOTE"}[phase],
              "phase": phase, "round": round_number, "cycle": 1, "status": "OPEN", "turn_player_id": None,
              "opened_state_version": 10, "deadline_at": now + timedelta(seconds=deadline_offset)}
    game = {"id": GAME_ID, "owner_user_id": USER_ID, "status": status, "phase": phase, "round": round_number,
            "day_number": 1 if phase == "NIGHT_ACTION" else 2, "state_version": 10, "player_count": len(players),
            "seed_ciphertext": b"synthetic", "seed_nonce": b"synthetic", "seed_key_id": "synthetic",
            "updated_at": now, "fast_forward_enabled": False}
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    service = PostgresActionCommandService(transactions=TransactionManager("postgresql://synthetic", connection_factory=lambda _: connection),
                                          keyring=Mock(), games=Mock(), players=Mock(), actions=Mock(), events=Mock(), outbox=Mock(), receipts=Mock())
    service._keyring.decrypt_seed.return_value = b"synthetic-b5-state"
    service._games.lock_game.return_value = game
    service._games.next_front_sequence.return_value = 5
    service._players.list_players.return_value = players
    service._actions.current_window.return_value = window
    service._actions.list_window_action_submissions.return_value = list(submissions or [])
    service._actions.list_resolutions.return_value = list(resolutions or [])
    service._events.append.side_effect = lambda *args, **kwargs: {"id": UUID(int=8000 + service._events.append.call_count)}
    service._receipts.find.return_value = None
    return service, game, players, window, now, connection


def _b5_submission(actor, target, action_type, source="HUMAN"):
    """외부 정보 없이 actor·대상·출처가 명확한 제출 fixture를 만든다."""

    return {"actor_player_id": UUID(int=7100 + actor), "target_player_id": UUID(int=7100 + target), "action_type": action_type, "source": source}


@pytest.mark.parametrize("phase,command", [("NIGHT_ACTION", "SUBMIT_NIGHT_ACTION"), ("DAY_VOTE", "SUBMIT_VOTE"), ("FINAL_ACCUSATION", "SUBMIT_VOTE")])
@pytest.mark.parametrize("offset", [0, -1])
def test_b5_rejects_submission_at_or_after_deadline(phase, command, offset):
    """마감과 같은 시각부터 인간 행동을 거부하고 원장·이벤트를 변경하지 않는다."""

    service, _, _, window, now, connection = _b5_action_service(phase=phase, deadline_offset=offset)
    with pytest.raises(ApiError) as error:
        service.submit(USER_ID, GAME_ID, GameCommandRequest(type=command, expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7101)), IDEMPOTENCY_KEY, now=now)
    assert error.value.code == "WINDOW_CLOSED"
    service._actions.insert_submission.assert_not_called()
    service._events.append.assert_not_called()
    assert connection.rolled_back


@pytest.mark.parametrize("phase", ["NIGHT_ACTION", "DAY_VOTE", "FINAL_ACCUSATION"])
def test_b5_expiry_rechecks_current_window_after_lock(phase):
    """worker 조회 뒤 열린 새 window가 아직 마감 전이면 아무 결과도 만들지 않는다."""

    service, _, _, _, now, _ = _b5_action_service(phase=phase)
    resolve = service.auto_resolve_expired_night if phase == "NIGHT_ACTION" else service.auto_resolve_expired_vote
    assert resolve(USER_ID, GAME_ID, now=now) is None
    service._actions.insert_resolution.assert_not_called()
    service._games.update_game_state.assert_not_called()


def test_b5_mixed_night_batch_keeps_human_choice_and_all_mafia():
    """인간 탐정 제출과 두 AI 마피아를 함께 해소하고 인간 조사만 private로 기록한다."""

    service, _, _, window, now, connection = _b5_action_service(submissions=[_b5_submission(0, 1, "INVESTIGATE")])
    actions = [{"player_id": UUID(int=7100 + actor), "target_player_id": UUID(int=7100 + target)} for actor, target in [(1, 4), (2, 4), (3, 4)]]
    result, replayed = service.submit_agent_night_actions(USER_ID, GAME_ID, actions, expected_state_version=10, window_id=window["id"], idempotency_key=IDEMPOTENCY_KEY, now=now)
    assert connection.committed and not replayed and result["result_state_version"] == 11
    payload = service._actions.insert_resolution.call_args.kwargs["payload"]
    assert len(payload["attack_choices"]) == 2
    assert payload["resolved_attack_target_player_id"] == str(UUID(int=7104))
    assert payload["killed_player_id"] is None
    assert payload["investigations"] == [{"actor_player_id": str(UUID(int=7100)), "target_player_id": str(UUID(int=7101)), "is_auto": False, "is_mafia": True}]
    private = [call.kwargs for call in service._events.append.call_args_list if call.kwargs["audience"] == "PLAYER"]
    assert len(private) == 1 and private[0]["audience_player_id"] == UUID(int=7100)
    assert private[0]["event_type"] == "INVESTIGATION_RESULT"
    public = [call.kwargs for call in service._events.append.call_args_list if call.kwargs["operation_type"] == "APPEND_PUBLIC_EVENT"]
    assert [event["event_type"] for event in public] == ["NIGHT_RESOLVED"]
    assert "target_player_id" not in json.dumps([event["payload"] for event in public])
    assert service._games.update_game_state.call_args.kwargs["user_action"] is False


def test_b5_partial_night_only_stores_choice_without_public_target():
    """밤 제출 한 건은 창을 닫거나 비공개 대상을 PUBLIC으로 기록하지 않는다."""

    service, _, _, window, now, _ = _b5_action_service()
    service.submit(USER_ID, GAME_ID, GameCommandRequest(type="SUBMIT_NIGHT_ACTION", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7101)), IDEMPOTENCY_KEY, now=now)
    service._actions.insert_resolution.assert_not_called()
    service._actions.open_window.assert_not_called()
    assert all(call.kwargs["operation_type"] != "APPEND_PUBLIC_EVENT" for call in service._events.append.call_args_list)
    assert service._games.update_game_state.call_args.kwargs["user_action"] is True


@pytest.mark.parametrize("existing_attack", [True, False])
def test_b5_expired_night_preserves_choices_and_faction_auto(existing_attack):
    """미제출 마피아의 가상 표를 만들지 않고 기존 공격 또는 진영 자동 공격을 기록한다."""

    submissions = [_b5_submission(0, 1, "INVESTIGATE")]
    if existing_attack:
        submissions.append(_b5_submission(1, 4, "ATTACK", "AGENT"))
    service, _, _, _, now, _ = _b5_action_service(submissions=submissions, deadline_offset=-1)
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    resolution = service._actions.insert_resolution.call_args.kwargs
    assert len(resolution["payload"]["attack_choices"]) == int(existing_attack)
    if existing_attack:
        assert resolution["target_player_id"] == UUID(int=7104)
    else:
        assert resolution["resolution_source"] == "FACTION_AUTO"
    assert resolution["rng_proof_hash"] is not None
    automatic = [call.args[1] for call in service._actions.insert_submission.call_args_list]
    assert [row.action_type for row in automatic] == ["PROTECT"]
    assert automatic[0].target_player_id != automatic[0].actor_player_id
    assert resolution["payload"]["investigations"][0]["target_player_id"] == str(UUID(int=7101))


@pytest.mark.parametrize("phase", ["DAY_VOTE", "FINAL_ACCUSATION"])
def test_b5_final_and_day_votes_wait_for_all_and_restore_prior_votes(phase):
    """인간 첫 표를 보존하고 마지막 AI batch가 모두 제출된 뒤에만 집계한다."""

    service, _, _, window, now, _ = _b5_action_service(phase=phase)
    command = GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7101))
    service.submit(USER_ID, GAME_ID, command, IDEMPOTENCY_KEY, now=now)
    service._actions.insert_resolution.assert_not_called()
    service, _, _, window, now, _ = _b5_action_service(phase=phase, submissions=[_b5_submission(0, 1, "VOTE")])
    actions = [{"player_id": UUID(int=7100 + actor), "target_player_id": UUID(int=7100 if actor == 1 else 7101)} for actor in range(1, 7)]
    service.submit_agent_votes(USER_ID, GAME_ID, actions, expected_state_version=10, window_id=window["id"], idempotency_key=IDEMPOTENCY_KEY, now=now)
    payload = service._actions.insert_resolution.call_args.kwargs["payload"]
    assert len(payload["ballots"]) == 7
    assert sum(item["vote_count"] for item in payload["counts"]) == 7
    assert service._players.update_eliminated_players.call_args.kwargs["phase"] == phase
    public = [call.kwargs["event_type"] for call in service._events.append.call_args_list if call.kwargs["operation_type"] == "APPEND_PUBLIC_EVENT"]
    assert public[:2] == ["VOTE_RESOLVED", "PLAYER_EXECUTED"]
    if phase == "FINAL_ACCUSATION":
        assert public[-1] == "GAME_ENDED"


@pytest.mark.parametrize("phase", ["DAY_VOTE", "FINAL_ACCUSATION"])
def test_b5_expired_vote_fills_only_missing_ballots(phase):
    """마감 시 이미 낸 표는 그대로 남고 나머지 표만 AUTO 원장에 저장된다."""

    service, _, _, _, now, _ = _b5_action_service(phase=phase, submissions=[_b5_submission(0, 1, "VOTE")], deadline_offset=0)
    service.auto_resolve_expired_vote(USER_ID, GAME_ID, now=now)
    payload = service._actions.insert_resolution.call_args.kwargs["payload"]
    assert payload["ballots"][0] == {"actor_player_id": str(UUID(int=7100)), "target_player_id": str(UUID(int=7101)), "is_auto": False}
    assert len(payload["ballots"]) == 7
    assert all(row["actor_player_id"] != row["target_player_id"] for row in payload["ballots"])
    assert sum(row["is_auto"] for row in payload["ballots"]) == 6
    assert service._actions.insert_submission.call_count == 6
    assert service._games.update_game_state.call_args.kwargs["user_action"] is False


@pytest.mark.parametrize("attackers", [[0], [1, 1]])
def test_b5_rejects_human_or_duplicate_actor_in_ai_batch(attackers):
    """AI batch가 인간 자격을 대리하거나 같은 actor를 중복 제출할 수 없다."""

    service, _, _, window, now, connection = _b5_action_service()
    actions = [{"player_id": UUID(int=7100 + actor), "target_player_id": UUID(int=7104)} for actor in attackers]
    with pytest.raises(ApiError) as error:
        service.submit_agent_night_actions(USER_ID, GAME_ID, actions, expected_state_version=10, window_id=window["id"], idempotency_key=IDEMPOTENCY_KEY, now=now)
    assert error.value.code in {"ACTOR_NOT_ALLOWED", "ACTION_ALREADY_SUBMITTED"}
    service._actions.insert_submission.assert_not_called()


def test_b5_fast_forward_persists_selection_without_advancing_phase():
    """관전 선택은 실제 DB bool만 켜고 생존자·round·window를 바꾸지 않는다."""

    service, game, _, _, _, connection = _b5_action_service(human_alive=False)
    service.fast_forward(USER_ID, GAME_ID, GameCommandRequest(type="FAST_FORWARD", expected_state_version=10), IDEMPOTENCY_KEY)
    update = service._games.update_game_state.call_args.kwargs
    assert update["state"].fast_forward_enabled is True
    assert update["user_action"] is True
    assert update["state"].phase.value == game["phase"] and update["state"].round == game["round"]
    service._actions.open_window.assert_not_called()
    service._actions.insert_resolution.assert_not_called()
    service._players.update_eliminated_players.assert_not_called()
    assert connection.committed


@pytest.mark.parametrize("human_alive,status", [(True, "IN_PROGRESS"), (False, "SAVED"), (False, "COMPLETED")])
def test_b5_fast_forward_rejects_alive_or_inactive_game(human_alive, status):
    """생존 상태와 저장·종료 상태는 빠른 진행 선택을 거부한다."""

    service, _, _, _, _, _ = _b5_action_service(human_alive=human_alive, status=status)
    with pytest.raises(ApiError) as error:
        service.fast_forward(USER_ID, GAME_ID, GameCommandRequest(type="FAST_FORWARD", expected_state_version=10), IDEMPOTENCY_KEY)
    assert error.value.code == "ACTION_NOT_ALLOWED"
    service._games.update_game_state.assert_not_called()


def _b5_tied_resolution():
    """유효한 첫날 투표 동률 원장을 후속 재투표 복원 테스트에 사용한다."""

    service, _, _, window, now, _ = _b5_action_service(phase="DAY_VOTE", roles=["DETECTIVE", "MAFIA", "DOCTOR", "CITIZEN", "CITIZEN", "CITIZEN"])
    # 0과 1이 세 표씩 받으며 모든 actor가 자기 자신을 피한다.
    ballots = [_b5_submission(actor, target, "VOTE", "HUMAN" if actor == 0 else "AGENT") for actor, target in enumerate([1, 0, 0, 0, 1, 1])]
    service._actions.list_window_action_submissions.return_value = ballots[:1]
    actions = [{"player_id": row["actor_player_id"], "target_player_id": row["target_player_id"]} for row in ballots[1:]]
    service.submit_agent_votes(USER_ID, GAME_ID, actions, expected_state_version=10, window_id=window["id"], idempotency_key=IDEMPOTENCY_KEY, now=now)
    payload = service._actions.insert_resolution.call_args.kwargs["payload"]
    assert payload["needs_revote"] is True
    assert service._actions.open_window.call_args.args[1].window_kind == "REVOTE"
    return {"game_id": GAME_ID, "resolution_type": "VOTE", "resolved_state_version": 9, "result_payload": payload}


def test_b5_revote_restores_only_tied_candidates_and_excludes_self():
    """확정 원장 복원 뒤 재투표 snapshot 후보와 엔진 거부 대상이 일치한다."""

    from backend.app.services.game.models import CanonicalGameRecord
    from backend.app.services.game.game_read_service import build_snapshot
    from backend.app.services.game.postgres_helpers import restore_locked_game

    resolution = _b5_tied_resolution()
    service, game, _, window, now, _ = _b5_action_service(phase="REVOTE", roles=["DETECTIVE", "MAFIA", "DOCTOR", "CITIZEN", "CITIZEN", "CITIZEN"], resolutions=[resolution])
    state, human = restore_locked_game(service, FakeCursor(), game)
    record = CanonicalGameRecord(state, {}, human, USER_ID, "synthetic", "synthetic", action_window=window)
    assert build_snapshot(record)["action_window"]["valid_targets"] == [{"player_id": str(UUID(int=7101)), "display_name": "플레이어 2"}]
    for target in [7100, 7102]:
        with pytest.raises(ApiError) as error:
            service.submit(USER_ID, GAME_ID, GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=target)), IDEMPOTENCY_KEY, now=now)
        assert error.value.code == "TARGET_INVALID"
    service._actions.insert_submission.assert_not_called()


def test_b5_revote_expiry_uses_original_candidates_and_preserves_round():
    """마감된 재투표의 자동 표는 원장 후보에만 투표하고 공개 round는 이전 낮 번호다."""

    resolution = _b5_tied_resolution()
    service, _, _, _, now, _ = _b5_action_service(phase="REVOTE", roles=["DETECTIVE", "MAFIA", "DOCTOR", "CITIZEN", "CITIZEN", "CITIZEN"], resolutions=[resolution], deadline_offset=0)
    service.auto_resolve_expired_vote(USER_ID, GAME_ID, now=now)
    payload = service._actions.insert_resolution.call_args.kwargs["payload"]
    assert {row["target_player_id"] for row in payload["ballots"]} <= {str(UUID(int=7100)), str(UUID(int=7101))}
    assert {row["target_player_id"] for row in payload["counts"]} == {str(UUID(int=7100)), str(UUID(int=7101))}
    assert payload["round"] == 1 and payload["phase"] == "REVOTE" and payload["needs_revote"] is False


def test_b5_missing_revote_ledger_fails_closed():
    """이전 확정 후보가 없으면 생존자 전체를 임의 재투표 후보로 만들지 않는다."""

    service, _, _, window, now, connection = _b5_action_service(phase="REVOTE")
    with pytest.raises(ApiError) as error:
        service.submit(USER_ID, GAME_ID, GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7101)), IDEMPOTENCY_KEY, now=now)
    assert error.value.code == "DEPENDENCY_UNAVAILABLE" and connection.rolled_back
    service._actions.insert_submission.assert_not_called()


def test_b5_resolution_failure_rolls_back_entire_action():
    """해소 원장 저장이 실패하면 player 상태·새 window·receipt를 확정하지 않는다."""

    service, _, _, _, now, connection = _b5_action_service(deadline_offset=0)
    service._actions.insert_resolution.side_effect = RuntimeError("synthetic failure")
    with pytest.raises(ApiError) as error:
        service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    assert error.value.code == "DEPENDENCY_UNAVAILABLE" and connection.rolled_back and not connection.committed
    service._players.update_eliminated_players.assert_not_called()
    service._games.update_game_state.assert_not_called()
    service._events.append.assert_not_called()
    service._receipts.insert.assert_not_called()


def test_b5_snapshot_restores_night_submission_and_actual_fast_forward_flag():
    """제출 복원은 인간 행동 버튼을 비활성화하고 사망만으로 빠른 진행을 켜지 않는다."""

    from backend.app.services.game.models import CanonicalGameRecord
    from backend.app.services.game.game_read_service import build_snapshot
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions

    service, game, _, window, _, _ = _b5_action_service()
    state, human = restore_locked_game(service, FakeCursor(), game)
    restore_action_submissions(state, [_b5_submission(0, 1, "INVESTIGATE")])
    record = CanonicalGameRecord(state, {}, human, USER_ID, "synthetic", "synthetic", action_window=window)
    snapshot = build_snapshot(record)
    assert snapshot["action_window"]["has_submitted"] is True
    assert "SUBMIT_NIGHT_ACTION" not in snapshot["legal_actions"]
    state.player_by_id[human].alive = False
    assert build_snapshot(record)["game"]["fast_forward_enabled"] is False
    state.fast_forward_enabled = True
    assert build_snapshot(record)["game"]["fast_forward_enabled"] is True
    assert "FAST_FORWARD" not in build_snapshot(record)["legal_actions"]


def test_b5_legacy_first_night_restores_as_round_one_and_result_keeps_round():
    """첫밤 round0/day1만 호환하고 해소·공개 사망 원장은 round1로 남긴다."""

    service, _, _, _, now, _ = _b5_action_service(round_number=0, deadline_offset=0)
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    assert service._actions.insert_resolution.call_args.kwargs["payload"]["round"] == 1
    assert service._games.update_game_state.call_args.kwargs["state"].round == 1
    assert service._players.update_eliminated_players.call_args.kwargs["round"] == 1
    assert service._players.update_eliminated_players.call_args.kwargs["phase"] == "NIGHT_ACTION"


def test_b5_result_reveals_only_committed_ledger_after_completion():
    """완료 전 원장 선택은 숨기고 완료 뒤 승인 필드만 복기하며 없는 과거는 비워 둔다."""

    from backend.app.models.enums import GameStatus
    from backend.app.services.game.result_service import build_result
    from backend.app.services.game.postgres_helpers import restore_locked_game

    service, game, _, _, now, _ = _b5_action_service(deadline_offset=0)
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    stored = service._actions.insert_resolution.call_args.kwargs
    row = {"game_id": GAME_ID, "resolved_state_version": 11, "resolution_type": "NIGHT", "result_payload": dict(stored["payload"], raw_model_response="synthetic-private")}
    state = service._games.update_game_state.call_args.kwargs["state"]
    assert build_result(state, resolutions=[row]) is None
    state.status = GameStatus.COMPLETED
    result = build_result(state, resolutions=[row], public_events=[{"event_id": str(EVENT_ID)}])
    assert len(result["nights"]) == 1 and result["votes"] == []
    assert result["nights"][0]["round"] == 1
    assert "synthetic-private" not in json.dumps(result)
    assert result["public_event_ids"] == [str(EVENT_ID)]
    assert build_result(state)["nights"] == []
    bad = dict(row, game_id=UUID(int=999))
    with pytest.raises(ValueError):
        build_result(state, resolutions=[bad])


@pytest.mark.parametrize("change", [{"audience_player_id": UUID(int=7101)}, {"game_id": UUID(int=99)}, {"audience": "PUBLIC"}, {"state_version": 11}, {"front_sequence": 6}, {"schema_version": True}, {"payload": {"round": 1, "target_player_id": str(UUID(int=7101)), "is_mafia": "false"}}])
def test_b5_private_snapshot_rejects_wrong_recipient_and_malformed_rows(change):
    """수신자·게임·버전·boolean 경계를 벗어난 조사 원문은 인간 snapshot에 나오지 않는다."""

    from backend.app.services.game.models import CanonicalGameRecord
    from backend.app.services.game.game_read_service import _snapshot_private_events
    from backend.app.services.game.postgres_helpers import restore_locked_game

    service, game, _, _, now, _ = _b5_action_service()
    state, human = restore_locked_game(service, FakeCursor(), game)
    record = CanonicalGameRecord(state, {}, human, USER_ID, "", "", front_sequence=5)
    row = {"id": EVENT_ID, "game_id": GAME_ID, "sequence": 10, "state_version": 10, "front_sequence": 5,
           "operation_index": 1, "operation_type": "APPEND_PRIVATE_EVENT", "audience": "PLAYER", "audience_player_id": human,
           "schema_version": 1, "created_at": now, "event_type": "INVESTIGATION_RESULT",
           "payload": {"round": 1, "target_player_id": str(UUID(int=7101)), "is_mafia": True}}
    assert len(_snapshot_private_events(record, [row], through_sequence=10)) == 1
    assert _snapshot_private_events(record, [dict(row, **change)], through_sequence=10) == []


def test_b5_ai_investigation_has_no_front_cursor_or_outbox_entry():
    """AI 조사 결과는 자기 PLAYER 원장에만 남고 인간 Front batch에는 들어가지 않는다."""

    service, _, _, _, now, _ = _b5_action_service(roles=["CITIZEN", "MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN", "CITIZEN"], deadline_offset=0)
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    private = [call.kwargs for call in service._events.append.call_args_list if call.kwargs["event_type"] == "INVESTIGATION_RESULT"]
    assert len(private) == 1 and private[0]["audience_player_id"] == UUID(int=7102)
    assert "front_sequence" not in private[0] and "operation_index" not in private[0]
    assert service._events.append.call_count == service._outbox.enqueue.call_count + 1


def test_b5_action_queries_include_all_mafia_and_all_vote_expiries():
    """두 번째 마피아 제외 조건 없이 조회하고 인간 무응답 최종 투표도 마감 대상으로 찾는다."""

    repository = PostgresActionRepository()
    cursor = FakeCursor()
    repository.list_ai_night_turns(cursor)
    sql, _ = cursor.statements[-1]
    assert "earlier_mafia" not in sql and "deadline_at > CURRENT_TIMESTAMP" in sql
    repository.list_ai_vote_turns(cursor)
    sql, _ = cursor.statements[-1]
    assert "window_kind <> 'FINAL_VOTE'" not in sql
    repository.list_expired_vote_windows(cursor, now=datetime.now(UTC))
    sql, _ = cursor.statements[-1]
    assert "('VOTE', 'REVOTE', 'FINAL_VOTE')" in sql and "human" not in sql


@pytest.mark.parametrize("phase", ["NIGHT_ACTION", "DAY_VOTE", "FINAL_ACCUSATION"])
def test_b5_agent_batch_cannot_submit_after_deadline(phase):
    """Agent batch도 인간 command와 같은 deadline을 적용해 늦은 응답을 버린다."""

    service, _, _, window, now, _ = _b5_action_service(phase=phase, deadline_offset=0)
    submit = service.submit_agent_night_actions if phase == "NIGHT_ACTION" else service.submit_agent_votes
    with pytest.raises(ApiError) as error:
        submit(USER_ID, GAME_ID, [{"player_id": UUID(int=7101), "target_player_id": UUID(int=7104)}], expected_state_version=10, window_id=window["id"], idempotency_key=IDEMPOTENCY_KEY, now=now)
    assert error.value.code == "WINDOW_CLOSED"
    service._actions.insert_submission.assert_not_called()


def test_b5_replay_still_checks_owner_and_never_reapplies_action():
    """기존 receipt를 재사용해도 소유권을 먼저 확인하고 원장을 중복 기록하지 않는다."""

    service, game, _, window, now, _ = _b5_action_service()
    payload = GameCommandRequest(type="SUBMIT_NIGHT_ACTION", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7101))
    first, _ = service.submit(USER_ID, GAME_ID, payload, IDEMPOTENCY_KEY, now=now)
    receipt = service._receipts.insert.call_args.kwargs
    service._receipts.find.return_value = receipt
    service._actions.insert_submission.reset_mock()
    second, replayed = service.submit(USER_ID, GAME_ID, payload, IDEMPOTENCY_KEY, now=now + timedelta(seconds=100))
    assert replayed and first == second
    service._actions.insert_submission.assert_not_called()
    with pytest.raises(ApiError) as error:
        service.submit(UUID(int=99), GAME_ID, payload, IDEMPOTENCY_KEY, now=now)
    assert error.value.code == "GAME_NOT_FOUND"
    with pytest.raises(ApiError) as error:
        service.submit(USER_ID, GAME_ID, payload.model_copy(update={"target_player_id": UUID(int=7102)}), IDEMPOTENCY_KEY, now=now)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize("change,expected", [({"expected_state_version": 9}, "STALE_STATE_VERSION"), ({"target_player_id": UUID(int=7100)}, "TARGET_INVALID")])
def test_b5_vote_rejects_stale_state_and_self_vote(change, expected):
    """오래된 버전과 자기 투표는 단일 제출도 같은 안전 경계에서 거부한다."""

    service, _, _, window, now, _ = _b5_action_service(phase="DAY_VOTE")
    payload = GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7101)).model_copy(update=change)
    with pytest.raises(ApiError) as error:
        service.submit(USER_ID, GAME_ID, payload, IDEMPOTENCY_KEY, now=now)
    assert error.value.code == expected
    service._actions.insert_submission.assert_not_called()


def test_b5_restored_submission_cannot_be_changed():
    """새 Idempotency-Key를 써도 이미 저장된 인간 밤 선택을 변경할 수 없다."""

    service, _, _, window, now, _ = _b5_action_service(submissions=[_b5_submission(0, 1, "INVESTIGATE")])
    with pytest.raises(ApiError) as error:
        service.submit(USER_ID, GAME_ID, GameCommandRequest(type="SUBMIT_NIGHT_ACTION", expected_state_version=10, window_id=window["id"], target_player_id=UUID(int=7102)), IDEMPOTENCY_KEY, now=now)
    assert error.value.code == "ACTION_ALREADY_SUBMITTED"
    service._actions.insert_submission.assert_not_called()


@pytest.mark.parametrize("change", [{"tied": 1}, {"needs_revote": "false"}, {"tied": False}, {"counts": [{"target_player_id": str(UUID(int=7100)), "vote_count": True}]}, {"counts": [{"target_player_id": str(UUID(int=999)), "vote_count": 6}]}])
def test_b5_vote_event_rejects_invalid_closed_union(change):
    """득표수와 동률의 boolean·UUID·정수 계약이 다른 event를 공개하지 않는다."""

    from backend.app.services.game.game_read_service import _public_event_data
    from backend.app.services.game.models import CanonicalGameRecord
    from backend.app.services.game.postgres_helpers import restore_locked_game

    resolution = _b5_tied_resolution()
    service, game, _, _, _, _ = _b5_action_service(phase="DAY_VOTE", roles=["DETECTIVE", "MAFIA", "DOCTOR", "CITIZEN", "CITIZEN", "CITIZEN"])
    state, human = restore_locked_game(service, FakeCursor(), game)
    record = CanonicalGameRecord(state, {}, human, USER_ID, "", "")
    payload = resolution["result_payload"]
    public = _public_event_data("VOTE_RESOLVED", payload, record)
    assert set(public) == {"round", "phase", "counts", "tied", "needs_revote"}
    with pytest.raises((ValueError, KeyError)):
        _public_event_data("VOTE_RESOLVED", dict(payload, **change), record)


@pytest.mark.parametrize("day,stored,expected", [(1, 0, 1), (2, 1, 2), (3, 2, 3), (5, 4, 5), (2, 2, 2), (5, 5, 5), (6, 5, 5)])
@pytest.mark.parametrize("status", ["IN_PROGRESS", "SAVED"])
def test_b5_legacy_night_round_normalization_preserves_inputs(day, stored, expected, status):
    """구형 밤 번호만 읽기·쓰기 복원에서 교정하며 기존 제출과 deadline은 유지한다."""

    from backend.app.services.game.game_read_service import initial_record_from_rows
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions

    service, game, _, window, _, _ = _b5_action_service(round_number=stored, status=status)
    game["day_number"] = day
    deadline = window["deadline_at"]
    state, human = restore_locked_game(service, FakeCursor(), game)
    restore_action_submissions(state, [_b5_submission(0, 1, "INVESTIGATE")])
    assert state.round == expected and state.state_version == 10
    assert state.night_actions[human].target_id == UUID(int=7101)
    assert game["round"] == stored and window["round"] == stored and window["deadline_at"] == deadline
    reader, cursor, _ = _snapshot_reader(game_changes={"phase": "NIGHT_ACTION", "round": stored, "day_number": day, "status": status})
    record = initial_record_from_rows(keyring=reader._keyring, game=cursor.one_rows[0], player_rows=cursor.all_rows[0])
    assert record.state.round == expected
