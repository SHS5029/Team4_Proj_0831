"""Fail-closed authorization gates shared by Streamlit pages."""

from __future__ import annotations

from auth.identity import is_external_user_logged_in

APPLICATION_ACCESS_SESSION_KEY = "application-access-granted"


def should_process_external_user(
    user: object,
    *,
    oidc_configuration_ready: bool,
) -> bool:
    """Trust an OIDC cookie only while the server configuration is valid."""

    return oidc_configuration_ready and is_external_user_logged_in(user)

