"""FastMCP composition root의 1단계 전환 경계를 검증한다."""

from mcp.server.fastmcp import FastMCP

from mafia_game.main import create_fastmcp_server


def test_fastmcp_server_is_created_with_streamable_http_settings() -> None:
    """기존 서버를 교체하지 않고 FastMCP 객체와 HTTP 설정을 준비한다."""

    server = create_fastmcp_server()

    assert isinstance(server, FastMCP)
    assert server.settings.json_response is True
    assert server.settings.stateless_http is False
    assert server.settings.streamable_http_path == "/mcp"
