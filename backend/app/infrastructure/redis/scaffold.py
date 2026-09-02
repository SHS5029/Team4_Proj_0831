"""연결 뼈대에서 사용하는 Redis 보조 기능이다."""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis import Redis


class ScaffoldRedis:
    """Redis 장애를 호출자에게 알리고 원본 DB fallback을 가능하게 한다."""

    def __init__(self, url: str) -> None:
        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)

    def ping(self) -> bool:
        """Redis 연결을 확인한다."""

        return bool(self.client.ping())

    def acquire_lock(self, game_id: str, ttl: int = 30) -> str | None:
        """게임별 lock을 token으로 획득한다."""

        token = str(uuid.uuid4())
        return token if self.client.set(f"team4:game:{game_id}:lock", token, nx=True, ex=ttl) else None

    def release_lock(self, game_id: str, token: str) -> None:
        """token 소유자만 lock을 해제한다."""

        self.client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1, f"team4:game:{game_id}:lock", token,
        )

    def set_operation(self, operation_id: str, value: dict[str, Any]) -> None:
        """operation projection을 짧은 TTL로 기록한다."""

        self.client.setex(f"team4:operation:{operation_id}:status", 900, json.dumps(value, default=str))

    def publish_event(self, game_id: str, value: dict[str, Any]) -> None:
        """SSE fan-out event를 발행한다."""

        self.client.publish(f"team4:game:{game_id}:events", json.dumps(value, default=str))

    def subscribe(self, game_id: str):
        """게임 event 채널의 Pub/Sub 객체를 반환한다."""

        pubsub = self.client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(f"team4:game:{game_id}:events")
        return pubsub
