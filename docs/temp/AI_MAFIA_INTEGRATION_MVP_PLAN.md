# AI 마피아 Integration MVP 구현 계획서

**문서 상태:** 범위 축소를 위한 임시 계획 초안  
**작성일:** 2026-09-04  
**목적:** 과도하게 확장된 구현을 정리하고, 메인 게임 로직에 들어가기 전에 시스템 연결 뼈대를 안정화  
**이번 단계:** 로그인·Game Engine·실제 Agent를 제외하고 모든 필수 시스템 연결의 실제 왕복 확인

이 문서는 기존 제품 정본을 대체하지 않는다. 공개 API, DB schema, MCP 계약을 변경해야
하는 경우에는 구현 전에 관련 정본과 섹터 간 합의를 갱신한다. 한 coding AI 세션은
이 계획의 WU 하나만 수행한다.

## 1. 성공 기준

이번 단계의 성공 기준은 게임을 플레이하는 것이 아니라, 공통지침에 정의된 필수
시스템 연결이 실제 process 간 왕복으로 작동하는 것을 증명하는 것이다.

```text
Frontend
  ⇄ Backend의 Integration MVP API 전체
       ├─ PostgreSQL 실제 연결·조회
       ├─ Redis 실제 PING·lock/cache
       ├─ MCP 실제 initialize/bootstrap/Engine HTTP 왕복
       └─ 실제 설정 Provider 또는 Dummy LLM 응답
  ⇄ Frontend에 연결 결과 표시
```

여기서 “Frontend–Backend API 전체”는 이 계획에서 정의한 health, ready,
integration-check와 연결 확인에 필요한 기존 API를 뜻한다. Game Engine이 필요한
게임 생성·command·sync API 전체를 포함한다는 뜻이 아니다. Game Engine은 호출하지
않으며, 게임 응답이 필요한 기존 scaffold 경로는 호환용으로만 유지한다.

최종 완료는 fake test만으로 판정하지 않는다. PostgreSQL, Redis, MCP process와
loopback HTTP, 그리고 명시적으로 선택한 LLM Provider의 실제 왕복 증거가 필요하다.
자동 회귀 테스트는 비용과 재현성을 위해 Dummy/fake를 사용한다.

## 2. 범위 제한

### 포함

- Google OIDC와 Streamlit 로그인 진입점 제거를 위한 대체 경로 검증
- Frontend가 생성한 UUID v4와 `X-User-Id` 전달
- 기존 Backend `/health`, `/ready`와 Integration MVP API 전체 확인
- 기존 PostgreSQL 실제 연결 및 기존 schema 접근 확인
- 기존 Redis 실제 PING·lock/cache 연결 확인
- 기존 MCP `/mcp` 실제 initialize와 bootstrap/Engine HTTP 왕복 확인
- 선택한 LLM Provider의 실제 structured response 연결 확인
- 기존 Frontend 화면에서 모든 연결 결과 표시

### 제외

- Game Engine과 실제 게임 규칙
- 역할·발언·밤 행동·투표·승패
- Agent job reservation과 실제 Agent decision loop
- MCP Resource 5개와 게임 Tool 4개
- Agent decision loop와 게임 판단을 위한 LLM 호출
- 새 PostgreSQL migration과 새 게임 테이블
- Redis Stream, event outbox worker, fan-out 재처리
- SSE 완성, 관리자 기능, scenario/persona 기능
- 사용자 계정, OAuth, 계정 병합

## 3. 디렉터리 변경 원칙

이번 단계에서는 디렉터리를 생성·삭제·이동·이름 변경하지 않는다. 현재 디렉터리와
기존 파일을 우선 사용하며, 새 파일이 불가피해도 기존 package 디렉터리 안의 최소
파일 하나 이하로 제한하고 구현 전에 영향 범위를 고지한다.

이번 단계의 목표 구조는 새로운 최종 구조가 아니라 현재 구조 안에서 사용하는 최소
실행 경로다.

