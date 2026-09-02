# AI 마피아 기획 문서 통합·수정 내역

**작성일:** 2026년 9월 1일
**통합 결과:** [AI_MAFIA_MVP_FINAL_PLAN.md](AI_MAFIA_MVP_FINAL_PLAN.md)
**통합 원본 3개:**

1. `docs/mafia_game_plan.md` — 추리게임 기획안 (제품 기획 관점)
2. `docs/AI_MAFIA_MVP_PLAN.md` — MVP 구현 설계 초안 (기술 설계 관점)
3. `docs/ai_mafia_game_engine분리규칙.md` — 엔진/Agent/MCP 분리 규칙 (보안 경계 관점)

이 문서는 세 문서의 역할·계약을 대조하면서 발견한 불일치, 결정한 통합 방향,
최종 플랜과 세부 계약에 반영한 수정 사항을 기록한다. 현재 디렉터리 목록은
구현 계약이 아니라 참고용 검증 기록이다.

## 1. 현재 저장소 구조 대비 검증 결과

### 1.1 문서와 실제 구조가 일치하는 항목

- `frontend_user`(app.py, app_pages/, core/api_client.py),
  `frontend_admin`(app.py, app_pages/, core/), `backend/app`의
  routers/schemas/services/models/repositories/agent/llm/mcp/
  infrastructure(redis, security)/core 경계는 문서 설계와 실제 구조가 일치.
- `backend/migrations/` 소유권과 실행기
  (`backend.app.infrastructure.migrations`) 일치.
- Google OIDC 로그인, HMAC 내부 서명, identity provision API는 저장소의 기존
  identity 기능으로 구현 완료 상태다. 단, 게임 MVP 경로에서는 이를 호출하지 않고
  별도 `X-User-Id` 식별자 계약을 사용한다.

### 1.2 문서와 실제 구조가 불일치한 항목 (최종 플랜에서 교정)

| 항목 | 문서 내용 | 실제 구조 | 최종 플랜 반영 |
|---|---|---|---|
| MCP 패키지 이름 | MVP_PLAN·README는 `mcp_server/tour`, `mcp_server/weather` 언급 | 실제는 `mcp_server/mcp_1`, `mcp_server/mcp_2` (범용 예약 이름으로 개편됨) | 게임 컨텍스트 MCP를 `mcp_1`에 배치, `mcp_2`는 후속 예약으로 명시 |
| MCP README 내용 | — | `mcp_1`/`mcp_2` README에 Tour·Weather 설명이 잔존 | 과거 예약 명칭임을 최종 플랜에 주석, 구현 시 README 갱신 예정 |
| 미추적 잔여 디렉터리 | — | `backend/app/api`, `backend/app/auth`, `backend/app/db`, `mcp_server/src`가 빈 디렉터리/캐시로 잔존 (git 미추적, 구조 개편 이전 잔재) | 구조 변경 없이 현황만 기록. 정리는 별도 승인 필요 |
| LLM 공급자 | 문서에 미확정 | `.env`에 OpenAI·Gemini·로컬 endpoint 항목이 존재 | local·OpenAI·Gemini 중 `LLM_PROVIDER` 선택 계약으로 확정 |

### 1.3 세 문서 간 충돌 항목과 결정

사용자 확인을 거쳐 다음과 같이 확정했다.

| 충돌 항목 | mafia_game_plan | AI_MAFIA_MVP_PLAN | 최종 결정 |
|---|---|---|---|
| 게임 인원 | 5~9명 | 4~8명 | **5~9명** (역할표도 5~9명 기준으로 재작성) |
| 조사 역할 명칭 | 탐정 | 경찰 | **경찰** |
| 의사 자기 보호 | 게임당 1회만 | 무제한 허용 | **무제한 허용** (구현 단순화) |
| 의사 연속 보호 | 금지 | 허용 | **허용** (구현 단순화) |
| 투표 동률 | 동점자 재투표 1회, 재동점 시 무처형 | 즉시 무처형 | **재투표 1회 후 무처형** (상태 머신에 `DAY_REVOTE` 추가) |
| 첫날 처형 생략 | 첫날은 의심도만 기록, 처형 생략 | 규정 없음 | **미채택.** MVP는 모든 낮에 동일 규칙 적용. 첫날 보호는 후속 검토 항목 |
| 추리극 요소 | 시나리오 패턴·사건 진실·단서·Red Herring·AI GM 해설 포함 | 없음 | **MVP 제외**, 후속 확장으로 명시 (사용자 결정) |
| 이벤트 공개 범위 | 3단계(공개/개인/내부) | 4단계 `PUBLIC/PRIVATE/FACTION/SYSTEM` | **4단계** (마피아 진영 합의에 `FACTION` 필요) |
| 진행자 명칭 | AI GM (사건 해설 포함) | 중재 에이전트 (진행 안내 전용) | **중재 에이전트**, 사건 해설은 추리극 확장 시 GM으로 승격 |

