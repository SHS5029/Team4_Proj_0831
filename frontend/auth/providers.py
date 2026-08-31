"""Provider presentation settings, kept separate from login UI code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    """UI metadata for one configured OIDC provider."""

    id: str
    display_name: str
    login_label: str
    unavailable_message: str


PROVIDERS: dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        id="google",
        display_name="Google",
        login_label="Google로 계속하기",
        unavailable_message="Google 로그인 설정이 아직 완료되지 않았어요.",
    ),
}


def get_provider(provider_id: str) -> OAuthProvider:
    """Return provider settings or fail early for an unsupported provider."""

    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError("지원하지 않는 로그인 제공자입니다.") from exc
