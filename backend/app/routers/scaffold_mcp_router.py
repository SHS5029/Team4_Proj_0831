"""게임 MCP 연결 상태를 확인하는 Backend endpoint다."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.mcp.game_client import GameMcpClient

router = APIRouter(prefix="/api/v1/mcp", tags=["scaffold-mcp"])


@router.get("/health")
async def mcp_health() -> JSONResponse:
    """연결 성공 여부만 노출하고 MCP 내부 오류는 외부에 공개하지 않는다."""

    try:
        await GameMcpClient().health()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "disconnected", "server": "game", "transport": "streamable-http"})
    return JSONResponse(status_code=200, content={"status": "connected", "server": "game", "transport": "streamable-http"})
