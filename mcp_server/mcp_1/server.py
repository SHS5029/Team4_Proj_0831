"""참조 프로젝트와 같은 FastMCP 기반 게임 연결 뼈대 서버다."""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from .config import MCP_HOST, MCP_PORT

mcp = FastMCP(
    "ai-mafia-game",
    instructions="AI 마피아 게임 context와 상태 변경 proposal을 제공하는 서버입니다.",
    host=MCP_HOST,
    port=MCP_PORT,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def game_ping(expected_version: int) -> dict[str, Any]:
    """Backend와 MCP 연결을 확인하고 상태를 변경하지 않는다."""

    return {"accepted": True, "action": "PING", "state_version": expected_version}


@mcp.tool()
def game_get_context() -> dict[str, Any]:
    """뼈대 단계의 공개 dummy context를 반환한다."""

    return {"schema_version": "scaffold-v1", "phase": "ROLE_REVEAL", "state_version": 1, "players": []}


@mcp.tool()
def game_submit_proposal(action: str, expected_version: int) -> dict[str, Any]:
    """허용된 PING proposal만 반환하고 게임 상태는 변경하지 않는다."""

    if action != "PING":
        raise ValueError("MCP_INVALID_ACTION")
    return {"proposal_id": "00000000-0000-4000-8000-000000000099", "action": action, "state_version": expected_version, "accepted": True}


@mcp.resource("mafia://games/scaffold/context")
def scaffold_context() -> dict[str, Any]:
    """Resource 호출용 dummy context를 반환한다."""

    return {"schema_version": "scaffold-v1", "phase": "ROLE_REVEAL", "state_version": 1, "players": []}


mcp_http_app = mcp.streamable_http_app()
app = FastAPI(title="AI Mafia Game MCP", version="scaffold-v1")


@app.get("/health")
def health() -> JSONResponse:
    """MCP 프로세스가 요청을 처리할 수 있음을 반환한다."""

    return JSONResponse({"status": "ok", "server": "game", "transport": "streamable-http"})


app.mount("/", mcp_http_app)
