from auth.identity import IdentityProfile
from ui import APP_CSS, GOOGLE_G_LOGO, profile_card_html


def test_google_logo_uses_official_brand_colors_and_is_decorative() -> None:
    assert 'aria-hidden="true"' in GOOGLE_G_LOGO
    assert "#4285F4" in GOOGLE_G_LOGO
    assert "#34A853" in GOOGLE_G_LOGO
    assert "#FBBC05" in GOOGLE_G_LOGO
    assert "#EA4335" in GOOGLE_G_LOGO


def test_theme_has_tokens_responsive_layout_and_keyboard_focus() -> None:
    assert "--color-ocean" in APP_CSS
    assert "--space-4" in APP_CSS
    assert "@media (max-width: 760px)" in APP_CSS
    assert ":focus-visible" in APP_CSS
    assert "prefers-reduced-motion" in APP_CSS


def test_profile_markup_escapes_external_identity_values() -> None:
    profile = IdentityProfile(
        provider="google",
        provider_subject="subject",
        email='person@example.com"><script>alert(1)</script>',
        email_verified=True,
        display_name="<img src=x onerror=alert(1)>",
        avatar_url=None,
    )

    markup = profile_card_html(profile)

    assert "<script>" not in markup
    assert "<img src=x" not in markup
    assert "&lt;script&gt;" in markup
    assert "&lt;img src=x" in markup
    assert 'aria-label="로그인한 사용자"' in markup
