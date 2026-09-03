"""Backend 내부 Engine API의 입력·출력 schema."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _uuid4(value: UUID) -> UUID:
    """내부 식별자가 UUID v4인지 확인한다."""

    if value.version != 4:
        raise ValueError("UUID v4만 사용할 수 있습니다.")
    return value


class BootstrapConsumeRequest(BaseModel):
    """MCP가 전달하는 signed token만 받고 capability는 header에서만 받는다."""

    model_config = ConfigDict(extra="forbid")
    bootstrap_token: str = Field(min_length=1, max_length=4096)


class AgentProposalRequest(BaseModel):
    """MCP Tool이 Engine에 제출하는 폐쇄형 proposal 요청."""

    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    game_id: UUID
    agent_id: UUID
    window_id: UUID
    expected_state_version: int = Field(ge=1)
    proposal: dict[str, Any]

    _proposal_id_v4 = field_validator("proposal_id")( _uuid4 )
    _game_id_v4 = field_validator("game_id")( _uuid4 )
    _agent_id_v4 = field_validator("agent_id")( _uuid4 )
    _window_id_v4 = field_validator("window_id")( _uuid4 )


class ProposalAcceptedResponse(BaseModel):
    """검증·반영된 Agent proposal의 최소 결과."""

    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    status: Literal["ACCEPTED"]
    result_state_version: int = Field(ge=1)

