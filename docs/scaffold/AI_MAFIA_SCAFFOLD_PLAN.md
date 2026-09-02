# AI 마피아 연결 뼈대 우선 구현 계획 `scaffold-v1`

상태: 구현 착수용 확정 계획  
목적: 게임 규칙·LLM·운영 기능을 완성하기 전에 Frontend, Backend, 게임 MCP 서버가 독립 실행되고 요청을 왕복하는 최소 시스템을 완성한다.

참고 구현은 다음 두 저장소에서 선별한다.

- MCP 참고: `C:\phase2\mini_agent_03_mcp_0827`
- Backend 참고: `C:\phase2\mini_agent_03_tool_0824`

두 참고 저장소의 여행·날씨·주차장 도메인과 `.env`, `.venv`, 실제 secret은 가져오지
않는다. 이 계획은 현재 저장소의 기존 OIDC·Backend 구조를 보존한 상태에서 적용한다.

세부 실행 문서는 [파일별 구현 계획](AI_MAFIA_SCAFFOLD_FILE_PLAN.md),
[JSON Schema 계약](AI_MAFIA_SCAFFOLD_SCHEMA.md),
[실행 절차](AI_MAFIA_SCAFFOLD_RUNBOOK.md),
[테스트 계획](AI_MAFIA_SCAFFOLD_TEST_PLAN.md)을 함께 사용한다.

## 1. 뼈대 단계의 완료 범위

### 포함

- `frontend_user`, `frontend_admin`, `backend`, `mcp_server/mcp_1`의 독립 실행
- Backend Swagger UI와 OpenAPI 계약 노출
- Frontend → Backend REST 요청 왕복
- Backend → PostgreSQL 저장 왕복
- Backend → Redis 연결 확인과 임시 operation 상태 기록
- Backend → MCP Client → 게임 MCP Server 왕복
- 게임 생성·조회·dummy command·operation 조회·SSE smoke flow
- HMAC, UUID, trace_id, idempotency_key, state_version의 연결 구조

### 제외

- 실제 마피아 role 배정·밤/낮 판정·승패 로직
- 실제 LLM 호출과 provider별 prompt 정책
- 완성된 MCP 게임 Resource·Tool
- 관리자 KPI 산출 로직과 인증·권한
- 실제 게임 결과·메모·평점 기능
- 외부 공개용 인증

뼈대 단계에서 게임 상태는 `SCAFFOLD` 또는 `ROLE_REVEAL`만 사용하고, dummy command는
상태 왕복과 version 증가만 검증한다. 실제 규칙은
[게임 규칙·로직](../AI_MAFIA_GAME_RULES.md) 구현 단계에서 추가한다.

## 2. 목표 실행 구조

```text
frontend_user :8501 ─┐
frontend_admin :8502 ─┼─ HTTP ─→ backend :8000
                       │              ├─ PostgreSQL
                       │              ├─ Redis
                       │              └─ MCP Client
                       │                    │ Streamable HTTP
                       └────────────────────┴─ mcp_server/mcp_1 :8010/mcp
```

Frontend는 Backend URL만 알고, MCP URL·DB URL·Redis URL을 알지 않는다. MCP 서버는
Frontend를 알지 않으며 Backend의 context/proposal port만 사용한다.

## 3. 참고 코드의 선별 이식표

| 참고 위치 | 가져올 원칙 | 현재 저장소 적용 위치 | 가져오지 않을 것 |
|---|---|---|---|
| `mcp_0827/backend/app/mcp_client.py` | `ClientSession`, Streamable HTTP, session lifecycle, `tools/list`·`tools/call` | `backend/app/mcp/client.py`·`registry.py` | weather/tour server registry |
| `mcp_0827/mcp_server/tour/server.py` | `FastMCP` 생성, transport, `create_server` | `mcp_server/mcp_1/server.py` | TourService, DB, embedding |
| `mcp_0827/mcp_server/*/api` | MCP registration 계층 | `mcp_server/mcp_1/api` | 날씨·관광 Tool/Resource |
| `tool_0824/backend/app/main.py` | FastAPI app, router, tag, Swagger | `backend/app/main.py` | stage/lab/parking router |
| `tool_0824/backend/app/tools/registry.py` | schema와 실행 함수의 registry 패턴 | `backend/app/mcp/registry.py` | weather·travel 함수 |
| `tool_0824/backend/app/providers/registry.py` | provider 선택·allowlist 패턴 | 후속 `backend/app/llm/registry.py` | 실제 provider 호출 |
| `tool_0824/backend/app/schemas` | Pydantic schema와 JSON Schema 생성 | `backend/app/schemas/game_schema.py` | 교육용 lab schema |

