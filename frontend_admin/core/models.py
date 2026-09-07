"""관리자 API의 민감정보 차단 모델."""

from __future__ import annotations

from typing import Any

# 관리자 목록 API가 허용하는 값만 UI와 요청 검증에서 함께 사용한다.
ADMIN_STATUSES = ("IN_PROGRESS", "SAVED", "COMPLETED", "FAILED")
ADMIN_PHASES = (
    "ROLE_REVEAL", "DAY_DISCUSSION", "NIGHT_ACTION", "DAY_VOTE", "REVOTE",
    "FINAL_DISCUSSION", "FINAL_ACCUSATION", "ENDED",
)

PRIVATE_KEYS = {"role", "alibi", "observation", "private_events", "action", "vote", "seed", "agent_context"}


def reject_private_fields(value: Any) -> Any:
    """진행 중 관리자 payload에 private field가 섞이면 즉시 거부한다."""

    # 팀 전달 사항: Backend 관리자 상세에는 진행 중 role·개인 사실·개별 행동·투표·
    # seed·Agent private context를 반환하지 않는다. `***`로 마스킹해 통과시키지 않는다.
    if isinstance(value, dict):
        if any(key in PRIVATE_KEYS for key in value):
            raise ValueError("ADMIN_PRIVATE_FIELD")
        return {key: reject_private_fields(item) for key, item in value.items()}
    if isinstance(value, list):
        return [reject_private_fields(item) for item in value]
    return value
