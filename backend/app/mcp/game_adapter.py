"""게임 흐름에서 사용할 얇은 MCP·LLM Agent adapter."""

from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import UUID, uuid4

from backend.app.llm_provider.base import LLMProvider, LLMRequest
from backend.app.llm_provider.schemas import agent_proposal_schema, normalize_agent_proposal
from backend.app.schemas.command_schema import GameCommandRequest


class GameCommandPort(Protocol):
    """검증된 AI command를 Backend 게임 업무 계층으로 전달하는 포트다."""

    def command(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]: ...


class GameContextAdapter(Protocol):
    """게임 context 조회와 action 전달만 담당하는 MCP 경계다."""

    async def read_context(self, *, game_id: UUID, player_id: UUID) -> dict[str, Any]: ...

    async def submit_action(
        self, *, game_id: UUID, player_id: UUID, action: dict[str, Any]
    ) -> dict[str, Any]: ...


class DeterministicGameAgent:
    """예약·lease·capability 없이 한 번의 AI 행동을 연결한다.

    게임 상태의 최종 검증과 저장은 Backend GameEngine에 남긴다. 이 adapter는
    context를 읽고 Provider proposal을 형식 검증한 뒤 action 경계로 전달할 뿐,
    DB transaction이나 게임 상태를 직접 변경하지 않는다.
    """

    def __init__(self, context: GameContextAdapter, provider: LLMProvider) -> None:
        self._context = context
        self._provider = provider

    async def run(self, *, game_id: UUID, player_id: UUID) -> dict[str, Any]:
        """context → deterministic Provider → Backend action 순서를 수행한다."""

        context = await self._context.read_context(game_id=game_id, player_id=player_id)
        response = await self._provider.generate(
            LLMRequest(
                messages=(
                    {"role": "system", "content": (
                        "정확히 JSON object 하나만 반환하세요. 설명·Markdown·추가 필드는 금지합니다. "
                        '형식은 {"type":"PASS|SPEAK|NIGHT_ACTION|VOTE",'
                        '"target_player_id":null,"message":null,"public_rationale":null} 입니다. '
                        "현재 speech turn에서는 PASS 또는 SPEAK만 선택하세요."
                    )},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False, sort_keys=True)},
                ),
                response_schema=agent_proposal_schema(),
                max_output_tokens=400,
                timeout_seconds=15,
            )
        )
        proposal = normalize_agent_proposal(response.output)
        return await self._context.submit_action(
            game_id=game_id,
            player_id=player_id,
            action=proposal.model_dump(mode="json"),
        )


class GameAgentCommandAdapter:
    """AI proposal을 공개 command와 같은 Backend 업무 계층으로 변환한다."""

    def __init__(self, command_port: GameCommandPort) -> None:
        self._command_port = command_port

    def submit(
        self,
        *,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        expected_state_version: int,
        window_id: UUID,
        proposal: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """proposal 형식만 변환하고 실제 phase·권한·target 검증은 Service에 위임한다."""

        normalized = normalize_agent_proposal(proposal)
        if normalized.type == "SPEAK":
            command_type = "SPEAK"
        elif normalized.type == "PASS":
            command_type = "PASS"
        else:
            command_type = normalized.type
        payload = GameCommandRequest(
            type=command_type,
            expected_state_version=expected_state_version,
            window_id=window_id,
            target_player_id=normalized.target_player_id,
            message=normalized.message,
        )
        return self._command_port.command(owner_user_id, game_id, payload, uuid4())
