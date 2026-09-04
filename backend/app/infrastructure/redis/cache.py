"""Redis 공개 projection cache 기능."""

from __future__ import annotations

import json
from typing import Any

from redis import Redis


PUBLIC_KEY_PREFIX = "mafia:v1:public:"


class RedisPublicCache:
    """PostgreSQL에서 다시 만들 수 있는 공개 snapshot만 짧게 캐시한다.

    이 클래스는 private role, seed, prompt를 받지 않는 호출부와 함께 사용해야
    한다. Redis 데이터가 없어져도 원본 DB로 응답을 재구성할 수 있어야 한다.
    """

    def __init__(self, client: Redis, *, ttl_seconds: int = 60) -> None:
        if ttl_seconds <= 0:
            raise ValueError("공개 cache TTL은 0보다 커야 합니다.")
        self._client = client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def key(game_id: str, state_version: int) -> str:
        """게임과 state version별 공개 cache key를 만든다."""

        return f"{PUBLIC_KEY_PREFIX}{game_id}:{state_version}"

    def set(self, game_id: str, state_version: int, projection: dict[str, Any]) -> None:
        """공개 projection을 JSON으로 저장한다."""

        if state_version <= 0:
            raise ValueError("state_version은 1 이상이어야 합니다.")
        value = json.dumps(projection, ensure_ascii=False, separators=(",", ":"))
        self._client.setex(self.key(game_id, state_version), self._ttl_seconds, value)

    def get(self, game_id: str, state_version: int) -> dict[str, Any] | None:
        """cache miss면 None을 반환하고, JSON object가 아니면 폐기한다."""

        raw = self._client.get(self.key(game_id, state_version))
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            self._client.delete(self.key(game_id, state_version))
            return None
        return parsed if isinstance(parsed, dict) else None

    def delete(self, game_id: str, state_version: int) -> None:
        """검증된 공개 cache 한 건만 삭제한다."""

        self._client.delete(self.key(game_id, state_version))
