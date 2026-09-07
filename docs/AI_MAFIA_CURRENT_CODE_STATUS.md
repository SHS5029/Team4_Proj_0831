# AI 마피아 현재 코드 상태

**기준일:** 2026-09-07  
**기준 브랜치:** `ik-2`  
**상태:** 작업 트리에 미커밋 변경이 존재함

이 문서는 여러 임시 계획 문서를 대신해 현재 저장소에 실제로 존재하는 구현,
실행 경로, 검증 결과와 남은 제약을 기록한다. 제품 규칙과 공개 API의 규범적
계약은 `docs/개발상세플랜/` 아래의 정본 문서를 따른다.

## 1. 현재 구현 요약

- 로그인·OAuth 없이 브라우저가 생성한 UUID v4를 사용자 식별자로 사용한다.
- Frontend는 Streamlit 사용자 앱과 관리자 앱으로 분리되어 있다.
- Backend는 FastAPI 공개 API, 게임 규칙 판정, PostgreSQL 영속화와 AI 진행 worker를 소유한다.
- 게임 상태 변경은 PostgreSQL transaction과 `expected_state_version`으로 보호된다.
- 게임 이벤트는 `game_events`에 기록하고 Frontend 동기화용 operation envelope로 변환한다.
- MCP 서버는 FastMCP Resource·Prompt·Tool을 등록하고 Backend 내부 API를 호출한다.
- LLM provider는 `dummy`, `local`, `openai`, `gemini` 중 하나를 선택하며 테스트는
  fake 또는 mock transport를 사용한다.

## 2. 게임 실행 흐름

```text
게임 생성 -> ROLE_REVEAL -> BEGIN_GAME -> DAY_DISCUSSION -> NIGHT_ACTION
-> DAY_DISCUSSION -> DAY_VOTE -> REVOTE(동률) -> NIGHT_ACTION 반복
-> FINAL_DISCUSSION / FINAL_ACCUSATION -> COMPLETED 또는 FAILED
```

- 게임 생성은 `POST /api/v1/games`에서 6~9명과 `mystery-v1`·`scenario-v1`을 검증한다.
- 생성 직후 역할 공개 snapshot을 반환하고 `BEGIN_GAME`이 첫날 토론을 연다.
- 낮 토론은 좌석 순서에 따른 `SPEAK` 또는 `PASS`다.
- 밤에는 마피아·탐정·의사만 `SUBMIT_NIGHT_ACTION`을 제출하고 시민은 Backend가 자동 처리한다.
- 투표·재투표·최종 지목은 `SUBMIT_VOTE`로 처리한다.
- Backend가 phase 전이, deadline, 대상, 생존 상태, 승패를 최종 판정한다.
- 인간 플레이어가 사망하면 Frontend는 관전 모드로 전환한다.
- `SAVE_AND_EXIT`과 `RESUME`은 action window와 남은 시간을 PostgreSQL에 보존·복원한다.

## 3. Backend 구조

- `backend/app/game_engine/`: 순수 규칙, phase 전이, 투표·밤 행동·승패와 deterministic fallback
- `backend/app/services/game/creation_service.py`: 게임·시나리오·플레이어 생성
- `backend/app/services/game/lifecycle_service.py`: BEGIN, SAVE, RESUME transaction
- `backend/app/services/game/discussion_command.py`: 인간·AI 토론 command
- `backend/app/services/game/action_command.py`: 밤 행동·투표·빠른 진행 command
- `backend/app/services/game/game_read_service.py`: 목록·snapshot·공개 projection
- `backend/app/services/game/event_sync_service.py`: game event와 sync envelope 변환
- `backend/app/services/game/postgres_runtime.py`: service와 repository 조합 facade
- `backend/app/services/game/ai_progress_worker.py`: 열린 AI window 비동기 진행
- `backend/app/repositories/`: game, player, action, event, receipt, feedback 저장소
- `backend/app/routers/game_router.py`: 공개 게임·sync·SSE·feedback API
- `backend/app/routers/mcp_registry_router.py`: 최소 MCP 내부 연결 API

운영 runtime은 `app.state.game_runtime`에 주입된다. 기존 scaffold와 legacy migration
구조는 호환을 위해 일부 남아 있지만 canonical 게임 실행은 PostgreSQL 경로를 사용한다.

## 4. Frontend 구조

