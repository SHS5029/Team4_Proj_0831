from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID

import pytest

from frontend_user.auth.identity import IdentityProfile
from frontend_user.core.api_client import (
    ApiClientConfigurationError,
    BackendApiConfig,
    IdentityApiClient,
    InactiveIdentityError,
)

INTERNAL_SECRET = "synthetic-internal-signing-secret-32-characters"  # noqa: S105
REQUEST_ID = UUID("9851419a-a796-4f1a-8d0f-786b113fc56d")
USER_ID = UUID("83d40f36-e835-4a1d-88db-e59b6920b739")


def _identity() -> IdentityProfile:
    return IdentityProfile(
        provider="google",
        provider_subject="opaque-subject",
        email="traveler@example.com",
        email_verified=True,
        display_name="여행자",
        avatar_url="https://example.com/avatar.png",
    )


def test_client_signs_the_exact_transmitted_body() -> None:
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return 200, json.dumps(
            {
                "user_id": str(USER_ID),
                "email": "traveler@example.com",
                "display_name": "여행자",
                "avatar_url": "https://example.com/avatar.png",
                "is_active": True,
            }
        ).encode()

    client = IdentityApiClient(
        BackendApiConfig(
            api_url="http://127.0.0.1:8000",
            internal_api_secret=INTERNAL_SECRET,
        ),
        transport=transport,
        clock=lambda: 1_700_000_000,
        request_id_factory=lambda: REQUEST_ID,
    )

    user = client.provision_identity(_identity())

    request = captured["request"]
    body = request.data
    canonical = f"1700000000.{REQUEST_ID}.".encode() + body
    expected = hmac.new(INTERNAL_SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    assert request.headers["X-internal-signature"] == expected
    assert json.loads(body)["provider_subject"] == "opaque-subject"
    assert user.user_id == USER_ID
    assert captured["timeout"] == 5.0


def test_inactive_backend_error_has_a_dedicated_type() -> None:
    def transport(request, timeout):
        return 403, b'{"code":"INACTIVE_USER"}'

    client = IdentityApiClient(
        BackendApiConfig(
            api_url="http://localhost:8000",
            internal_api_secret=INTERNAL_SECRET,
        ),
        transport=transport,
    )

    with pytest.raises(InactiveIdentityError):
        client.provision_identity(_identity())


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("http://example.com:8000", INTERNAL_SECRET),
        ("https://user:password@example.com", INTERNAL_SECRET),
        ("http://localhost:8000", "too-short"),
    ],
)
def test_client_rejects_unsafe_or_incomplete_configuration(url: str, secret: str) -> None:
    with pytest.raises(ApiClientConfigurationError):
        BackendApiConfig(api_url=url, internal_api_secret=secret)
