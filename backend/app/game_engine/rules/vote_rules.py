"""투표 결과를 계산하는 순수 규칙."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from backend.app.models.game_state import Vote


def leaders(votes: dict[UUID, Vote]) -> list[UUID]:
    """가장 많은 표를 받은 대상 목록을 반환한다."""

    counts = Counter(vote.target_id for vote in votes.values())
    highest = max(counts.values()) if counts else 0
    return [target_id for target_id, count in counts.items() if count == highest]