```text
backend/app/
├─ main.py                              # 기존 composition root
├─ core/
│  ├─ config.py                         # 기존 환경 설정
│  ├─ errors.py                         # 기존 오류
│  └─ responses.py                      # 기존 응답 envelope
├─ routers/
│  ├─ health_router.py                  # 기존 health/ready
│  ├─ scaffold_game_router.py           # 기존 호환 API, 확장 금지
│  └─ scaffold_mcp_router.py            # 기존 내부 MCP 연결 경계
├─ services/
│  ├─ internal_engine_service.py        # 기존 내부 요청 처리
│  └─ scaffold_game_service.py          # legacy 호환용, 확장 금지
├─ infrastructure/
│  ├─ postgres.py                        # 기존 PostgreSQL 연결
│  ├─ migrations.py                     # 기존 migration 상태 확인
│  └─ redis/
│     ├─ lock.py                        # 기존 game lock
│     ├─ cache.py                       # 기존 공개 cache
│     └─ streams.py                     # 이번 단계에서는 호출하지 않음
├─ mcp/
│  ├─ client.py                         # fake transport 우선
│  └─ game_client.py                    # 기존 placeholder, 실제 MCP 교체 전 보존
└─ llm_provider/
   ├─ base.py                           # 기존 Provider 계약
   ├─ dummy.py                          # 이번 단계 기본 구현
   └─ factory.py                        # Dummy 선택

frontend_user/
├─ core/
│  ├─ api_client.py                     # 기존 Backend client
│  ├─ session.py                        # 기존 UUID session 상태
│  └─ sync.py                           # 후속 게임 단계용, 이번 단계에서는 확장 금지
└─ app_pages/
   ├─ home_page.py                      # 기존 진입 화면
   ├─ game_scaffold_page.py             # 임시 연결 확인 화면으로 사용
   └─ login_page.py                     # 제거 전까지 접근 차단, 즉시 삭제하지 않음

mcp_server/mafia_game/
├─ main.py                              # 기존 MCP composition root
├─ api/bootstrap_auth.py                # 기존 bootstrap 인증
├─ services/bootstrap.py                # 기존 bootstrap/consume
├─ integrations/engine_http.py         # 기존 MCP→Backend adapter
└─ domain/session.py                    # 기존 session registry
```

참고 프로젝트의 작은 Workflow 수준을 넘지 않도록 새 계층을 만들지 않고 기존 adapter와
composition root를 재사용한다. 위 구조는 구현 목표를 표현한 것이며 계획서 작성만으로
파일을 이동하거나 생성하지 않는다.

## 4. 임시로 보존하는 파일

다음 파일은 이번 단계에서 즉시 삭제하거나 이동하지 않는다. 새 연결 경로에서 필요한
부분만 사용하고, 나머지는 legacy/deferred 상태로 둔다.

| 파일/영역 | 이번 단계 처리 | 후속 정리 시점 |
|---|---|---|
| `backend/app/routers/identity_router.py` | 새 경로에서 미사용, 삭제하지 않음 | 익명 UUID 전환과 회귀 검증 후 |
| `backend/app/services/identity_service.py` | 새 경로에서 미사용 | OIDC 제거 완료 후 |
| `backend/app/models/identity.py` | 수정하지 않음 | OAuth schema 정리 합의 후 |
| `frontend_user/app_pages/login_page.py` | 진입 차단 또는 미사용 처리 | Frontend 익명 UUID 검증 후 |
| `frontend_user/auth/*` | 새 경로에서 미사용 | 로그인 제거 후 별도 정리 WU |
| `backend/app/routers/scaffold_game_router.py` | 기존 호환 경로 보존, 기능 확장 금지 | canonical 게임 전환 완료 후 |
| `backend/app/services/scaffold_game_service.py` | 기존 호환 경로 보존, 기능 확장 금지 | scaffold API 종료 후 |
| `backend/app/infrastructure/redis/scaffold.py` | legacy 경로 보존 | legacy API 종료 후 |
| `backend/app/mcp/game_client.py` | placeholder 보존 | 실제 MCP Resource/Tool 통합 시 교체 |
| `backend/app/agent/*` | 이번 단계에서는 호출하지 않음 | Game Engine/Agent 별도 WU |
| `backend/app/llm_provider/openai_provider.py` | 실제 호출하지 않음 | Dummy 연결 검증 후 opt-in |
| `backend/migrations/001~004` | 수정하지 않음 | migration 정리 합의 후 |
| `mcp_server/mafia_game/api/resources/*` | 빈 package 보존 | Resource 구현 WU |
| `mcp_server/mafia_game/api/tools/*` | 기존 package 보존 | 게임 Tool 구현 WU |

