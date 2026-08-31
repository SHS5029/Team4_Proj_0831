"""Provider-neutral authentication domain models."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


class InactiveUserError(PermissionError):
    """Raised when a disabled local account attempts to sign in."""


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """A validated identity claim set received from an OIDC provider.

    The provider subject is the durable account key.  Email is profile data
    only and is never used to implicitly link accounts.
    """

    provider: str
    provider_subject: str
    email: str | None
    email_verified: bool
    display_name: str | None = None
    avatar_url: str | None = None

    def validate_for_login(self) -> None:
        if not self.provider.strip():
            raise ValueError("Identity provider is required")
        if not self.provider_subject.strip():
            raise ValueError("Identity provider subject is required")
        if not self.email_verified:
            raise ValueError("Identity email verification is required")
        if self.email is not None and not self.email.strip():
            raise ValueError("Identity email must not be blank")

    @property
    def normalized_provider(self) -> str:
        return self.provider.strip().lower()


@dataclass(frozen=True, slots=True)
class UserRecord:
    """The local user representation returned to the UI layer."""

    id: UUID
    email: str | None
    display_name: str | None
    avatar_url: str | None
    is_active: bool
