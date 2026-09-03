"""WU-M2 Mafia Game MCP runtime의 composition root다."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import anyio
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.types import ASGIApp

from mafia_game.api.bootstrap_auth import BootstrapAuthMiddleware
from mafia_game.core.config import RuntimeSettings
from mafia_game.domain.session import SessionRegistry
from mafia_game.integrations.engine_http import HttpEngineBootstrapAdapter
from mafia_game.ports.engine_bootstrap import EngineBootstrapPort
from mafia_game.schemas.bootstrap import BootstrapTokenVerifier
from mafia_game.services.bootstrap import BootstrapService, InMemoryReplayLedger


def create_app(
    settings: RuntimeSettings,
    *,
    engine: EngineBootstrapPort | None = None,
    clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
) -> Starlette:
    """stateful SDK manager와 bootstrap middleware를 단 한 번 조립한다."""

    mcp_server: Server[object] = Server("ai-mafia-mcp", version="0.1.0")
    session_manager = StreamableHTTPSessionManager(
        mcp_server,
        event_store=None,
        json_response=True,
        stateless=False,
        session_idle_timeout=30.0,
    )
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
    bootstrap_service = BootstrapService(verifier, actual_engine, replay_ledger)
    bootstrap_middleware = BootstrapAuthMiddleware(
        session_manager.handle_request,
        bootstrap_service,
        registry,
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
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run_reaper)
            async with session_manager.run():
                try:
                    yield
                finally:
                    try:
                        # shutdown cancellation보다 raw binding과 내부 HTTP client 정리를 앞선다.
                        with anyio.CancelScope(shield=True):
                            await registry.cleanup_all()
                            close = getattr(actual_engine, "aclose", None)
                            if close is not None:
                                await close()
                    finally:
                        tasks.cancel_scope.cancel()

    application = Starlette(lifespan=lifespan)
    application.mount("/", protected_app)
    application.state.session_manager = session_manager
    application.state.session_registry = registry
    application.state.bootstrap_middleware = bootstrap_middleware
    application.state.reaper_task_finished = lambda: reaper_finished
    return application


def run() -> None:
    """환경 검증 뒤 loopback 기본값으로 독립 MCP process를 실행한다."""

    import uvicorn

    settings = RuntimeSettings.from_env()
    uvicorn.run(create_app(settings), host=settings.listen_host, port=settings.listen_port)


if __name__ == "__main__":
    run()
