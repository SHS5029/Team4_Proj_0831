"""외부 LLM 없이 게임 흐름을 재현하는 deterministic Provider."""

from __future__ import annotations

from backend.app.llm_provider.base import LLMProvider, LLMRequest, LLMResponse


class DeterministicFakeProvider(LLMProvider):
    """항상 같은 PASS proposal을 반환하는 게임 흐름 전용 fake다."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """요청 내용이나 외부 상태에 의존하지 않는 고정 proposal을 반환한다."""

        return LLMResponse(
            provider="fake",
            model="deterministic-fake",
            output={
                "type": "PASS",
                "target_player_id": None,
                "message": None,
                "public_rationale": None,
            },
            finish_reason="stop",
        )
