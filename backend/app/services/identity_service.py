"""검증된 외부 identity를 내부 사용자와 연결하는 유스케이스."""

from typing import Protocol

from backend.app.models.identity import ExternalIdentity, UserRecord


class UserRepository(Protocol):
    """identity 연결 유스케이스가 요구하는 최소 저장소 계약."""

    def upsert_identity(self, profile: ExternalIdentity) -> UserRecord: ...


class IdentityService:
    """HTTP 세부사항 없이 identity 저장 흐름을 저장소에 위임한다."""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def provision(self, identity: ExternalIdentity) -> UserRecord:
        """도메인 검증을 한 번 더 적용한 뒤 원자적 저장 결과를 반환한다."""

        identity.validate_for_login()
        return self._repository.upsert_identity(identity)
