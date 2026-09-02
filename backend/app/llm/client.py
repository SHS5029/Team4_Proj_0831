"""외부 모델 없이 연결 경계를 검증하는 LLM adapter."""

from dataclasses import dataclass
from uuid import UUID

import httpx

from backend.app.core.config import get_settings


@dataclass(frozen=True)
class DummyProposal:
    """Backend가 검증할 최소 구조화 proposal이다."""

    action: str
    target_player_id: UUID | None
    source_state_version: int


class DummyLLMAdapter:
    """결정적인 PING proposal만 반환하는 테스트용 provider다."""

    def propose(self, *, state_version: int) -> DummyProposal:
        """외부 API를 호출하지 않고 항상 같은 proposal을 만든다."""

        return DummyProposal("PING", None, state_version)


class LocalLLMAdapter:
    """OpenAI 호환 API를 제공하는 로컬 모델에 최소 proposal 요청을 보낸다."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def propose(self, *, state_version: int) -> DummyProposal:
        """로컬 모델의 JSON 응답을 검증해 게임 proposal로 변환한다."""

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "temperature": 0,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "JSON만 반환한다. action은 PING, target_player_id는 null로 한다."},
                    {"role": "user", "content": f"source_state_version={state_version}"},
                ],
            },
            timeout=10,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        import json
        payload = json.loads(content)
        proposal = DummyProposal(
            action=payload["action"],
            target_player_id=UUID(payload["target_player_id"]) if payload.get("target_player_id") else None,
            source_state_version=int(payload["source_state_version"]),
        )
        if proposal.action != "PING" or proposal.source_state_version != state_version:
            raise ValueError("로컬 LLM proposal이 scaffold-v1 계약과 일치하지 않습니다.")
        return proposal


def get_proposal_adapter():
    """환경 변수에 따라 dummy 또는 local adapter를 선택한다."""

    settings = get_settings()
    if settings.llm_provider == "local":
        return LocalLLMAdapter(settings.local_llm_base_url, settings.local_llm_model)
    if settings.llm_provider == "dummy":
        return DummyLLMAdapter()
    raise ValueError("scaffold-v1은 LLM_PROVIDER=dummy 또는 local만 지원합니다.")
