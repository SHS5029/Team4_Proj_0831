from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from backend.app.auth.models import ExternalIdentity, InactiveUserError
from backend.app.db.users import PostgresUserRepository

USER_ID = UUID("83d40f36-e835-4a1d-88db-e59b6920b739")


@dataclass(frozen=True)
class ExecutedStatement:
    sql: str
    params: object

    @property
    def normalized_sql(self) -> str:
        return " ".join(self.sql.lower().split())


@dataclass
class DatabaseScenario:
    existing_identity_user: Mapping[str, Any] | None = None
    user_by_id: Mapping[str, Any] | None = None
    returned_user: Mapping[str, Any] = field(
        default_factory=lambda: {
            "id": USER_ID,
            "email": "traveler@example.com",
            "display_name": "Team4 Traveler",
            "avatar_url": "https://images.example/avatar.png",
            "is_active": True,
        }
    )
    fail_identity_insert: bool = False


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self._next_row: Mapping[str, Any] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> FakeCursor:
        statement = ExecutedStatement(sql=str(sql), params=params)
        self.connection.statements.append(statement)
        normalized = statement.normalized_sql

        if self.connection.scenario.fail_identity_insert and re.search(
            r"insert\s+into\s+oauth_identities\b", normalized
        ):
            raise RuntimeError("simulated identity insert failure")

        if "select" in normalized and "from oauth_identities" in normalized:
            self._next_row = self.connection.scenario.existing_identity_user
        elif re.search(r"insert\s+into\s+users\b", normalized):
            self._next_row = self.connection.scenario.returned_user
        elif re.search(r"update\s+users\b", normalized):
            self._next_row = self.connection.scenario.returned_user
        elif "select" in normalized and "from users" in normalized:
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

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False

    def cursor(self, *args: object, **kwargs: object) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeConnectionFactory:
    def __init__(self, scenario: DatabaseScenario) -> None:
        self.connection = FakeConnection(scenario)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> FakeConnection:
        self.calls.append((args, kwargs))
        return self.connection


def _identity(
    *,
    subject: str = "google-subject-123",
    email: str = "traveler@example.com",
    email_verified: bool = True,
) -> ExternalIdentity:
    return ExternalIdentity(
        provider="google",
        provider_subject=subject,
        email=email,
        email_verified=email_verified,
        display_name="Team4 Traveler",
        avatar_url="https://images.example/avatar.png",
    )


def _repository(
    scenario: DatabaseScenario,
) -> tuple[PostgresUserRepository, FakeConnectionFactory]:
    factory = FakeConnectionFactory(scenario)
    repository = PostgresUserRepository(
        "postgresql://app:secret@db.internal:5432/Team4_Proj",
        connection_factory=factory,
    )
    return repository, factory


def _statement_matching(
    statements: Sequence[ExecutedStatement], pattern: str
) -> list[ExecutedStatement]:
    expression = re.compile(pattern)
    return [statement for statement in statements if expression.search(statement.normalized_sql)]


def _assert_values_are_bound(
    statements: Sequence[ExecutedStatement], values: Sequence[str]
) -> None:
    sql_text = "\n".join(statement.sql for statement in statements)
    params_text = "\n".join(repr(statement.params) for statement in statements)
    for value in values:
        assert value not in sql_text
        assert value in params_text


def test_relogin_updates_user_for_the_same_provider_and_subject() -> None:
    profile = _identity(email="new-address@example.com")
    existing = {
        "id": USER_ID,
        "email": "old-address@example.com",
        "display_name": "Old Name",
        "avatar_url": None,
        "is_active": True,
    }
    updated = {
        "id": USER_ID,
        "email": profile.email,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "is_active": True,
    }
    scenario = DatabaseScenario(existing_identity_user=existing, returned_user=updated)
    repository, factory = _repository(scenario)

    user = repository.upsert_identity(profile)

    statements = factory.connection.statements
    identity_lookup = _statement_matching(statements, r"from oauth_identities\b")
    assert identity_lookup
    assert "provider" in identity_lookup[0].normalized_sql
    assert "provider_subject" in identity_lookup[0].normalized_sql
    _assert_values_are_bound(
        statements,
        [profile.provider, profile.provider_subject, profile.email or ""],
    )
    assert not _statement_matching(statements, r"insert into users\b")
    assert _statement_matching(statements, r"update users\b")
    assert _statement_matching(statements, r"update oauth_identities\b")
    assert user.id == USER_ID
    assert user.email == profile.email
    assert factory.connection.committed
    assert not factory.connection.rolled_back


