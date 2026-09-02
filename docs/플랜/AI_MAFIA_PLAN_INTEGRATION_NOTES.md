# AI 마피아 기획 문서 통합·수정 내역

**작성일:** 2026년 9월 1일
**최근 개정:** 2026년 9월 2일 — `mystery-v1`·`scenario-v1` 승인 반영
**통합 결과:** [AI_MAFIA_MVP_FINAL_PLAN.md](AI_MAFIA_MVP_FINAL_PLAN.md)
**최초 통합 원본 3개:**

1. `docs/초기기획안/mafia_game_plan.md` — 추리게임 기획안 (제품 기획 관점)
2. `docs/플랜/AI_MAFIA_MVP_PLAN.md` — MVP 구현 설계 초안 (기술 설계 관점)
3. `docs/규칙/ai_mafia_game_engine분리규칙.md` — 엔진/Agent/MCP 분리 규칙 (보안 경계 관점)

**2026-09-02 추가 제품 정본 2개:**

1. `docs/초기기획안/mafia_game_rules.md` — `mystery-v1` 게임 규칙
2. `docs/초기기획안/mafia_game_scenarios.md` — `scenario-v1` 시나리오 계약

이 문서는 세 문서를 현재 저장소 구조 기준으로 검증하면서 발견한 불일치,
결정한 통합 방향, 최종 플랜에 반영한 수정 사항을 기록한다.

1~5장은 최초 통합 당시의 역사적 결정 기록이다. 그 안의 `5~9명`, `POLICE`,
`FACTION`, `basic-v1`, `mcp_1`과 과거 WU·CP 번호는 현재 구현 기준이 아니다.
2026년 9월 2일 승인된 게임 규칙과 기술 계약은 6장 및 현재 공통·섹터별 상세
계획이 우선한다.

## 1. 현재 저장소 구조 대비 검증 결과

### 1.1 문서와 실제 구조가 일치하는 항목

- `frontend_user`(app.py, app_pages/, core/api_client.py),
  `frontend_admin`(app.py, app_pages/, core/), `backend/app`의
  routers/schemas/services/models/repositories/agent/llm/mcp/
  infrastructure(redis, security)/core 경계는 문서 설계와 실제 구조가 일치.
- `backend/migrations/` 소유권과 실행기
  (`backend.app.infrastructure.migrations`) 일치.
- Google OIDC 로그인, HMAC 내부 서명, identity provision API는 구현 완료
  상태로 세 문서의 전제와 일치.

### 1.2 문서와 실제 구조가 불일치한 항목 (최종 플랜에서 교정)

| 항목 | 문서 내용 | 실제 구조 | 최종 플랜 반영 |
|---|---|---|---|
| MCP 패키지 이름 | MVP_PLAN·README는 `mcp_server/tour`, `mcp_server/weather` 언급 | 실제는 `mcp_server/mcp_1`, `mcp_server/mcp_2` (범용 예약 이름으로 개편됨) | 게임 컨텍스트 MCP를 `mcp_1`에 배치, `mcp_2`는 후속 예약으로 명시 |
| MCP README 내용 | — | `mcp_1`/`mcp_2` README에 Tour·Weather 설명이 잔존 | 과거 예약 명칭임을 최종 플랜에 주석, 구현 시 README 갱신 예정 |
| 미추적 잔여 디렉터리 | — | `backend/app/api`, `backend/app/auth`, `backend/app/db`, `mcp_server/src`가 빈 디렉터리/캐시로 잔존 (git 미추적, 구조 개편 이전 잔재) | 구조 변경 없이 현황만 기록. 정리는 별도 승인 필요 |
| LLM 공급자 | 문서에 미확정 | `.env`에 OpenAI·Gemini·Ollama 키 항목이 이미 존재 | OpenAI·Gemini 이중 지원으로 확정 (사용자 결정) |

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
  **접속 종료 처리**(PAUSED 저장 후 동일 좌석 복귀, AI 자동 교체 금지),
  **경찰 결과는 진영만 반환**(정확한 역할명 비공개), **비공개 투표**,
  **처형자 역할 공개** 규칙을 최종 플랜 4·6·12장에 편입.

## 2. 최종 플랜에서 새로 확정한 사항

1. 역할표를 5~9명 기준으로 확정 (7명 이상 마피아 2명, 주범·공범 구분 없음).
2. 상태 전이에 `DAY_REVOTE`(동점자 재투표 1회) 단계 추가.
3. LLM 공급자를 OpenAI + Google Gemini 이중 지원으로 확정하고
   `LLM_PROVIDER` 환경 변수로 선택.
4. 게임 MCP 배치 위치를 `mcp_server/mcp_1`로 확정.
5. 구현 단계 0단계(계약 고정)의 미결 항목 중 규칙·명칭·공급자·MCP 위치를
   확정 처리하고, 인증 방식·비용 상한만 남은 결정으로 이월.

## 3. 함께 변경한 프로젝트 파일

### 3.1 패키지 목록

