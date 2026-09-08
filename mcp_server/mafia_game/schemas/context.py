"""API 8.2와 명시적으로 참조된 5.1 모델의 폐쇄형 context validator다."""

from __future__ import annotations

import math
from typing import Any

from mafia_game.schemas.common import (
    GAME_PHASES,
    WireContractError,
    canonical_uuid,
    integer,
    normalized_text,
    require_keys,
    strict_json_object,
    string,
    utc_rfc3339,
    utc_rfc3339_order_key,
)

_CONTEXT_KEYS = {
    "context_version",
    "game_id",
    "subject_type",
    "subject_id",
    "phase",
    "state_version",
    "window_id",
    "scope",
    "data",
}
_GAME_PHASES = GAME_PHASES
_GAME_STATUSES = {"IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"}
_ROLES = {"MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN"}
_FACTIONS = {"MAFIA", "CITIZEN"}
_WIN_REASONS = {
    "ALL_MAFIA_ELIMINATED",
    "MAFIA_PARITY",
    "FINAL_MAFIA_SELECTED",
    "FINAL_NON_MAFIA_SELECTED",
}
_PUBLIC_DATA_KEYS = {"game", "scenario", "players", "public_events"}
_GAME_KEYS = {
    "game_id",
    "status",
    "phase",
    "round",
    "day_number",
    "state_version",
    "last_sequence",
    "ruleset_version",
    "scenario_version",
    "player_count",
    "mafia_count",
    "fast_forward_enabled",
    "updated_at",
}
_SCENARIO_KEYS = {"scenario_id", "title", "background", "victim", "locations"}
_PLAYER_KEYS = {
    "player_id",
    "seat",
    "display_name",
    "kind",
    "alive",
    "revealed_role",
    "eliminated_phase",
    "eliminated_round",
}
_EVENT_KEYS = {"event_id", "event_type", "created_at", "data"}
_ME_KEYS = {"player_id", "role", "alive", "alibi", "observation", "private_events"}
_TURN_KEYS = {
    "window_id",
    "window_kind",
    "cycle",
    "opened_state_version",
    "server_time",
    "deadline_at",
    "turn_player_id",
    "allowed_tools",
    "valid_targets",
}
_TARGET_KEYS = {"player_id", "display_name"}
_PERSONA_KEYS = {
    "persona_id",
    "version",
    "display_name",
    "speech_style",
    "backstory",
    "parameters",
}
_PARAMETER_KEYS = {
    "sociability",
    "assertiveness",
    "suspicion",
    "deception",
    "risk_tolerance",
    "memory_recall",
    "reasoning_skill",
    "emotionality",
    "cooperativeness",
    "verbosity",
}
_GUIDE_KEYS = {"narration_kind", "source_public_event", "fixed_message_key"}
_FOLLOW_UP = "현재 가장 의심되는 플레이어와 그 이유를 한 문장으로 말해 주세요."
_GAME_INTRO = (
    "사건이 발생한 뒤, 현장에 있던 사람들은 범인을 찾기 위해 서로를 추궁하기 시작했습니다. "
    "그러나 범인은 자신의 정체가 드러나는 것을 막기 위해 밤마다 다른 플레이어를 제거하려 합니다."
)


class ContextContractError(ValueError):
    """응답 원문이나 private field를 보존하지 않고 계약 위반만 표시한다."""


def decode_and_validate_context(
    raw: bytes,
    *,
    game_id: str,
    subject_type: str,
    subject_id: str,
    phase: str,
    state_version: int,
    window_id: str,
    scope: str,
) -> dict[str, Any]:
    """raw duplicate 검증과 단일 응답 binding 검증을 한 요청 안에서 끝낸다."""

    try:
        payload = strict_json_object(raw)
    except WireContractError as error:
        raise ContextContractError from error
    return validate_context(
        payload,
        game_id=game_id,
        subject_type=subject_type,
        subject_id=subject_id,
        phase=phase,
        state_version=state_version,
        window_id=window_id,
        scope=scope,
    )


