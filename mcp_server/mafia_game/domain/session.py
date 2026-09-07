"""MCP·HTTP SDK에 의존하지 않는 job-bound session memory 모델이다."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import anyio

from mafia_game.schemas.bootstrap import BootstrapClaims, ConsumeBinding


def _completed_event() -> anyio.Event:
    """진행 중 성공 commit이 없는 초기 상태를 나타내는 set된 event를 만든다."""

    event = anyio.Event()
    event.set()
    return event


@dataclass(slots=True)
class SessionBinding:
    """실제 자격과 subject를 process memory 한 곳에만 보관하는 binding이다."""

    token: str
    capability: str
    claims: BootstrapClaims
    issuance: ConsumeBinding
    sdk_owner: str
    last_activity: float = 0.0
    terminal_gate: anyio.Lock = field(default_factory=anyio.Lock, repr=False)
    terminal_pending: bool = False
    active_commits: int = 0
    commits_drained: anyio.Event = field(default_factory=_completed_event, repr=False)


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
        """gate-aware registry reaper가 단독 소유하는 고정 idle 경계를 반환한다."""

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
        """membership·wall exp·idle을 한 lock에서 확인하고 필요하면 활동 시각을 갱신한다.

        만료 binding은 여기서 먼저 제거하지 않는다. 호출자가 expected identity로
        cleanup 소유권을 획득해야 동시 종료 경로에서 SDK transport를 한 번만
        닫을 수 있다.
        """

        async with self._lock:
            binding = self._bindings.get(session_id)
            if binding is None or expected is not None and binding is not expected:
                return self.Lookup()
            wall_now = self._clock()
            mono_now = self._monotonic()
            if self._is_expired(binding, wall_now, mono_now):
                return self.Lookup(expired=binding)
            if touch:
                binding.last_activity = mono_now
            return self.Lookup(active=binding)

    async def expired_candidates(self) -> list[tuple[str, SessionBinding]]:
        """reaper가 session별 gate에서 재판정할 만료 후보 snapshot만 반환한다."""

        async with self._lock:
            wall_now = self._clock()
            mono_now = self._monotonic()
            return [
                (session_id, binding)
                for session_id, binding in self._bindings.items()
                if self._is_expired(binding, wall_now, mono_now)
            ]

    async def cleanup_expired(
        self, session_id: str, *, expected: SessionBinding
    ) -> SessionBinding | None:
        """gate 대기 중 활동 시각이 바뀔 수 있으므로 만료를 재검사한 승자만 제거한다."""

        async with self._lock:
            binding = self._bindings.get(session_id)
            if binding is not expected:
                return None
            if not self._is_expired(binding, self._clock(), self._monotonic()):
                return None
            return self._bindings.pop(session_id, None)

    async def lookup_bound(self, session_id: str) -> SessionBinding | None:
        """인증 middleware가 확정한 같은 요청 안에서 binding을 제거 없이 조회한다."""

        async with self._lock:
            return self._bindings.get(session_id)

    async def cleanup(
        self, session_id: str, *, expected: SessionBinding | None = None
    ) -> SessionBinding | None:
        """expected binding을 원자적으로 한 번만 제거해 transport 종료 소유자를 정한다."""

        async with self._lock:
            binding = self._bindings.get(session_id)
            if binding is None or expected is not None and binding is not expected:
                return None
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
