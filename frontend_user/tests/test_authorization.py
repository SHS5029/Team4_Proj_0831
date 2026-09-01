from frontend_user.auth.authorization import should_process_external_user


def test_logged_in_cookie_is_not_trusted_when_oidc_configuration_is_invalid() -> None:
    forged_or_stale_user = {"is_logged_in": True, "sub": "untrusted-subject"}

    assert (
        should_process_external_user(
            forged_or_stale_user,
            oidc_configuration_ready=False,
        )
        is False
    )


def test_logged_in_user_requires_a_ready_oidc_configuration() -> None:
    user = {"is_logged_in": True}

    assert should_process_external_user(user, oidc_configuration_ready=True) is True
    assert should_process_external_user({}, oidc_configuration_ready=True) is False
