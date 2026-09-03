"""MCP·HTTP SDK에 의존하지 않는 job-bound session memory 모델이다."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass

import anyio

from mafia_game.schemas.bootstrap import BootstrapClaims


@dataclass(slots=True)
class SessionBinding:
    """실제 자격과 subject를 process memory 한 곳에만 보관하는 binding이다."""

    token: str
    capability: str
    claims: BootstrapClaims
    sdk_owner: str
    last_activity: float = 0.0


class SessionRegistry:
    """wall-clock 만료와 monotonic idle 중 이른 deadline에 binding을 폐기한다."""

    def __init__(
        self,
        *,
        idle_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if idle_timeout_seconds <= 0:
            raise ValueError("idle timeout must be positive")
        self._bindings: dict[str, SessionBinding] = {}
        self._lock = anyio.Lock()
        self._idle_timeout_seconds = idle_timeout_seconds
        self._clock = clock
        self._monotonic = monotonic

    @property
    def active_count(self) -> int:
        """민감 payload 없이 현재 memory binding 수만 반환한다."""

        return len(self._bindings)

    @property
    def idle_timeout_seconds(self) -> float:
        """SDK manager와 동일한 idle 경계를 구성했는지 확인한다."""

        return self._idle_timeout_seconds

    async def add(self, session_id: str, binding: SessionBinding) -> bool:
        """등록 lock에서 만료 또는 session ID 충돌을 확인해 기존 binding을 덮지 않는다."""

        async with self._lock:
            if session_id in self._bindings or self._clock() >= binding.claims.exp:
                return False
            binding.last_activity = self._monotonic()
            self._bindings[session_id] = binding
            return True

    @dataclass(frozen=True, slots=True)
    class Lookup:
        """active binding 또는 이번 판정에서 제거한 만료 binding 중 하나만 담는다."""

        active: SessionBinding | None = None
        expired: SessionBinding | None = None

    def _is_expired(self, binding: SessionBinding, wall_now: float, mono_now: float) -> bool:
        return (
            wall_now >= binding.claims.exp
            or mono_now - binding.last_activity >= self._idle_timeout_seconds
        )

    async def lookup_active(
        self,
        session_id: str,
        *,
        expected: SessionBinding | None = None,
        touch: bool = False,
    ) -> Lookup:
        """membership·wall exp·idle을 한 lock에서 확인하고 필요하면 활동 시각을 갱신한다."""

        async with self._lock:
            binding = self._bindings.get(session_id)
            if binding is None or expected is not None and binding is not expected:
                return self.Lookup()
            wall_now = self._clock()
            mono_now = self._monotonic()
            if self._is_expired(binding, wall_now, mono_now):
                self._bindings.pop(session_id, None)
                return self.Lookup(expired=binding)
            if touch:
                binding.last_activity = mono_now
            return self.Lookup(active=binding)

    async def pop_expired(self) -> list[tuple[str, SessionBinding]]:
        """bootstrap exp 또는 idle deadline이 지난 binding을 먼저 원자적으로 제거한다."""

        async with self._lock:
            wall_now = self._clock()
            mono_now = self._monotonic()
            expired = [
                (session_id, binding)
                for session_id, binding in self._bindings.items()
                if self._is_expired(binding, wall_now, mono_now)
            ]
            for session_id, _ in expired:
                self._bindings.pop(session_id, None)
            return expired

    async def cleanup(self, session_id: str) -> SessionBinding | None:
        """transport 결과와 무관하게 실제 자격을 먼저 멱등 폐기한다."""

        async with self._lock:
            return self._bindings.pop(session_id, None)

    async def cleanup_all(self) -> list[tuple[str, SessionBinding]]:
        """shutdown에서 실제 자격을 모두 먼저 제거하고 종료 대상 snapshot을 반환한다."""

        async with self._lock:
            bindings = list(self._bindings.items())
            self._bindings.clear()
            return bindings

    @staticmethod
    def token_matches(binding: SessionBinding, token: str) -> bool:
        """비 ASCII header는 먼저 거부하고 정상 owner bearer만 constant-time 비교한다."""

        return token.isascii() and hmac.compare_digest(binding.token, token)
