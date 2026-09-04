"""action_windows와 action_submissions의 PostgreSQL 저장소."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ActionWindowInsert:
    """현재 게임에서 열어 둘 행동 window의 확정 입력값."""

    window_id: UUID
    game_id: UUID
    window_kind: str
    phase: str
    round: int
    cycle: int
    turn_player_id: UUID | None
    opened_state_version: int
    deadline_at: datetime | None


@dataclass(frozen=True, slots=True)
class ActionSubmissionInsert:
    """인간·Agent·규칙 자동 행동의 공통 저장 입력값."""

    game_id: UUID
    window_id: UUID
    actor_player_id: UUID
    action_type: str
    target_player_id: UUID | None
    message: str | None
    source: str
    observed_state_version: int


class PostgresActionRepository:
    """행동 window와 제출 원장을 같은 transaction cursor에서 조작한다."""

    def current_window(self, cursor: Any, *, game_id: UUID) -> dict[str, Any] | None:
        """OPEN·PAUSED·RESOLVING 중인 유일한 window를 행 잠금과 함께 읽는다."""

        cursor.execute(
            """
            SELECT id, game_id, window_kind, phase, round, cycle, turn_player_id,
                   opened_state_version, status, opened_at, deadline_at,
                   remaining_ms_on_save, resolved_at
            FROM public.action_windows
            WHERE game_id = %s
              AND status IN ('OPEN', 'PAUSED', 'RESOLVING')
            FOR UPDATE
            """,
            (game_id,),
        )
        return cursor.fetchone()

    def active_window(self, cursor: Any, *, game_id: UUID) -> dict[str, Any] | None:
        """snapshot 조회용으로 활성 window를 잠금 없이 읽는다."""

        cursor.execute(
            """
            SELECT id, game_id, window_kind, phase, round, cycle, turn_player_id,
                   opened_state_version, status, opened_at, deadline_at,
                   remaining_ms_on_save, resolved_at
            FROM public.action_windows
            WHERE game_id = %s
              AND status IN ('OPEN', 'PAUSED', 'RESOLVING')
            """,
            (game_id,),
        )
        return cursor.fetchone()

    def list_discussion_submissions(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        phase: str,
        round: int,
        cycle: int,
    ) -> list[dict[str, Any]]:
        """현재 토론 순환에서 이미 확정된 SPEAK·PASS만 좌석 순서로 읽는다.

        게임 행에는 누가 이미 발언했는지 직접 저장하지 않는다. 따라서 서버가
        재시작해도 action_submissions 원장을 다시 읽어 다음 차례를 복원해야 한다.
        과거 날짜·다른 질문 순환의 발언을 섞으면 정상 발언을 중복으로 거부할 수 있어
        phase, round, cycle을 모두 조건으로 사용한다.
        """

        cursor.execute(
            """
            SELECT submission.actor_player_id, submission.action_type, submission.message
            FROM public.action_submissions AS submission
            JOIN public.action_windows AS window
              ON window.id = submission.window_id
             AND window.game_id = submission.game_id
            JOIN public.game_players AS player
              ON player.id = submission.actor_player_id
             AND player.game_id = submission.game_id
            WHERE submission.game_id = %s
              AND window.phase = %s
              AND window.round = %s
              AND window.cycle = %s
              AND submission.action_type IN ('SPEAK', 'PASS')
            ORDER BY player.seat, submission.submitted_at, submission.id
            """,
            (game_id, phase, round, cycle),
        )
        return [dict(row) for row in cursor.fetchall()]

    def cancel_current_window(self, cursor: Any, *, game_id: UUID) -> None:
        """다음 phase window를 열기 전에 기존 활성 window를 원자적으로 닫는다."""

        cursor.execute(
            """
            UPDATE public.action_windows
            SET status = 'CANCELLED', resolved_at = CURRENT_TIMESTAMP
            WHERE game_id = %s
              AND status IN ('OPEN', 'PAUSED', 'RESOLVING')
            """,
            (game_id,),
        )

    def open_window(self, cursor: Any, window: ActionWindowInsert) -> dict[str, Any]:
        """새로운 행동 단계의 단 하나의 OPEN window를 추가한다."""

        _validate_window(window)
        cursor.execute(
            """
            INSERT INTO public.action_windows (
                id, game_id, window_kind, phase, round, cycle, turn_player_id,
                opened_state_version, status, deadline_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'OPEN', %s)
            RETURNING id, game_id, window_kind, phase, round, cycle, turn_player_id,
                      opened_state_version, status, opened_at, deadline_at,
                      remaining_ms_on_save, resolved_at
            """,
            (
                window.window_id,
                window.game_id,
                window.window_kind,
                window.phase,
                window.round,
                window.cycle,
                window.turn_player_id,
                window.opened_state_version,
                window.deadline_at,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("행동 window 저장 결과가 반환되지 않았습니다.")
        return row

    def pause_window(
        self,
        cursor: Any,
        *,
        window_id: UUID,
        remaining_ms: int | None,
    ) -> dict[str, Any]:
        """저장 시 deadline을 제거하고 timed window의 시간만 보관한다.

        ``None``은 deadline이 원래 없는 발언 window를 뜻한다. 0과 구분해야 재개
        처리에서 발언을 즉시 만료된 timed window로 잘못 해석하지 않는다.
        """

        if remaining_ms is not None and remaining_ms < 0:
            raise ValueError("Window remaining time must not be negative")
        cursor.execute(
            """
            UPDATE public.action_windows
            SET status = 'PAUSED', deadline_at = NULL, remaining_ms_on_save = %s
            WHERE id = %s AND status = 'OPEN'
            RETURNING id, status, deadline_at, remaining_ms_on_save
            """,
            (remaining_ms, window_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("저장할 행동 window를 찾을 수 없습니다.")
        return row

    def resume_window(
        self,
        cursor: Any,
        *,
        window_id: UUID,
        deadline_at: datetime | None,
    ) -> dict[str, Any]:
        """재개 시 timed window에만 새 deadline을 설정하고 OPEN으로 바꾼다."""

        cursor.execute(
            """
            UPDATE public.action_windows
            SET status = 'OPEN', deadline_at = %s, remaining_ms_on_save = NULL
            WHERE id = %s AND status = 'PAUSED'
            RETURNING id, window_kind, status, deadline_at, remaining_ms_on_save
            """,
            (deadline_at, window_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("재개할 행동 window를 찾을 수 없습니다.")
        return row

    def insert_submission(self, cursor: Any, submission: ActionSubmissionInsert) -> dict[str, Any]:
        """검증이 끝난 첫 행동만 immutable 원장에 저장한다."""

        _validate_submission(submission)
        cursor.execute(
            """
            INSERT INTO public.action_submissions (
                game_id, window_id, actor_player_id, action_type, target_player_id,
                message, source, observed_state_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, game_id, window_id, actor_player_id, action_type,
                      target_player_id, message, source, observed_state_version,
                      submitted_at
            """,
            (
                submission.game_id,
                submission.window_id,
                submission.actor_player_id,
                submission.action_type,
                submission.target_player_id,
                submission.message,
                submission.source,
                submission.observed_state_version,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("행동 제출 저장 결과가 반환되지 않았습니다.")
        return row


def _validate_window(window: ActionWindowInsert) -> None:
    """DB CHECK보다 먼저 window 종류·phase·deadline 관계를 검증한다."""

    timed_kinds = {"NIGHT", "VOTE", "REVOTE", "FINAL_VOTE"}
    if window.window_kind not in {"SPEECH", *timed_kinds}:
        raise ValueError("Action window kind is invalid")
    if window.window_kind == "SPEECH":
        if window.turn_player_id is None or window.deadline_at is not None:
            raise ValueError("Speech window fields are invalid")
    elif window.turn_player_id is not None or window.deadline_at is None:
        raise ValueError("Timed action window fields are invalid")
    if window.opened_state_version < 1 or window.cycle < 1 or not 0 <= window.round <= 5:
        raise ValueError("Action window state is invalid")


def _validate_submission(submission: ActionSubmissionInsert) -> None:
    """행동 종류별 target·message 조합을 DB INSERT 전에 명확히 검사한다."""

    if submission.source not in {"HUMAN", "AGENT", "AUTO"}:
        raise ValueError("Action submission source is invalid")
    if submission.observed_state_version < 1:
        raise ValueError("Action submission state version is invalid")
    if submission.action_type == "SPEAK":
        if submission.target_player_id is not None or not submission.message:
            raise ValueError("Speech submission is invalid")
        return
    if submission.action_type == "PASS":
        if submission.target_player_id is not None or submission.message is not None:
            raise ValueError("Pass submission is invalid")
        return
    if submission.action_type in {"ATTACK", "INVESTIGATE", "PROTECT", "VOTE"}:
        if submission.target_player_id is None or submission.message is not None:
            raise ValueError("Targeted submission is invalid")
        return
    raise ValueError("Action submission type is invalid")
