"""단순화된 게임 Agent adapter의 context·LLM·action 경계를 검증한다."""

from uuid import UUID

import pytest

from backend.app.llm_provider.fake import DeterministicFakeProvider
from backend.app.mcp.game_adapter import DeterministicGameAgent, GameAgentCommandAdapter
from backend.app.schemas.command_schema import GameCommandRequest


class FakeGameContext:
    """MCP process 대신 호출 순서와 전달 payload를 기록하는 fake다."""

    def __init__(self) -> None:
        self.context_calls = []
        self.action_calls = []

    async def read_context(self, *, game_id: UUID, player_id: UUID):
        self.context_calls.append((game_id, player_id))
        return {"game_id": str(game_id), "player_id": str(player_id), "phase": "DAY_DISCUSSION"}

    async def submit_action(self, *, game_id: UUID, player_id: UUID, action: dict):
        self.action_calls.append((game_id, player_id, action))
        return {"accepted": True, "action": action}


class FakeCommandPort:
    """공개 command service 대신 변환된 payload를 확인하는 fake다."""

    def __init__(self) -> None:
        self.calls = []

    def command(self, owner_user_id, game_id, payload: GameCommandRequest, idempotency_key):
        self.calls.append((owner_user_id, game_id, payload, idempotency_key))
        return {"command_type": payload.type}, False


@pytest.mark.anyio
async def test_deterministic_game_agent_uses_one_context_and_one_action_call():
    """Agent가 예약·lease 없이 context 조회와 action 전달만 수행하는지 확인한다."""

    context = FakeGameContext()
    game_id = UUID(int=1)
    player_id = UUID(int=2)
    result = await DeterministicGameAgent(context, DeterministicFakeProvider()).run(
        game_id=game_id,
        player_id=player_id,
    )

    assert result["accepted"] is True
    assert context.context_calls == [(game_id, player_id)]
    assert context.action_calls[0][2]["type"] == "PASS"


def test_game_agent_command_adapter_reuses_backend_command_contract():
    """AI proposal이 별도 상태 변경 없이 공개 command payload로 변환되는지 확인한다."""

    port = FakeCommandPort()
    game_id = UUID(int=10)
    owner_id = UUID(int=11)
    result, replayed = GameAgentCommandAdapter(port).submit(
        owner_user_id=owner_id,
        game_id=game_id,
        player_id=UUID(int=12),
        expected_state_version=2,
        window_id=UUID(int=13),
        proposal={
            "type": "PASS",
            "target_player_id": None,
            "message": None,
            "public_rationale": None,
        },
    )

    assert result == {"command_type": "PASS"}
    assert replayed is False
    assert port.calls[0][2].type == "PASS"
    assert port.calls[0][2].expected_state_version == 2
