"""운영 제품 선택과 분리한 비밀 없는 감사 record의 출력 경계다."""

from collections.abc import Mapping
from typing import Protocol

AuditValue = str | float | None


class AuditSink(Protocol):
    """검증된 여섯 필드만 받는 신뢰된 동기 출력 경계다.

    구현체는 호출을 장시간 막지 않아야 하며 게임 payload를 조회하거나 덧붙이면
    안 된다. sink 제품·보존 기간·영속 저장 설정은 이 port가 결정하지 않는다.
    """

    def emit(self, record: Mapping[str, AuditValue]) -> None:
        """호출마다 새로 생성된 record를 받고 실패 시 원문을 별도 spool에 쓰지 않는다."""

        ...
