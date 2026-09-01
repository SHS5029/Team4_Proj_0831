"""서명된 Frontend identity 요청을 사용자 연결 유스케이스로 전달한다."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import ApiError
from backend.app.infrastructure.postgres import build_user_repository
from backend.app.infrastructure.security.internal_request import verify_internal_request
from backend.app.models.identity import InactiveUserError
from backend.app.schemas.common_schema import ErrorResponse
from backend.app.schemas.identity_schema import IdentityProvisionRequest
from backend.app.schemas.user_schema import UserResponse
from backend.app.services.identity_service import IdentityService

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/identity", tags=["identity"])


def get_identity_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IdentityService:
    """검증된 설정에서 현재 요청이 사용할 저장소와 서비스를 조립한다."""

    return IdentityService(build_user_repository(settings))


@router.post(
    "/provision",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def provision_identity(
    payload: IdentityProvisionRequest,
    _: Annotated[None, Depends(verify_internal_request)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> UserResponse:
    """외부 identity를 내부 사용자에 연결하고 안전한 사용자 필드만 반환한다."""

    try:
        user = service.provision(payload.to_domain())
    except InactiveUserError as exc:
        raise ApiError(
            status_code=403,
            code="INACTIVE_USER",
            message="비활성화된 사용자입니다.",
        ) from exc
    except ValueError as exc:
        raise ApiError(
            status_code=422,
            code="INVALID_IDENTITY",
            message="identity 요청 형식이 올바르지 않습니다.",
        ) from exc
    except Exception as exc:
        # DB 드라이버 예외에는 연결 정보가 포함될 수 있으므로 타입만 기록한다.
        LOGGER.warning("Identity persistence failed (%s)", type(exc).__name__)
        raise ApiError(
            status_code=503,
            code="IDENTITY_PERSISTENCE_UNAVAILABLE",
            message="사용자 저장소를 사용할 수 없습니다.",
        ) from exc
    return UserResponse.from_record(user)
