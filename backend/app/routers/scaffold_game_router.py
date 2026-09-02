"""연결 뼈대 게임의 REST 진입점이다."""

from uuid import UUID

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from backend.app.core.errors import ApiError
from backend.app.repositories.scaffold_repository import ScaffoldRepository
from backend.app.schemas.scaffold_schema import (
    CreateScaffoldGameRequest,
    CreateScaffoldGameResponse,
    ScaffoldCommandAcceptedResponse,
    ScaffoldCommandRequest,
    ScaffoldGameStateResponse,
    ScaffoldOperationResponse,
)
from backend.app.services.scaffold_game_service import ScaffoldGameService

router = APIRouter(prefix="/api/v1/games", tags=["scaffold-games"])
repository = ScaffoldRepository()
service = ScaffoldGameService(repository)


def user_id_header(value: str | None) -> UUID:
    """개발용 사용자 식별자를 UUID로만 검증한다."""

    if value is None:
        raise ApiError(status_code=400, code="INVALID_USER_ID", message="사용자 식별자가 필요합니다.")
    try:
        return UUID(value)
    except ValueError as error:
        raise ApiError(status_code=400, code="INVALID_USER_ID", message="사용자 식별자가 올바르지 않습니다.") from error


@router.post("", response_model=CreateScaffoldGameResponse, status_code=201)
async def create_game(payload: CreateScaffoldGameRequest, x_user_id: str | None = Header(default=None)) -> CreateScaffoldGameResponse:
    """dummy game을 생성한다."""

    return service.create(user_id_header(x_user_id), payload)


@router.get("/{game_id}", response_model=ScaffoldGameStateResponse)
async def get_game(game_id: UUID, x_user_id: str | None = Header(default=None)) -> ScaffoldGameStateResponse:
    """소유자에게 game projection을 반환한다."""

    return service.state(user_id_header(x_user_id), game_id)


@router.post("/{game_id}/commands", response_model=ScaffoldCommandAcceptedResponse, status_code=202)
async def command(game_id: UUID, payload: ScaffoldCommandRequest, x_user_id: str | None = Header(default=None)) -> ScaffoldCommandAcceptedResponse:
    """뼈대 command를 처리한다."""

    return service.command(user_id_header(x_user_id), game_id, payload)


@router.get("/{game_id}/operations/{operation_id}", response_model=ScaffoldOperationResponse)
async def get_operation(game_id: UUID, operation_id: UUID, x_user_id: str | None = Header(default=None)) -> ScaffoldOperationResponse:
    """operation polling 결과를 반환한다."""

    return service.operation(user_id_header(x_user_id), game_id, operation_id)


@router.get("/{game_id}/events")
async def events(game_id: UUID, x_user_id: str | None = Header(default=None)) -> StreamingResponse:
    """최소 SSE frame을 반환해 Frontend 연결과 재연결 경계를 시험한다."""

    service.state(user_id_header(x_user_id), game_id)

    async def stream():
        """무한 worker 없이 smoke 확인에 필요한 초기 frame만 전송한다."""

        yield "event: game.state_changed\ndata: {\"game_id\":\"%s\",\"state_version\":1}\n\n" % game_id
        yield ": heartbeat\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
