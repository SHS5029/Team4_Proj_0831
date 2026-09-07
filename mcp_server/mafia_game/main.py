"""WU-M2/M3 Mafia Game MCP session·Resource runtime의 composition root다."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import anyio
from mcp.server.lowlevel import Server
from starlette.applications import Starlette
from starlette.types import ASGIApp

from mafia_game.api.bootstrap_auth import BootstrapAuthMiddleware
from mafia_game.api.resources.handlers import register_resource_handlers
from mafia_game.api.streamable_session_pool import StreamableSessionPool
from mafia_game.core.audit import AuditRecorder, isolate_dependency_logs
from mafia_game.core.config import RuntimeSettings
from mafia_game.domain.session import SessionRegistry
from mafia_game.integrations.engine_http import HttpEngineBootstrapAdapter
from mafia_game.ports.audit import AuditSink
from mafia_game.ports.engine_context import EnginePort
from mafia_game.schemas.bootstrap import BootstrapTokenVerifier
from mafia_game.services.bootstrap import BootstrapService, InMemoryReplayLedger
from mafia_game.services.resources import ResourceService


def create_app(
    settings: RuntimeSettings,
    *,
    engine: EnginePort | None = None,
    clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    audit_sink: AuditSink | None = None,
) -> Starlette:
    """세션별 stateful SDK manager pool과 bootstrap middleware를 조립한다."""

    audit = AuditRecorder(audit_sink, clock=monotonic)
    registry = SessionRegistry(
        idle_timeout_seconds=30.0, clock=clock, monotonic=monotonic
    )
    replay_ledger = InMemoryReplayLedger(clock=clock)
    actual_engine = engine or HttpEngineBootstrapAdapter(
        settings.engine_api_url,
        settings.engine_internal_api_secret,
        clock=clock,
    )
    verifier = BootstrapTokenVerifier(settings.mcp_server_auth_secret, clock=clock)
    bootstrap_service = BootstrapService(verifier, actual_engine, replay_ledger, audit=audit)
    resource_service = ResourceService(actual_engine, audit=audit)

    def server_factory() -> Server[object]:
        """session마다 독립 request_context를 갖되 같은 registry·service를 캡처한다."""

        server: Server[object] = Server("ai-mafia-mcp", version="0.1.0")
        register_resource_handlers(server, registry, resource_service)
        return server

    session_pool = StreamableSessionPool(server_factory)
    bootstrap_middleware = BootstrapAuthMiddleware(
        session_pool,
        bootstrap_service,
        registry,
        audit=audit,
    )
    protected_app: ASGIApp = bootstrap_middleware

    reaper_finished = False

    async def run_reaper() -> None:
        nonlocal reaper_finished
        try:
            await bootstrap_middleware.run_reaper()
        finally:
            reaper_finished = True

    @asynccontextmanager
    async def runtime_lifespan() -> AsyncIterator[None]:
        async with session_pool.run():
            try:
                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(run_reaper)
                    try:
                        yield
                    finally:
                        # reaper의 session별 teardown부터 취소해 멎은 A가 shutdown의
                        # 나머지 registry·manager 정리 순서를 붙잡지 않게 한다.
                        tasks.cancel_scope.cancel()
            finally:
                bindings = await registry.cleanup_all()
                await bootstrap_middleware.shutdown(bindings)
                close = getattr(actual_engine, "aclose", None)
                if close is not None:
                    await close()

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        # SDK·HTTP 라이브러리의 debug/exception 원문은 애플리케이션 allowlist를
        # 우회하므로 lifespan 동안 formatter에 도달하기 전에 폐기한다.
        with isolate_dependency_logs():
            async with runtime_lifespan():
                yield

    application = Starlette(lifespan=lifespan)
    application.mount("/", protected_app)
    application.state.session_manager = session_pool
    application.state.session_registry = registry
    application.state.bootstrap_middleware = bootstrap_middleware
    application.state.reaper_task_finished = lambda: reaper_finished
    return application


def run() -> None:
    """환경 검증 뒤 loopback 기본값으로 독립 MCP process를 실행한다."""

    import uvicorn

    settings = RuntimeSettings.from_env()
    # lifespan 종료 오류를 host가 처리하는 시점까지 원문 진단 로그를 차단한다.
    with isolate_dependency_logs():
        uvicorn.run(
            create_app(settings), host=settings.listen_host, port=settings.listen_port,
            access_log=False,
        )


if __name__ == "__main__":
    run()
