"""뼈대 게임 MCP 서버와 통신하는 최소 HTTP client다."""

import os
from typing import Any

import httpx


class GameMcpClient:
    """MCP 서버의 health와 smoke tool을 호출한다."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("MAFIA_MCP_URL", "http://127.0.0.1:8010/mcp")).rstrip("/")

    async def health(self) -> dict[str, Any]:
        """HTTP health가 아닌 MCP initialize protocol로 연결을 확인한다."""

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as error:
            raise RuntimeError("mcp 패키지가 필요합니다.") from error
        async with streamable_http_client(self.base_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("game_ping", {"expected_version": 1})
        if result.isError:
            raise RuntimeError("MCP health tool failed")
        return {"status": "connected", "server": "game", "transport": "streamable-http"}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """참조 프로젝트와 같은 MCP ClientSession으로 Tool을 호출한다."""

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as error:
            raise RuntimeError("mcp 패키지가 필요합니다.") from error
        async with streamable_http_client(self.base_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError("MCP tool call failed")
        return {"content": [{"type": "text", "text": item.text} for item in result.content if hasattr(item, "text")]}
