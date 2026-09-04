"""연결 뼈대 게임의 PostgreSQL 원본 저장소."""

from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.app.models.scaffold_game import ScaffoldGame, ScaffoldOperation


class PostgresScaffoldRepository:
    """요청 단위 연결을 사용하는 최소 PostgreSQL repository다."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        # scaffold-v1에서는 프로세스 내 중복을 처리하고, 영속 idempotency 컬럼은
        # 실제 ruleset 스키마에서 추가한다.
        self.idempotency: dict[tuple[UUID, UUID], tuple[str, object]] = {}

    def create_game(self, game: ScaffoldGame) -> None:
        """게임 상태를 원본 DB에 저장한다."""

        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """INSERT INTO scaffold_games
                   (id, owner_user_id, player_count, ruleset_version, status, phase, state_version)
                   VALUES (%s,%s,%s,'scaffold-v1',%s,%s,%s)""",
                (game.game_id, game.owner_user_id, game.player_count, game.status, game.phase, game.state_version),
            )

    def get_game(self, game_id: UUID) -> ScaffoldGame | None:
        """게임 상태를 조회한다."""

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute("SELECT * FROM scaffold_games WHERE id=%s", (game_id,)).fetchone()
        if row is None:
            return None
        return ScaffoldGame(
            game_id=row["id"], owner_user_id=row["owner_user_id"], player_count=row["player_count"],
            state_version=row["state_version"], phase=row["phase"], status=row["status"],
            updated_at=row["updated_at"], players=[], display_names=[],
        )

    def list_games(self, owner_user_id: UUID, *, status: str | None = None,
                   limit: int = 20) -> list[ScaffoldGame]:
        """공개 목록에 필요한 소유자 게임만 최신 갱신순으로 조회한다."""

        query = "SELECT * FROM scaffold_games WHERE owner_user_id=%s"
        parameters: list[object] = [owner_user_id]
        if status is not None:
            query += " AND status=%s"
            parameters.append(status)
        query += " ORDER BY updated_at DESC, id DESC LIMIT %s"
        parameters.append(limit)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            ScaffoldGame(
                game_id=row["id"], owner_user_id=row["owner_user_id"],
                player_count=row["player_count"], state_version=row["state_version"],
                phase=row["phase"], status=row["status"], updated_at=row["updated_at"],
                players=[], display_names=[],
            )
            for row in rows
        ]

    def save_command(self, game: ScaffoldGame, operation: ScaffoldOperation, event_payload: dict) -> None:
        """상태·operation·event를 같은 transaction에서 확정한다."""

        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE scaffold_games SET status=%s, phase=%s, state_version=%s,
                       updated_at=%s WHERE id=%s""",
                    (game.status, game.phase, game.state_version, game.updated_at, game.game_id),
                )
                cursor.execute(
                    """INSERT INTO scaffold_operations
                       (id, game_id, command, status, accepted_version, result_version)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (operation.operation_id, operation.game_id, operation.command, operation.status,
                     operation.accepted_version, operation.result_version),
                )
                cursor.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM scaffold_events WHERE game_id=%s",
                    (game.game_id,),
                )
                sequence = cursor.fetchone()[0]
                cursor.execute(
                    """INSERT INTO scaffold_events
                       (game_id, sequence, event_type, payload, state_version)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (game.game_id, sequence, "game.state_changed", Jsonb(event_payload), game.state_version),
                )

    def get_operation(self, operation_id: UUID) -> ScaffoldOperation | None:
        """operation을 조회한다."""

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute("SELECT * FROM scaffold_operations WHERE id=%s", (operation_id,)).fetchone()
        if row is None:
            return None
        return ScaffoldOperation(
            operation_id=row["id"], game_id=row["game_id"], command=row["command"],
            accepted_version=row["accepted_version"], result_version=row["result_version"],
            status=row["status"], error_code=row["error_code"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def events_after(self, game_id: UUID, sequence: int) -> list[dict]:
        """지정 sequence 이후 event를 순서대로 반환한다."""

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT sequence, event_type, payload, state_version, created_at FROM scaffold_events "
                "WHERE game_id=%s AND sequence>%s ORDER BY sequence", (game_id, sequence),
            ).fetchall()
        return [dict(row) for row in rows]
