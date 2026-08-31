from types import SimpleNamespace

import pytest
from auth.identity import (
    IdentityMappingError,
    IdentityProfile,
    is_external_user_logged_in,
    map_external_identity,
)


def test_google_claims_are_mapped_to_provider_neutral_profile() -> None:
    user = {
        "sub": "google-subject-123",
        "email": "traveler@example.com",
        "email_verified": True,
        "name": "김여행",
        "picture": "https://images.example.com/avatar.png",
    }

    profile = map_external_identity(user, provider="google")

    assert profile == IdentityProfile(
        provider="google",
        provider_subject="google-subject-123",
        email="traveler@example.com",
        email_verified=True,
        display_name="김여행",
        avatar_url="https://images.example.com/avatar.png",
    )


def test_attribute_based_streamlit_user_is_supported() -> None:
    user = SimpleNamespace(
        sub="subject-from-attributes",
        email="person@example.com",
        email_verified="true",
        name=None,
        picture=None,
    )

    profile = map_external_identity(user, provider="google")

    assert profile.display_name == "person"
    assert profile.email_verified is True


@pytest.mark.parametrize("missing_claim", ["sub", "email"])
def test_required_claims_fail_without_exposing_identity_data(
    missing_claim: str,
) -> None:
    claims = {
        "sub": "private-subject",
        "email": "private-person@example.com",
        "name": "민감한 이름",
    }
    claims.pop(missing_claim)

    with pytest.raises(IdentityMappingError) as exc_info:
        map_external_identity(claims, provider="google")

    message = str(exc_info.value)
    assert "private-subject" not in message
    assert "private-person@example.com" not in message
    assert "민감한 이름" not in message


def test_untrusted_or_non_https_avatar_is_dropped() -> None:
    profile = map_external_identity(
        {
            "sub": "subject",
            "email": "person@example.com",
            "picture": "javascript:alert(1)",
        },
        provider="google",
    )

    assert profile.avatar_url is None


def test_missing_streamlit_login_flag_is_treated_as_signed_out() -> None:
    assert is_external_user_logged_in({}) is False
    assert is_external_user_logged_in({"is_logged_in": True}) is True
    assert is_external_user_logged_in({"is_logged_in": "true"}) is False
