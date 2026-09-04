"""내부 HMAC·MCP bootstrap nonce 영속 저장소."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.app.infrastructure.transaction import TransactionManager


class NonceRepository(Protocol):
    """nonce를 한 번만 소비하기 위해 필요한 최소 저장소 계약."""

    def consume(
        self,
        *,
        scope: str,
        nonce: UUID,
        request_hash: str,
        expires_at: datetime,
    ) -> bool: ...


class PostgresNonceRepository:
    """Redis가 비워져도 PostgreSQL unique key로 replay를 막는 저장소."""

    def __init__(self, transaction_manager: TransactionManager) -> None:
        self._transaction_manager = transaction_manager

    def consume(
        self,
        *,
        scope: str,
        nonce: UUID,
        request_hash: str,
        expires_at: datetime,
    ) -> bool:
        """nonce를 먼저 INSERT하고 성공 여부만 반환한다.

        INSERT가 성공한 요청만 내부 handler로 진행해야 한다. 이미 존재하는
        nonce는 PostgreSQL의 복합 primary key 충돌로 처리하며, 오류 원문은
        HTTP 응답에 전달하지 않는다.
        """

        if scope not in {"ENGINE_HMAC", "MCP_BOOTSTRAP"}:
            raise ValueError("허용되지 않은 nonce scope입니다.")
        if len(request_hash) != 64:
            raise ValueError("nonce request hash 형식이 올바르지 않습니다.")
        with self._transaction_manager.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.internal_request_nonces
                        (scope, nonce, request_hash, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (scope, nonce) DO NOTHING
                    RETURNING scope
                    """,
                    (scope, nonce, request_hash, expires_at),
                )
                return cursor.fetchone() is not None


class InMemoryNonceRepository:
    """실제 DB 없이 B7 보안 경계를 검증하는 테스트용 nonce 원장."""

    def __init__(self) -> None:
        self._consumed: set[tuple[str, UUID]] = set()

    def consume(
        self,
        *,
        scope: str,
        nonce: UUID,
        request_hash: str,
        expires_at: datetime,
    ) -> bool:
        """프로세스 메모리에서 primary key와 같은 중복 차단 동작을 흉내 낸다."""

        del request_hash, expires_at
        key = (scope, nonce)
        if key in self._consumed:
            return False
        self._consumed.add(key)
        return True
