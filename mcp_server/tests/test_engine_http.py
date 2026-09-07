"""Engine bootstrap consume adapter의 canonical HMAC와 응답 계약을 검증한다."""

import base64
import hashlib
import hmac
from uuid import UUID

import httpx
import pytest
from resource_fixtures import consume_payload

from mafia_game.core.security.errors import EngineConsumeDenied
from mafia_game.integrations.engine_http import HttpEngineBootstrapAdapter

NOW = 1_788_352_496
ENGINE_SECRET = "synthetic-engine-hmac-secret-value"


@pytest.mark.anyio
async def test_consume_signs_exact_body_and_required_headers() -> None:
    captured: dict[str, object] = {}
    expected_response = consume_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(method=request.method, path=request.url.raw_path, body=request.content)
        body_hash = hashlib.sha256(request.content).hexdigest()
        canonical = "\n".join(
            [
                "POST",
                "/internal/v1/mcp-bootstrap/consume",
                "",
                body_hash,
                str(NOW),
                request.headers["X-Engine-Nonce"],
            ]
        )
        expected = base64.urlsafe_b64encode(
            hmac.new(ENGINE_SECRET.encode(), canonical.encode(), hashlib.sha256).digest()
        ).decode().rstrip("=")
        assert request.headers["X-Engine-Signature"] == expected
        assert request.headers["X-Agent-Capability"] == "synthetic-capability"
        parsed_nonce = UUID(request.headers["X-Engine-Nonce"])
        assert str(parsed_nonce) == request.headers["X-Engine-Nonce"]
        assert parsed_nonce.version == 4
        return httpx.Response(
            200, content=expected_response, headers={"Content-Type": "application/json"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = HttpEngineBootstrapAdapter(
            "https://engine.invalid", ENGINE_SECRET, client=client, clock=lambda: NOW
        )
        response_body = await adapter.consume("signed.bootstrap", "synthetic-capability")

    assert captured == {
        "method": "POST",
        "path": b"/internal/v1/mcp-bootstrap/consume",
        "body": b'{"bootstrap_token":"signed.bootstrap"}',
    }
    assert response_body == expected_response


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "content_type"),
    [
        (403, "application/json"),
        (201, "application/json"),
        (200, "text/plain"),
    ],
)
async def test_consume_rejects_denial_or_nonexact_success(
    status: int, content_type: str
) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            status,
            content=consume_payload(),
            headers={"Content-Type": content_type},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = HttpEngineBootstrapAdapter(
            "https://engine.invalid", ENGINE_SECRET, client=client, clock=lambda: NOW
        )
        with pytest.raises(EngineConsumeDenied):
            await adapter.consume("signed.bootstrap", "synthetic-capability")


@pytest.mark.parametrize(
    "url",
    [
        "https://user@engine.invalid",
        "https://user:password@engine.invalid",
    ],
)
def test_engine_url_rejects_userinfo(url: str) -> None:
    with pytest.raises(ValueError, match="userinfo"):
        HttpEngineBootstrapAdapter(url, ENGINE_SECRET)


@pytest.mark.anyio
async def test_owned_client_ignores_proxy_env_and_injected_client_is_not_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """소유 client만 proxy env를 차단하고 외부 주입 client의 lifecycle은 호출자에게 둔다."""

    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def aclose(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr("mafia_game.integrations.engine_http.httpx.AsyncClient", CapturingClient)
    owned = HttpEngineBootstrapAdapter("https://engine.invalid", ENGINE_SECRET)
    await owned.aclose()

    assert captured["trust_env"] is False
    assert captured["closed"] is True

    injected = CapturingClient()
    captured.pop("closed")
    adapter = HttpEngineBootstrapAdapter(
        "https://engine.invalid", ENGINE_SECRET, client=injected  # type: ignore[arg-type]
    )
    await adapter.aclose()

    assert "closed" not in captured
