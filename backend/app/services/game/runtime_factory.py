"""게임 runtime composition root.

Router와 애플리케이션 생성부가 개별 service·repository 조합을 알지 않도록
PostgreSQL runtime 생성을 한 곳에 둔다.
"""

from __future__ import annotations

from typing import Any

from backend.app.agent.orchestrator import AgentOrchestrator, AgentRepository
from backend.app.llm_provider.factory import get_llm_provider
from backend.app.mcp.client import AgentContextClient
from backend.app.services.game.postgres_runtime import PostgresGameRuntime


def build_postgres_runtime(settings: Any) -> PostgresGameRuntime:
    """운영 설정으로 PostgreSQL 정본 runtime을 조합한다."""

    return PostgresGameRuntime(settings)


def build_agent_orchestrator(
    settings: Any,
    *,
    repository: AgentRepository,
    context_client: AgentContextClient,
) -> AgentOrchestrator:
    """설정된 LLM과 호출자가 제공한 MCP context client를 Agent에 주입한다.

    이 factory는 provider·MCP 구현을 Agent 내부에서 생성하지 않게 하는 조합
    경계다. 실제 repository와 context client의 수명은 호출하는 application
    runtime이 관리하며, 이 함수는 새 DB transaction이나 transport를 만들지 않는다.
    """

    return AgentOrchestrator(
        repository=repository,
        provider=get_llm_provider(settings),
        context_client=context_client,
        max_output_tokens=settings.llm_max_output_tokens,
    )
