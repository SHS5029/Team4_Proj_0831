"""세션별 MCP server와 stateful manager의 공개 lifecycle을 소유한다."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
from anyio.abc import TaskGroup, TaskStatus
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send

SESSION_POOL_OWNER_SCOPE_KEY = "mafia_game.session_pool_owner"
SESSION_POOL_PHASE_SCOPE_KEY = "mafia_game.session_pool_phase"
SESSION_POOL_BINDING_SCOPE_KEY = "mafia_game.session_pool_binding"
_CANDIDATE = "candidate"
_ACTIVE = "active"
_RETIRING = "retiring"


@dataclass(slots=True)
class _SessionRuntime:
    """manager 하나의 run context와 종료 신호를 다른 세션과 분리한다."""

    owner: str
    manager: StreamableHTTPSessionManager
    stop: anyio.Event = field(default_factory=anyio.Event)
    stopped: anyio.Event = field(default_factory=anyio.Event)
    teardown_started: bool = False


class StreamableSessionPool:
    """세션별 manager를 공개 SDK API만으로 생성·route·종료한다.

    SDK manager의 내부 transport·owner map은 관측하거나 수정하지 않는다. route에서
    분리한 runtime의 공개 DELETE를 최대 한 번 시도하고, 성공·오류·취소와 무관하게
    해당 manager의 단 한 번뿐인 ``run()`` context를 끝낸다.
    """

    stateless = False
    event_store = None
    json_response = True
    session_idle_timeout = None

    def __init__(self, server_factory: Callable[[], Server[Any]]) -> None:
        self._server_factory = server_factory
        self._lifecycle_tasks: TaskGroup | None = None
        self._has_started = False
        self._accepting = False
        self._candidates: dict[str, _SessionRuntime] = {}
        self._routes: dict[str, _SessionRuntime] = {}
        self._retiring: dict[str, _SessionRuntime] = {}
        self._running: dict[str, _SessionRuntime] = {}
        self._run_exit_count = 0
        self._run_exit_event = anyio.Event()

    @property
    def candidate_count(self) -> int:
        """민감한 session 식별자 없이 아직 publish되지 않은 runtime 수만 반환한다."""

        return len(self._candidates)

    @property
    def active_count(self) -> int:
        """외부 follow-up routing에 publish된 runtime 수만 반환한다."""

        return len(self._routes)

    @property
    def running_count(self) -> int:
        """아직 ``run()`` context가 종료되지 않은 manager 수만 반환한다."""

        return len(self._running)

    @property
    def run_exit_count(self) -> int:
        """process lifetime 동안 공개 ``run()`` context가 끝난 횟수만 반환한다."""

        return self._run_exit_count

    async def wait_for_run_exits(self, count: int) -> None:
        """민감 식별자 없이 요청한 개수의 manager run 종료가 관측될 때까지 기다린다."""

        while self._run_exit_count < count:
            changed = self._run_exit_event
            if self._run_exit_count >= count:
                return
            await changed.wait()

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """pool task group과 모든 manager별 단일 ``run()`` 소유권을 묶는다."""

        if self._has_started:
            raise RuntimeError("StreamableSessionPool.run() can only be called once")
        self._has_started = True
        async with anyio.create_task_group() as tasks:
            self._lifecycle_tasks = tasks
            self._accepting = True
            try:
                yield
            finally:
                self._accepting = False
                # 남은 request가 취소를 무시하더라도 먼저 manager별 stop을 독립 전달한다.
                # task group 취소는 그 뒤 공개 run context의 child 작업을 정리한다.
                for runtime in tuple(self._running.values()):
                    runtime.stop.set()
                tasks.cancel_scope.cancel()
                self._lifecycle_tasks = None
                self._candidates.clear()
                self._routes.clear()
                self._retiring.clear()

    async def start_candidate(self, owner: str) -> None:
        """fresh Server와 manager의 ``run()`` 준비가 끝난 뒤 candidate를 노출한다."""

        tasks = self._lifecycle_tasks
        if not self._accepting or tasks is None or owner in self._running:
            raise RuntimeError("session pool is not accepting candidates")
        manager = StreamableHTTPSessionManager(
            self._server_factory(),
            event_store=None,
            json_response=True,
            stateless=False,
            session_idle_timeout=None,
        )
        runtime = _SessionRuntime(owner=owner, manager=manager)
        try:
            await tasks.start(self._run_manager, runtime)
            # task_status.started() 뒤에는 manager.handle_request가 안전하며, 이 대입들은
            # await가 없어 같은 event loop의 다른 요청에 부분 candidate를 보이지 않는다.
            self._running[owner] = runtime
            self._candidates[owner] = runtime
        except BaseException:
            runtime.stop.set()
            raise

    async def _run_manager(
        self,
        runtime: _SessionRuntime,
        *,
        task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """manager 공개 run context를 정확히 한 번 열고 stop 신호 하나로 끝낸다."""

        try:
            async with runtime.manager.run():
                task_status.started()
                await runtime.stop.wait()
        finally:
            if self._running.get(runtime.owner) is runtime:
                self._running.pop(runtime.owner, None)
                self._run_exit_count += 1
                changed = self._run_exit_event
                self._run_exit_event = anyio.Event()
                changed.set()
            if self._candidates.get(runtime.owner) is runtime:
                self._candidates.pop(runtime.owner, None)
            for session_id, routed in tuple(self._routes.items()):
                if routed is runtime:
                    self._routes.pop(session_id, None)
            if self._retiring.get(runtime.owner) is runtime:
                self._retiring.pop(runtime.owner, None)
            runtime.stopped.set()

    def publish(self, session_id: str, owner: str) -> bool:
        """candidate identity가 맞고 ID 충돌이 없을 때만 follow-up route를 공개한다."""

        runtime = self._candidates.get(owner)
        if runtime is None or session_id in self._routes:
            return False
        self._candidates.pop(owner, None)
        self._routes[session_id] = runtime
        return True

    def begin_retirement(self, session_id: str | None, owner: str) -> bool:
        """expected owner runtime만 route/candidate에서 먼저 떼어 teardown 소유권을 준다."""

        if owner in self._retiring:
            return False
        runtime = self._routes.get(session_id) if session_id is not None else None
        if runtime is not None and runtime.owner == owner:
            self._routes.pop(session_id, None)
        else:
            runtime = self._candidates.get(owner)
            if runtime is None:
                return False
            self._candidates.pop(owner, None)
        self._retiring[owner] = runtime
        return True

    def restore(self, session_id: str, owner: str) -> bool:
        """registry 만료 재검사가 뒤집힌 경우 같은 entry만 route로 되돌린다."""

        runtime = self._retiring.get(owner)
        if runtime is None or runtime.teardown_started or session_id in self._routes:
            return False
        self._retiring.pop(owner, None)
        self._routes[session_id] = runtime
        return True

    def start_soon(self, function: Callable[..., Awaitable[None]], *args: object) -> None:
        """request 취소와 분리된 pool lifespan에 보상 teardown을 맡긴다."""

        tasks = self._lifecycle_tasks
        if tasks is None:
            return
        tasks.start_soon(function, *args)

    async def retire(
        self,
        owner: str,
        request: Callable[[], Awaitable[list[Message]]] | None,
    ) -> list[Message] | None:
        """공개 DELETE를 최대 한 번 호출하고 finally에서 manager stop을 확정한다."""

        runtime = self._retiring.get(owner)
        if runtime is None or runtime.teardown_started:
            return None
        # 첫 await 전에 소유권을 고정해 이미 취소된 호출도 finally stop까지 도달한다.
        runtime.teardown_started = True
        try:
            messages = await request() if request is not None else None
        except anyio.get_cancelled_exc_class():
            runtime.stop.set()
            raise
        except BaseException:
            runtime.stop.set()
            await runtime.stopped.wait()
            raise
        runtime.stop.set()
        await runtime.stopped.wait()
        return messages

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """scope의 opaque owner와 phase로 candidate·active·retiring manager만 선택한다."""

        owner = scope.get(SESSION_POOL_OWNER_SCOPE_KEY)
        phase = scope.get(SESSION_POOL_PHASE_SCOPE_KEY)
        runtime: _SessionRuntime | None = None
        if isinstance(owner, str) and phase == _CANDIDATE:
            runtime = self._candidates.get(owner)
        elif isinstance(owner, str) and phase == _RETIRING:
            runtime = self._retiring.get(owner)
        elif isinstance(owner, str) and phase == _ACTIVE:
            session_id = _single_session_id(scope)
            if session_id is not None:
                candidate = self._routes.get(session_id)
                if candidate is not None and candidate.owner == owner:
                    runtime = candidate
        if runtime is None:
            await Response(
                b'{"error":"SESSION_NOT_FOUND"}',
                status_code=404,
                media_type="application/json",
            )(scope, receive, send)
            return
        await runtime.manager.handle_request(scope, receive, send)


def mark_candidate(scope: Scope, owner: str) -> None:
    """initialize scope를 아직 외부 route가 아닌 특정 candidate에만 고정한다."""

    scope[SESSION_POOL_OWNER_SCOPE_KEY] = owner
    scope[SESSION_POOL_PHASE_SCOPE_KEY] = _CANDIDATE


def mark_active(scope: Scope, owner: str, binding: object) -> None:
    """follow-up scope에 expected owner와 요청 시점 binding identity를 함께 고정한다."""

    scope[SESSION_POOL_OWNER_SCOPE_KEY] = owner
    scope[SESSION_POOL_PHASE_SCOPE_KEY] = _ACTIVE
    scope[SESSION_POOL_BINDING_SCOPE_KEY] = binding


def mark_retiring(scope: Scope, owner: str) -> None:
    """route에서 제거된 old runtime만 terminal DELETE가 찾도록 identity를 고정한다."""

    scope[SESSION_POOL_OWNER_SCOPE_KEY] = owner
    scope[SESSION_POOL_PHASE_SCOPE_KEY] = _RETIRING


def _single_session_id(scope: Scope) -> str | None:
    values = [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == b"mcp-session-id"
    ]
    return values[0] if len(values) == 1 and values[0] else None
