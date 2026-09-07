"""FastMCP Resource 등록 모듈."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mafia_game.integrations.engine_http import BackendContextClient


def register_resources(mcp: FastMCP, backend: BackendContextClient) -> None:
    """최소 공개 Resource를 등록하고 데이터 조회를 Backend에 위임한다."""

    @mcp.resource("mafia://context/current/{game_id}/{user_id}", name="current_context")
    async def current_context(game_id: str, user_id: str) -> dict[str, Any]:
        """현재 컨텍스트를 Backend에서 읽어 반환한다."""

        return await backend.read_resource(
            f"mafia://context/current/{game_id}/{user_id}"
        )
