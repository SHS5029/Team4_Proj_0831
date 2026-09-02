"""LLM Provider 공통 계약과 설정 선택을 검증한다."""

import pytest

from backend.app.core.config import Settings
from backend.app.llm_provider.base import LLMRequest
from backend.app.llm_provider.dummy import DummyProvider
from backend.app.llm_provider.errors import LLMResponseError
from backend.app.llm_provider.factory import get_llm_provider
from backend.app.llm_provider.local import _normalize_json_content
from backend.app.llm_provider.schemas import parse_game_proposal, proposal_schema


def _settings(**overrides: object) -> Settings:
    """Provider 테스트에서 공통으로 사용할 비밀값 없는 설정을 만든다."""

    values = {"database_url": "postgresql://app:synthetic@localhost/Team4_Proj"}
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_dummy_provider_keeps_scaffold_proposal_contract() -> None:
    """Dummy Provider가 네트워크 없이 현재 상태 버전을 보존하는지 검증한다."""

    response = await DummyProvider().generate(
        LLMRequest(
            messages=(({"role": "user", "content": "source_state_version=7"}),),
            response_schema=proposal_schema(),
            max_output_tokens=100,
            timeout_seconds=1,
        )
    )

    proposal = parse_game_proposal(response.output, expected_state_version=7)
    assert response.provider == "dummy"
    assert proposal.action == "PING"
    assert proposal.source_state_version == 7


@pytest.mark.parametrize("provider", ["dummy", "local"])
def test_factory_selects_non_remote_providers(provider: str) -> None:
    """외부 API key 없이 dummy와 local Provider를 조립한다."""

    selected = get_llm_provider(_settings(llm_provider=provider))
    assert selected.__class__.__name__ in {"DummyProvider", "LocalProvider"}


@pytest.mark.parametrize(
    "provider, field",
    [("openai", "openai_api_key"), ("gemini", "gemini_api_key")],
)
def test_factory_rejects_missing_selected_remote_key(provider: str, field: str) -> None:
    """선택된 원격 Provider의 key 누락을 비밀값 없이 거부한다."""

    with pytest.raises(ValueError, match="required"):
        get_llm_provider(_settings(llm_provider=provider, **{field: ""}))


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "PING", "target_player_id": None},
        {"action": "PING", "target_player_id": None, "source_state_version": 1, "extra": True},
        {"action": "PING", "target_player_id": "not-a-uuid", "source_state_version": 1},
    ],
)
def test_proposal_parser_rejects_untrusted_output(payload: dict) -> None:
    """모델의 누락·추가 필드와 잘못된 UUID를 차단한다."""

    with pytest.raises(LLMResponseError):
        parse_game_proposal(payload, expected_state_version=1)


def test_settings_hides_provider_keys_from_repr() -> None:
    """원격 API key가 설정 repr에 포함되지 않는지 검증한다."""

    secret = "synthetic-openai-key"  # noqa: S105
    settings = _settings(openai_api_key=secret)
    assert secret not in repr(settings)


def test_local_json_normalizer_accepts_one_code_fence_only() -> None:
    """Ollama의 단일 JSON code fence는 허용하고 설명이 섞인 응답은 보존한다."""

    assert _normalize_json_content("```json\n{}\n```") == "{}"
    assert _normalize_json_content("설명\n```json\n{}\n```") != "{}"
