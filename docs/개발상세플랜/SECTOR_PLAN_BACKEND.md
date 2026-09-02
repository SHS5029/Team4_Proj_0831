# Backend 섹터 작업 지침서 (AI 마피아 MVP)

**대상 담당자:** Backend 섹터 개발자 1인 (별도 시스템에서 개발 후 merge)
**상위 계약 문서:** [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
— 2장(사용자·관리자 API)·3장(DB 설계)·4장(Backend 계획)·5장(내부 Engine API)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 지침서보다 우선한다.

이 문서는 Backend 섹터가 별도 시스템에서 독립 개발하고 통합 저장소에
merge하기까지의 작업 단위, coding AI agent 사용 규칙, 중간 merge·테스트
체크포인트를 확정한다. Backend는 Front와 MCP 양쪽의 계약 제공자이므로
**계약 구현(2·5장)을 임의로 바꾸지 않는 것**이 최우선 규율이다.

---

## 1. 소유 경계와 금지 사항

### 1.1 수정 허용 (이 섹터의 소유)

```text
backend/**
```

### 1.2 수정 금지 (다른 섹터 소유)

```text
frontend_user/**, frontend_admin/**   → Front 섹터
mcp_server/**                         → MCP 섹터
```

### 1.3 조건부 수정 (사전 고지 필요)

- 기존 identity 관련 파일(`routers/identity_router.py`,
  `services/identity_service.py`, `repositories/user_repository.py`,
  `infrastructure/security/internal_request.py`, `core/*`):
  **기존 로그인 동작과 canonical 서명 규칙을 바꾸지 않는다.** 게임 API용
  서명·오류 코드는 신규 파일에 추가한다.
- `backend/migrations/001_*.sql`: 수정 금지. 변경은 새 번호 SQL로만.
- 공유 파일(`pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`):
  수정 시 다른 섹터에 즉시 고지.

### 1.4 신규 파일 (승인된 구조 변경 범위 — 이 목록이 전부다)

```text
backend/app/models/game.py
backend/app/models/persona.py
backend/app/services/game_service.py
backend/app/services/admin_service.py
backend/app/repositories/game_repository.py
backend/app/repositories/feedback_repository.py
backend/app/repositories/admin_repository.py
backend/app/routers/game_router.py
backend/app/routers/feedback_router.py
backend/app/routers/admin_router.py
backend/app/routers/engine_internal_router.py
backend/app/schemas/game_schema.py
backend/app/schemas/admin_schema.py
backend/app/agent/manager.py
backend/app/agent/context.py
backend/app/agent/prompts.py
backend/app/llm/providers.py
backend/app/mcp/capability.py
backend/app/infrastructure/redis/client.py
backend/app/infrastructure/redis/locks.py
backend/app/infrastructure/security/game_request.py   # 게임 API용 서명 검증
backend/migrations/002_create_mafia_game_schema.sql
backend/tests/test_game_rules.py
backend/tests/test_game_state_machine.py
backend/tests/test_game_api.py
backend/tests/test_game_repository.py
backend/tests/test_snapshot_replay.py
backend/tests/test_agent_manager.py
backend/tests/test_context_isolation.py
backend/tests/test_admin_api.py
backend/tests/test_engine_internal_api.py
backend/tests/test_redis_locks.py
```

이 밖의 파일이 필요하면 착수 전에 이 문서와 구현 계획서를 갱신·합의한다.
기존 예약 파일(`agent/orchestrator.py`, `agent/policies.py`,
`mcp/client.py`, `mcp/registry.py`, `mcp/tool_router.py`, `llm/client.py`)은
내용을 채워 사용해도 되고, 사용하지 않으면 그대로 둔다(삭제 금지).

---

## 2. 별도 시스템 작업 환경 구성

```bash
git clone <repo-url> && cd Team4_Proj_0831
git checkout -b feat/backend-<기능이름>      # 예: feat/backend-rule-engine
uv sync --dev
cp .env.example .env && chmod 600 .env       # 기존 .env 있으면 덮어쓰지 않음
uv run pytest                                 # baseline 통과 확인
```

- **WU-B1(규칙 엔진)은 DB·Redis·LLM 없이** 순수 Python으로 개발한다.
- WU-B2부터 로컬 PostgreSQL(`Team4_Proj` DB 생성)과 Redis가 필요하다.
  단, **자동 테스트는 fake 연결로 실행 가능**해야 하며 실제 인프라는 수동
  검증에만 쓴다(기존 backend/tests의 fake DB 패턴을 따른다).
- 실제 LLM 키는 WU-B6의 수동 1회 검증에만 사용하고 자동 테스트에서
  호출하지 않는다. 키는 `.env`에만 둔다.

### 2.1 브랜치·merge 규칙

- 작업 브랜치: `feat/backend-<기능>` — WU 1~2개 규모.
- merge 대상: `develop`. **`main` 직접 커밋·푸시 금지.**
- Backend는 계약 제공자이므로 **CP-B3(사용자 API)·CP-B4(내부 Engine API)
  merge가 다른 두 섹터의 통합 선행 조건**이다. 해당 CP를 우선순위로 진행한다.
- 커밋은 승인 후에만, 메시지는 AGENTS.MD 형식(목적/범위/검증).

---

## 3. Coding AI Agent 사용 규칙 (필수)

1. **한 번에 모든 구현 지시 금지.** 한 세션 범위는 4장 WU 1개 이하.
2. 작업 범위는 이 문서 4장 WU 정의로 확정한다. 범위 밖 파일 수정·신규 파일
   제안 시 중단하고 재지시한다.
3. 프롬프트에 반드시 포함: 이 지침서·AGENTS.MD 선독, WU 범위 파일 제한,
   완료 기준, 검증 명령(3.4), **한국어 주석**, 고위험 항목의 거부 경로
   테스트 동시 작성.
4. agent 산출물 diff를 사람이 전수 검토한다. 특히: 응답에 역할·seed 누설
   여부, 로그에 prompt·비밀정보 기록 여부, migration이 001을 건드리는지,
   기존 identity 테스트 무손상 여부.
5. 무의미한(항상 통과) 테스트 금지. 거부 경로는 실제로 401/403/404/409/422를
   반환하는지 확인한다.
6. WU 완료 → 검증 → 사람 검토 → (승인 시) 커밋 → 다음 WU. 건너뛰기 금지.

### 3.4 WU 공통 검증 명령

```bash
uv run pytest backend/tests                 # focused
uv run ruff check backend
uv run python -m compileall -q backend
# merge 직전에만 전체 회귀:
uv run pytest
```

---

## 4. 작업 단위(WU) 분해

### WU-B1. 규칙 엔진 (LLM·DB 없음) — 최우선

- **범위 파일:** `models/game.py`, `models/persona.py`,
  `tests/test_game_rules.py`, `tests/test_game_state_machine.py`
- **내용:** 최종 플랜 6장 규칙의 순수 함수형 구현.
  - 5~9명 역할표, seed 결정적 무작위 배정
  - Phase 상태 머신(`DAY_REVOTE` 포함), 밤 해소(보호=공격 취소, 마피아 2인
    다수결·결정적 동률 해소), 투표(자기 투표 금지, 동률→재투표 1회→무처형,
    처형자 역할 공개), 승패 판정(마피아 ≥ 비마피아 / 마피아 0)
  - 이벤트 생성(visibility 4종)과 에이전트별 View 필터 함수
- **완료 기준:** 규칙 단위 테스트 + fake agent 5~9명 전 구성 자동 완주
  + View 필터가 타인 역할·조사 결과를 절대 포함하지 않는 검증(카나리 방식
  권장) 통과. 외부 의존성 import 0.

### WU-B2. DB 영속화

- **범위 파일:** `migrations/002_create_mafia_game_schema.sql`,
  `repositories/game_repository.py`, `repositories/feedback_repository.py`,
  `tests/test_game_repository.py`, `tests/test_snapshot_replay.py`
- **내용:** 구현 계획서 3장 설계 그대로. 001 컨벤션(단일 트랜잭션,
  IF NOT EXISTS, 재실행 가능, 한국어 주석, updated_at 트리거 재사용) 준수.
  persona 5종 시드 포함. event append + optimistic version + snapshot
  (checksum·이벤트 재생 복구).
- **완료 기준:** fake 연결 기반 repository 테스트, version 충돌·재생 복구
  테스트 통과. **001 파일 diff 없음.**

### WU-B3. Redis 기반 실행 조정

- **범위 파일:** `infrastructure/redis/client.py`, `locks.py`,
  `tests/test_redis_locks.py`
- **내용:** 3.3 key 설계. lock(token 소유자만 해제, heartbeat 연장),
  idempotency 저장, runtime cache, event stream 발행. fake Redis로 테스트.
- **완료 기준:** lock 경합·소유자 아닌 해제 거부·Redis 장애 시 안전 중단
  테스트 통과.

### WU-B4. 사용자 게임 API

- **범위 파일:** `routers/game_router.py`, `routers/feedback_router.py`,
  `schemas/game_schema.py`, `services/game_service.py`,
  `infrastructure/security/game_request.py`, `tests/test_game_api.py`
- **내용:** 구현 계획서 2장 명세 그대로(2.1~2.7). 게임 API용 canonical
  (`timestamp.request_id.acting_user_id.raw_body`) 서명 검증,
  `acting_user_id` 활성·소유권 재검증, GameStateView 필터, idempotency,
  SSE(`sse-starlette`), `?since_sequence` 증분.
- **완료 기준:** 2.0 오류 표 **전 코드의 거부 경로 테스트**, 응답에
  타인 역할·seed 부재 스냅샷 테스트, 같은 idempotency_key 재전송 동일 응답
  테스트 통과. 기존 identity 테스트 무손상.

### WU-B5. 내부 Engine API + capability

- **범위 파일:** `routers/engine_internal_router.py`, `mcp/capability.py`,
  `tests/test_engine_internal_api.py`
- **내용:** 구현 계획서 5장 계약 그대로. `ENGINE_INTERNAL_API_SECRET` 별도
  서명, capability_token 발급·검증(game/agent/phase 범위), `/context`
  7종 resource 응답(agent별 View 필터), `/actions` 이중 검증(역할·생존·
  페이즈·대상·중복을 capability와 무관하게 재검증), `proposal_id`
  idempotency, `audit_logs` 기록.
- **완료 기준:** actor 위조 필드 422, 만료·타 게임 capability 거부,
  Front용 secret으로 서명한 요청 거부, 감사 로그 기록 테스트 통과.
- **주의:** 이 WU 완료 즉시 CP-B4로 merge한다 — MCP 섹터 통합의 선행 조건.

### WU-B6. Agent Manager + LLM providers

- **범위 파일:** `agent/manager.py`, `agent/context.py`, `agent/prompts.py`,
  `llm/providers.py`, `tests/test_agent_manager.py`,
  `tests/test_context_isolation.py`
- **내용:** 최종 플랜 13장 실행 흐름. fake LLM로 루프 완성 후
  OpenAI·Gemini 어댑터(`LLM_PROVIDER` 선택, timeout, token 상한,
  `agent_runs` 기록). 프롬프트 2계층(공통 제약 불변 + persona 개성),
  컨텍스트 격리 검사(호출 전 타 agent 정보 부재 확인), 구조화 출력 검증,
  교정 1회 후 fallback(최종 플랜 7.4 표 전 항목).
- **완료 기준:** fallback 표 전 항목 테스트, 카나리 격리·비간섭성 테스트,
  회귀에서 실제 LLM 호출 0회. 실제 LLM 1회 수동 검증은 비용 승인 후
  별도 수행하고 결과만 기록.

### WU-B7. 관리자 API

- **범위 파일:** `routers/admin_router.py`, `schemas/admin_schema.py`,
  `services/admin_service.py`, `repositories/admin_repository.py`,
  `tests/test_admin_api.py` (+ migration에 `user_roles`가 없으면 003 추가)
- **내용:** 2.8 명세. `user_roles` ADMIN 검증(fail-closed), KPI 집계,
  로그 민감 필드 제거(prompt·역할 목록·비밀정보 부재), 피드백 상태 변경.
- **완료 기준:** 비관리자 403, 민감 필드 부재, 상태 변경 검증 테스트 통과.

---

## 5. 중간 merge·테스트 체크포인트

| 체크포인트 | 포함 WU | merge 전 필수 검증 | 후속 의존 |
|---|---|---|---|
| **CP-B0 계약 확인** | (코드 없음) | 2·3·5장 리뷰 의견 제출 | 3인 합의 |
| **CP-B1 규칙 엔진** | B1 | focused + 전체 회귀 | — |
| **CP-B2 영속화** | B2, B3 | 회귀 + 로컬 DB migration 수동 1회 | — |
| **CP-B3 사용자 API** | B4 | 회귀 + 오류 표 전 경로 확인 | **Front CP-F3 선행 조건** |
| **CP-B4 내부 API** | B5 | 회귀 + capability 거부 경로 확인 | **MCP CP-M3 선행 조건** |
| **CP-B5 에이전트·관리자** | B6, B7 | 회귀 + fake LLM 완주 | Front CP-F4, 통합 CP-ALL |

### 중간 테스트 규칙

- WU마다 focused, CP merge 직전 전체 회귀.
- CP-B3·CP-B4 merge 후 `develop`에서 서버 기동 스모크
  (`uvicorn` 기동 → `/health` 200 → 게임 생성 1회)를 실행하고 결과를
  Front·MCP 담당자에게 공유한다.
- 계약과 다른 동작을 발견하면 코드를 계약에 맞추는 것이 기본이다. 계약
  자체를 바꿔야 하면 구현 계획서 9장 절차(문서 먼저)로 진행한다.

---

## 6. 고위험 항목 (AGENTS.MD 테스트 규칙 직접 적용)

다음은 전부 인증·권한·보안·동시성 고위험으로 분류한다. **구현과 동시에
실패·거부 경로 테스트를 작성**하고 CP merge 전 전체 회귀를 실행한다.

- 게임 소유권(타인 게임 404 동일 응답), `acting_user_id` 검증
- GameStateView·`/context` 필터(타인 역할·조사·보호·seed 누설 금지)
- capability 위조·만료·범위 초과 거부, actor 필드 위조 422
- optimistic lock(409), idempotency, Redis lock 소유권
- 관리자 fail-closed
- 로그·오류 메시지에 prompt·seed·역할·비밀정보 미포함

## 7. 완료 보고 양식 (WU·CP 공통)

```text
[WU-B4 완료]
- 변경 파일: (목록)
- 실행 검증: uv run pytest backend/tests → NN passed / ruff OK / compileall OK
- 거부 경로 테스트: (401/403/404/409/422 항목 나열)
- 생략 검증과 이유: 실제 DB migration은 CP-B2에서 수동 실행 예정
- 범위 밖 변경: 없음
- 계약 이슈: (있으면 구현 계획서 장·절 지목)
- README 갱신 필요 여부: (실행 방법·env 변경 유무)
```
