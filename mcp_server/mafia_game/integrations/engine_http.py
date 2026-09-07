"""Backend 내부 Engine bootstrap consume과 Resource context의 HTTP adapter다."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

from mafia_game.core.security.errors import (
    CapabilityDenied,
    DependencyUnavailable,
    EngineConsumeDenied,
    UpstreamContractViolation,
)

_CONSUME_PATH = "/internal/v1/mcp-bootstrap/consume"
_CONTEXT_PATH = "/internal/v1/agent-context"


class HttpEngineBootstrapAdapter:
    """API 8.1 HMAC으로 consume과 context를 보내는 단일 HTTP adapter다."""

    def __init__(
        self,
        engine_api_url: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("ENGINE_INTERNAL_API_SECRET must contain at least 32 characters")
        parsed = urlsplit(engine_api_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ENGINE_API_URL must be an absolute HTTP(S) base URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("ENGINE_API_URL must not include userinfo")
        if parsed.path not in {"", "/"}:
            raise ValueError("ENGINE_API_URL must not include a path")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("plain HTTP is allowed only for loopback development")
        self._base_url = engine_api_url.rstrip("/")
        self._secret = secret.encode("utf-8")
        # 내부 capability가 process proxy 환경으로 우회되지 않게 소유 client만 env를 무시한다.
        self._client = client or httpx.AsyncClient(
            timeout=10.0, trust_env=False, follow_redirects=False
        )
        self._owns_client = client is None
        self._clock = clock

    def _headers(
        self,
        *,
        method: str,
        path: str,
        query: list[tuple[str, str]],
        body: bytes,
        capability: str,
    ) -> dict[str, str]:
        """전송 byte와 같은 body hash·정렬 query로 요청마다 새 HMAC을 만든다."""

        encoded = sorted(
            (quote(key, safe="-._~"), quote(value, safe="-._~"))
            for key, value in query
        )
        canonical_query = "&".join(f"{key}={value}" for key, value in encoded)
        timestamp = str(int(self._clock()))
        nonce = str(uuid4())
        canonical = "\n".join(
            [
                method.upper(),
                path,
                canonical_query,
                hashlib.sha256(body).hexdigest(),
                timestamp,
                nonce,
            ]
        )
        signature = base64.urlsafe_b64encode(
            hmac.new(self._secret, canonical.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        return {
            "X-Engine-Timestamp": timestamp,
            "X-Engine-Nonce": nonce,
            "X-Engine-Signature": signature,
            "X-Agent-Capability": capability,
        }

    @staticmethod
    def _is_json(response: httpx.Response) -> bool:
        """charset parameter는 허용하되 JSON이 아닌 media type은 거부한다."""

        media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        return media_type.strip().lower() == "application/json"

    async def consume(self, bootstrap_token: str, capability: str) -> bytes:
        """raw body를 먼저 확정한 뒤 동일 byte hash를 서명하고 전송한다."""

        body = json.dumps(
            {"bootstrap_token": bootstrap_token}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        try:
            response = await self._client.post(
                f"{self._base_url}{_CONSUME_PATH}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    **self._headers(
                        method="POST",
                        path=_CONSUME_PATH,
                        query=[],
                        body=body,
                        capability=capability,
                    ),
                },
            )
        except httpx.HTTPError as error:
            raise EngineConsumeDenied from error
        if response.status_code != 200 or not self._is_json(response):
            raise EngineConsumeDenied
        return response.content

    async def get_context(self, scope: str, capability: str) -> bytes:
        """scope 하나를 정확히 한 번 GET하고 status와 media type만 먼저 분류한다."""

        try:
            response = await self._client.get(
                f"{self._base_url}{_CONTEXT_PATH}",
                params=[("scope", scope)],
                headers=self._headers(
                    method="GET",
                    path=_CONTEXT_PATH,
                    query=[("scope", scope)],
                    body=b"",
                    capability=capability,
                ),
            )
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as error:
            raise DependencyUnavailable from error
        except httpx.HTTPError as error:
            raise UpstreamContractViolation from error
        if response.status_code in {403, 404}:
            raise CapabilityDenied
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            raise DependencyUnavailable
        if response.status_code != 200 or not self._is_json(response):
            raise UpstreamContractViolation
        return response.content

    async def aclose(self) -> None:
        """composition root가 소유한 client만 shutdown 시 닫아 외부 주입 경계를 보존한다."""

        if self._owns_client:
            await self._client.aclose()
