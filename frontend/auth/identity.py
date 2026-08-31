"""Safe, provider-neutral mapping of Streamlit OIDC user claims."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from backend.app.auth.models import ExternalIdentity

_PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TRUE_VALUES = {"1", "true", "yes", "on"}


class IdentityMappingError(ValueError):
    """Raised when required claims cannot be mapped to a local identity."""


# The backend owns the domain model.  This semantic alias keeps the UI vocabulary
# readable without maintaining a second, subtly different identity contract.
IdentityProfile = ExternalIdentity


def _read_claim(source: object, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)

    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            return getter(name)
        except (KeyError, TypeError, ValueError):
            pass

    try:
        return getattr(source, name)
    except (AttributeError, KeyError, TypeError):
        return None


def _clean_text(value: Any, *, limit: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C")
    )
    return text[:limit]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return _clean_text(value, limit=12).casefold() in _TRUE_VALUES


def _safe_avatar_url(value: Any) -> str | None:
    candidate = _clean_text(value, limit=2048)
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return candidate


def is_external_user_logged_in(user: object) -> bool:
    """Safely read Streamlit's flag, which is absent without OIDC configuration."""

    return _read_claim(user, "is_logged_in") is True


def map_external_identity(
    user: object,
    *,
    provider: str,
) -> IdentityProfile:
    """Map ``st.user`` or equivalent claims without leaking raw claims in errors."""

    normalized_provider = _clean_text(provider, limit=64).casefold()
    if not _PROVIDER_PATTERN.fullmatch(normalized_provider):
        raise IdentityMappingError("로그인 제공자 정보를 확인할 수 없습니다.")

    provider_subject = _clean_text(_read_claim(user, "sub"), limit=512)
    if not provider_subject:
        raise IdentityMappingError("로그인 계정 식별 정보를 확인할 수 없습니다.")

    email = _clean_text(_read_claim(user, "email"), limit=320).casefold()
    if not email or "@" not in email:
        raise IdentityMappingError("로그인 계정 이메일을 확인할 수 없습니다.")

    display_name = _clean_text(_read_claim(user, "name"), limit=120)
    if not display_name:
        display_name = _clean_text(_read_claim(user, "given_name"), limit=120)
    if not display_name:
        display_name = email.split("@", maxsplit=1)[0][:120] or "여행자"

    return IdentityProfile(
        provider=normalized_provider,
        provider_subject=provider_subject,
        email=email,
        email_verified=_as_bool(_read_claim(user, "email_verified")),
        display_name=display_name,
        avatar_url=_safe_avatar_url(_read_claim(user, "picture")),
    )
