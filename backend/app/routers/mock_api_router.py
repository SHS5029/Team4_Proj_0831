"""계획서 공개 API를 외부 저장소 없이 시연하기 위한 mock 전용 라우터."""

# ========================= MOCK ONLY START =========================
# 실제 Backend 전환 시 이 파일 전체를 삭제하고 canonical router를 사용한다.

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Header, Query

from backend.app.core.errors import ApiError

router = APIRouter(prefix="/api/v1", tags=["mock"])
games: dict[UUID, dict] = {}
feedbacks: list[dict] = []
NAMES = ["민수", "철수", "영희", "태경", "지효", "성주", "환석", "유빈", "태웅"]
SCENARIO = {"id": "BLACKOUT_STUDIO", "title": "정전된 방송국", "background": "생방송 준비 중 정전된 방송국에서 PD가 사망했습니다.", "victim": "생방송 PD", "locations": ["스튜디오", "조정실", "분장실", "대기실", "장비실"]}


def _user(value: str | None) -> UUID:
    """UUID header만 식별자로 사용하고 잘못된 입력은 고정 오류로 거부한다."""

    try:
        return UUID(value or "")
    except ValueError as error:
        raise ApiError(status_code=400, code="INVALID_USER_ID", message="사용자 식별자가 올바르지 않습니다.") from error


def _players(game: dict, *, completed: bool = False) -> list[dict]:
    """일반 사용자에게 허용된 공개 player projection만 반환한다."""

    return [
        {"player_id": str(player["id"]), "seat": index, "display_name": player["name"],
         "kind": "HUMAN" if index == 0 else "AI", "alive": player["alive"],
         **({"revealed_role": player["role"]} if completed else {})}
        for index, player in enumerate(game["players"])
    ]


def _snapshot(game: dict, user_id: UUID) -> dict:
    """현재 mock 상태를 Frontend snapshot envelope로 변환한다."""

    human = game["players"][0]
    phase = game["phase"]
    legal: list[str] = []
    window = None
    if game["status"] == "IN_PROGRESS" and phase == "ROLE_REVEAL":
        legal = ["BEGIN_GAME"]
    elif phase == "DAY_DISCUSSION":
        legal = ["SPEAK", "PASS"]
        window = {"window_id": "mock-discussion", "paused": False, "has_submitted": False,
                  "turn_player_id": str(human["id"]), "legal_actions": legal, "valid_targets": [], "remaining_ms": 180000}
    elif phase == "NIGHT_ACTION":
        legal = ["SUBMIT_NIGHT_ACTION"]
        targets = [{"player_id": str(player["id"]), "display_name": player["name"]}
                   for player in game["players"][1:] if player["alive"]]
        window = {"window_id": "mock-night", "paused": False, "has_submitted": False,
                  "turn_player_id": str(human["id"]), "legal_actions": legal, "valid_targets": targets, "remaining_ms": 20000}
    elif phase == "DAY_VOTE":
        legal = ["SUBMIT_VOTE"]
        targets = [{"player_id": str(player["id"]), "display_name": player["name"]}
                   for player in game["players"][1:] if player["alive"]]
        window = {"window_id": "mock-vote", "paused": False, "has_submitted": False,
                  "turn_player_id": str(human["id"]), "legal_actions": legal, "valid_targets": targets, "remaining_ms": 30000}
    result = game.get("result")
    return {"data": {"game": {"game_id": str(game["id"]), "status": game["status"], "phase": phase,
                                "round": game["round"], "day_number": 1, "player_count": len(game["players"]),
                                "state_version": game["version"], "last_sequence": game["version"],
                                "human_alive": human["alive"]}, "scenario": SCENARIO,
                    "players": _players(game, completed=game["status"] == "COMPLETED"),
                    "me": {"player_id": str(human["id"]), "role": human["role"], "alive": human["alive"],
                           "spectator": not human["alive"], "alibi": "조정실에서 장비를 확인했습니다.",
                           "observation": "정전 직전 장비실 쪽으로 이동하는 사람을 봤습니다.", "private_events": []},
                    "legal_actions": legal, "action_window": window, "public_events": game["events"],
                    **({"result": result} if result else {})}}