def validate_context(
    payload: dict[str, Any],
    *,
    game_id: str,
    subject_type: str,
    subject_id: str,
    phase: str,
    state_version: int,
    window_id: str,
    scope: str,
) -> dict[str, Any]:
    """consume issuance와 공통 envelope·scope data의 관측 가능한 불변식을 검증한다."""

    try:
        value = require_keys(payload, _CONTEXT_KEYS)
        if integer(value["context_version"]) != 1:
            raise WireContractError
        if canonical_uuid(value["game_id"]) != game_id:
            raise WireContractError
        if value["subject_type"] != subject_type or subject_type not in {"AI_PLAYER", "GM"}:
            raise WireContractError
        if canonical_uuid(value["subject_id"]) != subject_id:
            raise WireContractError
        if subject_type == "GM" and subject_id != game_id:
            raise WireContractError
        if value["phase"] not in _GAME_PHASES or value["phase"] != phase:
            raise WireContractError
        if integer(value["state_version"], minimum=1) != state_version:
            raise WireContractError
        if canonical_uuid(value["window_id"]) != window_id:
            raise WireContractError
        if value["scope"] != scope:
            raise WireContractError
        allowed = {
            "AI_PLAYER": {"public", "me", "turn", "persona"},
            "GM": {"public", "gm-guide"},
        }[subject_type]
        if scope not in allowed:
            raise WireContractError

        validators = {
            "public": lambda data: _validate_public(data, value),
            "me": lambda data: _validate_me(data, subject_id),
            "turn": lambda data: _validate_turn(data, value),
            "persona": _validate_persona,
            "gm-guide": _validate_gm_guide,
        }
        validator = validators.get(scope)
        if validator is None:
            raise WireContractError
        validator(value["data"])
    except (KeyError, TypeError, WireContractError) as error:
        raise ContextContractError from error
    return payload


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise WireContractError
    return value


