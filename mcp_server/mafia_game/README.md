# AI 마피아 최소 FastMCP 서버

이 package는 FastMCP Resource·Prompt·Tool 등록부와 Backend HTTP adapter만 제공한다.
게임 규칙, Agent Manager, DB, Redis, LLM, 인증과 상태 변경은 구현하지 않는다.

## 등록 항목

- Resource: `mafia://context/current`
- Prompt: `agent_instruction`
- Tool: `submit_action`

모든 handler는 Backend endpoint로 요청을 전달하고 응답을 반환한다.

```text
GET  /internal/mcp/context
GET  /internal/mcp/prompts/agent_instruction
POST /internal/mcp/actions
```

## 실행

Backend를 먼저 실행한 뒤 다음 환경변수로 FastMCP process를 실행한다.

```powershell
$env:BACKEND_API_URL = "http://127.0.0.1:8000"
$env:MCP_LISTEN_HOST = "127.0.0.1"
$env:MCP_LISTEN_PORT = "8100"
python -m mafia_game
```

MCP endpoint는 `http://127.0.0.1:8100/mcp`다. FastMCP 표준 protocol session은 SDK가
관리하지만, 별도의 bootstrap token·HMAC·nonce·session registry는 사용하지 않는다.

## 검증

```powershell
$env:PYTHONPATH = "mcp_server"
python -m pytest -q mcp_server/tests
```

테스트는 등록 목록, Backend adapter 위임, FastMCP ASGI 왕복과 Backend synthetic
endpoint 계약을 확인한다. `test_process_backend_roundtrip.py`는 Backend와 FastMCP를
각각 실제 subprocess로 실행해 같은 세 계약의 HTTP 왕복을 확인한다.
