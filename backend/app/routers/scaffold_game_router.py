"""연결 뼈대 게임의 REST 진입점이다."""

from uuid import UUID

import asyncio
import json
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
    ScaffoldProposalResponse,
)
from backend.app.llm.client import get_proposal_adapter
from backend.app.mcp.game_client import GameMcpClient
from backend.app.services.scaffold_game_service import ScaffoldGameService
from backend.app.core.config import get_settings
from backend.app.infrastructure.postgres_scaffold import PostgresScaffoldRepository
from backend.app.infrastructure.redis.scaffold import ScaffoldRedis

router = APIRouter(prefix="/api/v1/games", tags=["scaffold-games"])
_settings = get_settings()
repository = PostgresScaffoldRepository(_settings.effective_database_url)
redis = ScaffoldRedis(_settings.redis_url)
service = ScaffoldGameService(repository, redis=redis)


def configure_scaffold_dependencies(test_repository: ScaffoldRepository) -> None:
    """계약 테스트가 외부 DB 없이 fake repository를 주입할 수 있게 한다."""

    global repository, service
    repository = test_repository
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


@router.post("/{game_id}/proposal", response_model=ScaffoldProposalResponse)
async def proposal(game_id: UUID, x_user_id: str | None = Header(default=None)) -> ScaffoldProposalResponse:
    """dummy LLM이 MCP context를 받아 proposal을 반환하는 왕복을 시험한다."""

    owner = user_id_header(x_user_id)
    game = service._owned_game(owner, game_id)
    client = GameMcpClient(_settings.mafia_mcp_url)
    await client.get_context(str(game_id), game.state_version)
    generated = get_proposal_adapter().propose(state_version=game.state_version)
    receipt = await client.submit_proposal(generated.action, generated.source_state_version)
    if generated.source_state_version != game.state_version or generated.action != "PING":
        raise ApiError(status_code=409, code="INVALID_PROPOSAL", message="proposal이 현재 게임 상태와 일치하지 않습니다.")
    return ScaffoldProposalResponse(action="PING", source_state_version=generated.source_state_version, mcp_receipt=receipt)


@router.get("/{game_id}/events")
async def events(game_id: UUID, x_user_id: str | None = Header(default=None), last_event_id: int = Header(default=0, alias="Last-Event-ID")) -> StreamingResponse:
    """DB event replay와 Redis fan-out을 SSE로 전달한다."""

    service.state(user_id_header(x_user_id), game_id)

    async def stream():
        """재연결 기준 이후 event를 먼저 보내고 Redis event를 계속 수신한다."""

        sequence = max(last_event_id, 0)
        seen: set[int] = set()
        pubsub = None
        if service.redis is not None:
            try:
                # replay 중 발생한 event도 놓치지 않도록 fan-out 구독을 먼저 연다.
                pubsub = service.redis.subscribe(str(game_id))
            except Exception:
                pubsub = None
        for event in service.repository.events_after(game_id, sequence):
            event_id = int(event["sequence"])
            seen.add(event_id)
            yield _sse_frame(event_id, event["event_type"], event["payload"])
            sequence = max(sequence, event_id)
        try:
            while True:
                message = None
                if pubsub is not None:
                    try:
                        message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                    except Exception:
                        pubsub = None
                if message and message.get("data"):
                    event = json.loads(message["data"])
                    event_id = int(event["sequence"])
                    if event_id not in seen and event_id > sequence:
                        seen.add(event_id)
                        sequence = event_id
                        yield _sse_frame(event_id, "game.state_changed", event)
                else:
                    for event in service.repository.events_after(game_id, sequence):
                        event_id = int(event["sequence"])
                        if event_id not in seen:
                            seen.add(event_id)
                            sequence = event_id
                            yield _sse_frame(event_id, event["event_type"], event["payload"])
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(1)
        finally:
            if pubsub is not None:
                await asyncio.to_thread(pubsub.close)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _sse_frame(event_id: int, event_name: str, payload: dict) -> str:
    """SSE 프레임을 고정된 id·event·JSON data 형식으로 직렬화한다."""

    return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"
