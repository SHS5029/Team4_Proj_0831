"""신원 저장 결과를 공급자 중립적인 UI 상태로 표현하는 모듈.

저장소나 Streamlit을 직접 import하지 않는 순수 계층으로 유지해, DB 결과와 화면의
색상·재시도·접근 허용 정책을 한곳에서 일관되게 매핑한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from frontend_user.auth.identity import IdentityProfile
from frontend_user.core.api_client import (
    ApiClientConfigurationError,
    BackendApiConfig,
    IdentityApiClient,
    IdentityApiResponseError,
    IdentityApiUnavailable,
    InactiveIdentityError,
)

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


def persist_identity(profile: IdentityProfile, *, secrets: object) -> PersistenceResult:
    """Frontend가 DB를 직접 호출하지 않고 서명된 Backend API 결과만 해석한다.

    설정 누락은 아직 연결 기능을 사용할 수 없는 상태로, 비활성 사용자는 재시도할
    수 없는 차단으로 구분한다. 네트워크·서명·Backend 저장 실패의 내부 문자열은
    사용자에게 전달하지 않고 모두 고정된 일시 실패 안내로 바꾼다.
    """

    try:
        config = BackendApiConfig.from_secrets(secrets)
        IdentityApiClient(config).provision_identity(profile)
    except ApiClientConfigurationError:
        return PersistenceResult(
            state="unavailable",
            user_message=(
                "로그인은 완료됐어요. 계정 저장 기능은 현재 준비 중이라 "
                "잠시 후 다시 확인해 주세요."
            ),
        )
    except InactiveIdentityError:
        return PersistenceResult(
            state="blocked",
            user_message="비활성화된 계정입니다. 관리자에게 문의해 주세요.",
        )
    except (IdentityApiUnavailable, IdentityApiResponseError, ValueError):
        return PersistenceResult(
            state="failed",
            user_message=(
                "로그인은 완료됐지만 계정 정보를 저장하지 못했어요. "
                "잠시 후 다시 시도해 주세요."
            ),
        )
    return PersistenceResult(
        state="saved",
        user_message="Google 로그인과 계정 연결이 완료됐어요.",
    )


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
