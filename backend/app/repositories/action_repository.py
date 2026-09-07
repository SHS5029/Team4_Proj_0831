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

    def list_ai_speech_turns(self, cursor: Any) -> list[dict[str, Any]]:
        """서버 재시작 후에도 처리할 수 있는 열린 AI 발언 차례를 조회한다."""

        cursor.execute(
            """
            SELECT games.id AS game_id, games.owner_user_id,
                   action_window.id AS window_id,
                   action_window.turn_player_id,
                   games.state_version
            FROM public.games AS games
            JOIN public.action_windows AS action_window
              ON action_window.game_id = games.id
             AND action_window.status = 'OPEN'
             AND action_window.window_kind = 'SPEECH'
            JOIN public.game_players AS player
              ON player.game_id = games.id
             AND player.id = action_window.turn_player_id
             AND player.kind = 'AI'
            WHERE games.status = 'IN_PROGRESS'
            ORDER BY action_window.opened_at, games.id
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_ai_night_turns(self, cursor: Any) -> list[dict[str, Any]]:
        """required 밤 역할이 모두 AI인 게임의 actor 목록을 조회한다."""

        cursor.execute(
            """
            SELECT games.id AS game_id, games.owner_user_id,
                   action_window.id AS window_id, games.state_version,
                   player.id AS player_id
            FROM public.games AS games
            JOIN public.action_windows AS action_window
              ON action_window.game_id = games.id
             AND action_window.status = 'OPEN'
             AND action_window.window_kind = 'NIGHT'
            JOIN public.game_players AS player
              ON player.game_id = games.id
             AND player.kind = 'AI'
             AND player.role IN ('MAFIA', 'DETECTIVE', 'DOCTOR')
             AND player.alive = TRUE
            WHERE games.status = 'IN_PROGRESS'
              AND (player.role <> 'MAFIA' OR NOT EXISTS (
                  SELECT 1 FROM public.game_players AS earlier_mafia
                  WHERE earlier_mafia.game_id = games.id
                    AND earlier_mafia.role = 'MAFIA'
                    AND earlier_mafia.alive = TRUE
                    AND earlier_mafia.seat < player.seat
              ))
              AND NOT EXISTS (
                  SELECT 1 FROM public.action_submissions AS existing
                  WHERE existing.window_id = action_window.id
                    AND existing.actor_player_id = player.id
              )
              AND (
                  NOT EXISTS (
                      SELECT 1 FROM public.game_players AS human_required
                      WHERE human_required.game_id = games.id
                        AND human_required.kind = 'HUMAN'
                        AND human_required.role IN ('MAFIA', 'DETECTIVE', 'DOCTOR')
                        AND human_required.alive = TRUE
                  )
                  OR EXISTS (
                      SELECT 1 FROM public.action_submissions AS human_action
                      JOIN public.game_players AS human_actor
                        ON human_actor.id = human_action.actor_player_id
                       AND human_actor.game_id = games.id
                      WHERE human_action.window_id = action_window.id
                        AND human_actor.kind = 'HUMAN'
                  )
              )
            ORDER BY action_window.opened_at, games.id, player.seat
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_expired_night_windows(self, cursor: Any, *, now: Any) -> list[dict[str, Any]]:
        """deadline이 지난 열린 밤 window를 자동 해소 worker에 전달한다.

        인간 탐정·의사·마피아가 무응답이어도 정본의 결정적 자동 선택 규칙으로
        밤을 종료해야 한다. 이 조회는 아직 OPEN이고 deadline이 지난 게임만
        반환해 worker가 이미 해소된 window를 중복 처리하지 않도록 한다.
        """

        cursor.execute(
            """
            SELECT games.id AS game_id, games.owner_user_id,
                   action_window.id AS window_id, games.state_version
            FROM public.games AS games
            JOIN public.action_windows AS action_window
              ON action_window.game_id = games.id
             AND action_window.status = 'OPEN'
             AND action_window.window_kind = 'NIGHT'
             AND action_window.deadline_at <= %s
            WHERE games.status = 'IN_PROGRESS'
            ORDER BY action_window.deadline_at, games.id
            """,
            (now,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_ai_vote_turns(self, cursor: Any) -> list[dict[str, Any]]:
        """현재 투표 window에서 아직 표를 내지 않은 AI actor를 조회한다.

        인간이 생존한 게임은 인간 표가 먼저 원장에 기록된 경우에만 AI 표를
        깨운다. 인간 표가 없는 상태에서 AI가 먼저 진행하면 투표가 조기 해소될
        수 있으므로 이 조건을 조회 계층에서 함께 보장한다.
        """

        cursor.execute(
            """
            SELECT games.id AS game_id, games.owner_user_id,
                   action_window.id AS window_id, action_window.phase,
                   games.state_version,
                   player.id AS player_id
            FROM public.games AS games
            JOIN public.action_windows AS action_window
              ON action_window.game_id = games.id
             AND action_window.status = 'OPEN'
             AND action_window.window_kind IN ('VOTE', 'REVOTE', 'FINAL_VOTE')
            JOIN public.game_players AS player
              ON player.game_id = games.id
             AND player.kind = 'AI'
             AND player.alive = TRUE
            JOIN public.game_players AS human
              ON human.game_id = games.id
             AND human.kind = 'HUMAN'
            WHERE games.status = 'IN_PROGRESS'
              AND NOT EXISTS (
                  SELECT 1 FROM public.action_submissions AS existing
                  WHERE existing.window_id = action_window.id
                    AND existing.actor_player_id = player.id
              )
              AND (
                  human.alive = FALSE
                  OR (
                      action_window.window_kind <> 'FINAL_VOTE'
                      AND EXISTS (
                          SELECT 1 FROM public.action_submissions AS human_vote
                          WHERE human_vote.window_id = action_window.id
                            AND human_vote.actor_player_id = human.id
                            AND human_vote.action_type = 'VOTE'
                      )
                  )
              )
              AND (action_window.window_kind <> 'FINAL_VOTE' OR human.alive = FALSE)
            ORDER BY action_window.opened_at, games.id, player.seat
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_window_action_submissions(self, cursor: Any, *, window_id: UUID) -> list[dict[str, Any]]:
        """현재 action window의 확정 행동을 엔진 상태 복원용으로 읽는다."""

        cursor.execute(
            """
            SELECT actor_player_id, action_type, target_player_id
            FROM public.action_submissions
            WHERE window_id = %s
            ORDER BY submitted_at, id
            """,
            (window_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_window_vote_submissions(self, cursor: Any, *, window_id: UUID) -> list[dict[str, Any]]:
        """현재 투표 window의 확정 표를 엔진 상태 복원용으로 읽는다."""

        return [
            row
            for row in self.list_window_action_submissions(cursor, window_id=window_id)
            if row["action_type"] == "VOTE"
        ]

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
            JOIN public.action_windows AS action_window
              ON action_window.id = submission.window_id
             AND action_window.game_id = submission.game_id
            JOIN public.game_players AS player
              ON player.id = submission.actor_player_id
             AND player.game_id = submission.game_id
            WHERE submission.game_id = %s
              AND action_window.phase = %s
              AND action_window.round = %s
              AND action_window.cycle = %s
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