## 5. 구현 순서

각 WU는 별도 coding 세션에서 하나씩 수행한다. 선행 WU의 focused test와 완료 증거가
없으면 다음 WU로 진행하지 않는다.

### WU-IMVP-01 — 익명 UUID 경로 확인

대상:

- `frontend_user/core/session.py`
- `frontend_user/core/api_client.py`
- `frontend_user/app_pages/login_page.py`
- 기존 identity 관련 테스트의 전환 계획

작업:

- Frontend가 UUID v4를 생성하고 session state에 보관
- `X-User-Id`만 Backend에 전달
- 로그인 화면 진입 차단
- OIDC secret과 실제 계정 정보가 새 경로에 들어가지 않는지 확인

완료 기준: 로그인 없이 Frontend가 Backend health 또는 기존 호환 API를 호출한다.

### WU-IMVP-02 — Backend·PostgreSQL 연결 안정화

대상:

- `backend/app/routers/health_router.py`
- `backend/app/infrastructure/postgres.py`
- `backend/app/infrastructure/migrations.py`

작업:

- `/health`와 `/ready` 응답 확인
- PostgreSQL `SELECT 1` 연결 확인
- 기존 migration 목록과 적용 상태 확인
- 새 migration, 새 table, 새 repository는 추가하지 않음

완료 기준: 실제 PostgreSQL에 연결해 기존 schema 접근을 확인하고, 연결 실패를
안전한 상태값으로 구분한다.

### WU-IMVP-03 — Redis 최소 연결

대상:

- `backend/app/infrastructure/redis/lock.py`
- `backend/app/infrastructure/redis/cache.py`
- `backend/app/routers/health_router.py`

작업:

- Redis PING 확인
- 기존 key 규칙을 사용한 lock 또는 cache 한 건 확인
- Redis 장애 시 Backend가 준비 상태가 아니라고 응답
- Stream과 outbox는 호출하지 않음

완료 기준: 실제 Redis PING과 기존 lock 또는 cache 왕복, 장애 경로가 검증된다.

### WU-IMVP-04 — MCP bootstrap 연결

대상:

- `mcp_server/mafia_game/main.py`
- `mcp_server/mafia_game/services/bootstrap.py`
- `mcp_server/mafia_game/integrations/engine_http.py`
- `backend/app/mcp/client.py`
- `backend/app/routers/scaffold_mcp_router.py`

작업:

- MCP process 기동
- initialize와 bootstrap/consume 왕복
- fake transport 테스트 후 loopback 실제 HTTP 확인
- 실제 MCP process와 Backend 내부 HTTP 응답의 correlation 확인
- Resource·게임 Tool은 추가하지 않음

완료 기준: Backend가 실제 MCP process에서 initialize와 bootstrap/consume 왕복
결과를 받고, MCP가 Backend 내부 HTTP 응답을 정상 처리한다. Game Engine이 없으므로
bootstrap 검증에 필요한 job/capability는 통합 테스트용 synthetic fixture로만 만든다.