### 1.4 engine분리규칙 문서의 정합성 교정

- 문서 서두의 "4개의 AI Agent와 1명의 사용자"(5명 고정)는 예시 구성이며,
  최종 플랜의 5~9명 범위(AI 4~8명)와 충돌하지 않도록 인원 규칙은 최종
  플랜을 따르게 했다.
- Resource URI 체계가 두 문서에서 달랐다
  (`mafia://rules/basic-v1` vs `mafia://rules/core|roles|phases`,
  `public-timeline` vs `public-state|public-history`). 최종 플랜은
  `basic-v1`(버전 고정 규칙) + `public-state` + `public-timeline` +
  `agents/me` 계열로 병합했다.
- Tool 이름도 달랐다 (`submit_night_action`/`submit_vote`/
  `publish_statement` vs `game.kill`/`game.investigate`/`game.protect`/
  `game.vote`/`game.speak`/`game.end_turn`). **`game.*` 네임스페이스로
  통일**했다. 역할별 행동이 분리된 Tool이 노출 제어(8장)와 검증 규칙
  매핑에 더 명확하기 때문이다.
- `get_allowed_actions`는 Tool이 아닌 Resource
  (`.../agents/me/allowed-actions`)로 통일했다 (읽기 전용이므로).
- engine분리규칙의 상태 전이에 없던 `NIGHT_MAFIA_ACTION` 같은 세분 페이즈
  표기는 MVP_PLAN의 단일 `NIGHT_ACTION` 페이즈로 통일했다. 마피아·경찰·
  의사 행동은 같은 페이즈 안에서 병렬 수집한다 (13장 실행 흐름과 일치).

### 1.5 두 문서가 상호 보완되어 그대로 병합한 항목

- engine분리규칙의 **시스템 프롬프트 2계층 분리**(공통 제약 + 개성),
  **프롬프트 우선순위**, **이중 검증 원칙**, **식별자/세션 규칙**
  (`agent_id` 서버 고정, `actor_id` 미전달), **메모리 네임스페이스
  `{game_id}/{agent_id}`**, **감사 로그 규칙**, **컨텍스트 격리 검증**
  (비간섭성 테스트, 카나리 값)을 최종 플랜 7·8·12장에 편입.
- MVP_PLAN의 **상태 머신, 데이터 모델 8개 테이블, Redis key 설계,
  API 계약, 페르소나 파라미터 10종, fallback 표, 구현 단계**를 골격으로
  유지.
- mafia_game_plan의 **호스트 정책**(생성자는 소유자 메타정보만),
  **명시적 PAUSE 후 동일 좌석 복귀**(브라우저 강제 종료 자동 감지는 MVP 제외,
  AI 자동 교체 금지),
  **경찰 결과는 진영만 반환**(정확한 역할명 비공개), **비공개 투표**,
  **처형자 역할 공개** 규칙을 최종 플랜과 `AI_MAFIA_GAME_RULES.md`에 편입.

## 2. 최종 플랜에서 새로 확정한 사항

1. 역할표를 5~9명 기준으로 확정 (7명 이상 마피아 2명, 주범·공범 구분 없음).
   정확한 배정·해소 순서는 `AI_MAFIA_GAME_RULES.md`에 별도 고정했다.
2. 상태 전이에 `DAY_REVOTE`(동점자 재투표 1회) 단계 추가.
3. LLM 공급자를 local·OpenAI·Google Gemini 중 하나로 선택하고
   `LLM_PROVIDER` 환경 변수로 고정.
4. 게임 MCP 배치 위치를 `mcp_server/mcp_1`로 확정.
5. 구현 단계 0단계의 규칙·명칭·공급자·MCP 위치와 `X-User-Id` 식별자 계약을
   확정했다(로그인·인증 제외).
6. 최소 비동기 실행을 단일 Uvicorn worker의 복구 실행기,
   PostgreSQL `game_operations`·`api_idempotency_records` 원본, SSE와 operation
   polling으로 확정했다.
7. 게임당 60,000 token, 호출당 출력 400 token, 원격 모델 예상 비용 1 USD 경고선,
   PAUSED 30일·FINISHED 90일·audit 180일 보존을 확정했다.
8. MCP가 Backend의 필터링된 context만 HMAC 내부 endpoint로 조회하도록
   `MCP_INTERNAL_SECRET`과 session header 계약을 확정했다.

## 3. 함께 변경한 프로젝트 파일

### 3.1 패키지 목록

- `pyproject.toml`: MVP 구현에 필요한 런타임 의존성 추가
  — `redis`(lock/cache/stream), `cryptography`(seed AES-256-GCM 암호화),
  `openai`, `google-genai`(local·OpenAI·Gemini provider 계약),
  `mcp`(MCP 서버/클라이언트 SDK), `httpx`(LLM·MCP 비동기 HTTP,
  FastAPI TestClient 의존성이기도 함), `sse-starlette`(SSE 이벤트 구독).
  dev 그룹에 `pytest-asyncio`(비동기 엔진·agent 테스트) 추가.
