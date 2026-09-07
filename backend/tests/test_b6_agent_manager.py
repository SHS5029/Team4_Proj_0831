"""B6 Agent Manager, projection과 fallback의 경계 테스트."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from backend.app.agent.orchestrator import AgentJobSpec, AgentOrchestrator
from backend.app.agent.projections import build_context
from backend.app.llm_provider.base import LLMResponse
from backend.app.llm_provider.dummy import DummyProvider
from backend.app.llm_provider.schemas import NormalizedAgentProposal
from backend.app.mcp.client import FakeAgentContextClient
from backend.app.models.enums import GamePhase, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, PlayerState
from backend.app.repositories.agent_repository import AgentReservation, CapabilityGrant


GAME_ID = UUID(int=500)
PLAYER_ID = UUID(int=1)
WINDOW_ID = UUID(int=600)
NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def sample_state() -> GameState:
    """projection 테스트용 6명 상태를 비밀정보 없이 만든다."""

    players = [
        PlayerState(PLAYER_ID, 1, PlayerRole.CITIZEN, PlayerKind.AI, "AI 1"),
        PlayerState(UUID(int=2), 2, PlayerRole.MAFIA, PlayerKind.AI, "AI 2"),
        PlayerState(UUID(int=3), 3, PlayerRole.DETECTIVE, PlayerKind.AI, "AI 3"),
        PlayerState(UUID(int=4), 4, PlayerRole.DOCTOR, PlayerKind.AI, "AI 4"),
        PlayerState(UUID(int=5), 5, PlayerRole.CITIZEN, PlayerKind.AI, "AI 5"),
        PlayerState(UUID(int=6), 6, PlayerRole.CITIZEN, PlayerKind.HUMAN, "Human"),
    ]
    return GameState(game_id=GAME_ID, seed=b"b6-seed", players=players, phase=GamePhase.DAY_DISCUSSION)


class FakeRepository:
    """DB를 건드리지 않고 orchestrator의 fencing 흐름만 기록한다."""

    def __init__(self, now: datetime = NOW, lease_seconds: int = 15) -> None:
        self.now = now
        self.lease_seconds = lease_seconds
        self.completed: list[dict] = []
        self.revoked: list[str] = []

    def reserve_job(self, **kwargs):
        return AgentReservation(
            job_id=uuid4(), game_id=kwargs["game_id"], player_id=kwargs["player_id"],
            window_id=kwargs["window_id"], job_kind=kwargs["job_kind"],
            state_version=kwargs["state_version"], lease_token=uuid4(),
            lease_expires_at=self.now + timedelta(seconds=self.lease_seconds),
        )

    def issue_capability(self, reservation, **kwargs):
        raw = "opaque-test-capability"
        return CapabilityGrant(raw, "a" * 64, reservation.lease_expires_at)

    def complete_job(self, reservation, **kwargs):
        self.completed.append(kwargs)
        return True

    def revoke_capability(self, token_hash, **kwargs):
        self.revoked.append(token_hash)


class FakeProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        output = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return LLMResponse(provider="fake", model="fake", output=output)


@pytest.mark.asyncio
async def test_orchestrator_accepts_valid_proposal_and_closes_capability():
    repository = FakeRepository()
    provider = FakeProvider([{
        "type": "SPEAK",
        "target_player_id": None,
        "message": "공개된 사실을 다시 확인하겠습니다.",
        "public_rationale": "공개 정보만 사용",
    }])
    context_client = FakeAgentContextClient({"data": {"valid_targets": []}})
    result = await AgentOrchestrator(repository, provider, context_client, clock=lambda: NOW).run(
        AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "SPEECH", "DAY_DISCUSSION", 3)
    )
    assert result.status == "SUCCEEDED"
    assert result.proposal == NormalizedAgentProposal(
        type="SPEAK", message="공개된 사실을 다시 확인하겠습니다.", public_rationale="공개 정보만 사용"
    )
    assert repository.revoked == ["a" * 64]
    assert context_client.closed is True


@pytest.mark.asyncio
async def test_orchestrator_connects_fake_context_to_dummy_agent_provider():
    """실제 외부 서버 없이 Context 조회부터 Dummy proposal 완료까지 연결한다."""

    repository = FakeRepository()
    context_client = FakeAgentContextClient(
        {"data": {"public_events": [], "valid_targets": []}}
    )

    result = await AgentOrchestrator(
        repository,
        DummyProvider(),
        context_client,
        clock=lambda: NOW,
    ).run(AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "SPEECH", "DAY_DISCUSSION", 3))

    assert result.status == "SUCCEEDED"
    assert result.proposal == NormalizedAgentProposal(type="PASS")
    assert [scope for _, scope in context_client.calls] == ["public"]
    assert repository.completed[0]["status"] == "SUCCEEDED"
    assert repository.completed[0]["normalized_proposal"] == {
        "type": "PASS",
        "target_player_id": None,
        "message": None,
        "public_rationale": None,
    }
    assert context_client.closed is True


@pytest.mark.asyncio
async def test_target_action_converts_dummy_pass_to_first_valid_target():
    """밤·투표 작업은 PASS 대신 Context의 첫 합법 대상에 고정한다."""

    repository = FakeRepository()
    target = UUID(int=77)
    context_client = FakeAgentContextClient(
        {"data": {"valid_targets": [{"player_id": str(target)}]}}
    )

    result = await AgentOrchestrator(
        repository,
        DummyProvider(),
        context_client,
        clock=lambda: NOW,
    ).run(AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "NIGHT_ACTION", "NIGHT_ACTION", 3))

    assert result.status == "SUCCEEDED"
    assert result.proposal == NormalizedAgentProposal(
        type="NIGHT_ACTION", target_player_id=target
    )


@pytest.mark.asyncio
async def test_target_action_reads_valid_targets_from_canonical_action_window():
    """실제 MCP snapshot의 action_window 대상도 사용할 수 있는지 검증한다."""

    repository = FakeRepository()
    target = UUID(int=78)
    context_client = FakeAgentContextClient(
        {"action_window": {"valid_targets": [{"player_id": str(target)}]}}
    )

    result = await AgentOrchestrator(
        repository,
        DummyProvider(),
        context_client,
        clock=lambda: NOW,
    ).run(AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "NIGHT_ACTION", "NIGHT_ACTION", 3))

    assert result.proposal == NormalizedAgentProposal(
        type="NIGHT_ACTION", target_player_id=target
    )


@pytest.mark.asyncio
async def test_target_action_fallback_reads_canonical_action_window():
    """MCP·LLM 오류 fallback에서도 실제 snapshot의 합법 대상을 사용한다."""

    class BrokenProvider:
        async def generate(self, request):
            raise RuntimeError("synthetic provider failure")

    target = UUID(int=79)
    result = await AgentOrchestrator(
        FakeRepository(),
        BrokenProvider(),
        FakeAgentContextClient(
            {"action_window": {"valid_targets": [{"player_id": str(target)}]}}
        ),
        clock=lambda: NOW,
    ).run(AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "NIGHT_ACTION", "NIGHT_ACTION", 3))

    assert result.status == "FALLBACK"
    assert result.proposal == NormalizedAgentProposal(
        type="NIGHT_ACTION", target_player_id=target
    )


@pytest.mark.asyncio
async def test_invalid_provider_response_is_retried_once_then_speech_passes():
    repository = FakeRepository()
    provider = FakeProvider([{"unexpected": True}, {"still": "invalid"}])
    context_client = FakeAgentContextClient({"data": {"valid_targets": []}})
    result = await AgentOrchestrator(repository, provider, context_client, clock=lambda: NOW).run(
        AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "SPEECH", "DAY_DISCUSSION", 3)
    )
    assert result.status == "FALLBACK"
    assert result.failure_code == "PROPOSAL_INVALID"
    assert result.proposal is not None and result.proposal.type == "PASS"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_lease_expiry_discards_late_provider_result():
    repository = FakeRepository(lease_seconds=15)
    provider = FakeProvider([{
        "type": "PASS", "target_player_id": None, "message": None, "public_rationale": None,
    }])
    context_client = FakeAgentContextClient({"data": {"valid_targets": []}})
    clock_values = iter([NOW, NOW, NOW + timedelta(seconds=16), NOW + timedelta(seconds=16), NOW + timedelta(seconds=16)])
    result = await AgentOrchestrator(repository, provider, context_client, clock=lambda: next(clock_values)).run(
        AgentJobSpec(GAME_ID, PLAYER_ID, WINDOW_ID, "SPEECH", "DAY_DISCUSSION", 3)
    )
    # Provider 응답 자체는 정상이어도, 결과를 반영하는 순간 lease가 만료되면
    # fencing 규칙에 따라 외부 결과를 버려야 한다.
    assert result.status == "STALE"


def test_public_projection_does_not_change_with_subject_and_me_is_private():
    state = sample_state()
    first = build_context(state, subject_type="AI_PLAYER", subject_id=PLAYER_ID, scope="public")
    second = build_context(state, subject_type="AI_PLAYER", subject_id=UUID(int=2), scope="public")
    assert first["data"] == second["data"]
    assert "role" not in first["data"]["players"][0]

    private = build_context(
        state,
        subject_type="AI_PLAYER",
        subject_id=PLAYER_ID,
        scope="me",
        facts={"alibi": "도서관에 있었습니다.", "observation": "창문이 열려 있었습니다."},
    )
    assert private["data"]["role"] == "CITIZEN"
    assert "role" not in private["data"].get("players", {})


def test_gm_cannot_read_ai_private_scope():
    state = sample_state()
    with pytest.raises(PermissionError, match="CAPABILITY_DENIED"):
        build_context(state, subject_type="GM", subject_id=GAME_ID, scope="me")
