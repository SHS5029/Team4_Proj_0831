"""agent_jobs와 agent_capabilities의 PostgreSQL Repository."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from backend.app.infrastructure.transaction import TransactionManager

try:
    from psycopg.types.json import Jsonb
except ImportError:  # 테스트 환경에서 psycopg가 없어도 모듈 구조를 읽을 수 있게 한다.
    def Jsonb(value):  # type: ignore[misc]
        """psycopg가 없을 때 fake cursor에 원본 값을 전달한다."""

        return value


@dataclass(frozen=True, slots=True)
class AgentReservation:
    """DB에 RESERVED로 기록된 job과 fencing token이다."""

    job_id: UUID
    game_id: UUID
    player_id: UUID | None
    window_id: UUID
    job_kind: str
    state_version: int
    lease_token: UUID
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    """raw capability는 실행 중 메모리에만 두고 hash는 DB 저장용으로 쓴다."""

    raw_token: str
    token_hash: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """내부 API가 다시 확인해야 하는 capability·job의 공개 메타데이터다."""

    token_hash: str
    job_id: UUID | None
    game_id: UUID
    subject_type: str
    subject_player_id: UUID | None
    phase: str
    state_version: int
    window_id: UUID | None
    allowed_resources: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    expires_at: datetime
    revoked_at: datetime | None
    job_status: str | None
    job_lease_expires_at: datetime | None


class PostgresAgentRepository:
    """Agent 예약·capability의 SQL만 담당한다. 외부 호출은 orchestrator가 한다."""

    MAX_LEASE_SECONDS = 15
    MAX_CAPABILITY_SECONDS = 120

    def __init__(self, transaction_manager: TransactionManager | None = None) -> None:
        """짧은 Repository transaction을 열 연결 관리자를 받는다."""

        self.transaction_manager = transaction_manager

    def list_active_personas(
        self,
        cursor: Any,
        *,
        version: str,
    ) -> list[Mapping[str, Any]]:
        """게임 생성 시 AI에게 배정할 활성 persona 목록을 ID 순서로 읽는다.

        페르소나는 말투와 행동 성향만 바꾸며, 추리 능력 차이를 만들지 않는다.
        선택은 service의 seed 기반 RNG가 맡고 이 저장소는 승인된 후보만 반환한다.
        """

        cursor.execute(
            """
            SELECT id, version, display_name, speech_style, backstory,
                   parameters, content_hash
            FROM public.agent_personas
            WHERE version = %s
              AND active = TRUE
            ORDER BY id
            """,
            (version,),
        )
        return list(cursor.fetchall())

    def _connection_cursor(self):
        """공개 Repository 메서드가 사용할 짧은 DB transaction을 연다."""

        if self.transaction_manager is None:
            raise RuntimeError("TransactionManager is required for PostgresAgentRepository")
        connection_context = self.transaction_manager.transaction()
        connection = connection_context.__enter__()
        cursor_context = connection.cursor()
        cursor = (
            cursor_context.__enter__()
            if hasattr(cursor_context, "__enter__")
            else cursor_context
        )
        return connection_context, cursor_context, cursor

    @staticmethod
    def _close_connection_cursor(
        contexts: tuple[Any, Any, Any], error: BaseException | None = None
    ) -> None:
        """수동으로 연 cursor와 connection context를 예외 여부에 맞게 닫는다."""

        connection_context, cursor_context, _ = contexts
        if hasattr(cursor_context, "__exit__"):
            cursor_context.__exit__(type(error), error, error.__traceback__ if error else None)
        if error is None:
            connection_context.__exit__(None, None, None)
        else:
            connection_context.__exit__(type(error), error, error.__traceback__)

    def _run_transaction(self, operation: Callable[[Any], Any]) -> Any:
        """성공·실패와 무관하게 cursor와 connection을 반드시 닫는다.

        ``return``이 ``try`` 안에 있으면 Python의 ``else``가 실행되지 않아
        성공 transaction이 닫히지 않는 실수가 생길 수 있다. B7 내부 API가
        capability를 조회할 때도 같은 연결 생명주기를 사용하므로 결과를 변수에
        담은 뒤 정상 종료하는 형태로 고정한다.
        """

        contexts = self._connection_cursor()
        try:
            result = operation(contexts[2])
        except BaseException as error:
            self._close_connection_cursor(contexts, error)
            raise
        self._close_connection_cursor(contexts)
        return result

    def reserve_job(
        self,
        *,
        game_id: UUID,
        player_id: UUID | None,
        window_id: UUID,
        job_kind: str,
        state_version: int,
        window_deadline: datetime | None = None,
        now: datetime | None = None,
    ) -> AgentReservation | None:
        """중복 job은 만들지 않고, 새 예약만 최대 15초 lease로 만든다."""

        return self._run_transaction(
            lambda cursor: self._reserve_job(
                cursor,
                game_id=game_id,
                player_id=player_id,
                window_id=window_id,
                job_kind=job_kind,
                state_version=state_version,
                window_deadline=window_deadline,
                now=now,
            )
        )

    def _reserve_job(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        player_id: UUID | None,
        window_id: UUID,
        job_kind: str,
        state_version: int,
        window_deadline: datetime | None,
        now: datetime | None,
    ) -> AgentReservation | None:
        """예약 SQL을 실행하는 내부 cursor 버전이다."""

        current = now or datetime.now(UTC)
        lease_expires = current + timedelta(seconds=self.MAX_LEASE_SECONDS)
        if window_deadline is not None:
            lease_expires = min(lease_expires, window_deadline)
        if lease_expires <= current:
            return None
        job_id, lease_token = uuid4(), uuid4()
        # 이전 프로세스가 비정상 종료해 lease가 만료된 동일 작업은 새 예약을
        # 막지 않도록 terminal 상태로 회수한다. 정상적인 RESERVED 작업은
        # 건드리지 않아 동시에 실행 중인 Agent를 중복 처리하지 않는다.
        cursor.execute(
            """
            UPDATE agent_jobs
            SET status = 'FAILED', failure_code = 'LEASE_EXPIRED', completed_at = %s
            WHERE window_id = %s AND player_id IS NOT DISTINCT FROM %s
              AND job_kind = %s AND status = 'RESERVED'
              AND lease_expires_at <= %s
            """,
            (current, window_id, player_id, job_kind, current),
        )
        cursor.execute(
            """
            UPDATE agent_jobs
            SET status = 'RESERVED', reserved_state_version = %s,
                lease_token = %s, lease_expires_at = %s,
                normalized_proposal = NULL, failure_code = NULL, completed_at = NULL
            WHERE window_id = %s AND player_id IS NOT DISTINCT FROM %s
              AND job_kind = %s AND status IN ('FAILED', 'FALLBACK', 'STALE')
            RETURNING id, game_id, player_id, window_id, job_kind,
                      reserved_state_version, lease_token, lease_expires_at
            """,
            (state_version, lease_token, lease_expires, window_id, player_id, job_kind),
        )
        row = cursor.fetchone()
        if row is not None:
            return AgentReservation(
                job_id=row[0], game_id=row[1], player_id=row[2], window_id=row[3],
                job_kind=row[4], state_version=row[5], lease_token=row[6],
                lease_expires_at=row[7],
            )
        cursor.execute(
            """
            INSERT INTO agent_jobs (
                id, game_id, player_id, window_id, job_kind,
                reserved_state_version, status, lease_token, lease_expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'RESERVED', %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id, game_id, player_id, window_id, job_kind,
                      reserved_state_version, lease_token, lease_expires_at
            """,
            (
                job_id,
                game_id,
                player_id,
                window_id,
                job_kind,
                state_version,
                lease_token,
                lease_expires,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AgentReservation(
            job_id=row[0], game_id=row[1], player_id=row[2], window_id=row[3],
            job_kind=row[4], state_version=row[5], lease_token=row[6], lease_expires_at=row[7],
        )

    def issue_capability(
        self,
        reservation: AgentReservation,
        *,
        subject_type: str,
        phase: str,
        allowed_resources: list[str],
        allowed_tools: list[str],
        now: datetime | None = None,
    ) -> CapabilityGrant:
        """32-byte opaque token을 발급하고 token hash만 DB에 저장한다."""

        return self._run_transaction(
            lambda cursor: self._issue_capability(
                cursor,
                reservation,
                subject_type=subject_type,
                phase=phase,
                allowed_resources=allowed_resources,
                allowed_tools=allowed_tools,
                now=now,
            )
        )

    def _issue_capability(
        self,
        cursor: Any,
        reservation: AgentReservation,
        *,
        subject_type: str,
        phase: str,
        allowed_resources: list[str],
        allowed_tools: list[str],
        now: datetime | None,
    ) -> CapabilityGrant:
        """capability INSERT를 실행하는 내부 cursor 버전이다."""

        current = now or datetime.now(UTC)
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("ascii")).hexdigest()
        expires = min(
            current + timedelta(seconds=self.MAX_CAPABILITY_SECONDS),
            reservation.lease_expires_at,
        )
        cursor.execute(
            """
            INSERT INTO agent_capabilities (
                token_hash, game_id, subject_type, subject_player_id, phase,
                state_version, window_id, allowed_resources, allowed_tools,
                expires_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                token_hash, reservation.game_id, subject_type, reservation.player_id,
                phase, reservation.state_version, reservation.window_id,
                Jsonb(allowed_resources), Jsonb(allowed_tools), expires, current,
            ),
        )
        return CapabilityGrant(raw_token=raw, token_hash=token_hash, expires_at=expires)

    def complete_job(
        self,
        reservation: AgentReservation,
        *,
        status: str,
        normalized_proposal: dict[str, Any] | None,
        failure_code: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """lease token과 만료 시각을 함께 검사해 늦은 결과를 차단한다."""

        return self._run_transaction(
            lambda cursor: self._complete_job(
                cursor,
                reservation,
                status=status,
                normalized_proposal=normalized_proposal,
                failure_code=failure_code,
                now=now,
            )
        )

    def _complete_job(
        self,
        cursor: Any,
        reservation: AgentReservation,
        *,
        status: str,
        normalized_proposal: dict[str, Any] | None,
        failure_code: str | None,
        now: datetime | None,
    ) -> bool:
        """job UPDATE를 실행하는 내부 cursor 버전이다."""

        completed_at = now or datetime.now(UTC)
        cursor.execute(
            """
            UPDATE agent_jobs
            SET status = %s, normalized_proposal = %s, failure_code = %s,
                completed_at = %s
            WHERE id = %s AND lease_token = %s AND status = 'RESERVED'
              AND lease_expires_at > %s
            RETURNING id
            """,
            (
                status, Jsonb(normalized_proposal) if normalized_proposal is not None else None,
                failure_code,
                completed_at,
                reservation.job_id,
                reservation.lease_token,
                completed_at,
            ),
        )
        return cursor.fetchone() is not None

    def revoke_capability(self, token_hash: str, *, now: datetime | None = None) -> None:
        """job 종료 시 capability를 폐기한다. raw token은 SQL에 전달하지 않는다."""

        self._run_transaction(
            lambda cursor: self._revoke_capability(cursor, token_hash, now=now)
        )

    def _revoke_capability(
        self, cursor: Any, token_hash: str, *, now: datetime | None = None
    ) -> None:
        """capability UPDATE를 실행하는 내부 cursor 버전이다."""

        cursor.execute(
            """
            UPDATE agent_capabilities
            SET revoked_at = %s
            WHERE token_hash = %s AND revoked_at IS NULL
            """,
            (now or datetime.now(UTC), token_hash),
        )

    def find_capability(self, token_hash: str) -> CapabilityRecord | None:
        """token hash에 연결된 capability와 RESERVED job 메타데이터를 조회한다.

        현재 저장소 migration에는 capability의 job FK가 없으므로 game·window·
        subject·예약 version을 함께 맞춰 가장 최근 job을 연결한다. 향후 정본
        schema에 agent_job_id가 추가되면 이 조회의 join을 직접 FK로 좁힌다.
        """

        return self._run_transaction(lambda cursor: self._find_capability(cursor, token_hash))

    def _find_capability(self, cursor: Any, token_hash: str) -> CapabilityRecord | None:
        """capability 조회 SQL과 tuple row 변환을 담당한다."""

        cursor.execute(
            """
            SELECT c.token_hash, j.id, c.game_id, c.subject_type,
                   c.subject_player_id, c.phase, c.state_version, c.window_id,
                   c.allowed_resources, c.allowed_tools, c.expires_at, c.revoked_at,
                   j.status, j.lease_expires_at
            FROM public.agent_capabilities AS c
            LEFT JOIN public.agent_jobs AS j
              ON j.game_id = c.game_id
             AND j.window_id = c.window_id
             AND j.reserved_state_version = c.state_version
             AND (
                   (c.subject_type = 'AI_PLAYER' AND j.player_id = c.subject_player_id)
                   OR (c.subject_type = 'GM' AND j.player_id IS NULL)
                 )
            WHERE c.token_hash = %s
            ORDER BY j.created_at DESC NULLS LAST
            LIMIT 1
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return CapabilityRecord(
            token_hash=row[0],
            job_id=row[1],
            game_id=row[2],
            subject_type=row[3],
            subject_player_id=row[4],
            phase=row[5],
            state_version=int(row[6]),
            window_id=row[7],
            allowed_resources=tuple(row[8]),
            allowed_tools=tuple(row[9]),
            expires_at=row[10],
            revoked_at=row[11],
            job_status=row[12],
            job_lease_expires_at=row[13],
        )
