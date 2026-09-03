"""OIDC 제공자에 종속되지 않는 인증 도메인 모델.

외부 계정은 이메일이 아니라 OIDC 표준의 ``(provider, sub)`` 조합으로
식별한다. 이메일, 표시 이름, 아바타는 사용자가 다시 로그인할 때 바뀔 수
있는 프로필 스냅샷이며 계정 자동 연결의 근거로 사용하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class InactiveUserError(PermissionError):
    """비활성화된 내부 사용자가 다시 로그인하려 할 때 발생하는 예외.

    일반적인 저장 실패와 구분해 UI가 재시도 버튼을 숨기고 관리자 문의를
    안내할 수 있도록 별도 타입으로 정의한다.
    """


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """OIDC 로그인 결과에서 추출한 제공자 중립적인 외부 신원.

    ``provider_subject``에는 제공자가 발급한 불변 ``sub`` 값을 저장한다.
    ``provider``와 이 값을 합친 키만 기존 내부 사용자를 찾는 데 사용한다.
    이메일은 검증 여부를 함께 전달받지만 변경 가능한 프로필 정보이므로,
    같은 이메일이라는 이유만으로 서로 다른 외부 계정을 합치지 않는다.

    데이터 클래스는 불변(frozen)이고 슬롯을 사용하므로 로그인 처리 중
    검증을 마친 claim이 우연히 변경되거나 임의 필드가 추가되지 않는다.
    """

    provider: str
    provider_subject: str
    email: str | None
    email_verified: bool
    display_name: str | None = None
    avatar_url: str | None = None

    def validate_for_login(self) -> None:
        """저장소에 전달하기 전에 로그인에 필요한 최소 신뢰 조건을 검사한다.

        제공자와 subject는 계정 연결 키이므로 공백일 수 없다. 이메일 주소
        자체는 선택 정보지만, OIDC 제공자가 이메일 검증을 완료했다는 claim은
        반드시 참이어야 한다. 원문 claim이나 토큰은 예외에 포함하지 않는다.
        """

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
        """저장과 조회에 사용할 소문자 제공자 코드를 반환한다.

        subject 값은 제공자가 정의한 대소문자를 그대로 보존하지만, 서비스가
        관리하는 provider 코드는 앞뒤 공백을 제거하고 소문자로 통일한다.
        """

        return self.provider.strip().lower()


@dataclass(frozen=True, slots=True)
class UserRecord:
    """정본 ``users`` 테이블과 일치하는 최소 사용자 읽기 모델.

    B1에서는 OAuth 프로필을 저장하거나 반환하지 않는다. 사용자에게 필요한
    것은 UUID와 생성·최근 확인 시각뿐이며, UUID 자체는 인증 수단이 아니다.
    """

    id: UUID
    created_at: datetime
    last_seen_at: datetime
