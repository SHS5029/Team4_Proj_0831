"""계획서의 read-only 관리자 API를 mock 데이터로 제공한다."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Header

from backend.app.core.errors import ApiError
from backend.app.routers import scaffold_game_router as scaffold_game_module
from backend.app.routers import mock_api_router

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _admin_user_id(value: str | None) -> UUID:
    """요청 UUID가 환경 변수 allowlist에 등록됐는지 fail-closed로 확인한다."""

    try:
        user_id = UUID(value or "")
    except ValueError as error:
        raise ApiError(status_code=403, code="ADMIN_ACCESS_DENIED", message="관리자 권한이 없습니다.") from error
    allowed = {item.strip().lower() for item in os.getenv("ADMIN_USER_IDS", "").split(",") if item.strip()}
    if str(user_id).lower() not in allowed:
        raise ApiError(status_code=403, code="ADMIN_ACCESS_DENIED", message="관리자 권한이 없습니다.")
    return user_id


def _item(game) -> dict:
    """관리자 목록에 필요한 공개 게임 요약만 만든다."""

    return {
        "game_id": str(game.game_id),
        "status": game.status,
        "phase": game.phase,
        "round": 0,
        "day_number": 1,
        "state_version": game.state_version,
        "scenario_title": "정전된 방송국",
        "player_count": game.player_count,
        "updated_at": game.updated_at.isoformat(),
    }


def _mock_items() -> list[dict]:
    """mock API가 생성한 게임을 관리자 공개 요약 형식으로 변환한다.

    MOCK ONLY: canonical 관리자 repository가 연결되면 이 함수와 mock 분기를 제거한다.
    """

    return [{"game_id": str(game["id"]), "status": game["status"], "phase": game["phase"],
             "round": game["round"], "day_number": 1, "state_version": game["version"],
             "scenario_title": "정전된 방송국", "player_count": len(game["players"]),
             "updated_at": game["created_at"].isoformat()} for game in mock_api_router.games.values()]


@router.get("/metrics")
async def metrics(x_user_id: str | None = Header(default=None)) -> dict:
    """allowlist를 통과한 관리자에게 mock 운영 지표를 반환한다."""

    _admin_user_id(x_user_id)
    if os.getenv("BACKEND_DATA_MODE") == "mock":
        games = list(mock_api_router.games.values())
        completed = sum(game["status"] == "COMPLETED" for game in games)
        saved = sum(game["status"] == "SAVED" for game in games)
    else:
        games = list(scaffold_game_module.service.repository.games.values()) if hasattr(scaffold_game_module.service.repository, "games") else []
        completed = sum(game.status == "COMPLETED" for game in games)
        saved = sum(game.status == "PAUSED" for game in games)
    return {"data": {"games_created": len(games), "games_completed": completed,
                      "games_saved": saved,
                      "completion_rate": completed / len(games) if games else 0.0,
                      "average_rounds": 0.0, "wins_by_faction": {"CITIZEN": 0, "MAFIA": 0},
                      "auto_action_count": 0, "feedback_average": 0.0}}


@router.get("/games")
async def games(status: str | None = None, phase: str | None = None, limit: int = 20,
                 x_user_id: str | None = Header(default=None)) -> dict:
    """allowlist를 통과한 관리자에게 mock 게임 요약 목록을 반환한다."""

    _admin_user_id(x_user_id)
    if not 1 <= limit <= 100:
        raise ApiError(status_code=400, code="INVALID_REQUEST", message="게임 목록 limit이 올바르지 않습니다.")
    items = _mock_items() if os.getenv("BACKEND_DATA_MODE") == "mock" else (
        [_item(game) for game in scaffold_game_module.service.repository.games.values()]
        if hasattr(scaffold_game_module.service.repository, "games") else []
    )
    if status is not None:
        items = [item for item in items if item["status"] == status]
    if phase is not None:
        items = [item for item in items if item["phase"] == phase]
    items.sort(key=lambda item: (item["updated_at"], item["game_id"]), reverse=True)
    return {"data": {"items": items[:limit], "next_cursor": None}}


@router.get("/games/{game_id}")
async def game_detail(game_id: UUID, x_user_id: str | None = Header(default=None)) -> dict:
    """allowlist를 통과한 관리자에게 비밀 필드 없는 mock 상세를 반환한다."""

    _admin_user_id(x_user_id)
    if os.getenv("BACKEND_DATA_MODE") == "mock":
        game = mock_api_router.games.get(game_id)
        if game is None:
            raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="리소스를 찾을 수 없습니다.")
        detail = mock_api_router._snapshot(game, game["owner"])["data"]
        return {"data": {"game": detail["game"], "scenario": detail["scenario"],
                          "players": detail["players"], "public_events": detail["public_events"]}}
    game = scaffold_game_module.service.repository.get_game(game_id)
    if game is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="리소스를 찾을 수 없습니다.")
    return {"data": {**_item(game), "public_events": [], "failure_code": None,
                      "window": None, "players": []}}
