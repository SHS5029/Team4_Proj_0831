from __future__ import annotations

import json
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, get_settings
from backend.app.infrastructure.security.internal_request import calculate_signature
from backend.app.main import create_app
from backend.app.models.identity import ExternalIdentity, InactiveUserError, UserRecord
from backend.app.routers.identity_router import get_identity_service

INTERNAL_SECRET = "synthetic-internal-signing-secret-32-characters"  # noqa: S105
USER_ID = UUID("83d40f36-e835-4a1d-88db-e59b6920b739")


@dataclass
class FakeIdentityService:
    result: UserRecord | Exception
    calls: int = 0

    def provision(self, identity: ExternalIdentity) -> UserRecord:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _user(*, active: bool = True) -> UserRecord:
    return UserRecord(
        id=USER_ID,
        email="traveler@example.com",
        display_name="여행자",
        avatar_url="https://example.com/avatar.png",
        is_active=active,
    )


def _client(service: FakeIdentityService) -> TestClient:
    app = create_app()
    settings = Settings(
        database_url="postgresql://app:synthetic@localhost:5432/Team4_Proj",
        internal_api_secret=INTERNAL_SECRET,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_identity_service] = lambda: service
    return TestClient(app)


def _body(*, email_verified: bool = True) -> bytes:
    return json.dumps(
        {
            "provider": "google",
            "provider_subject": "opaque-subject",
            "email": "traveler@example.com",
            "email_verified": email_verified,
            "display_name": "여행자",
            "avatar_url": "https://example.com/avatar.png",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _headers(body: bytes, *, timestamp: int | None = None, signature: str | None = None):
    timestamp_text = str(timestamp if timestamp is not None else int(time.time()))
    request_id = str(uuid4())
    signed = signature or calculate_signature(
        secret=INTERNAL_SECRET.encode(),
        timestamp=timestamp_text,
        request_id=request_id,
        body=body,
    )
    return {
        "Content-Type": "application/json",
        "X-Internal-Timestamp": timestamp_text,
        "X-Internal-Request-Id": request_id,
        "X-Internal-Signature": signed,
    }


def test_health_endpoint_reports_process_status() -> None:
    response = _client(FakeIdentityService(_user())).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_hmac_request_provisions_identity() -> None:
    service = FakeIdentityService(_user())
    body = _body()

    response = _client(service).post(
        "/api/v1/identity/provision",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(USER_ID),
        "email": "traveler@example.com",
        "display_name": "여행자",
        "avatar_url": "https://example.com/avatar.png",
        "is_active": True,
    }
    assert service.calls == 1


def test_invalid_signature_is_rejected_before_service_call() -> None:
    service = FakeIdentityService(_user())
    body = _body()

    response = _client(service).post(
        "/api/v1/identity/provision",
        content=body,
        headers=_headers(body, signature="0" * 64),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_INTERNAL_SIGNATURE"
    assert service.calls == 0


def test_expired_timestamp_is_rejected_before_service_call() -> None:
    service = FakeIdentityService(_user())
    body = _body()

    response = _client(service).post(
        "/api/v1/identity/provision",
        content=body,
        headers=_headers(body, timestamp=int(time.time()) - 301),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_INTERNAL_SIGNATURE"
    assert service.calls == 0


def test_unverified_email_is_rejected_without_service_call() -> None:
    service = FakeIdentityService(_user())
    body = _body(email_verified=False)

    response = _client(service).post(
        "/api/v1/identity/provision",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IDENTITY"
    assert service.calls == 0


def test_inactive_user_returns_fixed_forbidden_error() -> None:
    service = FakeIdentityService(InactiveUserError())
    body = _body()

    response = _client(service).post(
        "/api/v1/identity/provision",
        content=body,
        headers=_headers(body),
    )

    payload = response.json()
    assert response.status_code == 403
    assert payload["code"] == "INACTIVE_USER"
    assert set(payload) == {"code", "message", "details", "trace_id"}


def test_database_failure_returns_safe_unavailable_error() -> None:
    service = FakeIdentityService(RuntimeError("secret database detail"))
    body = _body()

    response = _client(service).post(
        "/api/v1/identity/provision",
        content=body,
        headers=_headers(body),
    )

    payload = response.json()
    assert response.status_code == 503
    assert payload["code"] == "IDENTITY_PERSISTENCE_UNAVAILABLE"
    assert "secret database detail" not in response.text