@router.post("/games")
async def create_game(payload: dict, x_user_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    """계획서의 mystery-v1 생성 요청을 memory mock 게임으로 만든다."""

    user_id = _user(x_user_id)
    count = payload.get("player_count")
    if count not in {6, 7, 8, 9} or payload.get("ruleset_version") != "mystery-v1":
        raise ApiError(status_code=400, code="INVALID_REQUEST", message="게임 생성 요청이 올바르지 않습니다.")
    game_id = uuid4()
    players = [{"id": uuid5(NAMESPACE_URL, f"{game_id}:player:{index}"), "name": NAMES[index],
                "role": "DETECTIVE" if index == 0 else "CITIZEN", "alive": True} for index in range(count)]
    games[game_id] = {"id": game_id, "owner": user_id, "players": players, "status": "IN_PROGRESS",
                      "phase": "ROLE_REVEAL", "round": 0, "version": 1, "events": [], "result": None,
                      "created_at": datetime.now(timezone.utc)}
    return {"data": {"game_id": str(game_id), "snapshot_url": f"/api/v1/games/{game_id}",
                      "status": "IN_PROGRESS", "phase": "ROLE_REVEAL", "state_version": 1}}


@router.get("/games")
async def list_games(x_user_id: str | None = Header(default=None), status: str | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """현재 UUID가 만든 mock 게임 목록을 최신순으로 반환한다."""

    user_id = _user(x_user_id)
    items = [{"game_id": str(game["id"]), "status": game["status"], "phase": game["phase"], "round": game["round"],
              "day_number": 1, "state_version": game["version"], "scenario_title": SCENARIO["title"],
              "player_count": len(game["players"]), "human_alive": game["players"][0]["alive"],
              "winner": (game["result"] or {}).get("winner"), "can_resume": game["status"] == "SAVED",
              "updated_at": game["created_at"].isoformat()} for game in games.values() if game["owner"] == user_id]
    if status:
        items = [item for item in items if item["status"] == status]
    return {"data": {"items": items[:limit], "next_cursor": None}}


@router.get("/games/{game_id}")
async def get_game(game_id: UUID, x_user_id: str | None = Header(default=None)) -> dict:
    """소유자만 mock snapshot을 읽는다."""

    game = games.get(game_id)
    if game is None or game["owner"] != _user(x_user_id):
        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
    return _snapshot(game, game["owner"])


@router.post("/games/{game_id}/commands")
async def command(game_id: UUID, payload: dict, x_user_id: str | None = Header(default=None)) -> dict:
    """mock command로 핵심 화면 상태를 계획서 순서대로 전진시킨다."""

    game = games.get(game_id)
    if game is None or game["owner"] != _user(x_user_id):
        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
    if payload.get("expected_state_version") != game["version"]:
        raise ApiError(status_code=409, code="GAME_STATE_CONFLICT", message="게임 상태가 변경되었습니다.")
    command_type = payload.get("type")
    transitions = {"BEGIN_GAME": ("DAY_DISCUSSION", 0), "SPEAK": ("NIGHT_ACTION", 1), "PASS": ("NIGHT_ACTION", 1),
                   "SUBMIT_NIGHT_ACTION": ("DAY_VOTE", 1), "SUBMIT_VOTE": ("ENDED", 1)}
    if command_type == "SAVE_AND_EXIT":
        game["status"], game["phase"] = "SAVED", "ROLE_REVEAL"
    elif command_type == "RESUME":
        game["status"], game["phase"] = "IN_PROGRESS", "ROLE_REVEAL"
    elif command_type in transitions:
        game["phase"], game["round"] = transitions[command_type]
        if game["phase"] == "ENDED":
            game["status"] = "COMPLETED"
            game["result"] = {"winner": "CITIZEN", "win_reason": "FINAL_MAFIA_SELECTED", "players": _players(game, completed=True), "nights": [], "votes": [], "finished_at": datetime.now(timezone.utc).isoformat(), "public_event_ids": []}
    else:
        raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 상태에서 허용되지 않는 행동입니다.")
    game["version"] += 1
    return {"data": {"accepted": True, "state_version": game["version"], "status": game["status"], "phase": game["phase"]}}


@router.get("/games/{game_id}/sync")
async def sync(game_id: UUID, x_user_id: str | None = Header(default=None), after_state_version: int = 0, after_sequence: int = 0) -> dict:
    """mock에서는 항상 최신 snapshot을 반환해 새로고침 복구를 시연한다."""

    game = games.get(game_id)
    if game is None or game["owner"] != _user(x_user_id):
        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
    snapshot = _snapshot(game, game["owner"])["data"]
    return {"data": {"mode": "SNAPSHOT", **snapshot}}


@router.post("/feedback", status_code=201)
async def feedback(payload: dict, x_user_id: str | None = Header(default=None)) -> dict:
    """실제 저장소 대신 feedback 수를 memory에 기록한다."""

    feedbacks.append({"user_id": str(_user(x_user_id)), "payload": payload})
    return {"data": {"feedback_id": str(uuid4()), "accepted": True}}

# ========================== MOCK ONLY END ==========================
