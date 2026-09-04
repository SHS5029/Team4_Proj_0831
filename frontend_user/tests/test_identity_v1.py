from uuid import UUID

from frontend_user.core.api_client import ApiClient, ApiClientConfigurationError
from frontend_user.core.identity import parse_uuid_v4
from frontend_user.core.session import get_identity, reset_identity_scope, set_identity


def test_parse_uuid_v4_accepts_only_version_four() -> None:
    assert parse_uuid_v4("83d40f36-e835-4a1d-88db-e59b6920b739") is not None
    assert parse_uuid_v4("83d40f36-e835-1a1d-88db-e59b6920b739") is None
    assert parse_uuid_v4("not-a-uuid") is None


def test_identity_scope_reset_removes_user_scoped_state() -> None:
    state: dict[str, object] = {
        "game.snapshot": {"private": "must disappear"},
        "navigation.page": "game",
        "form.action": "target",
        "feedback.draft": "text",
        "unrelated": "keep",
    }
    set_identity(user_id=UUID("83d40f36-e835-4a1d-88db-e59b6920b739"), persistence="LOCAL", session_state=state)
    reset_identity_scope(state)
    assert get_identity(state) is None
    assert state == {"unrelated": "keep"}


def test_api_client_sends_uuid_headers_without_hmac() -> None:
    captured: dict[str, object] = {}

    def transport(request, timeout):
        captured["request"] = request
        return 200, b'{"data": {"items": []}}'

    client = ApiClient(user_id="83d40f36-e835-4a1d-88db-e59b6920b739", transport=transport)
    client.get_games()
    request = captured["request"]
    assert request.headers["X-user-id"] == "83d40f36-e835-4a1d-88db-e59b6920b739"
    assert "Authorization" not in request.headers
    assert "X-internal-signature" not in request.headers


def test_api_client_rejects_public_http_endpoint() -> None:
    try:
        ApiClient(user_id="83d40f36-e835-4a1d-88db-e59b6920b739", api_url="http://example.com")
    except ApiClientConfigurationError:
        return
    raise AssertionError("공개 HTTP endpoint가 허용되었습니다.")
