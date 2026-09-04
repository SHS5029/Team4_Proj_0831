"""연결 뼈대에서 사용하는 내부 게임 모델이다."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass
class ScaffoldGame:
    """규칙을 실행하지 않고 연결 상태만 저장하는 게임이다."""

    game_id: UUID
    owner_user_id: UUID
    player_count: int
    state_version: int = 1
    phase: str = "ROLE_REVEAL"
    status: str = "IN_PROGRESS"
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    players: list[UUID] = field(default_factory=list)


@dataclass
class ScaffoldOperation:
    """command 수락 결과를 polling할 수 있게 보관한다."""

    operation_id: UUID
    game_id: UUID
    command: str
    accepted_version: int
    result_version: int | None
    status: str = "COMPLETED"
    error_code: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

