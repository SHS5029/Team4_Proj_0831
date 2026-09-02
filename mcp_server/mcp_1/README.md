# AI 마피아 게임 MCP 연결 뼈대

참조 프로젝트의 `FastMCP`·Streamable HTTP 구조를 사용한 게임 MCP smoke 서버다.
FastAPI wrapper 없이 FastMCP가 제공하는 ASGI 앱을 직접 실행한다.
현재는 외부 API·DB·Redis·LLM을 호출하지 않는다.

```powershell
python -m mcp_server.mcp_1
```

FastMCP가 제공하는 `/mcp`에서 `initialize`, `tools/list`, `tools/call`,
`resources/list`, `resources/read`를 제공한다. 등록된 뼈대 Tool은
`game_ping`, `game_get_context`, `game_submit_proposal`이며 Tool은 proposal만
반환하고 게임 상태를 직접 변경하지 않는다. 연결 확인은 Backend가 MCP
`initialize`와 `game_ping`을 호출하는 방식으로 수행한다.

상세 구현 순서와 실행 절차는
[연결 뼈대 계획](../../docs/scaffold/AI_MAFIA_SCAFFOLD_PLAN.md)을 따른다.
