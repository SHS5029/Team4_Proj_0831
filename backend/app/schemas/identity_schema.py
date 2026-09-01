"""Frontend가 전달하는 외부 identity를 Backend 경계에서 다시 검증한다."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from backend.app.models.identity import ExternalIdentity

_PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class IdentityProvisionRequest(BaseModel):
    """서명 검증 후에도 신뢰하지 않고 형식과 길이를 제한하는 요청 schema."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=64)
    provider_subject: str = Field(min_length=1, max_length=512)
    email: str | None = Field(default=None, max_length=320)
    email_verified: StrictBool
    display_name: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=2048)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        """설정·DB 식별자에 안전한 정규화 provider 코드만 허용한다."""

        normalized = value.casefold()
        if not _PROVIDER_PATTERN.fullmatch(normalized):
            raise ValueError("provider format is invalid")
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        """빈 값과 구조가 없는 이메일이 저장소로 넘어가지 않게 한다."""

        if value is None:
            return None
        normalized = value.casefold()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or not domain or "@" in domain:
            raise ValueError("email format is invalid")
        return normalized

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        """브라우저로 전달될 수 있는 아바타는 HTTPS 절대 URL만 허용한다."""

        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("avatar URL must use HTTPS")
        return value

    def to_domain(self) -> ExternalIdentity:
        """검증 완료 요청을 변경 불가능한 Backend 도메인 모델로 변환한다."""

        identity = ExternalIdentity(**self.model_dump())
        identity.validate_for_login()
        return identity
