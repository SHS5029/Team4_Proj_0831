"""내부 사용자 정보를 외부 identity 없이 반환하는 API 응답 schema."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.models.identity import UserRecord


class UserResponse(BaseModel):
    """Frontend가 접근 판정과 프로필 표시에 필요한 최소 사용자 필드."""

    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    email: str | None
    display_name: str | None
    avatar_url: str | None
    is_active: bool

    @classmethod
    def from_record(cls, record: UserRecord) -> "UserResponse":
        """저장소 읽기 모델에서 제공자 식별자를 제외한 응답을 만든다."""

        return cls(
            user_id=record.id,
            email=record.email,
            display_name=record.display_name,
            avatar_url=record.avatar_url,
            is_active=record.is_active,
        )
