# AI 마피아 MVP 최종 조율 계획 `minimum-v1`

이 문서는 Frontend·Backend·게임 MCP를 독립 개발한 뒤 통합하는 최종 조율 기준이다. 먼저 [연결 뼈대 우선 구현 계획](scaffold/AI_MAFIA_SCAFFOLD_PLAN.md)의 smoke 단계를 완료한 뒤 이 문서의 게임 기능 단계를 진행한다. 구현 전 결정은 모두 아래 계약으로 고정했으며 별도 합의 없이 변경하지 않는다.

## 1. 고정 범위

사용자 1명과 AI 참가자 4~8명의 `basic-v1` 마피아 게임, 저장·재개·관전·결과·단일 평점, 관리자 KPI·로그·feedback 조회를 제공한다. OIDC는 기존 서비스에 남지만 게임 MVP는 개발용 `X-User-Id`를 사용한다. 사용자 인증, 사용자 즉시 삭제, 관리자 수정, MCP의 비게임 기능, 다중 worker는 제외한다.

## 2. 소유권과 연결

| 영역 | 소유 컴포넌트 | 직접 의존 | 금지 |
|---|---|---|---|
| 화면·UX | `frontend_user`, `frontend_admin` | Backend REST/SSE | DB/Redis/LLM/MCP 직접 연결 |
| 규칙·상태·영속 | Backend | PostgreSQL, Redis, LLM, MCP client | Frontend가 규칙 판정 |
| 게임 context·proposal | `mcp_server/mcp_1` | Backend context port | 최종 상태 변경·비게임 Tool |
| 역할·phase·판정 | Backend rule engine | 고정 ruleset | LLM에 판정 위임 |

연결 계약은 [Backend API](AI_MAFIA_BACKEND_API_CONTRACT.md)와 [MCP API](AI_MAFIA_MCP_API_CONTRACT.md)가 소유한다. 전체 저장 필드는 [DB 설계](AI_MAFIA_DATA_REDIS_DESIGN.md), 화면 상태는 [Frontend 설계](AI_MAFIA_FRONTEND_SPEC.md), 전이는 [게임 규칙](AI_MAFIA_GAME_RULES.md)에서만 정의한다.

## 3. 병렬 개발 단위

### Track A — Backend

1. 공통 오류·UUID·idempotency·version middleware와 OpenAPI schema를 만든다.
2. ruleset engine과 in-memory contract test를 만든다.
3. migration·repository·transaction·snapshot·operation을 연결한다.
4. 사용자 REST/SSE와 관리자 조회 API를 구현한다.
5. Agent Manager, LLM provider adapter, MCP client와 fallback을 연결한다.

완료 기준은 API 문서의 모든 endpoint/schema/error와 정상·409·중복·장애 fixture 통과다.

### Track B — Frontend

Backend mock server를 기준으로 `HOME`, `CREATE_GAME`, `GAME`, `SAVED_GAMES`, `RESULT`, 관리자 3개 화면을 구현한다. 화면은 `status`, `phase`, `allowed_commands`를 읽고 SSE 실패 시 polling으로 전환한다. 완료 기준은 화면 문서의 모든 상태(loading, empty, submitting, reconnecting, error, forbidden)와 새로고침 복구 테스트다.

### Track C — 게임 MCP

`mcp_server/mcp_1`에서 Streamable HTTP initialize, session HMAC, capability, 5개 Resource와 5개 game Tool을 구현한다. Backend가 제공하는 두 port만 사용하며 proposal receipt만 반환한다. 완료 기준은 MCP inspector와 잘못된 HMAC·scope·capability·version·중복·private data 차단 fixture다.

## 4. 통합 순서

1. 계약 freeze: enum, JSON schema, 오류, version, ID, 시간대를 fixture로 고정한다.
2. Backend rule engine + Frontend mock을 병렬 실행해 화면 계약을 먼저 검증한다.
3. PostgreSQL migration과 transaction/replay를 붙이고 REST contract test를 통과시킨다.
4. SSE·operation polling을 붙인 뒤 저장·재개·탈락 관전을 검증한다.
5. MCP를 HMAC session으로 연결하고 Agent proposal을 Backend command로 변환한다.
6. fake LLM과 deterministic seed로 5/6/7/9명 전 게임을 실행한다.
7. 보안·장애·성능·보존 점검 후 문서와 OpenAPI diff를 확인한다.

## 5. 공통 합의값

API prefix `/api/v1`, ruleset `basic-v1`, UUID, UTC, SSE 30초 heartbeat·45초 reconnect,
명령 202 + operation polling, `PAUSED` 30일·`FINISHED` 90일·audit 180일, 게임당 token
60,000, 호출 출력 400 token, LLM timeout 30초를 사용한다. PostgreSQL이 원본이고 Redis
장애 시 DB polling으로 강등한다. MCP secret은 Frontend에 전달하지 않는다.

## 6. 완료 게이트

각 Track은 독립 mock/fixture로 개발하고, 통합 시 다음을 모두 통과해야 한다: `uv run pytest`, `uv run python -m compileall -q backend frontend_user frontend_admin mcp_server`, `uv run ruff check .`, OpenAPI·MCP schema diff 0, private role/메모/prompt 누출 0, version/idempotency 재전송 테스트 통과, snapshot replay와 재기동 복구 통과. 실제 유료 LLM·외부 OAuth는 회귀 테스트에서 호출하지 않는다.
