"""read-only 관리자 API의 query 입력을 검증한다.

관리자 API는 화면이 보내는 값을 그대로 SQL이나 서비스에 전달하지 않는다.
목록의 상태·phase와 metrics의 기간을 이 경계에서 먼저 제한해 잘못된 조회가
일어나거나 지나치게 큰 범위를 한 번에 읽는 일을 막는다.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AdminStatus = Literal["IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"]
AdminPhase = Literal[
    "ROLE_REVEAL",
    "DAY_DISCUSSION",
    "NIGHT_ACTION",
    "DAY_VOTE",
    "REVOTE",
    "FINAL_DISCUSSION",
    "FINAL_ACCUSATION",
    "ENDED",
]


class AdminGameListQuery(BaseModel):
    """관리자 게임 목록의 허용된 필터와 페이지 크기다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: AdminStatus | None = None
    phase: AdminPhase | None = None
    cursor: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)


class AdminMetricsQuery(BaseModel):
    """관리자 통계 조회 기간이다. 최대 31일만 허용한다."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "AdminMetricsQuery":
        """시작·종료 순서와 최대 조회 기간을 검사한다."""

        if self.from_ is not None and self.from_.tzinfo is None:
            self.from_ = self.from_.replace(tzinfo=UTC)
        if self.to is not None and self.to.tzinfo is None:
            self.to = self.to.replace(tzinfo=UTC)
        if self.from_ is not None and self.to is not None:
            if self.from_ > self.to:
                raise ValueError("from must not be later than to")
            if (self.to - self.from_).total_seconds() > 31 * 24 * 60 * 60:
                raise ValueError("metrics range must not exceed 31 days")
        return self
