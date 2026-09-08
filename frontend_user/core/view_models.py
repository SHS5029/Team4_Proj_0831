"""Backend snapshot을 화면 표시용 안전한 ViewModel로 투영한다."""

from __future__ import annotations

from typing import Any


def public_players(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """공개 player 필드만 복사해 다른 player private 값의 화면 유입을 막는다."""

    # 팀 전달 사항: Backend snapshot의 players에는 공개 player projection만 넣는다.
    # role은 처형 직후 또는 게임 종료 때만 revealed_role로 공개하고, 밤 사망자의
    # role과 모든 alibi·observation·action은 일반 Front snapshot에서 제외한다.

    result: list[dict[str, Any]] = []
    for player in snapshot.get("players", []):
        if not isinstance(player, dict):
            continue
        result.append({
            key: player.get(key)
            for key in ("player_id", "seat", "display_name", "kind", "alive", "revealed_role", "revealed_role_name", "eliminated_phase", "eliminated_round")
            if key in player
        })
    return sorted(result, key=lambda item: item.get("seat", 0))


def own_private_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Backend가 제공한 me projection에서 허용된 본인 정보만 표시한다."""

    # 팀 전달 사항: me는 현재 UUID에 해당하는 인간 player 한 명의 projection이어야
    # 한다. Backend는 다른 player의 private state를 섞지 않고, Front는 me 외의
    # private 정보를 자체적으로 추론하지 않는다.

    me = snapshot.get("me")
    if not isinstance(me, dict):
        return {}
    return {key: me.get(key) for key in ("player_id", "role", "alive", "spectator", "alibi", "observation", "private_events", "role_name", "faction", "ability_ids", "ability_options") if key in me}


def public_timeline(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """공개 이벤트의 허용 필드만 timeline ViewModel로 변환한다."""

    # 팀 전달 사항: public_events에는 공개 확정 이벤트만 전달한다. 개별 투표,
    # 공격·보호·조사 선택, Agent prompt와 chain-of-thought는 timeline 대상이 아니다.

    events = snapshot.get("public_events", [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def custom_role_description(me: dict[str, Any]) -> str:
    """본인 projection의 공개 능력 ID만 설명으로 바꾸며 다른 player는 조회하지 않는다."""

    from frontend_user.core.commands import ABILITY_DESCRIPTIONS

    if not isinstance(me.get("role_name"), str) or me.get("faction") not in {"CITIZEN", "MAFIA"}:
        return ""
    faction = "시민 진영" if me["faction"] == "CITIZEN" else "마피아 진영"
    ids = me.get("ability_ids", [])
    descriptions = [ABILITY_DESCRIPTIONS[value] for value in ids if isinstance(value, str) and value in ABILITY_DESCRIPTIONS] if isinstance(ids, list) else []
    return "\n".join([faction, *descriptions, "밤마다 능력 하나만 사용합니다."])



def validate_special_roles(response: Any, scope: tuple) -> list[dict[str, Any]] | None:
    """요청 범위와 폐쇄형 응답을 대조하고 다른 역할·본인·중복 좌석은 표시하지 않는다."""

    data = response.get("data") if isinstance(response, dict) and "error" not in response else None
    if (not isinstance(data, dict)
            or set(data) != {"game_id", "player_id", "ability_id", "state_version", "roles"}
            or data["game_id"] != scope[2] or data["player_id"] != scope[3]
            or type(data["state_version"]) is not int or data["state_version"] != scope[4]
            or data["ability_id"] != "intel.special_roles.v1" or not isinstance(data["roles"], list)):
        return None
    roles, seen = [], set()
    for row in data["roles"]:
        if (not isinstance(row, dict) or set(row) != {"player_id", "display_name", "role", "alive"}
                or not isinstance(row["player_id"], str) or row["player_id"] == scope[3]
                or row["player_id"] in seen or not isinstance(row["display_name"], str)
                or not isinstance(row["role"], str) or row["role"] not in {"DETECTIVE", "DOCTOR"}
                or type(row["alive"]) is not bool):
            return None
        seen.add(row["player_id"])
        roles.append(dict(row))
    return roles
