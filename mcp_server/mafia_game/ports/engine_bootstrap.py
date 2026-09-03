"""MCP session 활성화가 의존하는 Backend bootstrap consume 추상 경계다.

WU-M2의 domain·middleware는 HTTP 구현을 알지 않으며, 실제 Backend가 없을 때도
동일한 일회성 consume 성공·거부 계약을 fake port로 검증할 수 있어야 한다.
"""

from typing import Protocol


class EngineBootstrapPort(Protocol):
    """검증된 bootstrap과 opaque capability를 Backend에서 일회성 소비한다."""

    async def consume(self, bootstrap_token: str, capability: str) -> None:
        """정확한 성공 응답일 때만 반환하고 그 밖의 결과는 거부 예외로 변환한다."""

        ...
