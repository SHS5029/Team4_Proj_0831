"""FastMCP Prompt 등록 모듈."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mafia_game.integrations.engine_http import BackendContextClient


def register_prompts(mcp: FastMCP, backend: BackendContextClient) -> None:
    """최소 에이전트 지침 Prompt를 등록하고 본문 생성을 Backend에 위임한다."""

    @mcp.prompt(name="agent_instruction", description="AI 플레이어의 기본 행동 지침")
    async def agent_instruction(game_id: str = "", user_id: str = "") -> str:
        """Prompt 조합을 MCP에 중복 구현하지 않고 Backend 결과를 전달한다."""

        return await backend.get_prompt(
            "agent_instruction",
            {"game_id": game_id, "user_id": user_id},
        )
