"""연결 뼈대 API의 요청·응답 schema를 정의한다."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateScaffoldGameRequest(BaseModel):
    """게임 연결을 시험하는 최소 생성 요청이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    player_count: int = Field(ge=5, le=9)
    ruleset_version: Literal["scaffold-v1"]
    idempotency_key: UUID


class ScaffoldPlayerResponse(BaseModel):
    """뼈대 단계에서 공개하는 최소 참가자 projection이다."""

    model_config = ConfigDict(extra="forbid")
    player_id: UUID
    display_name: str = Field(min_length=1, max_length=20)
    kind: Literal["HUMAN", "AI"]
    role: None = None
    alive: bool = True


class CreateScaffoldGameResponse(BaseModel):
    """게임 생성 결과를 표현한다."""

    model_config = ConfigDict(extra="forbid")
    game_id: UUID
    status: Literal["IN_PROGRESS"]
    phase: Literal["ROLE_REVEAL"]
    state_version: int
    player: ScaffoldPlayerResponse
    players: list[ScaffoldPlayerResponse]


class ScaffoldGameStateResponse(BaseModel):
    """현재 뼈대 게임 상태와 Frontend 제어 정보를 표현한다."""

    model_config = ConfigDict(extra="forbid")
    game_id: UUID
    status: Literal["IN_PROGRESS", "PAUSED"]
    phase: Literal["ROLE_REVEAL", "PAUSED"]
    state_version: int
    players: list[ScaffoldPlayerResponse]
    public_events: list[dict]
    private_events: list[dict]
    allowed_commands: list[str]
    active_operation: dict | None
    updated_at: datetime


class ScaffoldCommandRequest(BaseModel):
    """뼈대에서 허용하는 command와 version 조건이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    command: Literal["PING", "BEGIN_GAME", "PAUSE", "RESUME"]
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class ScaffoldCommandAcceptedResponse(BaseModel):
    """수락된 command의 operation 식별자를 반환한다."""

    model_config = ConfigDict(extra="forbid")
    accepted: Literal[True] = True
    operation_id: UUID
    state_version: int
    phase: Literal["ROLE_REVEAL", "PAUSED"]
    status: Literal["COMPLETED"]


class ScaffoldOperationResponse(BaseModel):
    """operation polling 결과다."""

    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    game_id: UUID
    command: str
    status: Literal["COMPLETED", "FAILED"]
    accepted_version: int
    result_version: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class ScaffoldProposalResponse(BaseModel):
    """dummy LLM과 MCP 왕복 결과를 표현한다."""

    model_config = ConfigDict(extra="forbid")
    accepted: Literal[True] = True
    action: Literal["PING"]
    source_state_version: int
    mcp_receipt: dict
