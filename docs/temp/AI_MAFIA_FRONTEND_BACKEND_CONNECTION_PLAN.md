# AI 마피아 Frontend–Backend API 연결 구현 단위 계획서

**문서 상태:** Integration MVP의 소단위 실행 계획
**작성일:** 2026-09-04
**선행 문서:** [Integration MVP 계획](AI_MAFIA_INTEGRATION_MVP_PLAN.md),
[API 정본](../개발상세플랜/AI_MAFIA_API_SPEC.md), [AGENTS.MD](../../AGENTS.MD)
**이번 단위:** Frontend와 Backend 공개 HTTP API 연결만

이 계획은 DB·Redis·MCP·LLM·Game Engine 구현 계획이 아니다. 한 coding AI 세션에서
이 문서의 `WU-FB-01` 하나만 수행한다. 공개 API 계약이나 파일 구조를 바꾸어야 하면
구현 전에 관련 정본과 섹터 간 합의를 갱신한다.

## 1. 목적

로그인 없이 Frontend가 UUID를 준비하고 Backend 공개 API를 실제 HTTP로 호출하며,
정상 응답·오류 응답·재시도·멱등키·상태 갱신을 올바르게 처리하는지 확인한다.

이번 단위에서 “연결 완료”는 게임 규칙이 맞다는 뜻이 아니다. Backend가 반환한 응답을
Frontend가 계약에 맞게 해석하고 화면 상태로 반영하는 것이 완료 기준이다.

```text
Frontend Streamlit
  → X-User-Id(UUID v4), X-Request-Id, Idempotency-Key
  → Backend 공개 HTTP API
  → JSON envelope / error envelope
  → Frontend state와 화면
```

## 2. 범위

### 포함

- 로그인 화면을 거치지 않는 UUID-only 초기화
- Frontend API client의 Backend URL 검증과 HTTP 호출
- 현재 Frontend가 사용하는 공개 API의 실제 왕복
- 공통 header와 JSON 응답 envelope 검증
- 4xx, 409, 503, 잘못된 JSON, timeout 처리
- 쓰기 요청의 UUID v4 `Idempotency-Key` 전달
- Backend 응답의 `game_id`, `snapshot_url`, `sync_url`, `feedback_id` 해석
- 기존 화면의 로딩·성공·실패 상태 표시

### 제외

- Google OIDC, OAuth 계정 생성과 사용자 인증
- Game Engine 규칙, 역할, phase, 승패 검증
- PostgreSQL·Redis·MCP·LLM 연결 구현
- Agent job, MCP proposal, 실제 LLM 호출
- 새 DB migration, 새 Repository, 새 Service
- SSE 서버 구현 변경
- 화면 디자인 개편과 게임 기능 추가

## 3. 고정할 API 표면

이번 단위에서 Frontend가 실제로 호출하고 Backend가 응답해야 하는 공개 API는 다음과
같다. 게임 semantics는 검증하지 않고 HTTP 계약과 응답 연결만 검증한다.

| 기능 | Method | Path | 필수 header | Frontend 호출부 |
|---|---|---|---|---|
| 프로세스 확인 | GET | `/health` | 없음 | 연결 전 점검 |
| 의존성 준비 확인 | GET | `/ready` | 없음 | 연결 전 점검 |
| 게임 목록 | GET | `/api/v1/games` | `X-User-Id` | `ApiClient.get_games` |
| 게임 생성 | POST | `/api/v1/games` | `X-User-Id`, `X-Request-Id`, `Idempotency-Key` | `ApiClient.create_game` |
| 게임 snapshot | GET | `/api/v1/games/{game_id}` | `X-User-Id` | `ApiClient.get_game` |
| command 접수 | POST | `/api/v1/games/{game_id}/commands` | `X-User-Id`, `X-Request-Id`, `Idempotency-Key` | `ApiClient.submit_command` |
| polling sync | GET | `/api/v1/games/{game_id}/sync` | `X-User-Id` | `ApiClient.get_sync` |
| SSE event | GET | `/api/v1/games/{game_id}/events` | `X-User-Id`, `Last-Event-ID` | `sync_bridge.py` |
| feedback | POST | `/api/v1/feedback` | `X-User-Id`, `X-Request-Id`, `Idempotency-Key` | `ApiClient.submit_feedback` |

