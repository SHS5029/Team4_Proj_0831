"""외부 DB와 분리된 순수 게임 상태 모델.

이 파일의 객체는 게임 규칙 테스트와 replay에만 사용한다. 실제 PostgreSQL 저장은
B5/B7에서 Repository가 담당하며, 이 모델에 비밀번호·LLM 원문·Chain of Thought를
넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from backend.app.models.enums import (
    Faction,
    GamePhase,
    GameStatus,
    NightActionType,
    PlayerKind,
    PlayerRole,
    WinReason,
)


@dataclass
class PlayerState:
    """게임 한 판 안에서 변하지 않는 정보와 생존 여부를 보관한다."""

    player_id: UUID
    seat: int
    role: PlayerRole
    kind: PlayerKind = PlayerKind.AI
    display_name: str = ""
    alive: bool = True

    @property
    def faction(self) -> Faction:
        """역할에서 진영을 계산한다. 진영을 별도로 바꾸지 못하게 한다."""

        return Faction.MAFIA if self.role is PlayerRole.MAFIA else Faction.CITIZEN


@dataclass(frozen=True)
class NightAction:
    """한 플레이어가 제출한 유효한 첫 밤 행동이다."""

    actor_id: UUID
    action_type: NightActionType
    target_id: UUID


@dataclass(frozen=True)
class Vote:
    """한 플레이어가 제출한 유효한 표이다."""

    actor_id: UUID
    target_id: UUID


@dataclass(frozen=True)
class EngineOperation:
    """replay에 필요한 최소 명령 기록이다."""

    command: str
    actor_id: UUID | None = None
    target_id: UUID | None = None
    text: str | None = None
    result_state_version: int = 0


@dataclass
class GameState:
    """게임 규칙이 읽고 수정하는 단일 메모리 상태이다."""

    game_id: UUID
    seed: bytes
    players: list[PlayerState]
    phase: GamePhase = GamePhase.ROLE_REVEAL
    status: GameStatus = GameStatus.IN_PROGRESS
    round: int = 0
    day_number: int = 1
    state_version: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    speech_actors: set[UUID] = field(default_factory=set)
    speech_question_cycle_used: bool = False
    speech_had_content: bool = False
    night_actions: dict[UUID, NightAction] = field(default_factory=dict)
    votes: dict[UUID, Vote] = field(default_factory=dict)
    final_accusation_target: UUID | None = None
    last_detective_result: dict[UUID, bool] = field(default_factory=dict)
    remaining_ms_on_save: int | None = None
    deadline_at: datetime | None = None
    winner: Faction | None = None
    win_reason: WinReason | None = None
    operations: list[EngineOperation] = field(default_factory=list)

    @property
    def alive_players(self) -> list[PlayerState]:
        """좌석순 생존 플레이어 목록을 반환한다."""

        return sorted((player for player in self.players if player.alive), key=lambda p: p.seat)

    @property
    def player_by_id(self) -> dict[UUID, PlayerState]:
        """검증할 때 반복 검색하지 않도록 현재 플레이어를 색인한다."""

        return {player.player_id: player for player in self.players}

    @property
    def human_alive(self) -> bool:
        """생존한 인간이 있는지 반환한다."""

        return any(player.alive and player.kind is PlayerKind.HUMAN for player in self.players)
