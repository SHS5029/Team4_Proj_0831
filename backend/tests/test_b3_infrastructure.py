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
from backend.app.infrastructure.redis.cache import RedisPublicCache
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


def test_postgres_game_reader_projects_owned_initial_snapshot_without_role_leak() -> None:
    """DB game·player·fact 행에서 인간 본인 정보만 포함한 최초 snapshot을 복원한다."""

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
    cursor = FakeCursor(
        one_rows=[game_row],
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
        ],
    )
    connection = FakeConnection(cursor)
    reader = PostgresGameReadService(
        transactions=TransactionManager(
            "postgresql://synthetic",
            connection_factory=lambda _: connection,
        ),
        keyring=keyring,
    )

    snapshot = reader.snapshot(USER_ID, GAME_ID)

    assert snapshot["game"]["game_id"] == str(GAME_ID)
    assert snapshot["game"]["phase"] == "ROLE_REVEAL"
    assert len(snapshot["players"]) == 6
    assert all("role" not in player for player in snapshot["players"])
    assert snapshot["me"]["role"] in {"MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN"}
    assert snapshot["me"]["alibi"] == "좌석 1은 스튜디오에 있었다."
    assert snapshot["me"]["observation"] == "좌석 1은 조정실 쪽을 보았다."
    assert connection.committed


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


def test_save_game_transaction_pauses_window_and_persists_result() -> None:
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

    result, replayed = service.save(
        USER_ID,
        GAME_ID,
        GameCommandRequest(type="SAVE_AND_EXIT", expected_state_version=2),
        IDEMPOTENCY_KEY,
        now=now,
    )

    assert not replayed
    assert result["accepted_state_version"] == 2
    assert result["result_state_version"] == 3
    assert connection.committed
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

    stream = RedisEventStream(client, max_length=100)
    stream_id = stream.publish_batch(str(GAME_ID), 2, [str(EVENT_ID)])
    stream.publish_outbox_wakeup(7)
    assert stream_id == "1-0"
    assert client.xadd_calls[0][0] == f"mafia:v1:events:{GAME_ID}"
    assert client.published == [("mafia:v1:outbox:wakeup", "7")]
