"""공개 게임 API의 요청 검증과 응답용 타입."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateGameRequest(BaseModel):
    """정본에 정의된 게임 생성 요청이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    player_count: int = Field(ge=6, le=9)
    ruleset_version: Literal["mystery-v1"]
    scenario_version: Literal["scenario-v1"]


class GameListQuery(BaseModel):
    """게임 목록 조회 조건을 서비스에 전달하기 전 검증한다."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"] | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CreateGameData(BaseModel):
    """게임 생성 성공 data다."""

    model_config = ConfigDict(extra="forbid")

    game_id: UUID
    status: Literal["IN_PROGRESS"]
    phase: Literal["ROLE_REVEAL"]
    round: int
    state_version: int
    snapshot_url: str
