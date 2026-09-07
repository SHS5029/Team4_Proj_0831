"""인간·AI 게임 행동 주체를 표현하는 내부 공통 계약."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase

ActorKind = Literal["HUMAN", "AGENT"]


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Engine command가 사용할 player와 저장 principal을 함께 고정한다.

    공개 API의 사용자 인증과 게임 안의 player identity는 서로 다른 값일 수
    있다. 특히 AI는 소유자 사용자를 대신하지만 행동 원장과 idempotency는 AI
    player 기준으로 남겨야 하므로 두 식별자를 분리해 보관한다.
    """

    kind: ActorKind
    owner_user_id: UUID
    player_id: UUID
    principal_id: UUID

    def __post_init__(self) -> None:
        """허용된 actor 종류와 빈 식별자를 생성 시점에 차단한다."""

        if self.kind not in {"HUMAN", "AGENT"}:
            raise ValueError("actor kind must be HUMAN or AGENT")
        for name, value in (
            ("owner_user_id", self.owner_user_id),
            ("player_id", self.player_id),
            ("principal_id", self.principal_id),
        ):
            if not isinstance(value, UUID):
                raise TypeError(f"{name} must be UUID")

    @classmethod
    def human(cls, *, owner_user_id: UUID, player_id: UUID) -> "ActorContext":
        """사용자 principal과 human player를 연결한다."""

        return cls(
            kind="HUMAN",
            owner_user_id=owner_user_id,
            player_id=player_id,
            principal_id=owner_user_id,
        )

    @classmethod
    def agent(cls, *, owner_user_id: UUID, player_id: UUID) -> "ActorContext":
        """소유자 게임 안의 AI player를 Agent principal로 연결한다."""

        return cls(
            kind="AGENT",
            owner_user_id=owner_user_id,
            player_id=player_id,
            principal_id=player_id,
        )

    @property
    def source(self) -> str:
        """action_submissions에 기록할 행동 출처를 반환한다."""

        return self.kind

    @property
    def principal_type(self) -> str:
        """idempotency·receipt에 사용할 principal 종류를 반환한다."""

        return "USER" if self.kind == "HUMAN" else "AGENT"


def validate_discussion_actor(
    *,
    state: object,
    window: Mapping[str, object] | None,
    actor: ActorContext,
    window_id: UUID | None,
) -> None:
    """human·AI 공통으로 현재 speech actor와 window를 검증한다.

    actor 종류별 인증은 호출 계층이 담당하고, 게임 안에서 실제로 발언할 수
    있는지에 대한 phase·window·순서 조건은 이 helper에서 동일하게 적용한다.
    """

    phase = getattr(state, "phase", None)
    if phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        raise ApiError(status_code=409, code="INVALID_PHASE", message="현재 발언 단계가 아닙니다.")
    if (
        window is None
        or window_id is None
        or UUID(str(window["id"])) != window_id
        or window.get("status") != "OPEN"
        or window.get("window_kind") != "SPEECH"
        or window.get("phase") != phase.value
        or UUID(str(window.get("turn_player_id"))) != actor.player_id
    ):
        raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 발언 차례가 아닙니다.")
