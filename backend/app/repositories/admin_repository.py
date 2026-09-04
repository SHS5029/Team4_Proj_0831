"""관리자 read-only 조회와 ``admin_audit_events`` 기록 저장소.

관리자 저장소가 반환하는 게임 데이터는 공개 진행 정보만 포함한다. 역할,
개인 사실, 개별 행동·투표, seed와 Agent private context는 SQL 조회 단계에서
아예 선택하지 않는다. 테스트에서는 같은 계약의 메모리 저장소를 주입할 수 있고,
운영에서는 PostgreSQL 저장소로 바꿔 쓸 수 있다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from backend.app.services.game_service import CanonicalGameRecord, InMemoryGameRepository


class AdminRepository(Protocol):
    """관리자 서비스가 필요한 조회·감사 기록 계약."""

    def list_games(
        self,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    def get_game(self, game_id: UUID) -> dict[str, Any] | None: ...

    def metrics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> dict[str, Any]: ...

    def append_audit(
        self,
        *,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None: ...


def _iso(value: Any) -> str | None:
    """datetime을 API용 UTC 문자열로 바꾸고 나머지는 안전하게 비운다."""

    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _window_kind(phase: str, status: str) -> str | None:
    """DB phase를 관리자에게 보여줄 현재 action window 종류로 변환한다."""

    if status != "IN_PROGRESS":
        return None
    return {
        "DAY_DISCUSSION": "SPEECH",
        "NIGHT_ACTION": "NIGHT",
        "DAY_VOTE": "VOTE",
        "REVOTE": "REVOTE",
        "FINAL_ACCUSATION": "FINAL_VOTE",
    }.get(phase)


class InMemoryAdminRepository:
    """B5 메모리 게임 저장소를 읽기만 하는 B8 테스트용 adapter."""

    def __init__(self, game_repository: InMemoryGameRepository) -> None:
        self.game_repository = game_repository
        # 테스트에서 게임 저장소와 관리자 저장소를 함께 검사할 수 있도록 같은
        # append-only 목록을 공유한다. 운영 PostgreSQL adapter는 실제
        # admin_audit_events 테이블에만 기록하므로 이 편의 처리는 메모리 경로에
        # 한정된다.
        if not hasattr(game_repository, "audit_events"):
            game_repository.audit_events = []
        self.audit_events = game_repository.audit_events

    def _list_item(self, record: CanonicalGameRecord) -> dict[str, Any]:
        """개인정보를 제외한 관리자 목록 한 건을 만든다."""

        state = record.state
        status = state.status.value
        return {
            "game_id": str(state.game_id),
            "owner_user_id": str(record.owner_user_id),
            "status": status,
            "phase": state.phase.value,
            "round": state.round,
            "state_version": state.state_version,
            "player_count": len(state.players),
            "open_window_kind": _window_kind(state.phase.value, status),
            "updated_at": _iso(state.updated_at),
        }

    def list_games(
        self,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """최신 변경 순으로 필터링하고 다음 cursor를 game UUID로 반환한다."""

        records = [
            record
            for record in self.game_repository.games.values()
            if (status is None or record.state.status.value == status)
            and (phase is None or record.state.phase.value == phase)
        ]
        records.sort(
            key=lambda item: (item.state.updated_at, str(item.state.game_id)), reverse=True
        )
        if cursor:
            cursor_index = next(
                (index for index, item in enumerate(records) if str(item.state.game_id) == cursor),
                None,
            )
            if cursor_index is None:
                return [], None
            records = records[cursor_index + 1 :]
        selected = records[:limit]
        next_cursor = str(selected[-1].state.game_id) if len(records) > limit else None
        return [self._list_item(record) for record in selected], next_cursor

    def get_game(self, game_id: UUID) -> dict[str, Any] | None:
        """공개 event와 진행 정보만 상세 응답으로 만든다."""

        record = self.game_repository.games.get(game_id)
        if record is None:
            return None
        state = record.state
        status = state.status.value
        window_kind = _window_kind(state.phase.value, status)
        window = None
        if window_kind is not None:
            window = {
                "kind": window_kind,
                "cycle": 1,
                "opened_state_version": state.state_version,
                "deadline_at": _iso(state.deadline_at),
                "remaining_ms": state.remaining_ms_on_save,
                "status": "OPEN" if state.status.value == "IN_PROGRESS" else "PAUSED",
            }
        result = None
        if state.status.value == "COMPLETED":
            result = {
                "winner": state.winner.value if state.winner else None,
                "win_reason": state.win_reason.value if state.win_reason else None,
                "finished_at": _iso(state.updated_at),
            }
        return {
            "game": self._list_item(record),
            "public_events": [dict(event) for event in record.public_events],
            "action_window": window,
            "failure_code": None,
            "result": result,
        }

    def metrics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> dict[str, Any]:
        """메모리 게임의 운영 통계를 계산하며 LLM 비용 정보는 포함하지 않는다."""

        records = list(self.game_repository.games.values())
        if from_time is not None:
            records = [r for r in records if r.state.updated_at >= from_time]
        if to_time is not None:
            records = [r for r in records if r.state.updated_at <= to_time]
        completed = [r for r in records if r.state.status.value == "COMPLETED"]
        wins = {"CITIZEN": 0, "MAFIA": 0}
        for record in completed:
            if record.state.winner is not None:
                wins[record.state.winner.value] += 1
        ratings = [int(item["rating"]) for item in self.game_repository.feedback.values()]
        return {
            "games_created": len(records),
            "games_completed": len(completed),
            "games_saved": sum(r.state.status.value == "SAVED" for r in records),
            "completion_rate": round(len(completed) / len(records), 4) if records else 0.0,
            "average_rounds": round(sum(r.state.round for r in completed) / len(completed), 2)
            if completed
            else 0.0,
            "wins_by_faction": wins,
            # 현재 B5 메모리 adapter에는 자동 처리 횟수 원장이 없으므로
            # 추측값을 만들지 않고 0을 반환한다. PostgreSQL adapter에서 event
            # source='AUTO' 집계로 교체할 수 있는 고정된 응답 항목이다.
            "auto_action_count": 0,
            "feedback_average": round(sum(ratings) / len(ratings), 2) if ratings else None,
        }

    def append_audit(
        self,
        *,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None:
        """응답 payload 없이 감사에 필요한 최소 metadata만 append한다."""

        self.audit_events.append(
            {
                "admin_user_id": admin_user_id,
                "action": action,
                "target_game_id": target_game_id,
                "request_id": request_id,
            }
        )


ConnectionFactory = Callable[..., Any]


class PostgresAdminRepository:
    """정본 PostgreSQL에서 공개 관리자 조회와 감사 event를 수행한다."""

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory or psycopg.connect

    def _connection(self) -> Any:
        """dict row를 사용하는 연결을 열되 URL을 로그나 응답으로 내보내지 않는다."""

        return self._connection_factory(self._database_url, row_factory=dict_row)

    def list_games(
        self,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """게임 목록에서 개인 역할·사실 테이블을 조인하지 않는다."""

        if cursor:
            try:
                UUID(cursor)
            except ValueError as exc:
                raise ValueError("cursor must be a game UUID") from exc
        query = """
            SELECT g.id AS game_id, g.owner_user_id, g.status, g.phase, g.round,
                   g.state_version, g.player_count,
                   CASE WHEN g.status = 'IN_PROGRESS' THEN
                       CASE g.phase
                         WHEN 'DAY_DISCUSSION' THEN 'SPEECH'
                         WHEN 'NIGHT_ACTION' THEN 'NIGHT'
                         WHEN 'DAY_VOTE' THEN 'VOTE'
                         WHEN 'REVOTE' THEN 'REVOTE'
                         WHEN 'FINAL_ACCUSATION' THEN 'FINAL_VOTE'
                         ELSE NULL
                       END
                   ELSE NULL END AS open_window_kind,
                   g.updated_at
            FROM public.games g
            WHERE (%s IS NULL OR g.status = %s)
              AND (%s IS NULL OR g.phase = %s)
              AND (
                  %s IS NULL
                  OR (g.updated_at, g.id) < (
                      SELECT c.updated_at, c.id
                      FROM public.games c
                      WHERE c.id = %s
                  )
              )
            ORDER BY g.updated_at DESC, g.id DESC
            LIMIT %s
        """
        params = [status, status, phase, phase, cursor, cursor, limit + 1]
        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(query, params)
                rows = list(cursor_obj.fetchall())
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._list_row(row) for row in rows]
        return items, (items[-1]["game_id"] if has_more else None)

    @staticmethod
    def _list_row(row: Mapping[str, Any]) -> dict[str, Any]:
        """DB row를 관리자 목록 폐쇄형 object로 변환한다."""

        return {
            "game_id": str(row["game_id"]),
            "owner_user_id": str(row["owner_user_id"]),
            "status": row["status"],
            "phase": row["phase"],
            "round": int(row["round"]),
            "state_version": int(row["state_version"]),
            "player_count": int(row["player_count"]),
            "open_window_kind": row["open_window_kind"],
            "updated_at": _iso(row["updated_at"]),
        }

    def get_game(self, game_id: UUID) -> dict[str, Any] | None:
        """games·public game_events·현재 window metadata만 읽는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id AS game_id, owner_user_id, status, phase, round,
                           state_version, player_count, updated_at, winner, win_reason,
                           finished_at
                    FROM public.games
                    WHERE id = %s
                    """,
                    (game_id,),
                )
                game_row = cursor.fetchone()
                if game_row is None:
                    return None
                cursor.execute(
                    """
                    SELECT id AS event_id, event_type, created_at, payload
                    FROM public.game_events
                    WHERE game_id = %s AND audience = 'PUBLIC'
                    ORDER BY sequence
                    """,
                    (game_id,),
                )
                events = [
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "created_at": _iso(row["created_at"]),
                        "data": dict(row["payload"]),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT window_kind, cycle, opened_state_version, deadline_at,
                           remaining_ms_on_save, status
                    FROM public.action_windows
                    WHERE game_id = %s AND status IN ('OPEN', 'PAUSED', 'RESOLVING')
                    ORDER BY opened_at DESC, id DESC
                    LIMIT 1
                    """,
                    (game_id,),
                )
                window_row = cursor.fetchone()
        status = game_row["status"]
        result = None
        if status == "COMPLETED":
            result = {
                "winner": game_row["winner"],
                "win_reason": game_row["win_reason"],
                "finished_at": _iso(game_row["finished_at"]),
            }
        return {
            "game": self._list_row(
                {
                    **game_row,
                    "open_window_kind": window_row["window_kind"] if window_row else None,
                }
            ),
            "public_events": events,
            "action_window": (
                {
                    "kind": window_row["window_kind"],
                    "cycle": int(window_row["cycle"]),
                    "opened_state_version": int(window_row["opened_state_version"]),
                    "deadline_at": _iso(window_row["deadline_at"]),
                    "remaining_ms": window_row["remaining_ms_on_save"],
                    "status": window_row["status"],
                }
                if window_row
                else None
            ),
            "failure_code": None,
            "result": result,
        }

    def metrics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> dict[str, Any]:
        """정본 games와 feedback에서 문서에 정의된 운영 지표만 집계한다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT COUNT(*) AS games_created,
                           COUNT(*) FILTER (WHERE g.status = 'COMPLETED') AS games_completed,
                           COUNT(*) FILTER (WHERE g.status = 'SAVED') AS games_saved,
                           COALESCE(
                               AVG(g.round) FILTER (WHERE g.status = 'COMPLETED'), 0
                           ) AS average_rounds,
                           COUNT(*) FILTER (
                               WHERE g.status = 'COMPLETED' AND g.winner = 'CITIZEN'
                           ) AS citizen_wins,
                           COUNT(*) FILTER (
                               WHERE g.status = 'COMPLETED' AND g.winner = 'MAFIA'
                           ) AS mafia_wins,
                           COUNT(*) FILTER (WHERE g.status = 'COMPLETED') AS completed_for_rate
                    FROM public.games g
                    WHERE (%s IS NULL OR g.created_at >= %s)
                      AND (%s IS NULL OR g.created_at <= %s)
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                row = cursor_obj.fetchone()
                cursor_obj.execute(
                    """
                    SELECT AVG(f.rating) AS feedback_average
                    FROM public.feedback f
                    WHERE (%s IS NULL OR f.created_at >= %s)
                      AND (%s IS NULL OR f.created_at <= %s)
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                feedback_row = cursor_obj.fetchone()
        created = int(row["games_created"])
        return {
            "games_created": created,
            "games_completed": int(row["games_completed"]),
            "games_saved": int(row["games_saved"]),
            "completion_rate": round(int(row["completed_for_rate"]) / created, 4)
            if created
            else 0.0,
            "average_rounds": round(float(row["average_rounds"]), 2),
            "wins_by_faction": {
                "CITIZEN": int(row["citizen_wins"]),
                "MAFIA": int(row["mafia_wins"]),
            },
            "auto_action_count": 0,
            "feedback_average": (
                round(float(feedback_row["feedback_average"]), 2)
                if feedback_row["feedback_average"] is not None
                else None
            ),
        }

    def append_audit(
        self,
        *,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None:
        """감사 로그에 request metadata만 추가하고 응답 내용을 저장하지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    INSERT INTO public.admin_audit_events
                        (admin_user_id, action, target_game_id, request_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (admin_user_id, action, target_game_id, request_id),
                )
