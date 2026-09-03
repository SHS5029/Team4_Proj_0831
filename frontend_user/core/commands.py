"""게임 command 입력의 Front guard와 정규화 규칙."""

from __future__ import annotations

import unicodedata
from typing import Any
from uuid import UUID


def normalize_message(value: str) -> str:
    """Unicode NFC와 공백 정규화 후 1~200자, 제어 문자 없는 본문만 허용한다."""

    # 팀 전달 사항: Backend도 동일하게 공백 정규화·1~200 Unicode code point와
    # 제어 문자 규칙을 검증해야 한다. Front 검증은 UX용이며 서버 판정을 대체하지 않는다.
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("발언은 제어 문자 없이 1자부터 200자까지 입력해 주세요.")
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized or len(normalized) > 200:
        raise ValueError("발언은 제어 문자 없이 1자부터 200자까지 입력해 주세요.")
    return normalized


def build_command(*, snapshot: dict[str, Any], command_type: str,
                  message: str | None = None, target_player_id: str | None = None) -> dict[str, Any]:
    """snapshot의 legal_actions·window·target을 다시 확인해 command body를 만든다."""

    # 팀 전달 사항: Backend는 expected_state_version과 window_id를 authoritative하게
    # 재검증해야 한다. Front의 legal_actions·valid_targets는 stale될 수 있으므로
    # 허용 여부와 소유권 판정은 반드시 서버에서 최종 결정한다.

    game = snapshot.get("game")
    if not isinstance(game, dict):
        raise ValueError("게임 상태를 확인할 수 없습니다.")
    legal_actions = snapshot.get("legal_actions", [])
    if command_type not in legal_actions:
        raise ValueError("현재 상태에서는 해당 행동을 할 수 없습니다.")
    me = snapshot.get("me")
    if not isinstance(me, dict) or not me.get("alive", False):
        raise ValueError("현재는 행동할 수 없습니다.")
    window = snapshot.get("action_window")
    if command_type in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
        if not isinstance(window, dict) or window.get("paused") or window.get("has_submitted"):
            raise ValueError("현재 행동 창이 닫혀 있습니다.")
        if command_type not in window.get("legal_actions", []):
            raise ValueError("현재 행동 창에서는 해당 행동을 할 수 없습니다.")
        if command_type in {"SPEAK", "PASS"} and window.get("turn_player_id") != me.get("player_id"):
            raise ValueError("아직 발언 차례가 아닙니다.")
        if window.get("remaining_ms") is not None and window.get("remaining_ms", 0) <= 0:
            raise ValueError("행동 시간이 끝났습니다.")
    body: dict[str, Any] = {
        "type": command_type,
        "expected_state_version": game.get("state_version"),
    }
    if isinstance(window, dict) and command_type != "BEGIN_GAME":
        body["window_id"] = window.get("window_id")
    if command_type == "SPEAK":
        if not isinstance(message, str):
            raise ValueError("발언 내용을 입력해 주세요.")
        body["message"] = normalize_message(message)
    if command_type in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
        targets = window.get("valid_targets", []) if isinstance(window, dict) else []
        valid_ids = {str(item.get("player_id")) for item in targets if isinstance(item, dict)}
        try:
            candidate = str(UUID(str(target_player_id)))
        except (TypeError, ValueError):
            raise ValueError("유효한 대상이 아닙니다.") from None
        if candidate not in valid_ids:
            raise ValueError("현재 선택할 수 없는 대상입니다.")
        body["target_player_id"] = candidate
    return body