`/api/v1/games/{game_id}/proposal`, `/api/v1/games/{game_id}/operations/{operation_id}`와
`/api/v1/mcp/health`는 이번 Frontend 공개 API 연결 단위의 필수 표면이 아니다. 해당
경로는 MCP 또는 legacy smoke 검증 단위에서 다룬다.

## 4. 기존 디렉터리와 파일 사용 범위

디렉터리를 생성·삭제·이동·이름 변경하지 않는다. 기존 파일의 필요한 부분만 수정한다.

### Frontend 대상

```text
frontend_user/
├─ app.py                         # 로그인 우회와 UUID 초기화 진입점
├─ core/api_client.py             # 공개 API HTTP 호출·응답/오류 변환
├─ core/session.py                # UUID 보관·복구
├─ core/commands.py               # command body 생성
├─ core/sync.py                   # sync envelope 적용
├─ components/sync_bridge.py      # SSE 연결 실패 시 polling 전환
└─ app_pages/game_scaffold_page.py # 필요 시 연결 smoke 표시
```

`frontend_user/auth/*`, `login_page.py`, 기존 게임 화면은 이번 단위에서 삭제·이동하지
않는다. 로그인 없는 진입은 `app.py`에서만 처리하고, 인증 관련 파일은 후속 정리 단위로
남긴다.

### Backend 대상

```text
backend/app/
├─ main.py
├─ routers/health_router.py
├─ routers/scaffold_game_router.py
├─ services/game_service.py         # 기존 API adapter 동작 확인만
├─ services/scaffold_game_service.py # legacy compatibility 유지
└─ schemas/
   ├─ game_schema.py
   ├─ command_schema.py
   ├─ sync_schema.py
   └─ feedback_schema.py
```

Backend에서는 Engine 규칙, DB schema, Redis 동작을 수정하지 않는다. 기존 InMemory
canonical repository 또는 테스트 dependency injection을 사용해 API transport를
검증하고, 실제 저장소 연결은 별도 WU에서 수행한다.

## 5. 구현 순서 — WU-FB-01

### 5.1 사전 확인

1. 현재 브랜치와 변경 파일을 확인한다.
2. Backend의 `/openapi.json`과 위 API 표면을 대조한다.
3. Frontend `ApiClient`의 각 method가 위 path와 header를 사용하는지 확인한다.
4. 누락된 계약은 임의로 정하지 말고 `AI_MAFIA_API_SPEC.md`와 대조한다.

### 5.2 UUID-only 진입

1. `frontend_user/app.py`가 로그인 화면을 기본 진입점으로 사용하지 않게 한다.
2. `core/session.py`에서 UUID v4를 한 번 생성하고 Streamlit session state에 보관한다.
3. UUID가 손상되거나 누락되면 새 UUID를 생성한다.
4. `ApiClient` 생성 시 반드시 검증된 UUID를 주입한다.
5. `X-User-Id` 외의 OAuth token, Front HMAC, DB credential을 전송하지 않는다.

완료 조건: 로그인 없이 앱이 시작되고 Backend `/health` 요청에 UUID 자격증명이
섞이지 않는다.

### 5.3 API client 계약 확인

1. `ApiClient`의 HTTP method와 path를 API 표면과 일치시킨다.
2. 모든 요청에 `X-Request-Id`를 생성한다.
3. POST 요청에는 UUID v4 `Idempotency-Key`를 전달한다.
4. Backend JSON 성공 envelope에서 `data`를 안전하게 추출한다.
5. 오류 envelope에서는 내부 exception text 대신 status, code, request id만 사용한다.
6. URL은 기존 HTTPS/loopback 검증을 유지하고 임의 host·path를 허용하지 않는다.

완료 조건: 정상 응답, 고정 오류 응답, 비JSON 응답, timeout을 동일한 Client 계약으로
구분한다.

### 5.4 화면 연결

