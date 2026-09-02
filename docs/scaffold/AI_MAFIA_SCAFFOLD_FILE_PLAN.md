# AI 마피아 연결 뼈대 파일별 구현 계획

이 문서는 [연결 뼈대 계획](AI_MAFIA_SCAFFOLD_PLAN.md)의 단계별 작업을 실제 파일 단위로 고정한다. 기존 파일을 이동·삭제하지 않고 필요한 모듈만 추가한다.

## 1. Backend

| 파일 | 책임 | 의존 |
|---|---|---|
| `backend/app/routers/scaffold_game_router.py` | 게임 smoke HTTP 진입점 | service, schema |
| `backend/app/routers/scaffold_mcp_router.py` | MCP health 진입점 | mcp client |
| `backend/app/schemas/scaffold_schema.py` | smoke 요청·응답 Pydantic 모델 | 없음 |
| `backend/app/models/scaffold_game.py` | Game·Operation 내부 모델 | 없음 |
| `backend/app/repositories/scaffold_repository.py` | in-memory 저장소와 PostgreSQL port | model |
| `backend/app/services/scaffold_game_service.py` | 소유권·version·idempotency·operation 조정 | repository, mcp client |
| `backend/app/mcp/game_client.py` | MCP initialize, tools/list, tools/call, resources/read | `mcp` SDK |
| `backend/app/mcp/game_registry.py` | game MCP server allowlist와 tool metadata | game client |
| `backend/migrations/002_create_scaffold_game_schema.sql` | 뼈대 최소 테이블 | PostgreSQL |
| `backend/tests/test_scaffold_game_api.py` | REST 정상·실패·중복·version | TestClient, fake repository |
| `backend/tests/test_scaffold_mcp.py` | MCP client fake transport | fake MCP |

`backend/app/main.py`에는 기존 health·identity router를 유지한 채 scaffold router만 추가한다. 기존 `backend/app/mcp/client.py`가 게임 기능에 재사용 가능하면 확장하고, 현재 identity 코드의 import와 섞지 않는다.

## 2. MCP Server

| 파일 | 책임 |
|---|---|
| `mcp_server/mcp_1/server.py` | `FastMCP` 생성과 game handler 등록 |
| `mcp_server/mcp_1/__main__.py` | `python -m mcp_server.mcp_1` 실행 진입점 |
| `mcp_server/mcp_1/config.py` | host·port·internal secret 환경 설정 |
| `mcp_server/mcp_1/schemas/scaffold_schema.py` | Tool 입력·출력 모델 |
| `mcp_server/mcp_1/api/tools/scaffold_tools.py` | `game_ping`, `game_get_context`, `game_submit_proposal` 등록 |
| `mcp_server/mcp_1/api/resources/scaffold_resources.py` | dummy context Resource 등록 |
| `mcp_server/mcp_1/services/scaffold_service.py` | session scope·proposal 검증 |
| `mcp_server/mcp_1/ports/backend_context.py` | Backend context/proposal 추상 port |
| `mcp_server/mcp_1/tests/test_scaffold_server.py` | initialize/list/read/call 검증 |

MCP Server는 PostgreSQL·Redis·LLM을 직접 import하지 않는다. 뼈대에서는 `InMemoryContextPort`만 사용하고 후속 단계에서 Backend 내부 HTTP port adapter로 교체한다.

## 3. Frontend

| 파일 | 책임 |
|---|---|
| `frontend_user/core/game_api_client.py` | Backend game API 호출과 오류 정규화 |
| `frontend_user/app_pages/game_scaffold_page.py` | 생성·조회·PING·operation 표시 |
| `frontend_admin/app_pages/scaffold_status_page.py` | Backend/MCP health 표시 |
| `frontend_user/tests/test_game_api_client.py` | mock HTTP 계약 테스트 |

기존 login page와 OIDC flow는 수정하지 않는다. 사용자 UUID는 개발용 설정 또는 세션에서 읽고 Frontend가 임의로 role·phase를 계산하지 않는다.

## 4. 구현 순서

1. MCP schema·fake context
2. MCP server tools/resources
3. Backend MCP client·health router
4. Backend in-memory game API
5. PostgreSQL repository와 migration
6. Redis lock/status adapter
7. Frontend smoke 화면
8. 통합 테스트와 README 실행 안내
