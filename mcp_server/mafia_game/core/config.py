"""Mafia Game MCP process가 읽을 수 있는 설정 allowlist다."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """MCP runtime이 허용된 secret·Engine URL·listen 설정만 소비한다."""

    mcp_server_auth_secret: str
    engine_internal_api_secret: str
    engine_api_url: str
    listen_host: str = "127.0.0.1"
    listen_port: int = 8100

    def __post_init__(self) -> None:
        """방향이 다른 두 HMAC 경계가 같은 secret을 재사용하지 못하게 한다."""

        if len(self.mcp_server_auth_secret) < 32:
            raise ValueError("MCP_SERVER_AUTH_SECRET must contain at least 32 characters")
        if len(self.engine_internal_api_secret) < 32:
            raise ValueError("ENGINE_INTERNAL_API_SECRET must contain at least 32 characters")
        if self.mcp_server_auth_secret == self.engine_internal_api_secret:
            raise ValueError("MCP and Engine secrets must be different")

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        """공용 `.env`를 읽지 않고 process 환경의 명시적 allowlist만 조회한다."""

        try:
            bootstrap_secret = os.environ["MCP_SERVER_AUTH_SECRET"]
            engine_secret = os.environ["ENGINE_INTERNAL_API_SECRET"]
            engine_url = os.environ["ENGINE_API_URL"]
        except KeyError as error:
            raise RuntimeError(f"required MCP setting is missing: {error.args[0]}") from error
        try:
            port = int(os.environ.get("MCP_LISTEN_PORT", "8100"))
        except ValueError as error:
            raise RuntimeError("MCP_LISTEN_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise RuntimeError("MCP_LISTEN_PORT must be between 1 and 65535")
        host = os.environ.get("MCP_LISTEN_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("WU-M2 without TLS may listen only on loopback")
        return cls(
            mcp_server_auth_secret=bootstrap_secret,
            engine_internal_api_secret=engine_secret,
            engine_api_url=engine_url,
            listen_host=host,
            listen_port=port,
        )
