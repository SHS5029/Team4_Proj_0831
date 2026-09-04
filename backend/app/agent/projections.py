"""AI·GM audience별 context projection을 만드는 모듈.

같은 게임 상태라도 주체에 따라 볼 수 있는 정보가 다르다. 이 파일은 공개 정보와
개인 정보를 한 함수에서 섞지 않도록 분리하고, MCP가 DB에 직접 접근하지 않아도
받은 context만 전달할 수 있는 평범한 dict를 반환한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from backend.app.models.enums import GamePhase, GameStatus, NightActionType, PlayerRole
from backend.app.models.game_state import GameState


SCOPE_PERMISSIONS = {
    "AI_PLAYER": frozenset({"public", "me", "turn", "persona"}),
    "GM": frozenset({"public", "gm-guide"}),
}
WINDOW_BY_PHASE = {
    GamePhase.DAY_DISCUSSION: "SPEECH",
    GamePhase.FINAL_DISCUSSION: "SPEECH",
    GamePhase.NIGHT_ACTION: "NIGHT",
    GamePhase.DAY_VOTE: "VOTE",
    GamePhase.REVOTE: "REVOTE",
    GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
}
TOOL_BY_WINDOW = {
    "SPEECH": ["propose_speech", "propose_pass"],
    "NIGHT": ["propose_night_action"],
    "VOTE": ["propose_vote"],
    "REVOTE": ["propose_vote"],
    "FINAL_VOTE": ["propose_vote"],
}


def build_context(
    state: GameState,
    *,
    subject_type: str,
    subject_id: UUID,
    scope: str,
    window_id: UUID | None = None,
    deadline_at: datetime | None = None,
    scenario: Mapping[str, Any] | None = None,
    public_events: Sequence[Mapping[str, Any]] = (),
    private_events: Sequence[Mapping[str, Any]] = (),
    facts: Mapping[str, str] | None = None,
    persona: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """정본의 context envelope와 scope별 허용 data를 만든다."""

    if subject_type not in SCOPE_PERMISSIONS or scope not in SCOPE_PERMISSIONS[subject_type]:
        raise PermissionError("CAPABILITY_DENIED")
    expected_subject = state.game_id if subject_type == "GM" else subject_id
    if subject_type == "GM" and subject_id != state.game_id:
        raise PermissionError("CAPABILITY_DENIED")
    if subject_type == "AI_PLAYER":
        player = state.player_by_id.get(subject_id)
        if player is None or player.kind.value != "AI":
            raise PermissionError("CAPABILITY_DENIED")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    envelope = {
        "context_version": 1,
        "game_id": str(state.game_id),
        "subject_type": subject_type,
        "subject_id": str(expected_subject),
        "phase": state.phase.value,
        "state_version": state.state_version,
        "window_id": str(window_id or uuid4()),
        "scope": scope,
        "data": {},
    }
    if scope == "public":
        envelope["data"] = _public_data(state, scenario, public_events)
    elif scope == "me":
        envelope["data"] = _me_data(state, subject_id, facts, private_events)
    elif scope == "turn":
        envelope["data"] = _turn_data(state, subject_id, envelope["window_id"], current, deadline_at)
    elif scope == "persona":
        envelope["data"] = _persona_data(persona)
    else:
        envelope["data"] = _gm_guide_data(state, public_events)
    return envelope


def _public_data(
    state: GameState,
    scenario: Mapping[str, Any] | None,
    public_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """모든 subject가 같은 상태에서 동일하게 받는 공개 projection."""

    scenario_data = dict(scenario or {})
    scenario_data.setdefault("scenario_id", "unknown")
    scenario_data.setdefault("title", "시나리오 준비 중")
    scenario_data.setdefault("background", "공개 시나리오 정보가 없습니다.")
    scenario_data.setdefault("victim", "미정")
    scenario_data.setdefault("locations", [])
    return {
        "game": {
            "game_id": str(state.game_id),
            "status": state.status.value,
            "phase": state.phase.value,
            "round": state.round,
            "day_number": state.day_number,
            "state_version": state.state_version,
            "last_sequence": 0,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
            "player_count": len(state.players),
            "mafia_count": sum(player.role is PlayerRole.MAFIA for player in state.players),
            "fast_forward_enabled": not state.human_alive,
            "updated_at": state.updated_at.isoformat(),
        },
        "scenario": scenario_data,
        "players": [
            {
                "player_id": str(player.player_id),
                "seat": player.seat,
                "display_name": player.display_name or f"플레이어 {player.seat}",
                "kind": player.kind.value,
                "alive": player.alive,
                "revealed_role": player.role.value if state.status is GameStatus.COMPLETED else None,
                "eliminated_phase": None,
                "eliminated_round": None,
            }
            for player in sorted(state.players, key=lambda item: item.seat)
        ],
        # caller가 이미 PUBLIC으로 분류한 event만 복사한다. private payload를 이
        # projection 함수가 새로 만들지 않는 것이 audience 혼입을 막는 핵심이다.
        "public_events": [dict(event) for event in public_events],
    }


def _me_data(
    state: GameState,
    subject_id: UUID,
    facts: Mapping[str, str] | None,
    private_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """AI 자기 자신의 role·fact·private event만 반환한다."""

    player = state.player_by_id[subject_id]
    given = facts or {}
    return {
        "player_id": str(subject_id),
        "role": player.role.value,
        "alive": player.alive,
        "alibi": given.get("alibi", "등록된 알리바이가 없습니다."),
        "observation": given.get("observation", "등록된 관찰이 없습니다."),
        "private_events": [dict(event) for event in private_events],
    }


def _turn_data(
    state: GameState,
    subject_id: UUID,
    window_id: str,
    now: datetime,
    deadline_at: datetime | None,
) -> dict[str, Any]:
    """현재 AI job에 필요한 도구와 공개 대상만 계산한다."""

    player = state.player_by_id[subject_id]
    window_kind = WINDOW_BY_PHASE.get(state.phase)
    if window_kind is None:
        raise PermissionError("CAPABILITY_DENIED")
    if window_kind != "SPEECH" and deadline_at is None:
        raise PermissionError("CAPABILITY_DENIED")
    if not player.alive:
        raise PermissionError("CAPABILITY_DENIED")
    targets = []
    if window_kind == "NIGHT" and player.role in {
        PlayerRole.MAFIA,
        PlayerRole.DETECTIVE,
        PlayerRole.DOCTOR,
    }:
        targets = [
            candidate
            for candidate in state.alive_players
            if candidate.player_id != subject_id or player.role is PlayerRole.DOCTOR
        ]
    elif window_kind in {"VOTE", "REVOTE", "FINAL_VOTE"}:
        targets = [candidate for candidate in state.alive_players if candidate.player_id != subject_id]
    return {
        "window_id": window_id,
        "window_kind": window_kind,
        "cycle": 1,
        "opened_state_version": state.state_version,
        "server_time": now.isoformat(),
        "deadline_at": deadline_at.isoformat() if window_kind != "SPEECH" else None,
        "turn_player_id": str(subject_id) if window_kind == "SPEECH" else None,
        "allowed_tools": TOOL_BY_WINDOW[window_kind] if targets or window_kind == "SPEECH" else [],
        "valid_targets": [
            {"player_id": str(candidate.player_id), "display_name": candidate.display_name or f"플레이어 {candidate.seat}"}
            for candidate in targets
        ],
    }


def _persona_data(persona: Mapping[str, Any] | None) -> dict[str, Any]:
    """persona의 정본 field만 허용한다."""

    if not persona:
        raise PermissionError("CAPABILITY_DENIED")
    allowed = {"persona_id", "version", "display_name", "speech_style", "backstory", "parameters"}
    result = {key: persona[key] for key in allowed if key in persona}
    if set(result) != allowed:
        raise PermissionError("CAPABILITY_DENIED")
    return result


def _gm_guide_data(state: GameState, public_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """GM에게 공개 진행 지침만 제공한다. role·행동·조사 결과는 제외한다."""

    source = dict(public_events[-1]) if public_events else None
    return {
        "narration_kind": "PUBLIC_EVENT" if source else "FIXED_MESSAGE",
        "source_public_event": source,
        "fixed_message_key": None if source else "GAME_INTRO",
    }
