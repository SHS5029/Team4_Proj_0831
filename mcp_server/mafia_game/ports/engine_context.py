"""Resource service가 의존하는 내부 Engine context 추상 경계다."""

from typing import Protocol

from mafia_game.ports.engine_bootstrap import EngineBootstrapPort


class EngineContextPort(Protocol):
    """opaque capability로 scope 하나의 raw JSON을 매 요청 새로 조회한다."""

    async def get_context(self, scope: str, capability: str) -> bytes:
        """status·Content-Type을 통과한 body만 반환하고 payload를 보관하지 않는다."""

        ...


class EnginePort(EngineBootstrapPort, EngineContextPort, Protocol):
    """composition root가 consume과 context를 같은 서명 adapter로 조립하는 경계다."""
