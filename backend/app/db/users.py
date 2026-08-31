"""PostgreSQL repository for local users and external identities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from backend.app.auth.models import ExternalIdentity, InactiveUserError, UserRecord


class CursorLike(Protocol):
    def __enter__(self) -> CursorLike: ...

    def __exit__(self, *args: object) -> bool | None: ...

    def execute(self, query: str, params: object = None) -> CursorLike: ...

    def fetchone(self) -> Mapping[str, Any] | None: ...


class ConnectionLike(Protocol):
    def __enter__(self) -> ConnectionLike: ...

    def __exit__(self, *args: object) -> bool | None: ...

    def cursor(self, *args: object, **kwargs: object) -> CursorLike: ...


ConnectionFactory = Callable[..., ConnectionLike]


class PostgresUserRepository:
    """Persist users without coupling identity records to mutable email data."""

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory or cast(ConnectionFactory, psycopg.connect)

    @property
    def database_url(self) -> str:
        """Expose the URL only for infrastructure wiring; callers must not log it."""

        return self._database_url

    def upsert_identity(self, profile: ExternalIdentity) -> UserRecord:
        """Create or refresh a user selected exclusively by provider subject."""

        profile.validate_for_login()
        provider = profile.normalized_provider
        subject = profile.provider_subject.strip()
        identity_lock_key = f"{provider}:{subject}"

        with self._connection_factory(self._database_url) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                # Serialize first-login races for the same provider identity.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (identity_lock_key,),
                )
                cursor.execute(
                    """
                    SELECT
                        users.id,
                        users.email,
                        users.display_name,
                        users.avatar_url,
                        users.is_active
                    FROM oauth_identities
                    JOIN users ON users.id = oauth_identities.user_id
                    WHERE oauth_identities.provider = %s
                      AND oauth_identities.provider_subject = %s
                    FOR UPDATE OF oauth_identities, users
                    """,
                    (provider, subject),
                )
                existing_user = cursor.fetchone()

                if existing_user is None:
                    cursor.execute(
                        """
                        INSERT INTO users (email, display_name, avatar_url, last_login_at)
                        VALUES (%s, %s, %s, NOW())
                        RETURNING id, email, display_name, avatar_url, is_active
                        """,
                        (profile.email, profile.display_name, profile.avatar_url),
                    )
                    stored_user = _required_row(cursor.fetchone(), "created user")
                    cursor.execute(
                        """
                        INSERT INTO oauth_identities (
                            user_id,
                            provider,
                            provider_subject,
                            provider_email,
                            email_verified,
                            last_login_at
                        )
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            stored_user["id"],
                            provider,
                            subject,
                            profile.email,
                            profile.email_verified,
                        ),
                    )
                else:
                    if not bool(existing_user["is_active"]):
                        raise InactiveUserError("Local user account is inactive")
                    cursor.execute(
                        """
                        UPDATE oauth_identities
                        SET provider_email = %s,
                            email_verified = %s,
                            last_login_at = NOW(),
                            updated_at = NOW()
                        WHERE provider = %s
                          AND provider_subject = %s
                        """,
                        (profile.email, profile.email_verified, provider, subject),
                    )
                    cursor.execute(
                        """
                        UPDATE users
                        SET email = %s,
                            display_name = %s,
                            avatar_url = %s,
                            last_login_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, email, display_name, avatar_url, is_active
                        """,
                        (
                            profile.email,
                            profile.display_name,
                            profile.avatar_url,
                            existing_user["id"],
                        ),
                    )
                    stored_user = _required_row(cursor.fetchone(), "updated user")

        # Profile fields are the values written above.  Keeping them here also
        # makes the repository independent of cursor mapping implementations.
        return _row_to_user(stored_user, profile=profile)

    def get_user(self, user_id: UUID) -> UserRecord | None:
        with self._connection_factory(self._database_url) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, email, display_name, avatar_url, is_active
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                stored_user = cursor.fetchone()

        return _row_to_user(stored_user) if stored_user is not None else None


def _required_row(
    row: Mapping[str, Any] | None,
    operation: str,
) -> Mapping[str, Any]:
    if row is None:
        raise RuntimeError(f"Database did not return the {operation}")
    return row


def _row_to_user(
    row: Mapping[str, Any],
    *,
    profile: ExternalIdentity | None = None,
) -> UserRecord:
    user_id = row["id"]
    if not isinstance(user_id, UUID):
        user_id = UUID(str(user_id))
    return UserRecord(
        id=user_id,
        email=profile.email if profile is not None else row.get("email"),
        display_name=(
            profile.display_name if profile is not None else row.get("display_name")
        ),
        avatar_url=profile.avatar_url if profile is not None else row.get("avatar_url"),
        is_active=bool(row["is_active"]),
    )
