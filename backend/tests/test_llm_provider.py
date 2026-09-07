"""LLM Provider 공통 계약과 설정 선택을 검증한다."""

import pytest
import httpx
from uuid import UUID

from backend.app.core.config import Settings
from backend.app.llm_provider.base import LLMRequest
from backend.app.llm_provider.dummy import DummyProvider
from backend.app.llm_provider.errors import LLMResponseError, LLMTimeoutError
from backend.app.llm_provider.factory import get_llm_provider
from backend.app.llm_provider.local import _normalize_json_content
from backend.app.llm_provider.local import LocalProvider
from backend.app.llm_provider.schemas import (
    agent_proposal_schema,
    normalize_agent_proposal,
    parse_game_proposal,
    proposal_schema,
)


def _settings(**overrides: object) -> Settings:
    """Provider 테스트에서 공통으로 사용할 비밀값 없는 설정을 만든다."""

    values = {"database_url": "postgresql://app:synthetic@localhost/Team4_Proj"}
    values.update(overrides)
    return Settings(**values)


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


@pytest.mark.parametrize(
    "payload, expected_type",
    [
        (
            {
                "type": "SPEAK",
                "target_player_id": None,
                "message": "  공개 발언입니다.  ",
                "public_rationale": None,
            },
            "SPEAK",
        ),
        (
            {
                "type": "PASS",
                "target_player_id": None,
                "message": None,
                "public_rationale": None,
            },
            "PASS",
        ),
        (
            {
                "type": "NIGHT_ACTION",
                "target_player_id": "11111111-1111-4111-8111-111111111111",
                "message": None,
                "public_rationale": None,
            },
            "NIGHT_ACTION",
        ),
        (
            {
                "type": "VOTE",
                "target_player_id": "22222222-2222-4222-8222-222222222222",
                "message": None,
                "public_rationale": None,
            },
            "VOTE",
        ),
    ],
)
def test_normalize_agent_proposal_accepts_canonical_actions(
    payload: dict, expected_type: str
) -> None:
    """게임에서 사용하는 네 가지 proposal만 canonical 형식으로 통과시킨다."""

    proposal = normalize_agent_proposal(payload)

    assert proposal.type == expected_type
    if expected_type == "SPEAK":
        assert proposal.message == "공개 발언입니다."
    if expected_type in {"NIGHT_ACTION", "VOTE"}:
        assert isinstance(proposal.target_player_id, UUID)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "type": "SPEAK",
            "target_player_id": "11111111-1111-4111-8111-111111111111",
            "message": "발언",
            "public_rationale": None,
        },
        {
            "type": "SPEAK",
            "target_player_id": None,
            "message": None,
            "public_rationale": None,
        },
        {
            "type": "PASS",
            "target_player_id": None,
            "message": "설명",
            "public_rationale": None,
        },
        {
            "type": "NIGHT_ACTION",
            "target_player_id": None,
            "message": None,
            "public_rationale": None,
        },
        {
            "type": "VOTE",
            "target_player_id": "not-a-uuid",
            "message": None,
            "public_rationale": None,
        },
        {
            "type": "PASS",
            "target_player_id": None,
            "message": None,
            "public_rationale": None,
            "extra": True,
        },
    ],
)
def test_normalize_agent_proposal_rejects_invalid_actions(payload: dict) -> None:
    """누락·추가 field와 type별 금지 조합을 Engine 앞에서 차단한다."""

    with pytest.raises(LLMResponseError):
        normalize_agent_proposal(payload)


def test_normalize_agent_proposal_limits_speech_to_200_characters() -> None:
    """긴 모델 발언은 화면·이벤트 계약을 넘기지 않도록 거부한다."""

    payload = {
        "type": "SPEAK",
        "target_player_id": None,
        "message": "가" * 201,
        "public_rationale": None,
    }

    with pytest.raises(LLMResponseError):
        normalize_agent_proposal(payload)


def test_agent_proposal_schema_matches_speech_limit() -> None:
    """Provider에 전달하는 JSON schema와 Backend 정규화 제한을 일치시킨다."""

    assert agent_proposal_schema()["properties"]["message"]["maxLength"] == 200


