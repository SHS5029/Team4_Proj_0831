"""Agent adapter 조합 root의 주입 경계를 검증한다."""

from backend.app.agent.orchestrator import AgentOrchestrator
from backend.app.core.config import Settings
from backend.app.llm_provider.dummy import DummyProvider
from backend.app.mcp.client import FakeAgentContextClient
from backend.app.services.game.runtime_factory import build_agent_orchestrator


class _Repository:
    """factory가 저장소를 생성하지 않고 전달하는지 확인하는 대역."""


def test_runtime_factory_injects_existing_llm_and_mcp_adapters() -> None:
    """factory가 설정 Provider와 호출자가 준 MCP client를 같은 orchestrator에 주입한다."""

    context_client = FakeAgentContextClient()
    repository = _Repository()

    orchestrator = build_agent_orchestrator(
        Settings(database_url="postgresql://synthetic:test@127.0.0.1:5432/synthetic", llm_provider="dummy"),
        repository=repository,  # type: ignore[arg-type]
        context_client=context_client,
    )

    assert isinstance(orchestrator, AgentOrchestrator)
    assert isinstance(orchestrator.provider, DummyProvider)
    assert orchestrator.repository is repository
    assert orchestrator.context_client is context_client
