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
    """snapshot에서 입력 형식만 정규화해 Backend 검증용 command를 만든다."""

    # Front snapshot의 legal_actions·valid_targets·turn 정보는 SSE 시점 차이로
    # stale될 수 있다. Front는 형식만 정리하고 행동 가능 여부는 Backend가 최신
    # DB transaction에서 최종 판정하도록 요청을 전송한다.

    game = snapshot.get("game")
    if not isinstance(game, dict):
        raise ValueError("게임 상태를 확인할 수 없습니다.")
    if command_type not in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE", "SAVE_AND_EXIT", "RESUME", "FAST_FORWARD", "BEGIN_GAME"}:
        raise ValueError("지원하지 않는 게임 행동입니다.")
    window = snapshot.get("action_window")
    body: dict[str, Any] = {
        "type": command_type,
        "expected_state_version": game.get("state_version"),
    }
    if command_type in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"} and isinstance(window, dict):
        body["window_id"] = window.get("window_id")
    if command_type == "SPEAK":
        if not isinstance(message, str):
            raise ValueError("발언 내용을 입력해 주세요.")
        body["message"] = normalize_message(message)
    if command_type in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
        try:
            candidate = str(UUID(str(target_player_id)))
        except (TypeError, ValueError):
            raise ValueError("유효한 대상이 아닙니다.") from None
        body["target_player_id"] = candidate
    return body
