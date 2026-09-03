"""게임 상태 행을 잠그고 내부 sequence를 발급하는 PostgreSQL 저장소."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


GAME_COLUMNS = """
    id, owner_user_id, status, phase, round, day_number, state_version,
    next_event_sequence, next_front_sequence, player_count, mafia_count,
    ruleset_version, scenario_version, scenario_id, scenario_content_hash,
    seed_ciphertext, seed_nonce, seed_key_id, agent_config_version,
    fast_forward_enabled, winner, win_reason, saved_at, finished_at,
    created_at, updated_at
"""


class PostgresGameRepository:
    """게임별 PostgreSQL row lock과 sequence 발급을 담당한다."""

    def lock_game(self, cursor: Any, game_id: UUID) -> Mapping[str, Any] | None:
        """동시 command가 같은 게임 상태를 동시에 읽지 못하도록 행을 잠근다."""

        cursor.execute(
            f"""
            SELECT {GAME_COLUMNS}
            FROM public.games
            WHERE id = %s
            FOR UPDATE
            """,
            (game_id,),
        )
        return cursor.fetchone()

    def next_event_sequence(self, cursor: Any, game_id: UUID) -> int:
        """게임의 다음 내부 event sequence를 원자적으로 예약한다."""

        cursor.execute(
            """
            UPDATE public.games
            SET next_event_sequence = next_event_sequence + 1
            WHERE id = %s
            RETURNING next_event_sequence - 1 AS sequence
            """,
            (game_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("게임을 찾을 수 없습니다.")
        return int(row["sequence"])

    def next_front_sequence(self, cursor: Any, game_id: UUID) -> int:
        """client-visible transaction 하나의 Front batch 번호를 예약한다."""

        cursor.execute(
            """
            UPDATE public.games
            SET next_front_sequence = next_front_sequence + 1
            WHERE id = %s
            RETURNING next_front_sequence - 1 AS front_sequence
            """,
            (game_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("게임을 찾을 수 없습니다.")
        return int(row["front_sequence"])
