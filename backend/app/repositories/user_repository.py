"""내부 사용자와 외부 OIDC 신원을 저장하는 PostgreSQL 저장소.

계정 연결의 유일한 기준은 정규화한 제공자 코드와 제공자가 발급한 불변
subject의 조합이다. 이메일은 변경·중복될 수 있는 프로필 속성이므로 조회나
자동 병합 키로 사용하지 않는다. 첫 로그인 생성과 재로그인 갱신은 한
트랜잭션에서 수행하며, advisory lock과 행 잠금으로 동시 요청을 직렬화한다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from backend.app.models.identity import ExternalIdentity, InactiveUserError, UserRecord


class CursorLike(Protocol):
    """저장소가 사용하는 psycopg 커서의 최소 인터페이스.

    실제 커서와 테스트용 대역이 같은 계약을 따르게 해 SQL 로직을 외부
    데이터베이스 없이 검증할 수 있게 한다.
    """

    def __enter__(self) -> CursorLike: ...

    def __exit__(self, *args: object) -> bool | None: ...

    def execute(self, query: str, params: object = None) -> CursorLike: ...

    def fetchone(self) -> Mapping[str, Any] | None: ...


class ConnectionLike(Protocol):
    """컨텍스트 관리와 커서 생성만 요구하는 연결 최소 인터페이스."""

    def __enter__(self) -> ConnectionLike: ...

    def __exit__(self, *args: object) -> bool | None: ...

    def cursor(self, *args: object, **kwargs: object) -> CursorLike: ...


# 기본값은 psycopg.connect지만 테스트에서는 동일한 호출 형태의 가짜 연결
# 팩터리를 주입할 수 있다.
ConnectionFactory = Callable[..., ConnectionLike]


class PostgresUserRepository:
    """변경 가능한 이메일과 계정 식별을 분리해 사용자를 저장하는 저장소.

    ``users``는 애플리케이션 프로필과 활성 상태를, ``oauth_identities``는
    ``(provider, provider_subject)``와 내부 사용자 UUID의 연결을 담당한다.
    두 테이블을 같은 트랜잭션에서 변경해 중간 상태가 커밋되지 않게 한다.
    """

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        """대상 DB URL과 선택적인 연결 팩터리를 저장한다.

        URL은 이미 ``Settings.effective_database_url``로 안전하게 재작성된 값을
        받아야 한다. 운영에서는 psycopg 연결을 사용하고, 테스트만 팩터리를
        주입해 트랜잭션과 SQL 호출을 관찰한다.
        """

        self._database_url = database_url
        self._connection_factory = connection_factory or cast(ConnectionFactory, psycopg.connect)

    @property
    def database_url(self) -> str:
        """인프라 배선 확인용 DB URL을 반환한다.

        비밀번호를 포함할 수 있으므로 호출자는 이 값을 사용자 응답, 예외,
        애플리케이션 로그에 기록해서는 안 된다.
        """

        return self._database_url

    def upsert_identity(self, profile: ExternalIdentity) -> UserRecord:
        """제공자 subject만으로 사용자를 선택해 생성하거나 프로필을 갱신한다.

        1. 외부 신원의 필수 값과 이메일 검증 상태를 검사한다.
        2. ``provider:subject`` 기반 트랜잭션 advisory lock을 얻는다.
        3. 기존 연결이 있으면 관련 identity와 user 행을 잠근다.
        4. 최초 로그인은 두 행을 함께 만들고, 재로그인은 mutable 프로필과
           마지막 로그인 시각만 갱신한다.
        5. 기존 사용자가 비활성이면 어떤 로그인 정보도 갱신하지 않고 전용
           예외를 발생시킨다.

        연결 컨텍스트는 정상 종료 시 커밋하고 예외 시 롤백하므로 사용자 행과
        외부 신원 행이 서로 다른 상태로 남지 않는다.
        """

        # 저장소 진입점에서 한 번 더 검증해, UI 이외의 호출자가 검증되지 않은
        # claim을 전달하더라도 DB 쓰기 전에 거부한다.
        profile.validate_for_login()
        provider = profile.normalized_provider
        subject = profile.provider_subject.strip()
        identity_lock_key = f"{provider}:{subject}"

        # psycopg 연결 컨텍스트 하나가 아래 조회와 쓰기 전체의 트랜잭션 경계다.
        with self._connection_factory(self._database_url) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                # 동일 외부 계정의 첫 로그인 요청이 동시에 들어오면 둘 다
                # "존재하지 않음"을 보고 사용자 행을 중복 생성할 수 있다.
                # 트랜잭션 범위 advisory lock은 provider와 subject가 같은 요청을
                # 직렬화하고 커밋/롤백 시 자동 해제된다.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (identity_lock_key,),
                )
                # 연결이 이미 존재하면 identity와 user 행을 함께 잠가, 활성 상태
                # 확인과 프로필 갱신 사이에 다른 트랜잭션이 값을 바꾸지 못하게 한다.
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
                    # 최초 로그인은 내부 사용자부터 만들고, 반환된 UUID로 외부
                    # 신원 연결을 생성한다. 둘 중 하나라도 실패하면 전체가 롤백된다.
                    cursor.execute(
                        """
                        INSERT INTO users (email, display_name, avatar_url, last_login_at)
                        VALUES (%s, %s, %s, NOW())
                        RETURNING id, email, display_name, avatar_url, is_active
                        """,
                        (profile.email, profile.display_name, profile.avatar_url),
                    )
                    stored_user = _required_row(cursor.fetchone(), "created user")
                    # DB의 UNIQUE(provider, provider_subject) 제약은 advisory lock과
                    # 별개로 데이터 무결성을 최종 보장한다. 토큰은 저장하지 않는다.
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
                    # 비활성 사용자는 로그인 시각이나 프로필조차 갱신하지 않는다.
                    # 전용 예외가 연결 컨텍스트를 빠져나가며 트랜잭션을 롤백한다.
                    if not bool(existing_user["is_active"]):
                        raise InactiveUserError("Local user account is inactive")
                    # 제공자 테이블에는 이번 로그인에서 받은 이메일과 검증 상태를
                    # 스냅샷으로 남기되, 이것을 계정 식별키로 사용하지 않는다.
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
                    # 사용자 화면용 mutable 프로필과 최근 로그인 시각을 같은
                    # 트랜잭션에서 갱신한다. 내부 UUID와 활성 상태는 유지된다.
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

        # 프로필 필드는 바로 위에서 기록한 입력값과 동일하다. 이를 명시적으로
        # 넘기면 드라이버/테스트 커서의 행 매핑 방식과 무관하게 반환 모델이
        # 실제로 저장한 최신 프로필을 나타낸다.
        return _row_to_user(stored_user, profile=profile)

    def get_user(self, user_id: UUID) -> UserRecord | None:
        """내부 UUID로 현재 사용자 프로필을 조회한다.

        외부 subject나 이메일로 암묵적인 계정 연결을 수행하지 않는다. 행이
        없으면 예외 대신 ``None``을 반환하며, 조회 트랜잭션은 연결 컨텍스트가
        정리한다.
        """

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
    """RETURNING 결과가 반드시 있어야 하는 쓰기 연산을 방어한다.

    예상과 달리 행이 없으면 불완전한 ``UserRecord``를 만들지 않고 예외를
    올린다. 호출 중인 연결 컨텍스트가 이 예외를 받아 트랜잭션을 롤백한다.
    """

    if row is None:
        raise RuntimeError(f"Database did not return the {operation}")
    return row


def _row_to_user(
    row: Mapping[str, Any],
    *,
    profile: ExternalIdentity | None = None,
) -> UserRecord:
    """DB 행을 UI에 노출할 불변 ``UserRecord``로 변환한다.

    psycopg 또는 테스트 대역이 UUID를 문자열로 반환해도 UUID 타입으로
    정규화한다. upsert 직후에는 ``profile``에 든 값이 방금 DB에 쓴 값이므로
    이를 사용하고, 일반 조회에서는 행의 프로필 열을 그대로 사용한다.
    """

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