파일을 덮어쓰지 않고 현재 저장소의 import 경계에 맞춰 새 모듈을 추가한다. 참고
프로젝트의 `backend.app` 절대 import 방식은 현재 저장소 패키지명에 맞게 변환한다.

## 4. 뼈대 계약

### 4.1 공통 응답

```json
{
  "trace_id": "00000000-0000-4000-8000-000000000001",
  "data": {}
}
```

게임 API는 기존 Backend 계약의 응답 형태를 우선한다. 오류는 다음 형태로 고정한다.

```json
{
  "code": "INVALID_REQUEST",
  "message": "요청 형식이 올바르지 않습니다.",
  "details": null,
  "trace_id": "00000000-0000-4000-8000-000000000002"
}
```

### 4.2 Backend smoke API

| method | path | 목적 | 성공 응답 |
|---|---|---|---|
| `GET` | `/health` | Backend process 확인 | `{"status":"ok"}` |
| `GET` | `/api/v1/mcp/health` | MCP 연결 확인 | `{"status":"connected","server":"game","transport":"streamable-http"}` |
| `POST` | `/api/v1/games` | dummy game 생성 | `CreateGameResponse` |
| `GET` | `/api/v1/games/{game_id}` | 현재 dummy 상태 조회 | `GameStateResponse` |
| `POST` | `/api/v1/games/{game_id}/commands` | dummy command 수락 | `CommandAcceptedResponse` |
| `GET` | `/api/v1/games/{game_id}/operations/{operation_id}` | operation polling | `OperationResponse` |
| `GET` | `/api/v1/games/{game_id}/events` | SSE 연결·heartbeat 확인 | `text/event-stream` |

모든 game API는 `X-User-Id`를 요구한다. 생성 요청은 아래와 같다.

```json
{
  "player_count": 5,
  "ruleset_version": "scaffold-v1",
  "idempotency_key": "00000000-0000-4000-8000-000000000010"
}
```

생성 응답은 다음 필드를 가진다.

```json
{
  "game_id": "00000000-0000-4000-8000-000000000011",
  "status": "IN_PROGRESS",
  "phase": "ROLE_REVEAL",
  "state_version": 1,
  "player": {"player_id":"uuid","kind":"HUMAN","role":null,"alive":true},
  "players": []
}
```

뼈대 command는 `BEGIN_GAME`, `PAUSE`, `RESUME`, `PING`만 허용한다.

```json
{
  "command": "PING",
  "expected_version": 1,
  "idempotency_key": "00000000-0000-4000-8000-000000000012"
}
```

응답은 다음과 같다.

```json
{
  "accepted": true,
  "operation_id": "00000000-0000-4000-8000-000000000013",
  "state_version": 2,
  "phase": "ROLE_REVEAL",
  "status": "COMPLETED"
}
```

`PING`은 실제 게임 상태를 바꾸지 않는 연결 시험 명령이며 operation·trace 왕복만
검증한다. `BEGIN_GAME`은 phase와 state_version을 변경하지 않고 수락 경로만 검증한다.

### 4.3 MCP smoke 계약

MCP endpoint는 `http://127.0.0.1:8010/mcp`로 고정한다. `mcp_server/mcp_1`은 다음
표준 MCP method를 지원한다.

| method | 결과 |
|---|---|
| `initialize` | protocol version·server info·capabilities |
| `notifications/initialized` | session 초기화 완료 |
| `tools/list` | `game_ping`, `game_get_context`, `game_submit_proposal` |
| `tools/call` | proposal JSON 반환, 게임 상태 직접 변경 금지 |
| `resources/list` | scaffold game resource 목록 |
| `resources/read` | 현재 dummy context JSON |

`game_submit_proposal` 입력과 출력은 다음으로 고정한다.

```json
// input
{"action":"PING","expected_version":1}

// output
{"proposal_id":"uuid","action":"PING","state_version":1,"accepted":true}
```

뼈대 단계에서는 내부 HMAC header를 먼저 연결하되, 실제 role·private data 필터링은
dummy context로만 검증한다. 상세 최종 MCP 계약은
[MCP API 계약](../AI_MAFIA_MCP_API_CONTRACT.md)으로 확장한다.

## 5. 단계별 구현 순서

### 0단계 — 실행 환경과 설정

- 각 서비스의 host/port와 실행 명령을 고정한다.
- `.env.example`에 `BACKEND_API_URL`, `DATABASE_URL`, `REDIS_URL`, `MAFIA_MCP_URL`,
  `MCP_INTERNAL_SECRET` placeholder만 둔다.
