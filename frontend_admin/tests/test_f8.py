import pytest

from frontend_admin.core.api_client import AdminApiClient, AdminApiError
from frontend_admin.core.models import reject_private_fields


ADMIN_ID = "83d40f36-e835-4a1d-88db-e59b6920b739"


def test_admin_client_uses_uuid_header_for_read_only_metrics() -> None:
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        return 200, b'{"data":{"games_created":1}}'

    AdminApiClient(user_id=ADMIN_ID, transport=transport).metrics()
    assert captured["request"].headers["X-user-id"] == ADMIN_ID


def test_admin_403_is_fail_closed() -> None:
    def transport(request, timeout):
        return 403, b'{"error":{"code":"ADMIN_ACCESS_DENIED"}}'

    with pytest.raises(AdminApiError) as error:
        AdminApiClient(user_id=ADMIN_ID, transport=transport).metrics()
    assert error.value.code == "ADMIN_ACCESS_DENIED"


def test_private_fields_are_rejected_instead_of_masked() -> None:
    with pytest.raises(ValueError, match="ADMIN_PRIVATE_FIELD"):
        reject_private_fields({"status": "IN_PROGRESS", "role": "MAFIA"})
