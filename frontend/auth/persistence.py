"""신원 저장 결과를 공급자 중립적인 UI 상태로 표현하는 모듈.

저장소나 Streamlit을 직접 import하지 않는 순수 계층으로 유지해, DB 결과와 화면의
색상·재시도·접근 허용 정책을 한곳에서 일관되게 매핑한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# 저장 결과와 표현 톤을 닫힌 집합으로 제한해 새 상태 추가 시 매핑 누락을 드러낸다.
PersistenceState = Literal["saved", "unavailable", "failed", "blocked"]
FeedbackTone = Literal["success", "info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """저장 계층에서 UI로 전달하는 불변 결과와 안전한 사용자 안내 문구."""

    state: PersistenceState
    user_message: str


@dataclass(frozen=True, slots=True)
class PersistenceFeedback:
    """저장 결과에서 파생된 화면 표현과 접근 제어 결정."""

    tone: FeedbackTone
    retry_allowed: bool
    access_granted: bool


def should_refresh_persistence(
    cached_result: object,
    *,
    cached_identity_key: object,
    current_identity_key: str,
) -> bool:
    """성공 결과 뒤의 매 Streamlit 실행에서 DB 권한을 새로 확인한다.

    Streamlit은 위젯 상호작용마다 스크립트 전체를 다시 실행한다. 이전 저장 성공을
    영구 권한처럼 캐시하면 그 사이 비활성화된 로컬 계정도 계속 접근할 수 있으므로
    ``saved``는 항상 새 확인 대상으로 삼는다. 일시 실패는 사용자가 명시적으로
    재시도할 때까지 유지해 매 재실행의 DB 중복 요청을 피한다. 사용자 식별 키가
    바뀌거나 캐시 타입이 올바르지 않은 경우에도 반드시 새로 저장한다.
    """

    return (
        cached_identity_key != current_identity_key
        or not isinstance(cached_result, PersistenceResult)
        or cached_result.state == "saved"
    )


def persistence_feedback(result: PersistenceResult) -> PersistenceFeedback:
    """저장 도메인 결과를 Streamlit 비의존 UI 정책으로 변환한다.

    오직 ``saved``만 접근을 허용한다. 저장소 미구성은 안내만 하고, 비활성 계정은
    오류로 차단하며, 일반 실패만 사용자가 다시 시도할 수 있게 한다. 알 수 없는 상태는
    마지막 경로의 경고·재시도·접근 거부로 처리되어 기본 거부가 유지된다.
    """

    if result.state == "saved":
        return PersistenceFeedback(
            tone="success",
            retry_allowed=False,
            access_granted=True,
        )
    if result.state == "unavailable":
        return PersistenceFeedback(
            tone="info",
            retry_allowed=False,
            access_granted=False,
        )
    if result.state == "blocked":
        return PersistenceFeedback(
            tone="error",
            retry_allowed=False,
            access_granted=False,
        )
    return PersistenceFeedback(
        tone="warning",
        retry_allowed=True,
        access_granted=False,
    )