1. 기존 `home_page.py`에서 게임 목록 응답을 화면 모델로 변환한다.
2. 기존 생성 화면에서 `create_game` 응답의 `game_id`와 `snapshot_url`을 보관한다.
3. 기존 게임 화면에서 `get_game` 응답을 재조회한다.
4. command 제출 후 `sync_url` 또는 기존 sync method로 상태를 갱신한다.
5. SSE가 실패하면 기존 polling fallback을 사용한다.
6. Backend 오류 시 사용자에게 고정된 안내만 표시하고 raw response body를 노출하지 않는다.

완료 조건: 목록 → 생성 → snapshot 조회 → command 요청 → sync 조회의 Frontend 상태
전이가 HTTP 응답에 따라 동작한다. 규칙의 정합성은 판정하지 않는다.

### 5.5 Backend transport 확인

1. Backend router가 `X-User-Id`를 UUID v4로 검증하는지 확인한다.
2. 공개 API의 status code와 response envelope가 정본과 일치하는지 확인한다.
3. Frontend가 보내지 않은 Authorization/OIDC header를 요구하지 않는지 확인한다.
4. 테스트에서는 InMemory repository를 주입해 외부 DB 없이 HTTP 왕복을 재현한다.
5. Engine·PostgreSQL·Redis·MCP·LLM 호출이 이 WU에 새로 들어가지 않았는지 확인한다.

완료 조건: Frontend client가 실제 Backend HTTP endpoint를 호출하고, Backend는 정해진
응답 또는 고정 오류를 반환한다.

## 6. 테스트 계획

### Frontend 단위 테스트

- UUID 생성·손상 UUID 재생성
- `X-User-Id`, `X-Request-Id`, `Idempotency-Key` 확인
- URL 검증 실패
- status별 오류 변환
- 성공 envelope과 `data` 누락 거부
- timeout·비JSON 응답 처리

### Backend 계약 테스트

- `/health`, `/ready`
- 게임 목록·생성·조회
- command·sync·events·feedback의 header와 status
- 잘못된 UUID와 누락 header 거부
- 동일 Idempotency-Key 재요청 처리
- InMemory repository 주입 시 외부 DB 없이 재현

### 실제 HTTP smoke

Backend를 로컬 process로 실행하고 Frontend API client가 loopback HTTP를 호출한다.
최소 시나리오는 다음과 같다.

```text
GET /health
→ GET /ready
→ GET /api/v1/games
→ POST /api/v1/games
→ GET /api/v1/games/{game_id}
→ POST /api/v1/games/{game_id}/commands
→ GET /api/v1/games/{game_id}/sync
→ POST /api/v1/feedback
```

이번 smoke의 성공은 HTTP 연결과 계약 확인을 뜻하며, Engine이 실제 규칙을 계산했다는
뜻이 아니다. Engine이 필요한 endpoint는 현재 임시/기존 adapter의 응답 범위까지만
확인하고 규칙 검증은 후속 Engine WU로 넘긴다.

## 7. 완료 증거

다음 표를 완료 보고에 채운다.

| 항목 | 성공 기준 |
|---|---|
| UUID-only 진입 | 로그인 없이 Frontend 시작 |
| API client | 위 표의 path·method·header 일치 |
| 정상 HTTP | 각 연결 API의 예상 2xx 응답 |
| 오류 HTTP | 4xx/409/503을 고정 code로 표시 |
| 화면 반영 | 목록·생성·조회·sync 상태 반영 |
| 보안 | OAuth token·secret·raw body 미노출 |
| 범위 | Engine·DB·Redis·MCP·LLM 코드 변경 없음 |
| 회귀 | Frontend focused test와 Backend focused test 통과 |

## 8. 금지 사항과 다음 단계

- 이 WU에서 `game_service.py`를 리팩터링하지 않는다.
- 새 Router, Service, Repository, migration을 추가하지 않는다.
- 로그인 파일을 즉시 삭제하지 않는다.
- 실제 DB·Redis·MCP·LLM 연결 문제를 이 WU에서 해결하려고 확장하지 않는다.
- Game Engine의 판정 결과를 Frontend에서 재계산하지 않는다.

이 단위가 완료된 뒤 별도 순서로 PostgreSQL·Redis·MCP·LLM 연결을 진행하고, 그 후
Game Engine을 구현한다. 각 후속 작업도 한 coding AI 세션에 WU 하나만 배정한다.
