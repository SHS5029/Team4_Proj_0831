"""Pure validation for Streamlit's native OIDC secrets structure."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class OidcConfigurationStatus:
    provider_id: str
    ready: bool
    missing_fields: tuple[str, ...]
    user_message: str


def _mapping_value(source: object, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _text_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_real_value(value: Any, *, minimum_length: int = 1) -> bool:
    text = _text_value(value)
    return len(text) >= minimum_length and not text.upper().startswith("REPLACE_")


def _is_valid_redirect_uri(value: Any) -> bool:
    candidate = _text_value(value)
    if not candidate:
        return False
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return False

    if not parsed.hostname or parsed.username or parsed.password:
        return False
    if port is not None and not 1 <= port <= 65_535:
        return False
    if parsed.path != "/oauth2callback" or parsed.query or parsed.fragment:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname == "localhost"


def _is_valid_metadata_url(value: Any) -> bool:
    candidate = _text_value(value)
    if not candidate or candidate.upper().startswith("REPLACE_"):
        return False
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and (port is None or 1 <= port <= 65_535)
    )


def inspect_oidc_configuration(
    secrets: object | None,
    *,
    provider: str,
) -> OidcConfigurationStatus:
    """Check required keys without returning or displaying any secret values."""

    auth = _mapping_value(secrets, "auth") if secrets is not None else None
    provider_config = _mapping_value(auth, provider)

    checks = (
        (
            "auth.redirect_uri",
            _is_valid_redirect_uri(_mapping_value(auth, "redirect_uri")),
        ),
        (
            "auth.cookie_secret",
            _is_real_value(_mapping_value(auth, "cookie_secret"), minimum_length=32),
        ),
        (
            f"auth.{provider}.client_id",
            _is_real_value(_mapping_value(provider_config, "client_id")),
        ),
        (
            f"auth.{provider}.client_secret",
            _is_real_value(_mapping_value(provider_config, "client_secret")),
        ),
        (
            f"auth.{provider}.server_metadata_url",
            _is_valid_metadata_url(
                _mapping_value(provider_config, "server_metadata_url")
            ),
        ),
    )
    missing_fields = tuple(name for name, is_valid in checks if not is_valid)

    if missing_fields:
        return OidcConfigurationStatus(
            provider_id=provider,
            ready=False,
            missing_fields=missing_fields,
            user_message="로그인 설정이 아직 완료되지 않았어요.",
        )

    return OidcConfigurationStatus(
        provider_id=provider,
        ready=True,
        missing_fields=(),
        user_message="안전한 Google 로그인을 사용할 수 있어요.",
    )