### WU-IMVP-05 — Dummy LLM adapter 확인

대상:

- `backend/app/llm_provider/base.py`
- `backend/app/llm_provider/dummy.py`
- `backend/app/llm_provider/factory.py`

작업:

- 자동 테스트에서는 DummyProvider를 사용
- 실제 실행에서는 환경변수로 선택한 Provider를 호출해 structured response 확인
- 실제 API key는 로그·fixture·문서에 기록하지 않음

완료 기준: DummyProvider 자동 테스트가 통과하고, 별도 opt-in smoke에서 선택한
실제 Provider의 structured response 왕복을 1회 이상 확인한다. API key가 없는
환경에서는 실제 Provider smoke를 완료로 표시하지 않는다.

### WU-IMVP-06 — 기존 Frontend 화면에서 연결 결과 확인

대상:

- `frontend_user/app_pages/game_scaffold_page.py`
- `frontend_user/core/api_client.py`
- 필요한 최소 테스트

작업:

- 새 페이지와 새 디렉터리를 만들지 않음
- 기존 scaffold 화면에 연결 확인 결과를 임시 표시
- 성공/실패한 시스템만 구분해 표시
- 게임 규칙과 결과 화면은 구현하지 않음

완료 기준: Frontend에서 Integration MVP API 전체를 호출하고 Backend·PostgreSQL·
Redis·MCP·선택 Provider LLM의 정상·실패 상태를 구분해 확인한다.

## 6. 복잡도 제한

참고 프로젝트의 Backend가 약 517줄, 최대 파일 174줄인 점을 기준으로 이번 단계의
신규·수정 코드가 불필요하게 커지지 않도록 다음 상한을 둔다.

- 이번 단계의 신규·수정 Python 코드 합계: 1,000줄 이하
- 단일 파일: 200줄 이하를 목표로 하고 초과 시 분리 사유를 기록
- 새 class hierarchy, generic event bus, dependency container를 만들지 않음
- 새 Repository·Factory·Domain model은 추가하지 않음
- integration-check는 개발용 진단 경로이며 제품 기능으로 확장하지 않음
- 주석과 docstring은 AGENTS.MD에 따라 한국어로 작성

## 7. 검증 명령과 완료 증거

각 WU는 focused test를 먼저 실행하고, 마지막 WU에서 전체 회귀를 실행한다.

```text
.venv\Scripts\python.exe -m pytest -q backend/tests
frontend_user 전용 환경에서 pytest 실행
mcp_server 전용 환경에서 pytest 실행
```

실제 PostgreSQL·Redis·MCP process·선택 Provider 연결은 synthetic test와 분리해
다음 증거를 기록한다.

- 사용한 서비스의 health 결과
- migration 적용 여부
- 정상 연결 결과
- 의도적인 장애·거부 결과
- Frontend에서 시작한 실제 API 왕복 결과
- MCP initialize/bootstrap/Engine HTTP 왕복 결과
- 선택 Provider structured response 결과
- 비밀값을 제외한 실행 명령과 결과

실제 외부 LLM은 자동 테스트에서 호출하지 않는다. DummyProvider로 계약을 검증한 뒤,
완료 전 opt-in smoke를 별도로 실행한다. 실제 Provider smoke를 실행하지 못하면
Integration MVP는 “자동 테스트 완료·실제 LLM 연결 미확인” 상태로 남긴다.

## 8. 이후 메인 로직 개발 순서

Integration MVP가 완료된 뒤에만 다음 작업을 시작한다.

```text
Integration MVP
→ 순수 Game Engine
→ canonical game state 저장
→ Dummy Agent 행동
→ MCP Resource/Tool
→ 실제 LLM Provider
→ SSE/Outbox/Fallback
→ 관리자·시나리오·운영 기능
```

Game Engine을 시작할 때는
[AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md](AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md)를
기초로 하되, 구현 전 Backend 정본과 WU 범위를 다시 확정한다.
