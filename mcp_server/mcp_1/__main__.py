"""게임 MCP 서버를 uvicorn으로 실행한다."""

from .server import mcp


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
