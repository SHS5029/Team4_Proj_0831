"""관리자 read-only 조회와 ``admin_audit_events`` 기록 저장소.

관리자 저장소가 반환하는 게임 데이터는 공개 진행 정보만 포함한다. 역할,
개인 사실, 개별 행동·투표, seed와 Agent private context는 SQL 조회 단계에서
아예 선택하지 않는다. 테스트에서는 같은 계약의 메모리 저장소를 주입할 수 있고,
운영에서는 PostgreSQL 저장소로 바꿔 쓸 수 있다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


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

    def role_win_rates(self, *, from_time: datetime | None,
                       to_time: datetime | None) -> list[dict[str, Any]]: ...

    def persona_win_rates(self, *, from_time: datetime | None,
                          to_time: datetime | None) -> list[dict[str, Any]]: ...

    def list_feedback(self, *, feedback_type: str | None, rating: int | None,
                      cursor: UUID | None, limit: int) -> tuple[list[dict], str | None]: ...

    def list_audit_logs(self, *, event_type: str | None, cursor: int | None,
                        limit: int) -> tuple[list[dict], str | None]: ...

    def search_knowledge(
        self,
        *,
        question: str,
        source_types: list[str],
        rating_lte: int | None,
        from_time: datetime | None,
        to_time: datetime | None,
        top_k: int,
    ) -> list[dict[str, Any]]: ...


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
                    WHERE (%s::timestamptz IS NULL OR g.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                row = cursor_obj.fetchone()
                cursor_obj.execute(
                    """
                    SELECT AVG(f.rating) AS feedback_average
                    FROM public.feedback f
                    WHERE (%s::timestamptz IS NULL OR f.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR f.created_at <= %s)
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                feedback_row = cursor_obj.fetchone()
                cursor_obj.execute("SELECT COUNT(*) AS users_total FROM public.users")
                users_total = int(cursor_obj.fetchone()["users_total"])
                cursor_obj.execute(
                    """
                    SELECT COUNT(*) AS total FROM public.action_submissions s
                    JOIN public.games g ON g.id = s.game_id
                    WHERE s.source = 'AUTO'
                      AND (%s::timestamptz IS NULL OR g.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    """, [from_time, from_time, to_time, to_time],
                )
                auto_actions = int(cursor_obj.fetchone()["total"])
                # 전체 기간 KPI라도 일별 그래프의 응답 크기는 UTC 최근 30일로 제한한다.
                daily_end = to_time or datetime.now(UTC)
                daily_start = from_time or (
                    daily_end.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=29)
                )
                if from_time is not None and to_time is None:
                    daily_end = min(daily_end, from_time + timedelta(days=31))
                cursor_obj.execute(
                    """
                    SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*) AS total
                    FROM public.games WHERE created_at >= %s AND created_at <= %s
                    GROUP BY day ORDER BY day
                    """, [daily_start, daily_end],
                )
                counts = {r["day"].isoformat(): int(r["total"]) for r in cursor_obj.fetchall()}
                start_day, end_day = daily_start.astimezone(UTC).date(), daily_end.astimezone(UTC).date()
                daily = [{"date": (start_day + timedelta(days=i)).isoformat(),
                          "games_created": counts.get((start_day + timedelta(days=i)).isoformat(), 0)}
                         for i in range(max(0, (end_day - start_day).days + 1))]
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
            "users_total": users_total,
            "daily_games": daily,
            "auto_action_count": auto_actions,
            "feedback_average": (
                round(float(feedback_row["feedback_average"]), 2)
                if feedback_row["feedback_average"] is not None
                else None
            ),
        }

    def role_win_rates(self, *, from_time: datetime | None,
                       to_time: datetime | None) -> list[dict[str, Any]]:
        """종료 게임의 AI 역할을 DB에서 집계하고 개별 좌석 정보는 반환하지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT p.role AS job, COUNT(*) AS participations,
                           COUNT(*) FILTER (WHERE p.faction = g.winner) AS wins
                    FROM public.game_players p JOIN public.games g ON g.id = p.game_id
                    WHERE g.status = 'COMPLETED' AND p.kind = 'AI'
                      AND (%s::timestamptz IS NULL OR g.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    GROUP BY p.role
                    """, [from_time, from_time, to_time, to_time],
                )
                counts = {row["job"]: row for row in cursor_obj.fetchall()}
        items = []
        for job in ["MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN"]:
            row = counts.get(job, {})
            total, wins = int(row.get("participations", 0)), int(row.get("wins", 0))
            items.append({"job": job, "participations": total, "wins": wins,
                          "win_rate": round(wins / total, 6) if total else 0.0})
        return items

    def persona_win_rates(self, *, from_time: datetime | None,
                          to_time: datetime | None) -> list[dict[str, Any]]:
        """에이전트 페르소나별 AI 참여·승리를 집계하고 내부 파라미터는 반환하지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT ap.id AS persona_id, ap.display_name AS persona_name,
                           ap.speech_style AS personality_summary,
                           COUNT(gp.id) FILTER (WHERE g.id IS NOT NULL) AS participations,
                           COUNT(gp.id) FILTER (
                               WHERE g.id IS NOT NULL AND gp.faction = g.winner
                           ) AS wins
                    FROM public.agent_personas ap
                    LEFT JOIN public.game_players gp
                      ON gp.persona_id = ap.id AND gp.kind = 'AI'
                    LEFT JOIN public.games g
                      ON g.id = gp.game_id
                     AND g.status = 'COMPLETED'
                     AND (%s::timestamptz IS NULL OR g.created_at >= %s)
                     AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    WHERE ap.active = TRUE
                    GROUP BY ap.id, ap.display_name, ap.speech_style
                    ORDER BY ap.display_name, ap.id
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                rows = list(cursor_obj.fetchall())
        return [
            {
                "persona_id": str(row["persona_id"]),
                "persona_name": row["persona_name"],
                "personality_summary": row["personality_summary"],
                "participations": int(row["participations"]),
                "wins": int(row["wins"]),
                "win_rate": (
                    round(int(row["wins"]) / int(row["participations"]), 6)
                    if int(row["participations"])
                    else 0.0
                ),
            }
            for row in rows
        ]

    def list_feedback(self, *, feedback_type: str | None, rating: int | None,
                      cursor: UUID | None, limit: int) -> tuple[list[dict], str | None]:
        """사용자가 작성한 의견만 읽고 UUID 커서로 동일 시각의 기록까지 순서대로 조회한다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT f.id, f.user_id, f.feedback_type, f.game_id,
                           f.rating, f.comment, f.tags, f.created_at
                    FROM public.feedback f
                    WHERE (%s::text IS NULL OR f.feedback_type = %s)
                      AND (%s::integer IS NULL OR f.rating = %s)
                      AND (%s::uuid IS NULL OR (f.created_at, f.id) < (
                          SELECT c.created_at, c.id FROM public.feedback c WHERE c.id = %s))
                    ORDER BY f.created_at DESC, f.id DESC LIMIT %s
                    """, [feedback_type, feedback_type, rating, rating, cursor, cursor, limit + 1],
                )
                rows = list(cursor_obj.fetchall())
        items = [{"feedback_id": str(row["id"]), "user_id": str(row["user_id"]),
                  "feedback_type": row["feedback_type"],
                  "game_id": str(row["game_id"]) if row["game_id"] else None,
                  "rating": int(row["rating"]), "comment": row["comment"],
                  "tags": list(row["tags"]), "created_at": _iso(row["created_at"])}
                 for row in rows[:limit]]
        return items, items[-1]["feedback_id"] if len(rows) > limit else None

    def list_audit_logs(self, *, event_type: str | None, cursor: int | None,
                        limit: int) -> tuple[list[dict], str | None]:
        """감사 이벤트의 허용 메타데이터를 PK 커서로 읽고 원문 서버 로그는 읽지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT id, admin_user_id, action, target_game_id, request_id, created_at
                    FROM public.admin_audit_events
                    WHERE (%s::text IS NULL OR action = %s)
                      AND (%s::bigint IS NULL OR id < %s)
                    ORDER BY id DESC LIMIT %s
                    """, [event_type, event_type, cursor, cursor, limit + 1],
                )
                rows = list(cursor_obj.fetchall())
        items = [{"audit_id": str(row["id"]), "admin_user_id": str(row["admin_user_id"]),
                  "event_type": row["action"],
                  "target_game_id": str(row["target_game_id"]) if row["target_game_id"] else None,
                  "request_id": str(row["request_id"]), "created_at": _iso(row["created_at"])}
                 for row in rows[:limit]]
        return items, items[-1]["audit_id"] if len(rows) > limit else None

    def search_knowledge(
        self,
        *,
        question: str,
        source_types: list[str],
        rating_lte: int | None,
        from_time: datetime | None,
        to_time: datetime | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """승인된 지식 청크만 키워드·벡터 혼합 점수로 검색한다.

        질문 API는 이 메서드에서 INSERT·UPDATE를 수행하지 않는다. 색인된
        문서의 공개 메타데이터와 정제된 청크만 반환하고, 역할·private context와
        같은 게임 내부 자료 테이블은 조인하지 않는다.
        """

        from backend.app.services.admin_knowledge import local_embedding

        query_embedding = local_embedding(question)
        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    WITH ranked AS (
                        SELECT d.source_type, d.source_id, d.title,
                               c.content AS snippet,
                               ts_rank_cd(c.content_tsv, plainto_tsquery('simple', %s))
                                   AS keyword_score,
                               GREATEST(0.0, 1.0 - (c.embedding <=> %s::vector))
                                   AS vector_score
                        FROM public.admin_knowledge_documents d
                        JOIN public.admin_knowledge_chunks c ON c.document_id = d.id
                        WHERE d.visibility = 'ADMIN_APPROVED'
                          AND (%s::text[] IS NULL OR d.source_type = ANY(%s::text[]))
                          AND (%s::smallint IS NULL OR d.feedback_rating <= %s)
                          AND (%s::timestamptz IS NULL OR d.approved_at >= %s)
                          AND (%s::timestamptz IS NULL OR d.approved_at <= %s)
                    )
                    SELECT source_type, source_id, title, snippet,
                           (keyword_score * 0.55 + vector_score * 0.45) AS score
                    FROM ranked
                    WHERE keyword_score > 0 OR vector_score > 0
                    ORDER BY score DESC, source_type, source_id
                    LIMIT %s
                    """,
                    [
                        question,
                        query_embedding,
                        source_types or None,
                        source_types or None,
                        rating_lte,
                        rating_lte,
                        from_time,
                        from_time,
                        to_time,
                        to_time,
                        top_k,
                    ],
                )
                rows = list(cursor_obj.fetchall())
        return [
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "title": row["title"],
                "snippet": str(row["snippet"])[:240],
                "score": float(row["score"]),
            }
            for row in rows
        ]

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
