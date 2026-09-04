"""게임 플레이어와 시나리오 개인 단서를 저장하는 PostgreSQL 저장소."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlayerInsert:
    """game_players의 생성 시점 값을 명시적으로 묶은 내부 입력."""

    player_id: UUID
    user_id: UUID | None
    kind: str
    seat: int
    display_name: str
    role: str
    faction: str
    persona_id: str | None


@dataclass(frozen=True, slots=True)
class ScenarioFactInsert:
    """플레이어 한 명에게 확정된 ALIBI 또는 OBSERVATION 입력."""

    fact_id: UUID
    player_id: UUID
    fact_kind: str
    template_id: UUID
    rendered_text: str
    subject_player_id: UUID | None = None


class PostgresPlayerRepository:
    """계산이 끝난 플레이어와 단서를 같은 transaction cursor로 INSERT한다."""

    def insert_players(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        players: list[PlayerInsert],
    ) -> None:
        """6~9명의 플레이어를 정본 컬럼에 저장한다."""

        _validate_players(players)
        for player in players:
            cursor.execute(
                """
                INSERT INTO public.game_players (
                    id, game_id, user_id, kind, seat, display_name,
                    role, faction, alive, persona_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                """,
                (
                    player.player_id,
                    game_id,
                    player.user_id,
                    player.kind,
                    player.seat,
                    player.display_name,
                    player.role,
                    player.faction,
                    player.persona_id,
                ),
            )

    def insert_facts(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        facts: list[ScenarioFactInsert],
    ) -> None:
        """렌더링이 끝난 개인 단서를 역할 정보 없이 저장한다."""

        _validate_facts(facts)
        for fact in facts:
            cursor.execute(
                """
                INSERT INTO public.player_scenario_facts (
                    id, game_id, player_id, fact_kind, template_id,
                    rendered_text, subject_player_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fact.fact_id,
                    game_id,
                    fact.player_id,
                    fact.fact_kind,
                    fact.template_id,
                    fact.rendered_text,
                    fact.subject_player_id,
                ),
            )


def _validate_players(players: list[PlayerInsert]) -> None:
    """DB에 보내기 전에 인원·좌석·HUMAN/AI 식별 규칙을 검사한다."""

    if not 6 <= len(players) <= 9:
        raise ValueError("Game creation requires 6 to 9 players")
    if len({player.player_id for player in players}) != len(players):
        raise ValueError("Player IDs must be unique")
    if {player.seat for player in players} != set(range(1, len(players) + 1)):
        raise ValueError("Player seats must be consecutive from 1")

    human_count = 0
    for player in players:
        if not player.display_name.strip() or len(player.display_name) > 40:
            raise ValueError("Player display name is invalid")
        if player.kind == "HUMAN":
            human_count += 1
            if player.user_id is None or player.persona_id is not None:
                raise ValueError("Human player identity is invalid")
        elif player.kind == "AI":
            if player.user_id is not None or not player.persona_id:
                raise ValueError("AI player identity is invalid")
        else:
            raise ValueError("Player kind is invalid")
    if human_count != 1:
        raise ValueError("Game creation requires exactly one human player")


def _validate_facts(facts: list[ScenarioFactInsert]) -> None:
    """같은 플레이어에게 같은 종류의 단서가 중복되지 않게 검사한다."""

    unique_keys = {(fact.player_id, fact.fact_kind) for fact in facts}
    if len(unique_keys) != len(facts):
        raise ValueError("Player scenario facts must be unique by kind")
    for fact in facts:
        if fact.fact_kind not in {"ALIBI", "OBSERVATION"}:
            raise ValueError("Scenario fact kind is invalid")
        if not fact.rendered_text.strip() or len(fact.rendered_text) > 240:
            raise ValueError("Rendered scenario fact is invalid")