- `frontend_user/app.py`: UUID 초기화와 화면 dispatcher
- `frontend_user/app_pages/game_create_page.py`: 6~9명 게임 생성
- `frontend_user/app_pages/role_reveal_page.py`: 본인 역할·단서 표시와 BEGIN
- `frontend_user/app_pages/game_page.py`: 진행 중 게임·관전 shell
- `frontend_user/components/action_panel.py`: 토론·밤 행동·투표 입력
- `frontend_user/core/api_client.py`: UUID header 기반 Backend client
- `frontend_user/core/commands.py`: Front UX guard와 command body 구성
- `frontend_user/core/sync.py`: SSE·polling operation 검증·원자 적용
- `frontend_user/components/browser_components/sync/`: fetch streaming SSE
- `frontend_user/app_pages/result_page.py`: Backend 확정 결과 표시
- `frontend_user/app_pages/feedback_page.py`: 일반·게임별 feedback 제출

Front는 규칙·승패·자동 선택을 계산하지 않는다. snapshot의 `legal_actions`,
`action_window`, `valid_targets`를 표시하고 command 결과 후 Backend snapshot을 다시 읽는다.

## 5. 공개 API와 동기화

공개 API prefix는 `/api/v1`이다.

| 기능 | 경로 |
|---|---|
| 게임 생성 | `POST /api/v1/games` |
| 게임 목록 | `GET /api/v1/games` |
| snapshot | `GET /api/v1/games/{game_id}` |
| command | `POST /api/v1/games/{game_id}/commands` |
| polling sync | `GET /api/v1/games/{game_id}/sync` |
| SSE sync | `GET /api/v1/games/{game_id}/events` |
| feedback | `POST /api/v1/feedback` |

변경 요청에는 UUID v4 `Idempotency-Key`, 게임 command에는 `expected_state_version`이 필요하다.
사용자 식별은 `X-User-Id`, 요청 추적은 `X-Request-Id`를 사용한다.

Polling과 SSE는 같은 `game_sync` envelope를 사용한다. sequence/version 불일치 시 전체
snapshot을 반환하고, Front는 부분 operation을 적용하지 않은 채 authoritative snapshot을
재조회한다. 활성 timed window의 `remaining_ms`는 Backend deadline에서 계산한다.

SSE browser fetch를 위해 Backend는 `CORS_ALLOWED_ORIGINS`에 등록된 Front origin의
preflight와 `X-User-Id`, `X-Request-Id`, `Last-Event-ID` header를 허용한다. 기본값은
`localhost`와 `127.0.0.1`의 사용자·관리자 Front port다.

## 6. 저장소와 설정

- PostgreSQL migration은 `backend/migrations/001~004` 순서로 적용한다.
- canonical game schema는 games, game_players, action_windows, action_submissions,
  game_events, receipts와 scenario/fact 데이터를 사용한다.
- seed와 snapshot 암호화 keyring은 저장소 외부 설정을 사용한다.
- Redis client·lock·stream 코드는 Backend에 있으나 canonical 이벤트 원본은 PostgreSQL이다.
- Backend는 `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, `MCP_SERVER_URL`,
  `CORS_ALLOWED_ORIGINS`와 선택한 LLM 설정을 사용한다.
- MCP process는 `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT`를 사용한다.

실제 비밀번호, API key, token, 사용자 데이터는 문서·로그·fixture에 기록하지 않는다.

## 7. 검증 상태

확인된 명령과 결과:

```text
py -3.12 -m pytest frontend_user/tests backend/tests/test_config.py \
  backend/tests/test_b5_game_api.py backend/tests/test_postgres_game_flow.py -q
55 passed, 1 warning

py -3.12 -m compileall -q backend/app frontend_user
git diff --check
```

전체 Backend·Frontend 테스트 실행에서는 **161 passed, 12 failed**였다. 실패한 12개는
이번 게임 연결 변경과 무관한 async 테스트이며 현재 환경에 `pytest-asyncio`가 없어
`pytest.mark.asyncio`를 실행하지 못한 결과다. Starlette/httpx deprecation warning도
1건 확인되었다.

## 8. 현재 제약과 다음 통합 확인

- UUID는 인증 수단이 아니므로 개인 개발 환경 또는 사설망 전용이다.
- 실제 browser에서 `localhost:8501` 또는 `127.0.0.1:8501`로 접속해 SSE preflight,
  reconnect와 polling fallback을 확인해야 한다.
- 실제 PostgreSQL·Redis·FastMCP를 함께 기동한 상태에서 생성→BEGIN→토론→밤→투표→
  저장·재개→관전→종료→feedback 전체 E2E가 최종 통합 gate다.
- async 회귀 테스트 실행을 위해 해당 환경에 `pytest-asyncio`를 설치해야 한다.
- 작업 트리에는 본 문서 작성 시점 이전부터 존재한 대규모 미커밋 변경이 있으므로,
  커밋·push 전 변경 소유권과 diff를 별도로 확인해야 한다.
