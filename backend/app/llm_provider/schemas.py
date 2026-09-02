"""모델이 반환한 신뢰할 수 없는 JSON을 게임 proposal로 검증한다."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.llm_provider.errors import LLMResponseError


class GameProposal(BaseModel):
    """Backend가 후속 phase·권한 검증을 수행할 최소 proposal이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=32)
    target_player_id: UUID | None = None
    source_state_version: int = Field(ge=1)
    message: str | None = Field(default=None, max_length=2_000)


def parse_game_proposal(payload: Any, *, expected_state_version: int) -> GameProposal:
    """JSON object와 상태 버전을 검증해 안전한 proposal만 반환한다.

    Provider가 반환한 값은 외부 입력과 같으므로 필드 누락·추가 필드·잘못된
    UUID를 허용하지 않는다. 상태 버전 검사는 오래된 모델 응답이 MCP로
    전달되는 것을 막는 마지막 방어선이며, phase와 역할 검사는 Backend가
    proposal을 제출하기 직전에 별도로 수행한다.
    """

    if not isinstance(payload, dict):
        raise LLMResponseError("LLM response must be a JSON object")
    try:
        proposal = GameProposal.model_validate(payload)
    except ValidationError as error:
        raise LLMResponseError("LLM response does not match the proposal schema") from error
    if proposal.source_state_version != expected_state_version:
        raise LLMResponseError("LLM proposal uses a stale game state version")
    return proposal


def proposal_schema() -> dict[str, Any]:
    """OpenAI·Gemini에 전달할 Provider 독립 JSON schema를 반환한다."""

    # OpenAI structured output은 선택 필드도 required에 포함하고 nullable로
    # 표현해야 하므로, Pydantic 입력 모델과 Provider 출력 schema를 분리한다.
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "minLength": 1, "maxLength": 32},
            "target_player_id": {"type": ["string", "null"], "format": "uuid"},
            "source_state_version": {"type": "integer", "minimum": 1},
            "message": {"type": ["string", "null"], "maxLength": 2_000},
        },
        "required": ["action", "target_player_id", "source_state_version", "message"],
    }