- 실제 `.env`와 secret은 참고 프로젝트에서 복사하지 않는다.
- 공통 dependency 버전을 현재 저장소 `pyproject.toml`에서 관리한다.

완료: 네 프로세스가 별도 터미널에서 기동되고 잘못된 설정은 시작 시 명확히 실패한다.

### 1단계 — MCP 서버 뼈대

- `mcp_server/mcp_1/server.py`와 `__main__.py`를 만든다.
- `FastMCP` Streamable HTTP를 `8010`에서 실행한다.
- `tools/list`, `tools/call`, `resources/list`, `resources/read` smoke 구현을 추가한다.
- game 전용 schema와 오류 변환을 추가한다.

완료: MCP inspector 또는 MCP Client로 initialize부터 Tool call까지 재현된다.

### 2단계 — Backend app과 MCP Client

- 현재 FastAPI app에 game router와 mcp health router를 등록한다.
- 참고 MCP client의 session lifecycle만 이식한다.
- MCP URL allowlist는 game 서버 한 개만 허용한다.
- MCP 장애는 Backend 503으로 정규화하고 game 상태를 변경하지 않는다.

완료: Backend `/api/v1/mcp/health`와 내부 MCP Tool call이 통과한다.

### 3단계 — dummy game REST와 Swagger

- `game_schema.py`에 위 request/response schema를 작성한다.
- in-memory repository로 생성·조회·command·operation을 구현한다.
- `state_version` 비교, idempotency fingerprint, 소유자 확인을 적용한다.
- OpenAPI path와 schema를 `AI_MAFIA_BACKEND_OPENAPI.yaml`과 비교한다.

완료: Swagger UI에서 모든 smoke API를 실행하고 JSON 응답을 확인한다.

### 4단계 — PostgreSQL·Redis 연결

- game 핵심 migration을 추가한다.
- repository를 in-memory에서 PostgreSQL adapter로 교체한다.
- Redis는 lock·operation projection·rate limit smoke만 연결한다.
- Redis 중단 시 operation GET과 game GET은 PostgreSQL로 동작하게 한다.

완료: 재시작 후 생성한 dummy game과 operation을 조회할 수 있다.

### 5단계 — Frontend smoke

- `frontend_user`에 create/list/game 최소 화면을 추가한다.
- `frontend_admin`에는 Backend health·MCP health 표시만 추가한다.
- Frontend는 `X-User-Id`와 Backend URL만 사용한다.
- command 제출 중 중복 클릭을 차단하고 SSE 실패 시 state polling으로 전환한다.

완료: 브라우저에서 생성 → 조회 → PING → operation 완료 → SSE 연결을 확인한다.

### 6단계 — 뼈대 통합 게이트

- Backend·MCP·Frontend를 깨끗한 환경에서 순서대로 기동한다.
- 정상·잘못된 UUID·404·409 version·idempotency 중복·MCP 중단을 확인한다.
- `pytest`, `compileall`, `ruff`, OpenAPI schema diff를 실행한다.
- 통과 후에만 실제 ruleset `basic-v1`, LLM, persona, 결과 기능을 착수한다.

## 6. 책임 경계

| 질문 | 결정 |
|---|---|
| 최종 상태는 누가 변경하는가 | Backend만 변경 |
| MCP Tool은 무엇을 반환하는가 | proposal 또는 context |
| DB에 직접 접근하는 컴포넌트 | Backend만 |
| Redis 장애 시 원본은 무엇인가 | PostgreSQL |
| Frontend가 게임 규칙을 계산하는가 | 계산하지 않고 API projection만 표시 |
| 뼈대 단계의 게임 규칙 | dummy 상태만 사용 |
| 참고 코드의 domain | 이식하지 않고 구조만 참고 |

## 7. 산출물과 완료 기준

산출물은 `mcp_server/mcp_1` 실행 서버, Backend smoke router/schema/client, PostgreSQL
migration, Frontend smoke 화면, 실행 안내 README, smoke/contract test다. 아래 흐름이
한 번에 통과하면 뼈대 단계 완료다.

```text
GET /health
→ GET /api/v1/mcp/health
→ POST /api/v1/games
→ GET /api/v1/games/{game_id}
→ POST .../commands (PING)
→ GET .../operations/{operation_id}
→ GET .../events
→ Frontend 화면에 상태 표시
```

이 계획서와 실제 구현이 달라질 경우, 게임 기능 구현 전에 이 문서·OpenAPI·README를
동시에 갱신한다.
