"""Agent Manager가 의존하는 MCP context transport 계약.

B6에서는 실제 MCP 서버를 직접 붙이지 않고 fake transport로 흐름을 검증한다. 실제
Streamable HTTP initialize·HMAC·bootstrap·session 연결은 B7에서 구현하며, MCP
runtime이 DB나 Redis를 직접 만지는 구조는 이 파일에 넣지 않는다.
"""

from __future__ import annotations

from typing import Any, Protocol


class AgentContextClient(Protocol):
    """Agent Manager가 필요한 최소 MCP context 조회 계약."""

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """현재 job에 묶인 audience context를 반환한다."""

    async def close(self) -> None:
        """job 종료 시 session을 닫는다."""


class FakeAgentContextClient:
    """외부 네트워크 없이 B6를 테스트하는 fake MCP transport."""

    def __init__(self, context: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.context = context or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """capability 원문을 저장·출력하지 않고 호출 사실만 기록한다."""

        self.calls.append(("<opaque>", scope))
        if self.error:
            raise self.error
        return dict(self.context)

    async def close(self) -> None:
        """fake session 종료 상태만 기록한다."""

        self.closed = True
