"""FastMCP가 실제 게임 runtime을 호출하는 Backend 내부 adapter."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.core.errors import ApiError
from backend.app.schemas.command_schema import GameCommandRequest

router = APIRouter(prefix="/internal/mcp", tags=["mcp"])


class McpActionRequest(BaseModel):
    """MCP Tool 입력을 공개 GameCommand 입력으로 변환하기 위한 폐쇄형 schema."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["PASS", "SPEAK", "NIGHT_ACTION", "VOTE"]
    user_id: UUID
    game_id: UUID
    player_id: UUID | None = None
    expected_state_version: int = Field(ge=1)
    window_id: UUID
    target_player_id: UUID | None = None
    message: str | None = Field(default=None, max_length=200)
    idempotency_key: UUID


@router.get("/context")
def read_context(
    request: Request,
    game_id: UUID = Query(...),
    user_id: UUID = Query(...),
) -> dict[str, Any]:
    """요청 사용자가 소유한 실제 PostgreSQL 게임 snapshot을 반환한다."""

    snapshot = request.app.state.game_runtime.snapshot(user_id, game_id)
    return {"status": "ok", "source": "backend", "context": snapshot}


@router.get("/prompts/{name}")
def read_prompt(
    name: str,
    game_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
) -> dict[str, str]:
    """Agent가 실제 게임 command를 만들 때 지켜야 할 고정 지침을 반환한다."""

    if name != "agent_instruction":
        raise ApiError(
            status_code=404,
            code="PROMPT_NOT_FOUND",
            message="요청한 Prompt를 찾을 수 없습니다.",
        )
    del game_id, user_id
    return {
        "prompt": (
            "Backend가 제공한 게임 context만 사용하고, 하나의 허용된 proposal만 반환하세요. "
            "게임 상태 변경은 Backend command 검증을 통해서만 수행됩니다."
        )
    }


@router.post("/actions")
def submit_action(request: Request, payload: McpActionRequest) -> dict[str, Any]:
    """MCP action을 기존 PostgreSQL GameCommand service에 위임한다."""

    if payload.player_id is not None and payload.action == "PASS":
        result, replayed = request.app.state.game_runtime.agent_pass(
            payload.user_id,
            payload.game_id,
            payload.player_id,
            expected_state_version=payload.expected_state_version,
            window_id=payload.window_id,
        )
        return {
            "status": "accepted",
            "source": "backend",
            "accepted": True,
            "replayed": replayed,
            "result": result,
        }
    if payload.player_id is not None and payload.action == "SPEAK" and payload.message is not None:
        result, replayed = request.app.state.game_runtime.agent_speak(
            payload.user_id, payload.game_id, payload.player_id, payload.message,
            expected_state_version=payload.expected_state_version, window_id=payload.window_id,
        )
        return {"status": "accepted", "source": "backend", "accepted": True, "replayed": replayed, "result": result}
    if payload.player_id is not None and payload.action in {"NIGHT_ACTION", "VOTE"}:
        command_type = "SUBMIT_NIGHT_ACTION" if payload.action == "NIGHT_ACTION" else "SUBMIT_VOTE"
        command = GameCommandRequest(
            type=command_type,
            expected_state_version=payload.expected_state_version,
            window_id=payload.window_id,
            target_player_id=payload.target_player_id,
        )
        result, replayed = request.app.state.game_runtime.agent_action(
            payload.user_id, payload.game_id, payload.player_id, command, payload.idempotency_key
        )
        return {"status": "accepted", "source": "backend", "accepted": True, "replayed": replayed, "result": result}

    command_type = {
        "PASS": "PASS",
        "SPEAK": "SPEAK",
        "NIGHT_ACTION": "SUBMIT_NIGHT_ACTION",
        "VOTE": "SUBMIT_VOTE",
    }[payload.action]
    try:
        command = GameCommandRequest(
            type=command_type,
            expected_state_version=payload.expected_state_version,
            window_id=payload.window_id,
            target_player_id=payload.target_player_id,
            message=payload.message,
        )
    except ValidationError as error:
        raise ApiError(
            status_code=422,
            code="INVALID_REQUEST",
            message="MCP action 형식이 올바르지 않습니다.",
        ) from error

    result, replayed = request.app.state.game_runtime.command(
        payload.user_id,
        payload.game_id,
        command,
        payload.idempotency_key,
    )
    return {
        "status": "accepted",
        "source": "backend",
        "accepted": True,
        "replayed": replayed,
        "result": result,
    }
