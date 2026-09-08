# AI 마피아 최소 FastMCP 서버

이 package는 FastMCP Resource·Prompt·Tool, Backend HTTP adapter와 역할별 Agent
지침을 제공한다. 게임 판정, Agent Manager, DB, Redis, LLM 호출과 상태 변경은
Backend가 담당한다.

## 등록 항목

- Resource: `mafia://context/current/{game_id}/{user_id}`,
  `mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}`
- Prompt: `agent_instruction(role="CITIZEN", phase="DAY_DISCUSSION")`
- Tool: `submit_action`

Resource의 게임 데이터와 Tool 실행은 아래 Backend endpoint에 위임한다.

```text
GET  /internal/mcp/context
POST /internal/mcp/actions
```

역할별 승리 계획·단계별 행동 전략은 `api/prompts/instructions.py`의 `ROLE_PLANS`에서
관리한다. 시민·탐정·의사·마피아 중 `me.role`에 해당하는 전략만 운영 `me.data`의
`agent_instruction`으로 제공한다. `persona.data.agent_instruction`은 검증된 성격
수치로 만든 고정 말투 지침이며 토론 외 단계에서는 빈 문자열이다. 자유 문자열은
지시문에 삽입하지 않는다. Prompt도 같은 렌더러를 사용하며 Backend prompt endpoint를
호출하지 않는다. 기존 `game_id`·`user_id` 인자는 호환용으로만 받는다.

Backend는 두 지침을 developer 메시지로 한 번 전달하고 게임 원문은 user 데이터에
둔다. 메인 system 메시지는 짧은 공통 규칙만 유지한다. 운영 응답의 정확한 계약은
[API 명세](../../docs/개발상세플랜/AI_MAFIA_API_SPEC.md)의 WU-M6 절을 따른다.

`api/prompts`, `api/resources`, `api/tools`의 `__init__.py`는 패키지 설명만 포함한다.
FastMCP 등록 코드는 각 패키지의 `registry.py`에 두며, `main.py`는 이 모듈들을 직접
import한다. Prompt와 Resource는 `api/prompts/instructions.py`의 같은 생성 함수를
사용한다. 구조 분리로 프롬프트 내용·등록명·URI·인자는 변경하지 않는다.

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
이번 변경은 MCP를 먼저 갱신한 뒤 Backend를 갱신한다. 구버전 MCP가 역할 지침을
보내지 않으면 Backend는 MCP 오류로 처리한다. `run_openai.sh`를 사용 중이면 전체
스크립트를 재시작한다. MCP 프로세스에는 자동 reload가 없다.

## 검증

```powershell
$env:PYTHONPATH = "mcp_server"
python -m pytest -q mcp_server/tests
```

테스트는 역할·단계별 선택, 페르소나 수치 검증과 원문 분리, 등록 목록, Backend adapter
위임, FastMCP ASGI 왕복을 확인한다. `test_process_backend_roundtrip.py`는 Backend와
FastMCP를 각각 실제 subprocess로 실행한다. 이 테스트는 Backend 의존성과 migration·seed가
준비된 격리 PostgreSQL이 필요하며 LLM은 dummy로 검증한다.