class _FakeLocalResponse:
    """Local Provider 테스트에서 사용할 비밀정보 없는 HTTP 응답 double이다."""

    def __init__(self, body: dict, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://local.test/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("synthetic error", request=request, response=response)

    def json(self) -> dict:
        return self._body


class _FakeLocalClient:
    """Provider가 전송한 URL과 payload를 기록하는 비동기 HTTP client double이다."""

    response: _FakeLocalResponse
    calls: list[tuple[str, dict]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "_FakeLocalClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict) -> _FakeLocalResponse:
        self.calls.append((url, json))
        return self.response


def _llm_request() -> LLMRequest:
    """Local Provider 호출에 사용할 최소 synthetic request를 만든다."""

    return LLMRequest(
        messages=(({"role": "user", "content": "synthetic context"}),),
        response_schema=agent_proposal_schema(),
        max_output_tokens=128,
        timeout_seconds=3,
    )


@pytest.mark.asyncio
async def test_local_provider_sends_openai_compatible_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local endpoint에 최소 payload를 보내고 canonical JSON object를 받는다."""

    _FakeLocalClient.calls = []
    _FakeLocalClient.response = _FakeLocalResponse(
        {
            "id": "synthetic-response",
            "choices": [
                {
                    "message": {
                        "content": '{"type":"PASS","target_player_id":null,"message":null,"public_rationale":null}'
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    )
    monkeypatch.setattr("backend.app.llm_provider.local.httpx.AsyncClient", _FakeLocalClient)

    response = await LocalProvider("http://127.0.0.1:1234/v1", "synthetic-model").generate(
        _llm_request()
    )

    assert response.provider == "local"
    assert response.output["type"] == "PASS"
    url, payload = _FakeLocalClient.calls[0]
    assert url == "http://127.0.0.1:1234/v1/chat/completions"
    assert payload["model"] == "synthetic-model"
    assert payload["stream"] is False
    assert payload["max_tokens"] == 128
    assert payload["think"] is False
    assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_local_provider_converts_timeout_to_common_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local HTTP timeout을 Provider 공통 timeout 오류로 변환한다."""

    class TimeoutClient(_FakeLocalClient):
        async def post(self, _url: str, *, json: dict) -> _FakeLocalResponse:
            raise httpx.ReadTimeout("synthetic timeout")

    monkeypatch.setattr("backend.app.llm_provider.local.httpx.AsyncClient", TimeoutClient)

    with pytest.raises(LLMTimeoutError, match="timed out"):
        await LocalProvider("http://127.0.0.1:1234/v1", "synthetic-model").generate(
            _llm_request()
        )


@pytest.mark.asyncio
async def test_local_provider_rejects_non_json_model_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local 모델이 JSON이 아닌 자연어를 반환하면 응답 오류로 거부한다."""

    _FakeLocalClient.response = _FakeLocalResponse(
        {"choices": [{"message": {"content": "결과는 PASS입니다."}}]}
    )
    monkeypatch.setattr("backend.app.llm_provider.local.httpx.AsyncClient", _FakeLocalClient)

    with pytest.raises(LLMResponseError, match="structured response"):
        await LocalProvider("http://127.0.0.1:1234/v1", "synthetic-model").generate(
            _llm_request()
        )


@pytest.mark.asyncio
async def test_openai_reasoning_has_room_for_final_json_and_classifies_incomplete(monkeypatch):
    """400토큰을 추론에서 소진한 응답을 빈 JSON 오류로 뭉개지 않는다."""

    from types import SimpleNamespace
    from backend.app.llm_provider.openai_provider import OpenAIProvider
    calls = []
    response = SimpleNamespace(status="completed", output_text='{"type":"PASS"}', usage=None, id="synthetic")
    async def create(**kwargs):
        calls.append(kwargs)
        return response
    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        return SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr("openai.AsyncOpenAI", factory)
    provider = OpenAIProvider("synthetic-key", "gpt-5.6-luna")
    assert (await provider.generate(_llm_request())).output == {"type": "PASS"}
    assert calls[0]["reasoning"] == {"effort": "high"}
    assert calls[0]["max_output_tokens"] >= 4096
    assert calls[0]["store"] is False
    response.status = "incomplete"
    response.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    with pytest.raises(LLMResponseError) as caught:
        await provider.generate(_llm_request())
    assert caught.value.code == "LLM_INCOMPLETE"


@pytest.mark.parametrize("basis", ["PUBLIC_EVIDENCE", "NO_NEW_INFORMATION"])
def test_pass_accepts_only_public_basis_codes(basis):
    """자발적 PASS 사유는 허용 코드만 사용해 공개 추론 원문을 만들지 않는다."""

    assert normalize_agent_proposal({"type": "PASS", "public_rationale": basis}).public_rationale == basis
    with pytest.raises(LLMResponseError):
        normalize_agent_proposal({"type": "PASS", "public_rationale": "합성 비공개 원문"})


@pytest.mark.parametrize("name,code,expected", [
    ("AuthenticationError", None, "PROVIDER_AUTHENTICATION"),
    ("RateLimitError", None, "PROVIDER_RATE_LIMIT"),
    ("APITimeoutError", None, "PROVIDER_TIMEOUT"),
    ("NotFoundError", None, "PROVIDER_MODEL_UNAVAILABLE"),
    ("BadRequestError", "model_not_found", "PROVIDER_MODEL_UNAVAILABLE"),
])
def test_openai_failure_codes_preserve_safe_cause(name, code, expected):
    """SDK 오류 원문 대신 운영자가 구분할 수 있는 고정 원인만 전달한다."""

    from backend.app.agent.orchestrator import AgentOrchestrator
    from backend.app.llm_provider.errors import LLMProviderError
    from backend.app.llm_provider.openai_provider import _raise_openai_error
    error = type(name, (Exception,), {"code": code})("synthetic private payload")
    with pytest.raises(LLMProviderError) as caught:
        _raise_openai_error(error)
    assert "private" not in str(caught.value)
    assert AgentOrchestrator._failure_code(caught.value) == expected


@pytest.mark.asyncio
async def test_openai_non_reasoning_keeps_existing_request_contract(monkeypatch):
    """비추론 모델에는 지원하지 않는 reasoning 옵션을 보내지 않는다."""

    from types import SimpleNamespace
    from backend.app.llm_provider.openai_provider import OpenAIProvider
    calls = []
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text='{"type":"PASS"}', usage=None, id="synthetic")
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)))
    await OpenAIProvider("synthetic-key", "gpt-4.1-mini").generate(_llm_request())
    assert "reasoning" not in calls[0]
    assert calls[0]["max_output_tokens"] == 128
