"""WU-M2 Mafia Game MCP runtime의 composition root다."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from mafia_game.api.prompts import register_prompts
from mafia_game.api.resources import register_resources
from mafia_game.api.tools import register_tools
from mafia_game.integrations.engine_http import (
    BackendContextClient,
    MinimalBackendContextClient,
)


def create_fastmcp_server(backend: BackendContextClient | None = None) -> FastMCP:
    """FastMCP 운영 객체를 만들고 주입된 Backend adapter의 등록부를 조립한다.

    FastMCP가 protocol session을 관리하도록 위임하고, 프로젝트 내부에는 별도의
    bootstrap·session 상태 머신을 두지 않는다. 게임 규칙과 상태 변경은 Backend에
    남겨 MCP 등록부가 자체 판단을 수행하지 않도록 한다.
    """

    server = FastMCP(
        "ai-mafia-mcp",
        json_response=True,
        stateless_http=False,
        streamable_http_path="/mcp",
    )
    if backend is not None:
        register_fastmcp_components(server, backend)
    return server


def register_fastmcp_components(server: FastMCP, backend: BackendContextClient) -> None:
    """컨텍스트 Resource·Prompt 등록을 한 composition root에서 조립한다."""

    register_resources(server, backend)
    register_tools(server, backend)
    register_prompts(server, backend)


def create_minimal_fastmcp_app(backend: BackendContextClient):
    """기존 인증 runtime 없이 FastMCP 등록부만 노출하는 최소 ASGI 앱을 만든다."""

    return create_fastmcp_server(backend).streamable_http_app()


def run() -> None:
    """최소 FastMCP 등록부를 loopback 개발 서버로 실행한다."""

    import uvicorn

    backend_url = os.environ.get("BACKEND_API_URL", "http://127.0.0.1:8000")
    host = os.environ.get("MCP_LISTEN_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_LISTEN_PORT", "8100"))
    backend = MinimalBackendContextClient(backend_url)
    uvicorn.run(create_minimal_fastmcp_app(backend), host=host, port=port)


if __name__ == "__main__":
    run()