- `pyproject.toml`: MVP 구현에 필요한 런타임 의존성 추가
  — `redis`(lock/cache/stream), `openai`, `google-genai`(LLM 이중 공급자),
  `mcp`(MCP 서버/클라이언트 SDK), `httpx`(LLM·MCP 비동기 HTTP,
  FastAPI TestClient 의존성이기도 함), `sse-starlette`(SSE 이벤트 구독).
  dev 그룹에 `pytest-asyncio`(비동기 엔진·agent 테스트) 추가.
- `backend/requirements.txt`: 동일 런타임 의존성 반영 (독립 실행 단위 기준).

설치: `uv sync --dev`

### 3.2 `.env.example`

기존 DB·HMAC 항목을 유지하고 다음 예약 항목을 placeholder로 추가했다.
실제 키 값은 `.env`에만 보관한다.

- `REDIS_URL`: 게임 lock/cache/stream용 Redis 연결
- `LLM_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
  `GEMINI_API_KEY`, `GEMINI_MODEL`: LLM 이중 공급자 설정
- `LLM_TIMEOUT_SECONDS`, `GAME_MAX_TOKENS_PER_RUN`: agent run 제한
- `MAFIA_MCP_URL`: 게임 컨텍스트 MCP(`mcp_server/mcp_1`) 주소

### 3.3 문서

- `docs/플랜/AI_MAFIA_MVP_FINAL_PLAN.md` 신규 작성 (구현 기준 문서).
- 원본 3개 문서 서두에 최종 플랜으로 대체되었음을 알리는 안내 추가.
- 루트 `README.md`의 문서 링크·프로젝트 구조 표기를 실제 구조
  (`mcp_server/mcp_1`, `mcp_2`)와 최종 플랜 기준으로 갱신.

## 4. 검증

- 문서 통합은 실행 동작 변경이 없으므로 자동 테스트 대상이 아니며, 세 원본
  문서와 최종 플랜의 규칙 표·상태 머신·URI·Tool 명세를 상호 대조해 확인했다.
- 패키지·환경변수 변경은 `uv sync --dev` 성공과 `uv run pytest`,
  `uv run ruff check .`, compileall 통과로 검증했다 (결과는 완료 보고 참조).

## 5. 2026-09-02 섹터 역할 변경

사용자 요청에 따라 PostgreSQL·Redis의 설치, 인스턴스·DB 생성, 기동, 중지,
접속 계정·권한 준비, Backend migration 실행과 health 확인 책임을 Backend
섹터에서 MCP 섹터로 이동했다.

- Backend는 DB schema·migration SQL·repository와 Redis client·key·TTL·lock
  의미 등 application code·data contract를 계속 소유한다.
- MCP 담당자는 Backend가 제공한 migration과 Redis 계약을 수정하지 않고 실제
  환경에서 실행·재실행·health를 확인한다.
- Backend runtime은 PostgreSQL·Redis에 직접 연결한다. MCP 서버 runtime은
  데이터 프록시가 아니며 DB·Redis에 직접 접근하지 않는다.
- 당시 MCP 지침서는 Data Infrastructure WU-M1을 추가해 WU-M1~M6,
  CP-M0~M5로 재편했다. 이번 최종 개정에서는 순환 의존 제거와 한 세션 1 WU를
  위해 WU-M1A·M1B·M2~M8, CP-M0·M1A·M1B·M2~M8로 다시 세분했다.
- 실제 접속 URL·비밀번호는 `.env`와 승인된 비밀 전달 채널에만 두며 문서·로그·
  완료 보고에는 서비스 상태와 적용 migration 파일명만 기록한다.

## 6. 2026-09-02 최종 규칙·시나리오 반영

사용자가 `docs/초기기획안/mafia_game_rules.md`와
`docs/초기기획안/mafia_game_scenarios.md`를 게임 규칙 정본으로 승인했다. 이
결정은 1.3의 인원·역할명·첫날·시나리오·마피아 협력 결정을 다음과 같이 대체한다.

| 항목 | 이전 `basic-v1` 계획 | 승인된 계약 |
|---|---|---|
| 규칙·시나리오 버전 | `basic-v1`, 시나리오 제외 | `mystery-v1` + `scenario-v1` |
| 전체 인원 | 5~9명 | **6~9명** |
| 역할표 | 7명부터 마피아 2명 | 6·7명 1명, 8·9명 2명 |
| 조사 역할 | 경찰 / `POLICE` | 탐정 / `DETECTIVE` |
| 마피아 정보 | 서로 인지, `FACTION` 공유 | 서로 비인지, 팀원·`FACTION` 공유 없음 |
| 첫 진행 | 역할 공개 후 밤 | 첫날 낮 1순환, 무투표 후 밤 |
| 토론 | 버튼형 턴제 일반 원칙 | 좌석순 1순환·200자, 전원 PASS 시 고정 질문 후 추가 1순환 |
| 시간 제한 | 구체 계약 없음 | 밤 20초, 일반·재·최종 투표 30초의 서버 deadline |
| 최대 길이 | 상한 없음 | 최대 5밤, 이후 `FINAL_ACCUSATION` 급사 |
| 공개 | 비공개 투표 집계 | 집계만 공개, 밤 사망 역할 비공개·처형 역할 공개 |
| 진행자 | 중재 에이전트 | UI 명칭 AI GM, 공개 확정 이벤트만 접근 |
| AI 차이 | 추론 능력도 persona별 차등 | 추론 능력·정보권한 동일, 표현 성향만 차등 |

`FINAL_ACCUSATION`은 일반 시민 승리 조건의 명시적 예외다. 다섯째 밤 공개 후
표준 승패가 나지 않았을 때 최종 최고 득표 후보가 마피아이면 남은 마피아 수와
관계없이 시민이, 비마피아이면 마피아가 승리한다. 최종 동률은 저장된 seed로
결정한다. 이는 별도 Phase가 아니라 `FINAL_DISCUSSION`, `FINAL_VOTE`,
`FINAL_RESOLUTION` 세 Phase의 합성 규칙명이다.

시나리오는 LLM이 즉석에서 사건 사실을 생성하지 않는다. 검증된 정적 카탈로그를
seed로 배정하고 소유 사용자별 직전 성공 commit 게임의 시나리오만 제외한다. 공개
배경과 개인별 알리바이·관찰 정보를 분리하고 선택 당시 snapshot을 저장한다.

### 6.1 타당성 검토에 따른 기술 계약 교정

- deadline·자동 선택·재접속 결과를 PostgreSQL 이벤트와 snapshot에 고정하고
  제출/timeout 경합은 game lock과 `state_version` CAS로 한 번만 확정한다.
- 시나리오 반복 제외 기준은 사용자별 직전 **성공 commit 게임** 1건이며, 생성
  실패·rollback은 직전 기록을 바꾸지 않는다. 같은 사용자 동시 생성은 PostgreSQL
  transaction-scoped advisory lock 안에서 조회·선택·insert를 함께 commit한다.
- 시나리오 문서의 개인 정보 문장은 방향 예시이므로 WU-B2에서 5종×최대 9좌석의
  알리바이·관찰 최소 90개 template record를 작성하고 역할 중립성·무모순을 제품
  검수한다. 이 승인 전에는 `scenario-v1` 콘텐츠 완료로 보지 않는다.
- LLM·MCP 호출 중에는 Redis game lock을 보유하지 않는다. 짧은 reservation 후
  lock을 풀고 외부 호출한 다음 재획득해 version·deadline을 검증한다.
- 호출별 15초 timeout만으로 20초 밤 마감을 보장할 수 없으므로 3초 commit·network
  reserve를 먼저 빼고 외부 작업 총예산을 적용한다. 예산이 부족하면 교정을 생략하고
  즉시 결정적 fallback을 사용하며 늦은 결과는 CAS로 폐기한다.
- capability는 game/agent/phase/version/deadline에 묶고 agent turn마다 갱신하며
  이전 capability와 session을 폐기한다.
- MCP session bootstrap 인증, 운영 TLS, Backend audit sink와 실패 재시도 계약을
  추가한다. 안정적 audit ID와 정량 bounded outbox를 사용하고 이미 commit한 게임
  행동은 감사 전송 실패로 되돌리지 않는다. MCP runtime의 DB·Redis 직접 접근 금지는
  유지한다.
- PostgreSQL DDL용 `DATABASE_MIGRATION_URL`과 DML runtime `DATABASE_URL`을
  분리하고 migration runner도 전용 URL만 읽게 한다. `.env.example`은 카탈로그일
  뿐이며 Backend·MCP·migration·Front 프로세스에는 각 allowlist만 주입한다.
- `MAFIA_MCP_URL`은 `/mcp`를 포함한 full endpoint로 고정하고 client가 suffix를
  다시 붙이지 않는다.
- checksum이 틀린 snapshot은 사용하지 않고 이전 검증 snapshot 또는 genesis부터
  이벤트를 재생한다. MCP 장애 fallback에서도 raw snapshot을 전달하지 않고 정상
  경로와 같은 audience projector로 Agent에는 PUBLIC+자기 PRIVATE, GM에는 PUBLIC만
  재투영한다.
- 두 LLM provider가 모두 실패해도 발언은 `PASS`, 밤·투표는 결정적 자동 선택으로
  진행하며 provider 장애만으로 게임을 자동 pause하지 않는다.
- MCP 인프라 체크포인트를 기반 인프라 준비와 Backend migration 적용 검증으로
  분리해 Backend WU와의 순환 의존을 제거한다.

### 6.2 검증 전략

- 6~9명별 100회 이상, 가능하면 1,000회의 규칙 시뮬레이션은 heuristic bot과
  fake LLM으로 수행한다. 유료 LLM은 비용 승인된 소수 표본에만 사용한다.
- 6·7명의 시민 우세 가능성, 8명의 마피아 증가 효과, 의사 무제한 보호와 최종
  지목의 승률 영향을 측정한다. 한 진영 승률이 60%를 넘으면 한 번에 규칙 하나만
  조정한다.
- 이번 개정은 문서 계약 변경이며 실제 게임 구현 완료를 의미하지 않는다.
