# Backend 섹터 작업 지침서 (AI 마피아 MVP)

**대상 담당자:** Backend 섹터 개발자 1인 (별도 시스템에서 개발 후 merge)
**상위 계약 문서:** [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
— 2장(사용자·관리자 API)·3장(DB 설계)·4장(Backend 계획)·5장(내부 Engine API)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 지침서보다 우선한다.

이 문서는 Backend 섹터가 별도 시스템에서 독립 개발하고 통합 저장소에
merge하기까지의 작업 단위, coding AI agent 사용 규칙, 중간 merge·테스트
체크포인트를 확정한다. Backend는 Front와 MCP 양쪽의 계약 제공자이므로
**계약 구현(2·5장)을 임의로 바꾸지 않는 것**이 최우선 규율이다.

PostgreSQL·Redis의 **인스턴스 설치, 생성, 기동, 중지, 접속 계정·권한 준비,
migration 실행과 health 확인은 MCP 섹터의 운영 책임**이다. Backend 섹터는
DB schema·migration SQL·repository와 Redis client·lock 의미를 구현하고 fake로
검증하지만, 실제 DB·Redis 프로세스를 직접 구축하거나 실행하지 않는다.

---

## 1. 소유 경계와 금지 사항

### 1.1 수정 허용 (이 섹터의 소유)

```text
backend/**
```

위 소유권은 Backend 애플리케이션 코드와 DB·Redis 사용 계약에 한정한다.
PostgreSQL·Redis 실행 환경의 구축·기동과 migration 실행은 포함하지 않는다.

### 1.2 수정 금지 (다른 섹터 소유)

```text
frontend_user/**, frontend_admin/**   → Front 섹터
mcp_server/**                         → MCP 섹터
PostgreSQL·Redis 실행 환경 구축·운영 → MCP 섹터
```

### 1.3 조건부 수정 (사전 고지 필요)

- 기존 identity 관련 파일(`routers/identity_router.py`,
  `services/identity_service.py`, `repositories/user_repository.py`,
  `infrastructure/security/internal_request.py`):
  **기존 로그인 동작과 canonical 서명 규칙을 바꾸지 않는다.** 게임 API용
  서명·오류 코드는 신규 파일에 추가한다.
- 기존 `backend/app/core/config.py`, `backend/app/infrastructure/migrations.py`,
  `backend/tests/test_config.py`, `backend/tests/test_migrations.py`는 WU-B3의
  runtime/migration env 분리만, `backend/app/main.py`는 WU-B5~B7의 router와
  scheduler lifespan 등록만 수정한다. 무관한 설정·bootstrap 리팩터링은 금지한다.
- `backend/migrations/001_*.sql`: 수정 금지. 변경은 새 번호 SQL로만.
- 공유 파일(`pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`):
  수정 시 다른 섹터에 즉시 고지.

### 1.4 신규 파일 (승인된 구조 변경 범위 — 이 목록이 전부다)

```text
backend/app/models/game.py
backend/app/models/scenario.py
backend/app/models/persona.py
backend/app/services/game_service.py
backend/app/services/game_timer_service.py
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
backend/app/mcp/transport_auth.py
backend/app/infrastructure/redis/client.py
backend/app/infrastructure/redis/locks.py
backend/app/infrastructure/security/game_request.py   # 게임 API용 서명 검증
backend/migrations/002_create_mafia_game_schema.sql
backend/tests/test_game_rules.py
backend/tests/test_game_state_machine.py
backend/tests/test_game_scenarios.py
backend/tests/test_game_timers.py
backend/tests/test_game_api.py
backend/tests/test_game_repository.py
backend/tests/test_game_receipts.py
backend/tests/test_snapshot_replay.py
backend/tests/test_audit_outbox.py
backend/tests/test_agent_manager.py
backend/tests/test_context_isolation.py
backend/tests/test_admin_api.py
backend/tests/test_engine_internal_api.py
backend/tests/test_mcp_transport_auth.py
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
uv run pytest                                 # baseline 통과 확인
```

- `.env.example`은 여러 프로세스의 설정 **카탈로그**일 뿐이다. 생산에서 통째로
  복사·로드하지 않고 2.1의 프로세스별 allowlist만 승인된 비밀 주입 방식으로
  제공한다. 실제 값·placeholder를 문서·로그·테스트 출력에 남기지 않는다.
- **WU-B1~B2는 DB·Redis·LLM 없이** 순수 Python으로 개발한다.
- WU-B3~B4의 자동 테스트는 **MCP 섹터의 실제 PostgreSQL·Redis 없이 fake
  연결로 실행 가능**해야 한다(기존 backend/tests의 fake DB 패턴을 따른다).
- 실제 인프라 검증이 필요한 시점에는 MCP 섹터의 CP-M1A/M1B 결과를
  사용한다. 정확한 순서는 `CP-M1A → WU-B3 산출물 → CP-M1B → CP-B2`다.
  Backend 담당자가 DB·Redis를 설치·생성·기동하지 않고, 필요한 migration과
  접속 요구사항을 MCP 담당자에게 전달한다.
- 실제 LLM 키는 WU-B8의 비용 승인된 수동 1회 검증에만 사용하고 자동 테스트에서
  호출하지 않는다. 키는 `.env`에만 둔다.

### 2.1 Backend 프로세스별 env allowlist

- **Backend runtime:** `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`,
  `LLM_PROVIDER`, 필요한 `LLM_*`·`OPENAI_*`·`GEMINI_*`, full endpoint인
  `MAFIA_MCP_URL`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`,
  `INTERNAL_API_SECRET`과 상위 계약에 명시된 비밀이 아닌 timeout·TLS 설정만.
  `DATABASE_MIGRATION_URL`은 절대 주입하지 않는다.
- **Migration CLI/process:** `DATABASE_MIGRATION_URL`과 필요한 비밀 아닌
  `DATABASE_NAME`만. `DATABASE_URL`, Redis·LLM·Front/Engine/MCP secret은 금지한다.
- Backend 소유가 아닌 **MCP runtime**에는 `MCP_SERVER_AUTH_SECRET`,
  `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`과 비밀 아닌 host/port·TLS·timeout·
  bounded-outbox 설정만 허용한다. DB·Redis·LLM·`INTERNAL_API_SECRET`은 넘기지 않는다.

기본값은 `LLM_TIMEOUT_SECONDS=15`, `MCP_TIMEOUT_SECONDS=3`,
`AGENT_EXTERNAL_CALL_BUDGET_SECONDS=16`,
`AGENT_COMMIT_NETWORK_RESERVE_SECONDS=3`이다. `MAFIA_MCP_URL`은 개발에서
`http://127.0.0.1:8100/mcp`처럼 `/mcp`를 포함하며 client가 suffix를 붙이지 않는다.
평문은 loopback 개발만, 생산은 `MCP_REQUIRE_TLS=true`와 검증된 CA/hostname을
fail-closed로 강제한다.

### 2.2 브랜치·merge 규칙

- 작업 브랜치: `feat/backend-<기능>` — coding AI agent 한 세션은 WU 1개 이하.
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
   완료 기준, 검증 명령(3.1), **한국어 주석**, 고위험 항목의 거부 경로
   테스트 동시 작성.
4. agent 산출물 diff를 사람이 전수 검토한다. 특히: 응답에 역할·seed 누설
   여부, 로그에 prompt·비밀정보 기록 여부, migration이 001을 건드리는지,
   기존 identity 테스트 무손상 여부.
5. 무의미한(항상 통과) 테스트 금지. 공통 오류 13종의 401/403/404/409/422/503
   거부 경로와 response code를 실제로 확인한다.
6. WU 완료 → 검증 → 사람 검토 → (승인 시) 커밋 → 다음 WU. 건너뛰기 금지.

### 3.1 WU 공통 검증 명령

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
- **내용:** 상위 계약의 `mystery-v1` 순수 함수형 구현.
  - 6/7명=`1 MAFIA + 1 DETECTIVE + 1 DOCTOR + 나머지 CITIZEN`,
    8/9명=`2 MAFIA + 1 DETECTIVE + 1 DOCTOR + 나머지 CITIZEN` 역할표와
    seed 기반 결정적 배정. 진영은 role에서 내부 파생하며 `faction` 저장·응답·
    event와 마피아 팀원 공유를 만들지 않는다.
  - 정확한 Phase 12종과 round 계약:
    `ROLE_REVEAL → DAY_ANNOUNCEMENT(round=0) → DAY_DISCUSSION(round=0,no vote)
    → NIGHT_ACTION(round=1)`, 이후 최대 5밤, 필요 시
    `FINAL_DISCUSSION → FINAL_VOTE → FINAL_RESOLUTION`.
  - 생존 좌석순 PRIMARY 1순환, `SPEAK` 1~200자 또는 `PASS`; 전원 PASS일 때만
    고정 질문과 FOLLOWUP 1순환. AI GM 고정 시작·최종 안내문은 PUBLIC event이며
    GM이 phase·순환·승패를 결정하지 않는다.
  - 밤 자격은 시작 시 고정하고 보호·공격·조사를 동시 해소한다. blind-mafia
    개별 제안의 동일/상이/한 명/전원 미응답 규칙, 탐정·의사 자동 대상에서
    자기 제외, 의사 직접 자기·연속 보호 허용, 보호 성공 비공개를 구현한다.
  - 일반 투표 동률→동률자 대상 재투표 정확히 1회→재동률 무처형. 진행 중
    ballot·자동 여부는 SYSTEM, 해소 후 PUBLIC은 aggregate만. 밤 사망 role은 숨기고
    낮 처형 role만 공개한다.
  - 표준 승패와 5번째 밤 뒤 최종 다수/결정적 동률 판정을 구현한다.
- **완료 기준:** 6~9명 전 구성·첫날 무투표·하이브리드 토론·밤 동시성·
  일반/재/최종 투표·표준/급사 승패의 seed 재현 테스트, `NIGHT_RESOLVED`가
  round별 한 번만 생성되는 테스트, PUBLIC/PRIVATE/SYSTEM 카나리 통과.
  외부 의존성 import 0.

### WU-B2. `scenario-v1` 엔진 (DB 없음)

- **범위 파일:** `models/scenario.py`, `tests/test_game_scenarios.py`
- **내용:** 불변 catalog ID/title을 다음 5종으로 고정한다:
  `broadcast-blackout`, `snow-lodge`, `museum-closing`, `hotel-banquet`,
  `night-train-stop`. 공개 필드는
  `scenario_id/scenario_version/title/background/victim/locations/objective`이며
  objective는 "현장에 있던 플레이어 중 마피아를 찾아내세요."다.
- 초기 기획의 예시만 복사해 완료 처리하지 않는다. 5종×최대 9좌석의
  알리바이 1+관찰 1, **최소 90개 정적 template record**를 작성하고 제품 리뷰를
  받는다. 관찰은 `text/target_seat/anonymous` 구조이며 target은 현재 인원의
  관찰자 외 유효 좌석이거나 명시적 anonymous다. 역할중립·blind-mafia·상호
  무모순·6/7/8/9명 완전 배정을 정적 검증한다.
- selector는 seed/version/player_count와 **해당 사용자가 직전에 성공적으로
  생성(트랜잭션 commit)한 게임 1건**의 `scenario_id`를 입력으로 받고 런타임
  LLM 없이 결정적 배정한다. 최초 게임은 5종 전체, 이후에는 직전 1종을 제외하며
  생성 실패·rollback은 직전 기록을 바꾸지 않는다. owner advisory lock용 key는
  소문자 canonical UUID에 `team4:scenario-owner:v1:` namespace를 붙인 SHA-256의
  앞 8바이트를 big-endian signed 64-bit로 해석한다. 이 순수 함수만 WU-B2에서
  구현하고 DB lock은 WU-B3가 담당한다.
- **완료 기준:** 같은 입력 재현, 5종×4개 인원 완전 배정, 다른 game/role 비간섭,
  관찰 target/anonymous·모순 검증, lock-key 고정 벡터 통과와 전체 문구 제품 승인.
  콘텐츠 승인이 없으면 **CP-B1 완료 금지**.

### WU-B3. DB 계약·영속화 (인프라 실행 제외)

- **선행:** CP-M1A 기반 환경 완료. Backend는 인프라를 직접 구축하지 않는다.
- **범위 파일:** `migrations/002_create_mafia_game_schema.sql`,
  `repositories/game_repository.py`, `repositories/feedback_repository.py`,
  기존 `core/config.py`, `infrastructure/migrations.py`,
  `tests/test_config.py`, `tests/test_migrations.py`,
  `tests/test_game_repository.py`, `tests/test_game_receipts.py`,
  `tests/test_snapshot_replay.py`, `tests/test_audit_outbox.py`
- **schema:** 상위 계약 3장의 `game_sessions`(고정 rules/scenario CHECK,
  `creation_order`, deadline·pause·scheduler lease), `game_players`(role만 저장,
  faction 열 금지, 구조화 private profile), append-only `game_events`,
  `game_snapshots`, `game_command_receipts`, `agent_personas`, `agent_runs`,
  feedback·role·audit log/outbox를 002 하나의 순방향 migration으로 만든다.
  001은 수정하지 않고 기존 trigger/재실행 컨벤션을 지킨다.
- **시나리오 생성 원자성:** 인증된 owner canonical UUID의 stable 64-bit key로
  `READ COMMITTED` transaction의 첫 DB statement에서
  `pg_advisory_xact_lock`을 얻는다. 그 뒤 `creation_order DESC`로 **해당 사용자가
  직전에 성공적으로 생성(트랜잭션 commit)한 게임 1건** 조회→scenario 선택→
  game/player/event/snapshot insert를 같은 transaction에서
  commit한다. identity sequence는 lock 뒤 발급하며 rollback gap은 허용한다.
  hash 충돌은 다른 owner를 추가 직렬화할 뿐 조회는 정확한 UUID로 격리한다.
- **복구·멱등:** snapshot은 checksum·schema·ruleset/scenario·연속 sequence를
  검증하고 손상본을 절대 사용하지 않는다. 이전 유효본+후속 event, 없으면 genesis
  replay다. command/resume/Engine proposal receipt는 canonical request hash와
  민감정보 없는 outcome/event id를 같은 transaction에 저장한다. 재시도 View는
  저장 body가 아니라 현재 audience projector로 다시 만든다.
- **감사:** `audit_logs`에는 `(source_instance_id,audit_id)` partial unique와
  canonical `payload_hash` 비교를, `audit_outbox`에는
  `(source,source_instance_id,audit_id)` unique를 구현한다. 같은 감사 ID의 다른
  payload는 별도 row가 아니라 409다. 감사 저장 실패는 이미 commit된 행동을 되돌리지 않고
  같은 game transaction의 outbox/SYSTEM retry marker로 보존한다.
- **env 분리:** migration CLI/process만 `DATABASE_MIGRATION_URL`(+필요한
  `DATABASE_NAME`)을 필수 소비하고 누락·placeholder를 fail-closed한다. Backend
  runtime Settings·connection은 `DATABASE_URL`만 사용하며 migration URL을 보유·
  로그하지 않는다.
- **완료 기준:** fake repository에서 version conflict, append-only, snapshot 손상→
  이전 본→genesis, 영구 receipt/Redis flush 후 중복 방지, 사망 전 receipt를 사망 후
  replay해도 PUBLIC-only, advisory key·첫 게임·같은 owner 동시 요청·강제 hash
  충돌·transaction 시작/commit 순서·rollback sequence 공백을 검증한다. migration
  파일·revision·예상 결과를 MCP WU-M1B에 전달하고, 실제 최초/재실행·runtime DDL
  거부·동시 transaction 검증은 CP-M1B 뒤 CP-B2 smoke에서 완료한다.

### WU-B4. Redis 애플리케이션 연동 (서버 실행 제외)

- **범위 파일:** `infrastructure/redis/client.py`, `locks.py`,
  `tests/test_redis_locks.py`
- **내용:** 상위 계약 3.3의 game lock(소유 token만 해제·heartbeat), runtime
  cache, event stream, PostgreSQL deadline의 sorted-set 가속 index, 영구 DB receipt의
  24시간 idempotency 조회 cache, agent reservation/status를 구현한다. scenario 생성은
  Redis TTL lock을 쓰지 않고 WU-B3의 PostgreSQL transaction advisory lock만 쓴다.
- Redis 손실·flush 시 PostgreSQL snapshot/event/receipt/`next_wakeup_at`에서
  복구한다. DB commit 전에 cache·stream을 갱신하지 않는다. Redis 설치·기동·health는
  MCP 섹터 책임이고 Backend는 `REDIS_URL`과 application 의미만 소유한다.
- **완료 기준:** lock 경합·비소유 해제·TTL/heartbeat, Redis 손실 뒤 DB 재구성,
  receipt cache miss에도 중복 event 없음, deadline index 재등록 테스트 통과.
  CP-M1B 뒤 runtime DML·Redis smoke를 완료해야 CP-B2가 닫힌다.

### WU-B5. 사용자 게임 API

- **범위 파일:** `routers/game_router.py`, `routers/feedback_router.py`,
  `schemas/game_schema.py`, `services/game_service.py`,
  `infrastructure/security/game_request.py`, 기존 `app/main.py`,
  `tests/test_game_api.py`
- **내용:** 상위 계약 2장의 생성·저장 목록·명시적 resume·GameStateView·commands·
  SSE/증분 polling·FINISHED result·feedback를 그대로 구현한다. 게임 API canonical
  `timestamp.request_id.acting_user_id.raw_body`, 13개 공통 오류 code, 활성 사용자·
  소유권·expected version·영구 idempotency receipt를 적용한다.
- 공개 scenario serializer는 7필드와 구조화 observation을 고정한다. 진행 중에는
  night-kill role·개별/중간 ballot·타인의 role/alibi/observation/private event·seed를
  숨긴다. 낮 처형 role과 vote aggregate만 PUBLIC이다. FINISHED result에서만 전체
  role·private profile·밤 행동·ballot·정제된 판단 요약을 공개한다.
- 인간이 사망하면 종료 전 `you`는 identity/seat/alive만, private events는 빈 배열,
  submission은 null, command는 `SAVE_AND_EXIT|FAST_FORWARD`만 반환한다. 사망 전
  receipt 재전송도 현재 projector를 거쳐 PUBLIC-only다. AI 사망 처리는 WU-B7/B8과
  연결한다.
- resume는 남은 deadline을 새 서버 시각으로 재발급하고 이전 reservation/session/
  capability를 폐기한다. MCP instance bootstrap은 anchor가 없거나 만료될 때만 한다.
- **완료 기준:** 13종 오류 거부 경로, 타인·GM·관전자 격리, scenario objective·
  structured observation, 밤 role/ballot 숨김, receipt 재시도·현재 audience,
  SSE→poll 복구, resume/FAST_FORWARD 테스트. 기존 identity 테스트 무손상.

### WU-B6. 서버 권위 timer·background lifecycle

- **범위 파일:** `services/game_timer_service.py`, `services/game_service.py`,
  기존 `app/main.py`, `tests/test_game_timers.py`
- **내용:** `NIGHT_ACTION=20초`, `DAY_VOTE/DAY_REVOTE/FINAL_VOTE=각 30초`의
  UTC deadline을 Backend만 발급·판정한다. 미제출은 규칙 엔진의 seed 기반 유효
  대상 자동 선택이고, 토론 AI 실패는 PASS다. Front/MCP clock은 판정 권한이 없다.
- API lifespan startup에서 PostgreSQL `next_wakeup_at`을 sweep해 Redis 가속
  index를 재구성한다. 실행 중 due row는 조건부 UPDATE/RETURNING으로 짧은
  `worker_claim_id/until` lease를 잡고, 다중 API worker는 game version CAS와
  round별 `NIGHT_RESOLVED` 멱등 marker로 정확히 한 번만 해소한다. lease owner
  장애·Redis 손실은 DB 원본에서 회수한다.
- `PAUSED`는 wakeup·claim을 비우고 남은 ms를 저장하며 resume는 새 deadline과
  wakeup을 등록한다. startup 시 이미 지난 deadline은 즉시 해소한다. deadline 없는
  discussion도 현재 speaker가 AI면 `next_wakeup_at=now()`로 등록해 client/SSE가
  없어도 진행하고, 인간 speaker면 입력을 기다린다.
- **완료 기준:** 실제 sleep 없는 fake clock으로 정확한 전/후 경계, 제출-vs-timeout
  race, 재투표/최종투표, pause/resume, restart overdue, 두 worker claim/lease 탈취,
  Redis flush, 무접속 AI 토론, 중복 resolution 없음 테스트 통과.

### WU-B7. 내부 Engine API·capability·transport auth

- **범위 파일:** `routers/engine_internal_router.py`, `mcp/capability.py`,
  `mcp/transport_auth.py`, `agent/context.py`, 기존 `app/main.py`,
  `tests/test_engine_internal_api.py`, `tests/test_mcp_transport_auth.py`,
  `tests/test_audit_outbox.py`
- **endpoint:** `/internal/v1/engine/bootstrap|context|actions|audit`를 상위 계약
  5장 그대로 구현한다. 요청은 Front와 다른 `ENGINE_INTERNAL_API_SECRET` HMAC·
  timestamp·request-id replay 방지, 응답도
  `response_timestamp.request_id.status_code.raw_body` HMAC이다.
- bootstrap은 `mystery-v1/scenario-v1/mcp-transport-v1/audit-v1`, instance,
  client time을 검증하고 `server_time`, 30초 skew를 반환한다. Backend가
  `MCP_SERVER_AUTH_SECRET`으로 발급하는 transport token은
  `audience+instance+session+game+subject_kind+subject_id+expiry`를 묶고,
  평문은 loopback만 허용한다. 생산은 TLS·CA·hostname
  검증 실패 시 fallback 없이 거부한다.
- session subject는 `PLAYER(agent_player_id)` 또는 `GM(gm_run_id)`다. capability는
  `game_id+subject_kind+subject_id+phase+state_version+reservation_id+expiry`에
  귀속해 turn마다 갱신하고
  phase/version/run 종료·취소 시 즉시 폐기한다. AI 사망 commit 시 reservation,
  capability, transport session을 즉시 폐기한다. GM은 rules·현재 scenario·
  public-state·public-timeline만, Tool은 0개다.
- `/context`는 8종 Resource field partition과 모든 응답의 인증된 `server_time`,
  timed-phase `deadline_at`을 같은 allowlist projector로 만든다. `agents/me`는
  identity만, `private-state`는 자기 role/profile/event/receipt만이다. raw snapshot,
  다른 actor PRIVATE, SYSTEM, faction/팀원 정보는 절대 응답하지 않는다.
  Resource key는 `rules | scenario | public-state | public-timeline | me |
  private-state | allowed-actions | persona`이며 scenario는 현재 game의 7개 공개
  필드와 일치하는 ID만, persona는 현재 PLAYER subject의 표현 필드만 허용한다.
  `additionalProperties=false`를 중첩까지 적용하고 GM은 첫 4개 공개 key만 성공한다.
  `server_time`은 응답 생성 시각이며 MCP가 수신 monotonic 시각의 보수적 lower-bound
  anchor로 사용한다. RTT/2를 임의 가산하지 않는다. MCP가 최대 허용 RTT 오차로
  늦은 요청을 통과시켜도 Backend의 현재 UTC deadline 검증이 최종 거부한다.
- `/actions`는 actor 입력을 거부하고 capability와 무관하게 phase/version/
  reservation/deadline/생존/role/target/중복을 재검증한다. `proposal_id`는 WU-B3
  receipt로 영속 멱등 처리하고 vote는 해소 전 SYSTEM이다.
- `/audit`은 `audit-v1`의 `(instance_id,audit_id)`, 최대 100 records와 승인된
  `request_id/trace_id/event_id/game_id/actor_player_id_hash/session_id_hash/operation/
  resource_or_tool/allowed/reason_code/occurred_at` 필드만 받는다. payload hash가
  같은 재전송은 duplicate, 다른 payload는 409다.
  record는 최대 4 KiB이고 `additionalProperties=false`; raw actor/session ID,
  token, prompt/response, role/profile, action arguments는 거부한다. 응답은
  `accepted_ids/duplicate_ids/rejected[{audit_id,code}]`만 반환한다.
  Backend audit 저장 장애는 action commit을 바꾸지 않고 outbox/SYSTEM으로 재시도한다.
- **완료 기준:** 13개 오류 schema, 요청·응답 HMAC, Front secret/무인증/평문 원격,
  PLAYER↔GM·타 game/subject·stale/expired capability·죽은 AI·actor 위조 거부,
  Resource 8종 exact field, vote/role/secret 비누설, audit 멱등·outbox 테스트 통과.
- **주의:** 완료 후 CP-B4로 merge하고 MCP WU-M7 실 Engine 연동의 입력으로 전달한다.

### WU-B8. Agent Manager + LLM/MCP clients

- **범위 파일:** `agent/manager.py`, `agent/context.py`, `agent/prompts.py`,
  `llm/providers.py`, 기존 `mcp/client.py`, `tests/test_agent_manager.py`,
  `tests/test_context_isolation.py`
- **호출 구조:** fake LLM/MCP로 먼저 완성한 뒤 OpenAI·Gemini adapter를 연결한다.
  `MAFIA_MCP_URL`은 `/mcp` 포함 full endpoint이고 suffix를 다시 붙이지 않는다.
  공통 안전 제약+persona 표현의 2계층 prompt를 사용하되 모든 persona의 model,
  추론 설정, 컨텍스트·Tool 권한, timeout/token 상한은 동일하다.
- game lock 안에서는 phase/version/subject를 검증하고 reservation event와 CAS만
  commit한다. lock을 놓은 뒤 `/context → LLM → MCP /actions`를 호출하고 다시
  lock을 얻어 reservation/phase/version/deadline/alive를 CAS 검증한다. 외부 호출
  중 lock 보유 금지, 늦은 결과는 폐기한다. 같은 phase의 AI는 짧은 reservation
  구간 뒤 provider 한도 내 병렬 실행하며 `N × timeout`을 만들지 않는다.
- **절대 deadline 예산:** 기본 `context 3초 + LLM ≤11초 + actions 3초 +
  commit reserve 3초 ≤ 20초` 구조다. 실제 각 timeout은 호출 직전 남은 phase와
  `AGENT_EXTERNAL_CALL_BUDGET_SECONDS=16`에서 후속 `/actions` 3초와 commit 3초를
  먼저 빼 clamp한다. 두 번째 provider·교정 1회도 같은 계산을 통과할 때만 호출하고,
  부족하면 기다리지 않고 fallback한다. 기본 LLM 15초는 단일 상한일 뿐이다.
- MCP 조회 실패 시 checksum·schema·ruleset/scenario·연속 sequence가 검증된
  snapshot+event로 현재 state를 복구한 뒤 **정상 `/context`와 동일 projector**로
  agent는 PUBLIC+현재 actor PRIVATE, GM은 PUBLIC만 재투영한다. raw snapshot,
  다른 actor PRIVATE, SYSTEM을 prompt로 넘기지 않는다. 검증된 최소 context가
  없으면 외부 호출 없이 결정적 fallback한다.
- 양 LLM provider 장애·invalid output이면 토론 `PASS`, 밤/투표 seed 기반 유효
  target으로 계속 진행하고 자동 pause하지 않는다. 교정은 예산이 있을 때 최대 1회다.
  AI GM은 고정문구 fallback, PUBLIC 중립 요약만 수행하고 유죄 단정·catalog 밖
  사건 사실을 만들거나 phase를 바꾸지 않는다. 짧은 판단 요약만 저장하고 prompt,
  response, chain-of-thought는 저장·로그하지 않는다.
- **완료 기준:** fake clock으로 context 3초 뒤 LLM clamp/취소, 20초 내 fallback
  commit, 늦은 CAS 거부, 4개 밤/최대 8개 투표 AI 병렬성, 두 provider 장애,
  교정 생략을 검증한다. raw snapshot과 타인 PRIVATE/SYSTEM canary가 정상·fallback
  prompt/결정/감사 요약에 영향 없는 비간섭성, GM 중립성, restart pending 토론,
  AI 사망 session/capability 폐기 테스트를 통과한다. 자동 회귀의 실제 LLM 호출은
  0회이며 비용 승인 후 수동 1회만 별도 기록한다.

### WU-B9. 관리자 API·밸런스 지표

- **범위 파일:** `routers/admin_router.py`, `schemas/admin_schema.py`,
  `services/admin_service.py`, `repositories/admin_repository.py`,
  `tests/test_admin_api.py`
- **내용:** 2.8 명세의 `user_roles` ADMIN 검증(fail-closed), feedback 상태 변경,
  audit/outbox 지연과 KPI를 구현한다. KPI는 6~9명·scenario별 진영 승률,
  평균 완료 밤/시간, 보호 성공, 탐정 생존·조사 영향, mafia-on-mafia 공격·투표,
  인간 첫날 밤 사망, timeout 자동 선택, LLM 성공/timeout/fallback/token·비용이다.
  prompt·role 목록·private profile·seed·token·secret은 로그/응답에서 제거한다.
- **완료 기준:** 비관리자·비활성 403, 최소 필드 allowlist, 민감 카나리 부재,
  집계 분모/기간/인원·scenario 경계, 피드백 상태 변경 테스트 통과. 6~9명별
  최소 100회(가능하면 1,000회) offline simulation에서 각 진영 45~55% 목표,
  40~60% 허용, 어느 한 진영 >60%면 조정 gate로 보고한다.

---

## 5. 중간 merge·테스트 체크포인트

| 체크포인트 | 포함 WU | merge 전 필수 검증 | 후속 의존 |
|---|---|---|---|
| **CP-B0 계약 확인** | (코드 없음) | `mystery-v1`·`scenario-v1`과 상위 2·3·5·6장 리뷰 합의 | 3인 합의 |
| **CP-B1 규칙·시나리오** | B1, B2 | focused+전체 회귀, 90+ template 제품 승인, 6~9명 fake 완주 | — |
| **CP-B2 영속화** | B3, B4 + CP-M1B | migration 최초/재실행, runtime DML·DDL 경계, DB/Redis/snapshot/receipt smoke | CP-M1A→B3→CP-M1B 뒤 완료 |
| **CP-B3 사용자 API·timer** | B5, B6 | 13종 오류, PUBLIC-only 관전, resume, 20/30초·restart 전체 회귀 | **CP-M1B와 함께 Front CP-F3 선행** |
| **CP-B4 내부 Engine API** | B7 | HMAC/TLS/capability/audit/Resource 8종 거부 경로 | **MCP CP-M7 선행** |
| **CP-B5 Agent·관리자** | B8, B9 | deadline 예산·snapshot 격리·fake LLM 완주·관리자 403 | MCP CP-M8과 CP-ALL |

```text
CP-M1A → WU-B3 산출물 → CP-M1B → CP-B2
CP-B3 + CP-M1B → Front CP-F3
CP-B4 → MCP CP-M7
CP-B5 + MCP CP-M8 → CP-ALL
```

### 중간 테스트 규칙

- WU마다 focused, CP merge 직전 전체 회귀.
- Backend 담당자는 PostgreSQL·Redis 프로세스를 직접 설치·기동·중지하지 않는다.
  CP-M1A가 기반을 준비한 뒤 WU-B3 migration을 전달하고, MCP 담당자가 CP-M1B에서
  `DATABASE_MIGRATION_URL`로 최초·재실행한다. 그 뒤 Backend가 `DATABASE_URL`로
  persistence/lock smoke와 runtime DDL 거부를 공동 판정해야 CP-B2가 완료된다.
- CP-B3·CP-B4 merge 후 `develop`에서 서버 기동 스모크
  (`uvicorn` 기동 → `/health` 200 → 게임 생성·resume·deadline 1회)를 실행한다.
  CP-B3+CP-M1B 뒤 Front CP-F3, CP-B4 뒤 MCP CP-M7, CP-B5+CP-M8 뒤 CP-ALL이다.
  MCP M2~M6은 fake Engine으로 독립 진행할 수 있다.
- 계약과 다른 동작을 발견하면 코드를 계약에 맞추는 것이 기본이다. 계약
  자체를 바꿔야 하면 구현 계획서 9장 절차(문서 먼저)로 진행한다.

---

## 6. 고위험 항목 (AGENTS.MD 테스트 규칙 직접 적용)

다음은 전부 인증·권한·보안·동시성 고위험으로 분류한다. **구현과 동시에
실패·거부 경로 테스트를 작성**하고 CP merge 전 전체 회귀를 실행한다.

- 게임 소유권(타인 게임 404 동일 응답), `acting_user_id` 검증
- GameStateView·`/context`·snapshot fallback의 동일 projector(타인 role/profile,
  SYSTEM, ballot, seed 누설 금지), 인간 사망 후 receipt replay PUBLIC-only
- PostgreSQL owner advisory lock·`creation_order`·rollback·동시 생성,
  migration/runtime DB role·env 분리와 runtime DDL 거부
- 손상 snapshot 배제·이전 검증본/genesis replay·event sequence 공백 거부
- capability subject/phase/version/reservation 위조·만료·AI 사망 폐기,
  actor 필드 위조 422, Engine 요청·응답 HMAC·transport TLS fail-closed
- optimistic version(409), 영구 receipt, Redis lock 소유권·손실 복구
- 20/30초 deadline과 다중 worker DB lease/CAS, 외부 호출 중 lock 미보유,
  `/context→LLM→/actions→CAS` 후속 reserve·늦은 결과 거부
- audit-v1 승인 필드·payload hash·outbox 재시도; audit 실패가 이미 commit된
  game action을 rollback/재제출하지 않음
- 관리자 fail-closed
- 로그·오류 메시지에 prompt·response·seed·역할·private profile·token·비밀정보 미포함

## 7. 완료 보고 양식 (WU·CP 공통)

```text
[WU-B5 완료]
- 변경 파일: (목록)
- 실행 검증: uv run pytest backend/tests → NN passed / ruff OK / compileall OK
- 거부 경로 테스트: (공통 13종의 401/403/404/409/422/503 항목 나열)
- 생략 검증과 이유: 기반 DB·Redis는 MCP CP-M1A, migration 실행은 CP-M1B에서
  MCP 담당자가 수행 예정
- 범위 밖 변경: 없음
- 계약 이슈: (있으면 구현 계획서 장·절 지목)
- README 갱신 필요 여부: (실행 방법·env 변경 유무)
```
