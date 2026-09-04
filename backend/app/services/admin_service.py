"""read-only 관리자 API의 접근 제어·조회·감사 흐름."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.repositories.admin_repository import AdminRepository


def parse_admin_allowlist(values: str | Iterable[str] | None) -> frozenset[UUID]:
    """관리자 UUID 목록을 검증한다.

    빈 목록뿐 아니라 한 건이라도 잘못된 값이 있으면 전체를 비운다. 일부만
    허용하면 운영자가 설정을 잘못 입력했을 때 예상하지 못한 계정만 관리자 권한을
    얻을 수 있으므로 정본의 fail-closed 규칙을 따른다.
    """

    if values is None:
        return frozenset()
    if isinstance(values, str):
        candidates = values.split(",")
    else:
        candidates = list(values)
    candidates = [candidate.strip() for candidate in candidates]
    if not candidates or any(not candidate for candidate in candidates):
        return frozenset()
    parsed: set[UUID] = set()
    for candidate in candidates:
        try:
            value = UUID(candidate)
        except (ValueError, AttributeError):
            return frozenset()
        if value.version != 4 or str(value) != candidate.lower():
            return frozenset()
        parsed.add(value)
    return frozenset(parsed)


class AdminService:
    """관리자 allowlist를 통과한 read-only 조회만 실행한다."""

    def __init__(self, repository: AdminRepository, allowlist: str | Iterable[str] | None):
        self.repository = repository
        self.allowlist = parse_admin_allowlist(allowlist)

    def require_admin(self, admin_user_id: UUID) -> None:
        """허용 목록이 비어 있거나 UUID가 없으면 항상 같은 403을 반환한다."""

        if admin_user_id not in self.allowlist:
            raise ApiError(
                status_code=403,
                code="ADMIN_ACCESS_DENIED",
                message="관리자 접근 권한이 없습니다.",
            )

    def list_games(
        self,
        admin_user_id: UUID,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
        request_id: UUID,
    ) -> dict[str, object]:
        """관리자 목록을 읽고 성공한 조회 흔적만 append한다."""

        self.require_admin(admin_user_id)
        items, next_cursor = self.repository.list_games(
            status=status, phase=phase, cursor=cursor, limit=limit
        )
        self._audit(admin_user_id, "ADMIN_LIST_GAMES", None, request_id)
        return {"items": items, "next_cursor": next_cursor}

    def get_game(
        self,
        admin_user_id: UUID,
        game_id: UUID,
        *,
        request_id: UUID,
    ) -> dict[str, object]:
        """게임 상세에서 공개 진행 정보만 반환한다."""

        self.require_admin(admin_user_id)
        data = self.repository.get_game(game_id)
        if data is None:
            raise ApiError(
                status_code=404,
                code="GAME_NOT_FOUND",
                message="게임을 찾을 수 없습니다.",
            )
        self._audit(admin_user_id, "ADMIN_GET_GAME", game_id, request_id)
        return data

    def metrics(
        self,
        admin_user_id: UUID,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        request_id: UUID,
    ) -> dict[str, object]:
        """문서에 정의된 운영 지표를 읽고 LLM 비용·prompt를 반환하지 않는다."""

        self.require_admin(admin_user_id)
        data = self.repository.metrics(from_time=from_time, to_time=to_time)
        self._audit(admin_user_id, "ADMIN_GET_METRICS", None, request_id)
        return data

    def _audit(
        self,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None:
        """감사 저장 실패를 성공 응답으로 숨기지 않는다."""

        try:
            self.repository.append_audit(
                admin_user_id=admin_user_id,
                action=action,
                target_game_id=target_game_id,
                request_id=request_id,
            )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="관리자 감사 기록을 저장할 수 없습니다.",
                retryable=True,
            ) from exc