def test_inactive_existing_user_is_rejected_before_profile_updates() -> None:
    inactive_user = {
        "id": USER_ID,
        "email": "disabled@example.com",
        "display_name": "Disabled User",
        "avatar_url": None,
        "is_active": False,
    }
    scenario = DatabaseScenario(existing_identity_user=inactive_user)
    repository, factory = _repository(scenario)

    with pytest.raises(InactiveUserError):
        repository.upsert_identity(_identity())

    statements = factory.connection.statements
    assert _statement_matching(statements, r"from oauth_identities\b")
    assert not _statement_matching(statements, r"update users\b")
    assert not _statement_matching(statements, r"update oauth_identities\b")
    assert factory.connection.rolled_back
    assert not factory.connection.committed


def test_new_identity_creates_a_user_and_provider_identity() -> None:
    scenario = DatabaseScenario(existing_identity_user=None)
    repository, factory = _repository(scenario)
    profile = _identity()

    user = repository.upsert_identity(profile)

    statements = factory.connection.statements
    assert _statement_matching(statements, r"insert into users\b")
    identity_inserts = _statement_matching(statements, r"insert into oauth_identities\b")
    assert identity_inserts
    assert "provider_subject" in identity_inserts[0].normalized_sql
    _assert_values_are_bound(
        statements,
        [profile.provider, profile.provider_subject, profile.email or ""],
    )
    assert user.id == USER_ID
    assert user.email == profile.email
    assert factory.connection.committed


def test_unverified_identity_is_rejected_before_opening_a_connection() -> None:
    repository, factory = _repository(DatabaseScenario())
    profile = _identity(email_verified=False)

    with pytest.raises(ValueError, match="(?i)verified|verification"):
        repository.upsert_identity(profile)

    assert factory.calls == []


def test_matching_email_does_not_implicitly_link_a_different_identity() -> None:
    scenario = DatabaseScenario(existing_identity_user=None)
    repository, factory = _repository(scenario)
    profile = _identity(subject="a-brand-new-google-subject")

    repository.upsert_identity(profile)

    statements = factory.connection.statements
    assert _statement_matching(statements, r"insert into users\b")
    for statement in statements:
        if " where " not in f" {statement.normalized_sql} ":
            continue
        where_clause = statement.normalized_sql.split(" where ", 1)[1]
        assert not re.search(r"\b(?:provider_)?email\s*=", where_clause)


def test_transaction_rolls_back_when_identity_creation_fails() -> None:
    scenario = DatabaseScenario(existing_identity_user=None, fail_identity_insert=True)
    repository, factory = _repository(scenario)

    with pytest.raises(RuntimeError, match="simulated identity insert failure"):
        repository.upsert_identity(_identity())

    assert factory.connection.rolled_back
    assert not factory.connection.committed


@pytest.mark.parametrize("stored_user", [None, DatabaseScenario().returned_user])
def test_get_user_looks_up_by_bound_user_id(
    stored_user: Mapping[str, Any] | None,
) -> None:
    scenario = DatabaseScenario(user_by_id=stored_user)
    repository, factory = _repository(scenario)

    user = repository.get_user(USER_ID)

    statements = factory.connection.statements
    user_queries = _statement_matching(statements, r"select .* from users\b")
    assert user_queries
    assert str(USER_ID) not in user_queries[0].sql
    assert str(USER_ID) in repr(user_queries[0].params)
    if stored_user is None:
        assert user is None
    else:
        assert user is not None
        assert user.id == USER_ID
