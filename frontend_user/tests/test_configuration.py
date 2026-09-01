from frontend_user.auth.configuration import inspect_oidc_configuration


def test_complete_google_oidc_configuration_is_ready() -> None:
    status = inspect_oidc_configuration(
        {
            "auth": {
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "cookie_secret": "synthetic-cookie-secret-over-32-characters",
                "google": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "server_metadata_url": (
                        "https://accounts.google.com/.well-known/"
                        "openid-configuration"
                    ),
                },
            }
        },
        provider="google",
    )

    assert status.ready is True
    assert status.missing_fields == ()


def test_missing_configuration_reports_field_names_only() -> None:
    status = inspect_oidc_configuration(
        {
            "auth": {
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "cookie_secret": "",
                "google": {"client_id": "sensitive-client-id"},
            }
        },
        provider="google",
    )

    assert status.ready is False
    assert status.missing_fields == (
        "auth.cookie_secret",
        "auth.google.client_secret",
        "auth.google.server_metadata_url",
    )
    assert "sensitive-client-id" not in status.user_message


def test_absent_secrets_are_a_safe_configuration_error() -> None:
    status = inspect_oidc_configuration(None, provider="google")

    assert status.ready is False
    assert status.user_message == "로그인 설정이 아직 완료되지 않았어요."


def test_short_cookie_secret_and_example_placeholders_are_rejected() -> None:
    status = inspect_oidc_configuration(
        {
            "auth": {
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "cookie_secret": "too-short",
                "google": {
                    "client_id": "REPLACE_WITH_GOOGLE_CLIENT_ID",
                    "client_secret": "REPLACE_WITH_GOOGLE_CLIENT_SECRET",
                    "server_metadata_url": (
                        "https://accounts.google.com/.well-known/"
                        "openid-configuration"
                    ),
                },
            }
        },
        provider="google",
    )

    assert status.ready is False
    assert status.missing_fields == (
        "auth.cookie_secret",
        "auth.google.client_id",
        "auth.google.client_secret",
    )
    assert status.user_message == "로그인 설정이 아직 완료되지 않았어요."


def test_placeholder_cookie_secret_is_rejected_even_when_long_enough() -> None:
    status = inspect_oidc_configuration(
        {
            "auth": {
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "cookie_secret": "REPLACE_WITH_A_LONG_RANDOM_SECRET_VALUE",
                "google": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "server_metadata_url": (
                        "https://accounts.google.com/.well-known/"
                        "openid-configuration"
                    ),
                },
            }
        },
        provider="google",
    )

    assert status.ready is False
    assert status.missing_fields == ("auth.cookie_secret",)


def test_redirect_and_metadata_urls_must_be_safe_absolute_urls() -> None:
    base = {
        "auth": {
            "redirect_uri": "http://example.com/oauth2callback",
            "cookie_secret": "synthetic-cookie-secret-over-32-characters",
            "google": {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "server_metadata_url": "http://accounts.google.com/metadata",
            },
        }
    }

    status = inspect_oidc_configuration(base, provider="google")

    assert status.ready is False
    assert status.missing_fields == (
        "auth.redirect_uri",
        "auth.google.server_metadata_url",
    )


def test_https_redirect_requires_exact_oauth_callback_path() -> None:
    status = inspect_oidc_configuration(
        {
            "auth": {
                "redirect_uri": "https://travel.example.com/not-the-callback",
                "cookie_secret": "synthetic-cookie-secret-over-32-characters",
                "google": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "server_metadata_url": "https://accounts.google.com/metadata",
                },
            }
        },
        provider="google",
    )

    assert status.ready is False
    assert status.missing_fields == ("auth.redirect_uri",)