def _enum(value: Any, allowed: set[str] | frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise WireContractError
    return value


def _nullable_enum(value: Any, allowed: set[str] | frozenset[str]) -> str | None:
    return None if value is None else _enum(value, allowed)


def _nonblank(value: Any, *, maximum: int | None = None) -> str:
    checked = string(value, maximum=maximum)
    if not checked.strip():
        raise WireContractError
    return checked


def _validate_public(data: Any, envelope: dict[str, Any]) -> None:
    value = require_keys(data, _PUBLIC_DATA_KEYS)
    game = _validate_game(value["game"], envelope)
    _validate_scenario(value["scenario"])
    player_ids, seats = _validate_players(value["players"], game)
    if envelope["subject_type"] == "AI_PLAYER":
        subject = next(
            (
                player
                for player in value["players"]
                if player["player_id"] == envelope["subject_id"]
            ),
            None,
        )
        if subject is None or subject["kind"] != "AI":
            raise WireContractError
    events = value["public_events"]
    if not isinstance(events, list):
        raise WireContractError
    event_ids: set[str] = set()
    for event in events:
        event_id = _validate_public_event(event, player_ids=player_ids, seats=seats)
        if event_id in event_ids:
            raise WireContractError
        event_ids.add(event_id)


def _validate_game(data: Any, envelope: dict[str, Any]) -> dict[str, Any]:
    game = require_keys(data, _GAME_KEYS)
    if canonical_uuid(game["game_id"]) != envelope["game_id"]:
        raise WireContractError
    _enum(game["status"], _GAME_STATUSES)
    if _enum(game["phase"], _GAME_PHASES) != envelope["phase"]:
        raise WireContractError
    integer(game["round"], minimum=0, maximum=5)
    integer(game["day_number"], minimum=1, maximum=6)
    if integer(game["state_version"], minimum=1) != envelope["state_version"]:
        raise WireContractError
    integer(game["last_sequence"], minimum=0)
    if game["ruleset_version"] != "mystery-v1" or game["scenario_version"] != "scenario-v1":
        raise WireContractError
    player_count = integer(game["player_count"], minimum=6, maximum=9)
    mafia_count = integer(game["mafia_count"], minimum=1, maximum=2)
    if mafia_count != (1 if player_count <= 7 else 2):
        raise WireContractError
    _boolean(game["fast_forward_enabled"])
    utc_rfc3339(game["updated_at"])
    return game


def _validate_scenario(data: Any) -> None:
    scenario = require_keys(data, _SCENARIO_KEYS)
    string(scenario["scenario_id"], maximum=64)
    string(scenario["title"], maximum=120)
    _nonblank(scenario["background"])
    string(scenario["victim"], maximum=120)
    locations = scenario["locations"]
    if not isinstance(locations, list) or not 4 <= len(locations) <= 5:
        raise WireContractError
    checked = [_nonblank(location, maximum=80) for location in locations]
    if len(set(checked)) != len(checked):
        raise WireContractError


def _validate_players(data: Any, game: dict[str, Any]) -> tuple[set[str], dict[str, int]]:
    if not isinstance(data, list) or not 6 <= len(data) <= 9:
        raise WireContractError
    if len(data) != game["player_count"]:
        raise WireContractError
    ids: set[str] = set()
    seats: dict[str, int] = {}
    human_count = 0
    previous_seat = 0
    completed = game["status"] == "COMPLETED"
    for raw_player in data:
        player = require_keys(raw_player, _PLAYER_KEYS)
        player_id = canonical_uuid(player["player_id"])
        seat = integer(player["seat"], minimum=1, maximum=9)
        if player_id in ids or seat in seats.values() or seat <= previous_seat:
            raise WireContractError
        previous_seat = seat
        ids.add(player_id)
        seats[player_id] = seat
        string(player["display_name"], maximum=40)
        kind = _enum(player["kind"], {"HUMAN", "AI"})
        human_count += kind == "HUMAN"
        alive = _boolean(player["alive"])
        revealed = _nullable_enum(player["revealed_role"], _ROLES)
        eliminated_phase = _nullable_enum(player["eliminated_phase"], _GAME_PHASES)
        eliminated_round = (
            None
            if player["eliminated_round"] is None
            else integer(player["eliminated_round"], minimum=1, maximum=5)
        )
        if alive and (eliminated_phase is not None or eliminated_round is not None):
            raise WireContractError
        if not alive:
            if eliminated_phase not in {"NIGHT_ACTION", "DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}:
                raise WireContractError
            if eliminated_round is None:
                raise WireContractError
        if completed and revealed is None:
            raise WireContractError
        if not completed and alive and revealed is not None:
            raise WireContractError
        if not completed and eliminated_phase == "NIGHT_ACTION" and revealed is not None:
            raise WireContractError
        if (
            not completed
            and eliminated_phase in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
            and revealed is None
        ):
            raise WireContractError
    if human_count != 1:
        raise WireContractError
    return ids, seats


def _validate_public_event(
    data: Any,
    *,
    player_ids: set[str] | None = None,
    seats: dict[str, int] | None = None,
) -> str:
    event = require_keys(data, _EVENT_KEYS)
    event_id = canonical_uuid(event["event_id"])
    event_type = _enum(
        event["event_type"],
        {
            "GAME_BEGAN",
            "TURN_OPENED",
            "PLAYER_SPOKE",
            "PLAYER_PASSED",
            "NIGHT_RESOLVED",
            "VOTE_RESOLVED",
            "PLAYER_EXECUTED",
            "FAST_FORWARD_ENABLED",
            "GAME_SAVED",
            "GAME_RESUMED",
            "GAME_ENDED",
        },
    )
    utc_rfc3339(event["created_at"])
    details = event["data"]
    if event_type == "GAME_BEGAN":
        details = require_keys(details, {"message"})
        if details["message"] != _GAME_INTRO:
            raise WireContractError
    elif event_type == "TURN_OPENED":
        details = require_keys(details, {"player_id", "cycle", "prompt"})
        _event_player(details["player_id"], player_ids)
        integer(details["cycle"], minimum=1, maximum=2)
        if details["prompt"] is not None and details["prompt"] != _FOLLOW_UP:
            raise WireContractError
    elif event_type == "PLAYER_SPOKE":
        details = require_keys(details, {"player_id", "message"})
        _event_player(details["player_id"], player_ids)
        normalized_text(details["message"], maximum=200)
    elif event_type == "PLAYER_PASSED":
        details = require_keys(details, {"player_id"})
        _event_player(details["player_id"], player_ids)
    elif event_type == "NIGHT_RESOLVED":
        details = require_keys(details, {"round", "killed_player_id"})
        integer(details["round"], minimum=1, maximum=5)
        if details["killed_player_id"] is not None:
            _event_player(details["killed_player_id"], player_ids)
    elif event_type == "VOTE_RESOLVED":
        details = require_keys(details, {"round", "phase", "counts", "tied", "needs_revote"})
        integer(details["round"], minimum=1, maximum=5)
        _enum(details["phase"], {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"})
        _validate_vote_counts(details["counts"], player_ids=player_ids, seats=seats)
        _boolean(details["tied"])
        _boolean(details["needs_revote"])
    elif event_type == "PLAYER_EXECUTED":
        details = require_keys(details, {"player_id", "revealed_role"})
        _event_player(details["player_id"], player_ids)
        _enum(details["revealed_role"], _ROLES)
    elif event_type == "FAST_FORWARD_ENABLED":
        details = require_keys(details, {"enabled"})
        if details["enabled"] is not True:
            raise WireContractError
    elif event_type in {"GAME_SAVED", "GAME_RESUMED"}:
        details = require_keys(details, {"phase", "round"})
        _enum(details["phase"], _GAME_PHASES)
        integer(details["round"], minimum=0, maximum=5)
    else:
        details = require_keys(details, {"winner", "win_reason"})
        _enum(details["winner"], _FACTIONS)
        _enum(details["win_reason"], _WIN_REASONS)
    return event_id


def _event_player(value: Any, player_ids: set[str] | None) -> str:
    player_id = canonical_uuid(value)
    if player_ids is not None and player_id not in player_ids:
        raise WireContractError
    return player_id


def _validate_vote_counts(
    data: Any,
    *,
    player_ids: set[str] | None,
    seats: dict[str, int] | None,
) -> None:
    if not isinstance(data, list):
        raise WireContractError
    seen: set[str] = set()
    observed_seats: list[int] = []
    total_votes = 0
    population = len(player_ids) if player_ids is not None else None
    for item in data:
        value = require_keys(item, {"target_player_id", "vote_count"})
        player_id = _event_player(value["target_player_id"], player_ids)
        if player_id in seen:
            raise WireContractError
        seen.add(player_id)
        vote_count = integer(value["vote_count"], minimum=0)
        if population is not None and vote_count > population:
            raise WireContractError
        total_votes += vote_count
        if seats is not None:
            observed_seats.append(seats[player_id])
    if observed_seats != sorted(observed_seats):
        raise WireContractError
    if population is not None and total_votes > population:
        raise WireContractError


def _validate_me(data: Any, subject_id: str) -> None:
    value = require_keys(data, _ME_KEYS)
    if canonical_uuid(value["player_id"]) != subject_id:
        raise WireContractError
    _enum(value["role"], _ROLES)
    _boolean(value["alive"])
    normalized_text(value["alibi"], maximum=240)
    normalized_text(value["observation"], maximum=240)
    events = value["private_events"]
    if not isinstance(events, list):
        raise WireContractError
    event_ids: set[str] = set()
    for raw_event in events:
        event = require_keys(raw_event, _EVENT_KEYS)
        event_id = canonical_uuid(event["event_id"])
        if event_id in event_ids:
            raise WireContractError
        event_ids.add(event_id)
        event_type = _enum(event["event_type"], {"INVESTIGATION_RESULT", "NIGHT_ACTION_ACCEPTED"})
        utc_rfc3339(event["created_at"])
        if event_type == "INVESTIGATION_RESULT":
            details = require_keys(event["data"], {"round", "target_player_id", "is_mafia"})
            integer(details["round"], minimum=1, maximum=5)
            canonical_uuid(details["target_player_id"])
            _boolean(details["is_mafia"])
        else:
            details = require_keys(
                event["data"], {"round", "action_type", "target_player_id"}
            )
            integer(details["round"], minimum=1, maximum=5)
            _enum(details["action_type"], {"ATTACK", "INVESTIGATE", "PROTECT"})
            canonical_uuid(details["target_player_id"])


def _validate_turn(data: Any, envelope: dict[str, Any]) -> None:
    value = require_keys(data, _TURN_KEYS)
    if canonical_uuid(value["window_id"]) != envelope["window_id"]:
        raise WireContractError
    kind = _enum(value["window_kind"], {"SPEECH", "NIGHT", "VOTE", "REVOTE", "FINAL_VOTE"})
    cycle = integer(value["cycle"], minimum=1, maximum=2)
    if kind != "SPEECH" and cycle != 1:
        raise WireContractError
    if integer(value["opened_state_version"], minimum=1) > envelope["state_version"]:
        raise WireContractError
    server_time = utc_rfc3339_order_key(value["server_time"])
    phase_to_kind = {
        "DAY_DISCUSSION": "SPEECH",
        "FINAL_DISCUSSION": "SPEECH",
        "NIGHT_ACTION": "NIGHT",
        "DAY_VOTE": "VOTE",
        "REVOTE": "REVOTE",
        "FINAL_ACCUSATION": "FINAL_VOTE",
    }
    if phase_to_kind.get(envelope["phase"]) != kind:
        raise WireContractError
    expected_tools = {
        "SPEECH": ["propose_speech", "propose_pass"],
        "NIGHT": ["propose_night_action"],
        "VOTE": ["propose_vote"],
        "REVOTE": ["propose_vote"],
        "FINAL_VOTE": ["propose_vote"],
    }[kind]
    if envelope["phase"] == "DAY_DISCUSSION" and value["allowed_tools"] == ["propose_speech"]:
        expected_tools = ["propose_speech"]
    if value["allowed_tools"] != expected_tools:
        raise WireContractError
    targets = value["valid_targets"]
    if not isinstance(targets, list):
        raise WireContractError
    target_ids: set[str] = set()
    for raw_target in targets:
        target = require_keys(raw_target, _TARGET_KEYS)
        player_id = canonical_uuid(target["player_id"])
        if player_id in target_ids:
            raise WireContractError
        target_ids.add(player_id)
        string(target["display_name"], maximum=40)
    if kind == "SPEECH":
        if (
            value["deadline_at"] is not None
            or value["turn_player_id"] != envelope["subject_id"]
            or targets
        ):
            raise WireContractError
    else:
        if value["turn_player_id"] is not None or not 1 <= len(targets) <= 8:
            raise WireContractError
        if kind in {"VOTE", "REVOTE", "FINAL_VOTE"} and envelope["subject_id"] in target_ids:
            raise WireContractError
        deadline = utc_rfc3339_order_key(value["deadline_at"])
        if deadline <= server_time:
            raise WireContractError


def _validate_persona(data: Any) -> None:
    value = require_keys(data, _PERSONA_KEYS)
    string(value["persona_id"], maximum=64)
    string(value["version"], maximum=32)
    string(value["display_name"], maximum=40)
    string(value["speech_style"], maximum=240)
    string(value["backstory"], maximum=500)
    parameters = require_keys(value["parameters"], _PARAMETER_KEYS)
    for parameter in parameters.values():
        if isinstance(parameter, bool) or not isinstance(parameter, int | float):
            raise WireContractError
        if isinstance(parameter, float) and not math.isfinite(parameter):
            raise WireContractError
        if not 0 <= parameter <= 1:
            raise WireContractError


def _validate_gm_guide(data: Any) -> None:
    value = require_keys(data, _GUIDE_KEYS)
    kind = _enum(value["narration_kind"], {"PUBLIC_EVENT", "FIXED_MESSAGE"})
    if kind == "PUBLIC_EVENT":
        if value["fixed_message_key"] is not None:
            raise WireContractError
        _validate_public_event(value["source_public_event"])
    else:
        if value["source_public_event"] is not None:
            raise WireContractError
        _enum(
            value["fixed_message_key"],
            {"GAME_INTRO", "ALL_PASS_FOLLOW_UP", "FINAL_ACCUSATION_NOTICE"},
        )