- `backend/requirements.txt`: 동일 런타임 의존성 반영 (독립 실행 단위 기준).

설치: `uv sync --dev`

### 3.2 `.env.example`

기존 DB·HMAC 항목을 유지하고 다음 예약 항목을 placeholder로 추가했다.
실제 키 값은 `.env`에만 보관한다.

- `REDIS_URL`: 게임 lock/cache/stream용 Redis 연결
- `LLM_PROVIDER`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`,
  `OPENAI_API_KEY`, `OPENAI_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`:
  LLM provider 선택 설정
- `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `GAME_MAX_TOTAL_TOKENS`,
  `GAME_COST_WARNING_USD`, provider token 가격: agent·게임 비용 제한
- `GAME_SEED_ENCRYPTION_KEY`: 역할 배정 seed 암호화 키
- `PAUSED_GAME_RETENTION_DAYS`, `FINISHED_GAME_RETENTION_DAYS`,
  `AUDIT_LOG_RETENTION_DAYS`: 보존 기간
- `MAFIA_MCP_URL`, `BACKEND_INTERNAL_URL`, `MCP_INTERNAL_SECRET`: 게임 컨텍스트
  MCP 주소와 전용 내부 HMAC 경계

### 3.3 문서

- `docs/AI_MAFIA_MVP_FINAL_PLAN.md` 신규 작성·정리 (제품 범위·책임 경계·구현 단계).
- `docs/AI_MAFIA_GAME_RULES.md` 신규 작성 (basic-v1 규칙·상태 전이·행동 해소 정본).
- `docs/AI_MAFIA_BACKEND_API_CONTRACT.md`와 `docs/AI_MAFIA_MCP_API_CONTRACT.md`로 Backend REST·SSE와 게임 MCP wire 계약을 분리했다. `docs/AI_MAFIA_API_CONTRACT.md`는 인덱스만 유지한다.
- `docs/AI_MAFIA_DATA_REDIS_DESIGN.md` 신규 작성·정리 (PostgreSQL schema·transaction·Redis 저장·복구 계약).
- `docs/AI_MAFIA_FRONTEND_SPEC.md` 신규 작성·정리 (사용자·관리자 화면과 호출 순서).
- 게임 화면 최하단에 개인 단서 메모 카드를 추가하고 `game_notes` 저장 계약과
  동기화했다. 구현 파일명은 계획서가 고정하지 않으며, 최종 플랜의 구현 경계와
  각 세부 계약(Frontend·API·DB)을 기준으로 실제 import 경계에 맞춰 정한다.
- 피드백은 결과 화면의 1~5 평점만 저장하도록 축소하고, 별도 서술·카테고리·상태
  변경 기능은 MVP에서 제외했다.
- 원본 3개 문서 서두에 최종 플랜으로 대체되었음을 알리는 안내 추가.
- 루트 `README.md`의 문서 링크·프로젝트 구조 표기를 실제 구조
  (`mcp_server/mcp_1`, `mcp_2`)와 최종 플랜 기준으로 갱신.

## 4. 검증

- 문서 간 역할표·상태 머신·endpoint·`user_id` 헤더·메모 version을 상호 대조했다.
- 최종 플랜의 책임 경계와 Frontend·API·DB 세부 계약을 상호 대조했다. 저장소의
  현재 디렉터리 목록은 구현 계획의 계약으로 취급하지 않는다.
- JSON 예시 block, Markdown 로컬 링크, TOML 구문과 `git diff --check`를 확인했다.
- 실제 게임 코드·migration·LLM/MCP 서버는 아직 없으므로 실행 테스트는 대상이 아니다.

## 5. 후속 문서 동기화 반영

이후 게임 MVP 범위에서 로그인·인증을 제외하고 `X-User-Id`를 식별자로 사용하도록
결정했다. 상세 Backend 계약은 `AI_MAFIA_BACKEND_API_CONTRACT.md`, MCP 계약은
`AI_MAFIA_MCP_API_CONTRACT.md`, DB의 users FK 예외와 Redis
변경은 `AI_MAFIA_DATA_REDIS_DESIGN.md`, user_id 입력 화면은
`AI_MAFIA_FRONTEND_SPEC.md`를 기준으로 한다. 기존 Google OIDC 구현은 저장소의
별도 기능으로 보존하지만 게임 MVP의 선행 조건으로 사용하지 않는다.

- 문서 통합은 실행 동작 변경이 없으므로 자동 테스트 대상이 아니며, 세 원본
  문서와 최종 플랜·게임 규칙 문서의 역할표·상태 머신·URI·Tool 명세를 상호 대조해 확인했다.
- 현재 작업 환경에는 `uv` 실행 파일이 없어 `uv sync --dev`, pytest, ruff와
  compileall은 실행하지 않았다. `py -c`의 Python 3.12 `tomllib`으로
  `pyproject.toml` 구문을 대신 검증했다.
