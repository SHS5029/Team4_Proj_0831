"""게임 MCP 서버의 최소 실행 설정이다."""

import os

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8010"))
