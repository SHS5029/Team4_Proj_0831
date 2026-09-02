"""OpenAI 호환 로컬 endpoint를 호출하는 Provider다."""

import json
import time
from typing import Any

import httpx

from backend.app.llm_provider.base import LLMProvider, LLMRequest, LLMResponse
from backend.app.llm_provider.errors import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)


class LocalProvider(LLMProvider):
    """LM Studio 등 OpenAI 호환 `/chat/completions` 서버용 adapter다."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """로컬 응답의 첫 message를 JSON object로 파싱한다."""

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": list(request.messages),
                        "max_tokens": request.max_output_tokens,
                    },
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.TimeoutException, httpx.ReadTimeout) as error:
            raise LLMTimeoutError("Local LLM request timed out") from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403}:
                raise LLMAuthenticationError("Local LLM authentication failed") from error
            if error.response.status_code == 429:
                raise LLMRateLimitError("Local LLM rate limit exceeded") from error
            raise LLMResponseError("Local LLM request failed") from error
        except httpx.HTTPError as error:
            raise LLMResponseError("Local LLM request failed") from error
        except (TypeError, ValueError) as error:
            raise LLMResponseError("Local LLM returned invalid JSON") from error

        try:
            content = body["choices"][0]["message"]["content"]
            output = json.loads(_normalize_json_content(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise LLMResponseError("Local LLM returned an invalid structured response") from error
        if not isinstance(output, dict):
            raise LLMResponseError("Local LLM response must be a JSON object")
        usage = body.get("usage") or {}
        return LLMResponse(
            provider="local",
            model=self.model,
            output=output,
            input_tokens=_token_count(usage, "prompt_tokens"),
            output_tokens=_token_count(usage, "completion_tokens"),
            finish_reason=_finish_reason(body),
            request_id=body.get("id"),
            latency_ms=int((time.perf_counter() - started) * 1_000),
        )


def _normalize_json_content(content: Any) -> str:
    """Ollama가 붙이는 단일 Markdown code fence만 제거한다.

    임의의 텍스트를 잘라내 JSON으로 추정하지 않는다. fence 안팎에 다른
    설명이 있으면 그대로 파싱에 실패하게 해 모델 출력 경계를 엄격히
    유지한다.
    """

    if not isinstance(content, str):
        raise LLMResponseError("Local LLM response content must be text")
    normalized = content.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1] == "```":
            normalized = "\n".join(lines[1:-1]).strip()
    return normalized


def _token_count(usage: Any, key: str) -> int | None:
    """호환 서버의 선택적 usage 값을 양의 정수로만 노출한다."""

    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and value >= 0 else None


def _finish_reason(body: Any) -> str | None:
    """호환 서버 응답에서 finish reason을 안전하게 꺼낸다."""

    try:
        value = body["choices"][0].get("finish_reason")
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) else None
