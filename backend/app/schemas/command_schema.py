"""공개 게임 command 요청의 폐쇄형 입력 타입."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CommandType = Literal[
    "BEGIN_GAME",
    "SPEAK",
    "PASS",
    "SUBMIT_NIGHT_ACTION",
    "SUBMIT_VOTE",
    "SAVE_AND_EXIT",
    "RESUME",
    "FAST_FORWARD",
]


class GameCommandRequest(BaseModel):
    """모든 게임 변경을 하나의 endpoint에서 받는 요청이다.

    command 종류별 필수 field는 schema가 아닌 service에서 phase와 함께
    확인한다. 같은 필드가 다른 command에서 재사용될 수 있고, 이 검증을
    service에 두어 HTTP·내부 Agent 경로가 동일한 규칙을 사용하게 한다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: CommandType
    expected_state_version: int = Field(ge=1)
    window_id: UUID | None = None
    target_player_id: UUID | None = None
    message: str | None = None


class CommandAcceptedData(BaseModel):
    """command 성공 시 snapshot 대신 반환하는 최소 결과다."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    command_type: CommandType
    accepted_state_version: int
    result_state_version: int
    sync_url: str
