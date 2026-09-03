"""Backend 내부 Engine bootstrap consume의 실제 HTTP adapter다."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from mafia_game.core.security.errors import EngineConsumeDenied

_CONSUME_PATH = "/internal/v1/mcp-bootstrap/consume"


class HttpEngineBootstrapAdapter:
    """API 8.1 canonical HMAC으로 consume을 보내고 정확한 성공 body만 허용한다."""

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
        self._client = client or httpx.AsyncClient(timeout=10.0, trust_env=False)
        self._owns_client = client is None
        self._clock = clock

    async def consume(self, bootstrap_token: str, capability: str) -> None:
        """raw body를 먼저 확정한 뒤 동일 byte hash를 서명하고 전송한다."""

        body = json.dumps(
            {"bootstrap_token": bootstrap_token}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        timestamp = str(int(self._clock()))
        nonce = str(uuid4())
        canonical = "\n".join(
            ["POST", _CONSUME_PATH, "", hashlib.sha256(body).hexdigest(), timestamp, nonce]
        )
        signature = base64.urlsafe_b64encode(
            hmac.new(self._secret, canonical.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        try:
            response = await self._client.post(
                f"{self._base_url}{_CONSUME_PATH}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Engine-Timestamp": timestamp,
                    "X-Engine-Nonce": nonce,
                    "X-Engine-Signature": signature,
                    "X-Agent-Capability": capability,
                },
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EngineConsumeDenied from error
        if response.status_code != 200 or payload != {"status": "CONSUMED"}:
            raise EngineConsumeDenied

    async def aclose(self) -> None:
        """composition root가 소유한 client만 shutdown 시 닫아 외부 주입 경계를 보존한다."""

        if self._owns_client:
            await self._client.aclose()
