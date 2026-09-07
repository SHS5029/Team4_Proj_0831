from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from backend.app.repositories.user_repository import PostgresUserRepository

USER_ID = UUID("83d40f36-e835-4a1d-88db-e59b6920b739")
CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
SEEN_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ExecutedStatement:
    sql: str
    params: object

    @property
    def normalized_sql(self) -> str:
        return " ".join(self.sql.lower().split())


@dataclass
class DatabaseScenario:
    returned_user: Mapping[str, Any] = field(
        default_factory=lambda: {
            "id": USER_ID,
            "created_at": CREATED_AT,
            "last_seen_at": SEEN_AT,
        }
    )
    user_by_id: Mapping[str, Any] | None = None


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self._next_row: Mapping[str, Any] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> "FakeCursor":
        statement = ExecutedStatement(sql=str(sql), params=params)
        self.connection.statements.append(statement)
        normalized = statement.normalized_sql
        if re.search(r"insert\s+into\s+users\b", normalized):
            self._next_row = self.connection.scenario.returned_user
        elif "select id, created_at, last_seen_at" in normalized:
            self._next_row = self.connection.scenario.user_by_id
        else:
            self._next_row = None
        return self

    def fetchone(self) -> Mapping[str, Any] | None:
        return self._next_row


class FakeConnection:
    def __init__(self, scenario: DatabaseScenario) -> None:
        self.scenario = scenario
        self.statements: list[ExecutedStatement] = []
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

    def cursor(self, *args: object, **kwargs: object) -> FakeCursor:
        return FakeCursor(self)


class FakeConnectionFactory:
    def __init__(self, scenario: DatabaseScenario) -> None:
        self.connection = FakeConnection(scenario)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> FakeConnection:
        self.calls.append((args, kwargs))
        return self.connection


def _repository(
    scenario: DatabaseScenario,
) -> tuple[PostgresUserRepository, FakeConnectionFactory]:
    factory = FakeConnectionFactory(scenario)
    repository = PostgresUserRepository(
        "postgresql://app:secret@db.internal:5432/Team4_Proj",
        connection_factory=factory,
    )
    return repository, factory


def _matching(
    statements: Sequence[ExecutedStatement], pattern: str
) -> list[ExecutedStatement]:
    expression = re.compile(pattern)
    return [statement for statement in statements if expression.search(statement.normalized_sql)]


def test_ensure_user_uses_exact_users_columns_and_is_idempotent() -> None:
    """사용자 행을 한 번만 만들고 재호출 때 last_seen_at만 갱신하는 SQL인지 확인한다."""

    repository, factory = _repository(DatabaseScenario())

    user = repository.ensure_user(USER_ID, now=SEEN_AT)

    inserts = _matching(factory.connection.statements, r"insert into users\b")
    assert len(inserts) == 1
    sql = inserts[0].normalized_sql
    assert "(id, created_at, last_seen_at)" in sql
    assert "on conflict (id) do update" in sql
    assert "set last_seen_at = excluded.last_seen_at" in sql
    assert USER_ID in inserts[0].params  # type: ignore[operator]
    assert user.id == USER_ID
    assert user.created_at == CREATED_AT
    assert factory.connection.committed
    assert not factory.connection.rolled_back


def test_ensure_user_does_not_use_a_database_id_default() -> None:
    """API가 받은 UUID를 INSERT 값으로 직접 전달하는지 확인한다."""

    repository, factory = _repository(DatabaseScenario())

    repository.ensure_user(USER_ID, now=SEEN_AT)

    insert = _matching(factory.connection.statements, r"insert into users\b")[0]
    assert insert.params == (USER_ID, SEEN_AT, SEEN_AT)


def test_get_user_only_reads_and_unknown_user_is_not_created() -> None:
    """조회 시 INSERT가 발생하지 않고 알 수 없는 UUID는 None이 된다."""

    repository, factory = _repository(DatabaseScenario(user_by_id=None))

    user = repository.get_user(USER_ID)

    assert user is None
    assert _matching(factory.connection.statements, r"select")
    assert not _matching(factory.connection.statements, r"insert into users\b")
    select = _matching(factory.connection.statements, r"select")[0]
    assert str(USER_ID) not in select.sql
    assert select.params == (USER_ID,)


def test_get_user_returns_only_canonical_users_columns() -> None:
    """사용자 프로필이나 외부 계정 없이 정본의 세 필드만 모델로 변환한다."""

    repository, _ = _repository(
        DatabaseScenario(
            user_by_id={
                "id": USER_ID,
                "created_at": CREATED_AT,
                "last_seen_at": SEEN_AT,
            }
        )
    )

    user = repository.get_user(USER_ID)

    assert user is not None
    assert user.id == USER_ID
    assert user.created_at == CREATED_AT
    assert user.last_seen_at == SEEN_AT
