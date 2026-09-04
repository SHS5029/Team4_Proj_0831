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
            for key in ("player_id", "seat", "display_name", "kind", "alive", "revealed_role", "eliminated_phase", "eliminated_round")
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
    return {key: me.get(key) for key in ("player_id", "role", "alive", "spectator", "alibi", "observation", "private_events") if key in me}


def public_timeline(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """공개 이벤트의 허용 필드만 timeline ViewModel로 변환한다."""

    # 팀 전달 사항: public_events에는 공개 확정 이벤트만 전달한다. 개별 투표,
    # 공격·보호·조사 선택, Agent prompt와 chain-of-thought는 timeline 대상이 아니다.

    events = snapshot.get("public_events", [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]
