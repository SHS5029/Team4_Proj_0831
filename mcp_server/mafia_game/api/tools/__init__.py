"""FastMCP Tool 등록 모듈."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mafia_game.integrations.engine_http import BackendContextClient


def register_tools(mcp: FastMCP, backend: BackendContextClient) -> None:
    """AI 행동 요청 Tool을 등록하고 실제 판정은 Backend에 위임한다."""

    @mcp.tool(name="submit_action", description="행동 payload를 Backend에 전달합니다.")
    async def submit_action(
        action: str,
        user_id: str,
        game_id: str,
        expected_state_version: int,
        window_id: str,
        idempotency_key: str,
        player_id: str | None = None,
        target_player_id: str | None = None,
        message: str | None = None,
    ) -> dict[str, object]:
        """행동의 유효성·권한·상태 변경을 직접 판단하지 않고 Backend에 전달한다."""

        return await backend.submit_action(
            action=action,
            user_id=user_id,
            game_id=game_id,
            player_id=player_id,
            expected_state_version=str(expected_state_version),
            window_id=window_id,
            idempotency_key=idempotency_key,
            target_player_id=target_player_id,
            message=message,
        )
