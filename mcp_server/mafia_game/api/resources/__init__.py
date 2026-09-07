"""FastMCP Resource 등록 모듈."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mafia_game.integrations.engine_http import BackendContextClient


def register_resources(mcp: FastMCP, backend: BackendContextClient) -> None:
    """공개 조회와 AI actor별 조회 URI를 등록하고 projection은 Backend에 위임한다."""

    @mcp.resource(
        "mafia://context/current/{game_id}/{user_id}",
        name="current_context",
        mime_type="application/json",
    )
    async def current_context(game_id: str, user_id: str) -> dict[str, Any]:
        """actor 없는 기존 URI는 Backend의 공개 scope만 읽는다."""

        return await backend.read_resource(
            f"mafia://context/current/{game_id}/{user_id}"
        )

    @mcp.resource(
        "mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}",
        name="scoped_context",
        mime_type="application/json",
    )
    async def scoped_context(
        game_id: str, user_id: str, player_id: str, scope: str
    ) -> dict[str, Any]:
        """AI actor와 scope를 전달하고 권한·응답 데이터의 최종 판정은 Backend에 맡긴다."""

        return await backend.read_resource(
            f"mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}"
        )
