"""참조 프로젝트와 같은 FastMCP 기반 게임 연결 뼈대 서버다."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .config import MCP_HOST, MCP_PORT

ALLOWED_MCP_HOST = f"{MCP_HOST}:{MCP_PORT}"

mcp = FastMCP(
    "ai-mafia-game",
    instructions="AI 마피아 게임 context와 상태 변경 proposal을 제공하는 서버입니다.",
    host=MCP_HOST,
    port=MCP_PORT,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[ALLOWED_MCP_HOST, "localhost:" + str(MCP_PORT), "testserver"],
        allowed_origins=["http://testserver"],
    ),
)


@mcp.tool()
def game_ping(expected_version: int) -> dict[str, Any]:
    """Backend와 MCP 연결을 확인하고 상태를 변경하지 않는다."""

    return {"accepted": True, "action": "PING", "state_version": expected_version}


@mcp.tool()
def game_get_context(game_id: str, state_version: int) -> dict[str, Any]:
    """뼈대 단계의 공개 dummy context를 반환한다."""

    return {"schema_version": "scaffold-v1", "game_id": game_id, "phase": "ROLE_REVEAL", "state_version": state_version, "players": []}


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


# FastMCP가 생성한 ASGI 앱을 직접 사용해 transport와 세션 수명주기를
# FastMCP가 일관되게 관리한다. 별도 FastAPI wrapper는 두지 않는다.
streamable_http_app = mcp.streamable_http_app()
