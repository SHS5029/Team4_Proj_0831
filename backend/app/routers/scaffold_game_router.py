"""정본 공개 게임 API와 기존 scaffold 호환 경로를 함께 제공한다.

B5의 새 요청은 ``mystery-v1``와 ``type`` field를 사용한다. 과거 B1~B4 계약
테스트가 사용하는 scaffold 요청은 별도 분기에서만 처리해 기존 테스트의
경계를 보존한다. 새 코드가 scaffold 응답을 참조하지 않도록 canonical
service와 legacy service를 변수부터 분리했다.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from backend.app.core.config import get_settings
from backend.app.core.errors import ApiError
from backend.app.core.responses import api_success_response
from backend.app.infrastructure.postgres_scaffold import PostgresScaffoldRepository
from backend.app.infrastructure.redis.scaffold import ScaffoldRedis
from backend.app.llm_provider.base import LLMRequest
from backend.app.llm_provider.factory import get_llm_provider
from backend.app.llm_provider.schemas import parse_game_proposal, proposal_schema
from backend.app.mcp.game_client import GameMcpClient
from backend.app.repositories.scaffold_repository import ScaffoldRepository
from backend.app.repositories.user_repository import PostgresUserRepository
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.schemas.scaffold_schema import (
    CreateScaffoldGameRequest,
    ScaffoldCommandRequest,
    ScaffoldOperationResponse,
    ScaffoldProposalResponse,
)
from backend.app.services.game_service import CanonicalGameService, InMemoryGameRepository
from backend.app.services.identity_service import IdentityService
from backend.app.services.scaffold_game_service import ScaffoldGameService

router = APIRouter(prefix="/api/v1/games", tags=["games"])
_settings = get_settings()

# canonical과 legacy는 서로 다른 저장소를 사용한다. 덕분에 B5 전환 중에도
# 예전 테스트의 scaffold game이 새 정본 응답으로 섞이지 않는다.
canonical_repository = InMemoryGameRepository()
canonical_user_service = IdentityService(
    PostgresUserRepository(_settings.effective_database_url)
)
# 정본의 최초 쓰기는 users 행을 먼저 준비한다. 게임 상태 자체는 다음 단계에서
# PostgreSQL repository로 옮기지만, owner FK의 선행 조건은 지금부터 지킨다.
canonical_service = CanonicalGameService(
    canonical_repository,
    user_service=canonical_user_service,
)
legacy_repository = PostgresScaffoldRepository(_settings.effective_database_url)
legacy_redis = ScaffoldRedis(_settings.redis_url)
legacy_user_service = IdentityService(PostgresUserRepository(_settings.effective_database_url))
legacy_service = ScaffoldGameService(
    legacy_repository, redis=legacy_redis, user_service=legacy_user_service
)


def configure_scaffold_dependencies(test_repository: ScaffoldRepository) -> None:
    """기존 scaffold 계약 테스트가 외부 DB 없이 동작하도록 legacy만 교체한다."""

    global legacy_repository, legacy_service
    legacy_repository = test_repository
    legacy_service = ScaffoldGameService(test_repository)


def configure_canonical_dependencies(test_repository: InMemoryGameRepository) -> None:
    """B5 계약 테스트가 외부 사용자 DB 없이 저장소를 주입하게 한다.

    운영 서비스에는 위의 PostgreSQL 사용자 저장소가 연결된다. 테스트에서는 synthetic
    UUID가 팀 공용 DB에 저장되지 않도록 user service를 의도적으로 생략한다.
    """

    global canonical_repository, canonical_service
    canonical_repository = test_repository
    canonical_service = CanonicalGameService(test_repository)


def user_id_header(value: str | None) -> UUID:
    """X-User-Id를 인증 토큰이 아닌 UUID v4 식별자로만 검증한다."""

    if value is None:
        raise ApiError(
            status_code=400, code="MISSING_USER_ID", message="X-User-Id 헤더가 필요합니다."
        )
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ApiError(
            status_code=400, code="INVALID_REQUEST", message="X-User-Id는 UUID 형식이어야 합니다."
        ) from error
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ApiError(
            status_code=400, code="INVALID_REQUEST", message="X-User-Id는 UUID v4여야 합니다."
        )
    return parsed


def idempotency_header(value: str | None) -> UUID:
    """변경 요청의 멱등 key를 UUID v4로 검증한다."""

    if value is None:
        raise ApiError(
            status_code=400,
            code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key 헤더가 필요합니다.",
        )
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ApiError(
            status_code=400,
            code="INVALID_REQUEST",
            message="Idempotency-Key는 UUID 형식이어야 합니다.",
        ) from error
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ApiError(
            status_code=400, code="INVALID_REQUEST", message="Idempotency-Key는 UUID v4여야 합니다."
        )
    return parsed


@router.post("", response_model=None, status_code=201)
async def create_game(
    request: Request,
    x_user_id: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """canonical 게임 생성은 정본 envelope로, 옛 scaffold 요청은 호환 형식으로 반환한다."""

    body = await request.json()
    owner = user_id_header(x_user_id)
    if body.get("ruleset_version") == "scaffold-v1":
        return legacy_service.create(owner, _validate_body(CreateScaffoldGameRequest, body))
    payload = _validate_body(CreateGameRequest, body)
    data, replayed = canonical_service.create(owner, payload, idempotency_header(idempotency_key))
    return api_success_response(request, data, status_code=201, replayed=replayed)


@router.get("")
async def list_games(
    request: Request,
    x_user_id: str | None = Header(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """현재 UUID가 소유한 게임만 목록으로 반환한다."""

    owner = user_id_header(x_user_id)
    if status is not None and status not in {"IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"}:
        raise ApiError(
            status_code=422, code="INVALID_REQUEST", message="status 값이 올바르지 않습니다."
        )
    # 첫 B5 저장소는 opaque cursor를 해석하지 않는다. API에는 cursor를 유지해
    # 다음 PostgreSQL adapter가 동일한 HTTP 계약을 그대로 이어받게 한다.
    del cursor
    return api_success_response(
        request,
        {
            "items": canonical_service.list_games(owner, status=status, limit=limit),
            "next_cursor": None,
        },
    )


@router.get("/{game_id}", response_model=None)
async def get_game(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """canonical snapshot을 우선 조회하고, 없을 때만 legacy 상태를 조회한다."""

    owner = user_id_header(x_user_id)
    if game_id in canonical_repository.games:
        return api_success_response(request, canonical_service.snapshot(owner, game_id))
    return legacy_service.state(owner, game_id)


@router.post("/{game_id}/commands", response_model=None)
async def command(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """type field가 있으면 B5 command, command field가 있으면 legacy command다."""

    owner = user_id_header(x_user_id)
    body = await request.json()
    if "command" in body:
        # 예전 scaffold 계약은 command가 비동기 접수되는 202 응답을 사용한다.
        # canonical B5 command의 응답 상태 코드와 섞이지 않도록 legacy 경계에서
        # Pydantic 결과를 JSON으로 변환한 뒤 이 분기에서만 202를 명시한다.
        legacy_result = legacy_service.command(
            owner, game_id, _validate_body(ScaffoldCommandRequest, body)
        )
        return JSONResponse(status_code=202, content=legacy_result.model_dump(mode="json"))
    payload = _validate_body(GameCommandRequest, body)
    data, replayed = canonical_service.command(
        owner, game_id, payload, idempotency_header(idempotency_key)
    )
    return api_success_response(request, data, replayed=replayed)


@router.get("/{game_id}/sync")
async def sync_game(
    request: Request,
    game_id: UUID,
    after_state_version: int = Query(..., ge=0),
    after_sequence: int = Query(..., ge=0),
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """polling과 SSE가 공유하는 canonical operations envelope를 반환한다."""

    data = canonical_service.sync(
        user_id_header(x_user_id),
        game_id,
        after_state_version=after_state_version,
        after_sequence=after_sequence,
    )
    return api_success_response(request, data)


@router.get("/{game_id}/events")
async def events(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
    last_event_id: int = Header(default=0, alias="Last-Event-ID"),
) -> StreamingResponse:
    """canonical event는 sync envelope로 보내고 legacy stream은 유지한다."""

    owner = user_id_header(x_user_id)
    if game_id not in canonical_repository.games:
        legacy_service.state(owner, game_id)
        return await _legacy_events(game_id, last_event_id)
    first = canonical_service.sync(
        owner, game_id, after_state_version=0, after_sequence=max(last_event_id, 0)
    )

    async def stream():
        """재연결 시 완전한 batch를 먼저 보내고 heartbeat를 보낸다."""

        yield f"event: game_sync\ndata: {json.dumps(first, ensure_ascii=False)}\n\n"
        yield ": heartbeat\n\n"
        await asyncio.sleep(0)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/{game_id}/operations/{operation_id}", response_model=ScaffoldOperationResponse)
async def get_operation(
    game_id: UUID, operation_id: UUID, x_user_id: str | None = Header(default=None)
) -> ScaffoldOperationResponse:
    """기존 scaffold polling 경로를 B5 전환 중에만 보존한다."""

    return legacy_service.operation(user_id_header(x_user_id), game_id, operation_id)


@router.post("/{game_id}/proposal", response_model=ScaffoldProposalResponse)
async def proposal(
    game_id: UUID, x_user_id: str | None = Header(default=None)
) -> ScaffoldProposalResponse:
    """기존 scaffold LLM 왕복 smoke 경로다. canonical command와 섞지 않는다."""

    owner = user_id_header(x_user_id)
    game = legacy_service._owned_game(owner, game_id)
    client = GameMcpClient(_settings.mafia_mcp_url)
    await client.get_context(str(game_id), game.state_version)
    generated = await get_llm_provider(_settings).generate(
        LLMRequest(
            messages=(
                {
                    "role": "system",
                    "content": "JSON만 반환한다. action은 PING, target_player_id는 null로 한다.",
                },
                {"role": "user", "content": f"source_state_version={game.state_version}"},
            ),
            response_schema=proposal_schema(),
            max_output_tokens=_settings.llm_max_output_tokens,
            timeout_seconds=_settings.llm_timeout_seconds,
        )
    )
    parsed = parse_game_proposal(generated.output, expected_state_version=game.state_version)
    if parsed.action != "PING":
        raise ApiError(
            status_code=409,
            code="INVALID_PROPOSAL",
            message="proposal이 현재 게임 상태와 일치하지 않습니다.",
        )
    receipt = await client.submit_proposal(parsed.action, parsed.source_state_version)
    return ScaffoldProposalResponse(
        action="PING", source_state_version=parsed.source_state_version, mcp_receipt=receipt
    )


async def _legacy_events(game_id: UUID, last_event_id: int) -> StreamingResponse:
    """legacy scaffold event를 기존 smoke 테스트에 맞게 전달한다."""

    async def stream():
        sequence = max(last_event_id, 0)
        for event in legacy_repository.events_after(game_id, sequence):
            event_id = int(event["sequence"])
            yield _sse_frame(event_id, event["event_type"], event["payload"])
        yield ": heartbeat\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def _sse_frame(event_id: int, event_name: str, payload: dict) -> str:
    """legacy SSE payload를 고정된 frame으로 직렬화한다."""

    return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


feedback_router = APIRouter(prefix="/api/v1", tags=["feedback"])


@feedback_router.post("/feedback", status_code=201)
async def create_feedback(
    request: Request,
    x_user_id: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """정본의 ``POST /api/v1/feedback``를 처리한다."""

    owner = user_id_header(x_user_id)
    payload = _validate_body(FeedbackRequest, await request.json())
    data, replayed = canonical_service.feedback(owner, payload, idempotency_header(idempotency_key))
    return api_success_response(request, data, status_code=201, replayed=replayed)


def _validate_body(model: type[BaseModel], body: object) -> BaseModel:
    """함수 내부 Pydantic 검증 오류도 공통 오류 envelope로 변환한다."""

    try:
        return model.model_validate(body)
    except ValidationError as error:
        details = [{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()]
        raise ApiError(
            status_code=422,
            code="INVALID_REQUEST",
            message="요청 형식이 올바르지 않습니다.",
            details=details,
        ) from error
