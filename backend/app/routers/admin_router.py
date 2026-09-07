"""read-only 관리자 API route."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.core.errors import ApiError
from backend.app.core.responses import api_success_response, request_trace_id
from backend.app.routers.game_router import user_id_header
from backend.app.schemas.admin_schema import AdminGameListQuery, AdminMetricsQuery

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _validation_error(error: ValidationError) -> ApiError:
    """관리자 query의 내부 검증 원문 대신 위치와 유형만 공개한다."""

    return ApiError(
        status_code=422,
        code="INVALID_REQUEST",
        message="요청 형식이 올바르지 않습니다.",
        details=[{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()],
    )


def _admin_service(request: Request):
    """앱 생성 시 주입한 관리자 서비스를 사용한다."""

    return request.app.state.admin_service


@router.get("/games", response_model=None)
async def list_admin_games(
    request: Request,
    x_user_id: str | None = Header(default=None),
    status: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """관리자 allowlist를 통과한 경우 게임 요약 목록만 반환한다."""

    try:
        query = AdminGameListQuery(status=status, phase=phase, cursor=cursor, limit=limit)
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).list_games(
        user_id_header(x_user_id),
        status=query.status,
        phase=query.phase,
        cursor=query.cursor,
        limit=query.limit,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/games/{game_id}", response_model=None)
async def get_admin_game(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """관리자에게도 role·개인 사실·개별 행동·seed를 보내지 않는다."""

    data = _admin_service(request).get_game(
        user_id_header(x_user_id), game_id, request_id=UUID(request_trace_id(request))
    )
    return api_success_response(request, data)


@router.get("/metrics", response_model=None)
async def get_admin_metrics(
    request: Request,
    x_user_id: str | None = Header(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> JSONResponse:
    """최대 31일 범위의 운영 지표만 반환한다."""

    try:
        query = AdminMetricsQuery.model_validate({"from": from_, "to": to})
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).metrics(
        user_id_header(x_user_id),
        from_time=query.from_,
        to_time=query.to,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)
