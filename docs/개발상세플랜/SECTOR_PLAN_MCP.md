# MCP Server·Data Infrastructure 섹터 작업 지침서 (AI 마피아 MVP)

**대상 담당자:** MCP 섹터 개발자 1인 (별도 시스템에서 개발 후 merge)
**상위 계약 문서:** [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
— 3장(DB·Redis 계약)·5장(내부 Engine API)·6장(MCP·인프라 계획)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 지침서보다 우선한다.

이 문서는 MCP 섹터가 별도 시스템에서 독립 개발하고 통합 저장소에 merge하기
까지의 작업 단위, coding AI agent 사용 규칙, 중간 merge·테스트 체크포인트를
확정한다. 이 서버의 존재 이유는 **정보 격리**다: 에이전트에게 허용되지 않은
정보가 Resource·Tool 결과·로그 어디에도 나타나지 않게 하는 것이 모든 작업의
1순위 완료 기준이다.

이 지침서의 게임 계약은 `ruleset_version=mystery-v1`,
`scenario_version=scenario-v1`, 전체 인원 6~9명, 조사 역할 `DETECTIVE`를
기준으로 한다. 마피아는 서로의 정체를 모르므로 `FACTION` 공유 정보나
팀원 목록을 만들지 않는다. AI GM은 공개 규칙·현재 시나리오·상태·타임라인만
조회하며, 어떤 이유로도 역할·개인 시나리오 정보를 받지 않는다.

이 섹터는 MCP 애플리케이션과 함께 PostgreSQL·Redis의 **인스턴스 설치, 생성,
기동, 중지, migration 전용·Backend runtime 전용 계정·권한 준비,
migration 실행, health 확인과 실행 결과
공유**를 맡는다. 다만 이것은 운영 책임의 이동이며 MCP 서버 코드가 DB·Redis에
직접 접근한다는 뜻이 아니다. DB schema·migration SQL·repository와 Redis
client·lock 의미는 계속 Backend 섹터가 작성한다.

---

## 1. 소유 경계와 금지 사항

### 1.1 수정 허용 (이 섹터의 소유)

```text
mcp_server/mafia_game/**
```

코드 디렉터리 소유와 별도로 다음 실행 환경을 이 섹터가 구축·운영한다.

```text
PostgreSQL 인스턴스·Team4_Proj DB·migrator/runtime 분리 role·migration 실행
Redis 인스턴스·접속 설정·기동/중지·PING/health 확인
```

### 1.2 수정 금지 (다른 섹터 소유)

```text
backend/**                            → Backend 섹터
frontend_user/**, frontend_admin/**   → Front 섹터
mcp_server/mcp_2/**                   → 용도 미정 예약, 건드리지 않음
```

Backend 내부 Engine API(5장)의 요청·응답이 계약과 다르면 Backend 코드를
고치지 말고 구현 계획서 9장 절차로 보고한다.
`mcp_server/mafia_game`은 `backend.*` 모듈을 **import하지 않는다**
(HTTP로만 통신). `mcp_2` 등 다른 MCP 패키지의 내부 모듈도 import 금지.
MCP 서버 runtime도 DB·Redis에 직접 접속하지 않는다. MCP 담당자는 Backend가
제공한 migration 파일을 실행할 수 있지만 내용을 수정하지 않으며, Redis
application key·TTL·lock 규칙도 Backend 계약을 임의로 바꾸지 않는다.
MCP 서버 프로세스에는 DB migrator/runtime 자격증명과 `REDIS_URL`을
주입하지 않는다. 감사 기록도 DB에 직접 쓰지 않고 상위 계약의
인증된 Backend audit sink로만 전달한다.

### 1.3 조건부 수정 (사전 고지 필요)

- 공유 파일(`pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`):
  수정 시 다른 섹터에 즉시 고지.
- `mcp_server/mafia_game/README.md`: 구현 진행에 맞춰 갱신(의무).

### 1.4 신규 파일 (승인된 구조 변경 범위 — 이 목록이 전부다)

```text
mcp_server/mafia_game/__main__.py
mcp_server/mafia_game/server.py
mcp_server/mafia_game/api/resources/game_resources.py
mcp_server/mafia_game/api/tools/game_tools.py
mcp_server/mafia_game/core/config.py
mcp_server/mafia_game/core/session.py
mcp_server/mafia_game/core/transport_auth.py
mcp_server/mafia_game/core/audit.py
mcp_server/mafia_game/services/context_service.py
mcp_server/mafia_game/services/action_service.py
mcp_server/mafia_game/ports/engine_port.py
mcp_server/mafia_game/integrations/engine/__init__.py
mcp_server/mafia_game/integrations/engine/client.py
mcp_server/mafia_game/integrations/engine/fake.py
mcp_server/mafia_game/schemas/contracts.py
mcp_server/mafia_game/tests/__init__.py
mcp_server/mafia_game/tests/test_contracts.py
mcp_server/mafia_game/tests/test_resources.py
mcp_server/mafia_game/tests/test_tools.py
mcp_server/mafia_game/tests/test_engine_client.py
mcp_server/mafia_game/tests/test_session_isolation.py
mcp_server/mafia_game/tests/test_bootstrap.py
mcp_server/mafia_game/tests/test_transport_auth.py
mcp_server/mafia_game/tests/test_capability_rotation.py
mcp_server/mafia_game/tests/test_audit.py
```

기존 계층(`api/ services/ ports/ integrations/ core/ schemas/ domain/`)을
사용하며 새 최상위 디렉터리를 만들지 않는다. 이 밖의 파일이 필요하면 착수
전에 이 문서와 구현 계획서를 갱신·합의한다.

인프라 책임 이동은 새 `infra/`, Docker Compose, provisioning script 생성을
자동 승인하지 않는다. 저장소 파일이 추가로 필요하면 먼저 이 문서의 승인 파일
목록과 루트 README를 갱신해 합의한다. 그 전에는 팀이 승인한 로컬·관리형 실행
환경을 사용하고 결과만 비밀값 없이 기록한다.

`tests/` 디렉터리 추가로 루트 `pyproject.toml`의 `testpaths` 갱신이
필요하면(`mcp_server/mafia_game/tests` 추가) 공유 파일 고지 규칙을 따른다.

---

## 2. 별도 시스템 작업 환경 구성

```bash
git clone <repo-url> && cd Team4_Proj_0831
git checkout -b feat/mcp-<기능이름>          # 예: feat/mcp-resources
uv sync --dev
uv run pytest                                 # baseline 통과 확인
```

- 루트 `.env.example`은 전체 설정 카탈로그일 뿐 MCP runtime용 파일이 아니다.
  통째로 복사·자동 로드하지 않고 fake 자동 테스트에는 synthetic 설정만 주입한다.
  실제 MCP runtime에는 `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`,
  `ENGINE_API_URL`과 비밀이 아닌 listen/TLS 설정만 allowlist로 주입한다.
- MCP 애플리케이션은 실 Backend 연동 전까지 Backend 없이 개발 가능해야 한다.
  WU-M2에서 만드는
  `integrations/engine/fake.py`(계약 5장의 정상·거부 응답 시나리오 재현)가
  모든 후속 WU와 자동 테스트의 기본 의존성이다.
- WU-M1A에서 migration을 실행하지 말고 PostgreSQL·Redis 기반과
  migrator/runtime DB role만 준비한다. Backend CP-B2가 migration 산출물을
  확정한 뒤 WU-M1B에서 적용·재실행·runtime 권한을 별도로 검증한다.
  실제 URL·계정명·비밀번호는 문서·로그·완료 보고에 남기지 않는다.
- 실제 Backend 연동(WU-M7)은 CP-B4 이후 로컬에서 Backend를 기동해 수동
  확인한다. 자동 테스트는 계속 fake만 사용한다.
- `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`, `MCP_SERVER_AUTH_SECRET`은
  MCP runtime 전용 비밀 주입 경로에만 둔다.
  Front용 `INTERNAL_API_SECRET`을 재사용하지 않는다.
  MCP runtime이 실행되는 계정에 DB·Redis·LLM 자격증명이 포함된
  공용 `.env`를 노출하지 않는다.

### 2.1 브랜치·merge 규칙

- 작업 브랜치: `feat/mcp-<기능>` — 기본 WU 1개 규모. 하나의 브랜치에
  여러 WU가 필요하면 각 WU를 별도 agent 세션·검증·사람 리뷰로 완료한다.
- merge 대상: `develop`. **`main` 직접 커밋·푸시 금지.**
- merge 전 `develop`을 자기 브랜치에 반영해 충돌을 해소하고 3.4 검증 통과.
- 커밋은 승인 후에만, 메시지는 AGENTS.MD 형식(목적/범위/검증).

---

## 3. Coding AI Agent 사용 규칙 (필수)

1. **한 번에 모든 구현 지시 금지.** 한 세션 범위는 4장 WU 1개 이하.
2. 작업 범위는 이 문서 4장 WU 정의로 확정한다. 범위 밖 파일 수정·신규 파일
   제안 시 중단하고 재지시한다.
3. 프롬프트에 반드시 포함: 이 지침서·AGENTS.MD 선독, WU 범위 파일 제한,
   완료 기준, 검증 명령(3.4), 한국어 주석, **격리 규칙(아래 4.0)**.
4. agent 산출물 diff를 사람이 전수 검토한다. 특히: Engine 응답을 schema
   검증 없이 그대로 통과시키는 코드, `agent_id`를 입력으로 받는 Tool,
   감사 로그에 비밀정보·전체 payload를 남기는 코드.
5. 무의미한 테스트 금지. 격리 테스트는 실제로 접근이 **거부**되는지
   확인해야 한다(응답 형태만 확인하는 테스트 불가).
6. WU 완료 → 검증 → 사람 검토 → (승인 시) 커밋 → 다음 WU. 건너뛰기 금지.

### 3.4 WU 공통 검증 명령

```bash
uv run pytest mcp_server/mafia_game/tests   # focused
uv run ruff check mcp_server
uv run python -m compileall -q mcp_server
# merge 직전에만 전체 회귀:
uv run pytest
```

---

## 4. 작업 단위(WU) 분해

### WU-M0. 격리 불변식 (모든 WU의 공통 완료 조건)

아래 항목은 각 WU 완료 기준에 자동 포함된다.

- Tool 입력으로 `agent_id`·`actor_id`·`session_id`·`capability_token`·
  `server_deadline_at`을 받지 않는다. 인증된 transport 세션이 actor와
  서버 마감시각을 결정한다.
- `me` 이외의 agent를 지정하는 조회 경로를 제공하지 않는다.
- Engine 응답은 `schemas/contracts.py`로 검증하고 중첩 객체까지
  **허용 필드만** 반환한다. 알 수 없는 필드는 통과시키지 않는다.
- `mystery-v1`에는 `FACTION`, 마피아 팀원 목록, 다른 마피아의
  정체·행동을 노출하는 응답 필드가 없다. 이러한 필드가 Engine 응답에
  있으면 계약 오류로 차단하고 감사 기록을 남긴다.
- 공개 시나리오는 `scenario_id`, `scenario_version`, `title`,
  `background`, `victim`, `locations`, `objective`만, 개인 시나리오는
  현재 actor의 `alibi`, `observation.text/target_seat/anonymous`만 허용한다.
  대상형과 익명형 관찰 조합을 schema로 검증한다. 다른 플레이어의
  알리바이·관찰, 내부 범인 표식, random seed는 반환하지 않는다.
- GM은 `rules`·현재 게임의 `scenario`·`public-state`·`public-timeline`만 조회할 수 있고
  `me`·`private-state`·`persona`·플레이어 Tool은 모두 거부한다.
- capability는 game·actor·agent turn·phase·`state_version`·ruleset·scenario
  version·만료시각에 귀속한다. 시간 제한 phase의 capability 만료는
  `server_deadline_at`을 넘을 수 없다. agent turn 완료·취소, phase나
  `state_version` 변경 시 기존 token을 폐기하고 인증된 control 경로로 새 token을
  받기 전까지 fail-closed한다. 완료된 turn의 동일 `proposal_id` 재전송은 기존
  결과만 멱등 조회할 수 있고 새 행동을 만들 수 없다.
- Engine이 반환한 `server_time`과 `server_deadline_at`은 UTC 절대시각으로
  검증한다. 응답 수신 시 `server_time`을 monotonic clock에 고정해 남은 시간을
  계산하고, host wall clock이나 bootstrap의 최대 허용 clock skew를 phase 판정에
  사용하지 않는다. MCP·에이전트·클라이언트는 deadline을 연장하거나 덮어쓸 수
  없다. 시간 제한 phase에서만 deadline 값을 요구하고 타이머가 없는 토론·발표
  phase에서는 `null`을 허용한다. 마감된 capability는 Resource와 Tool 모두
  거부한다. Backend가 timeout·phase 전이를 확정한 뒤에만 새 read/turn
  capability로 bootstrap하며 최종 deadline 판정은 Backend가 다시 수행한다.
- 다른 게임·다른 세션·만료·폐기된 capability로 접근하면 거부한다.
- 감사 event에 secret·token·HMAC·전체 prompt·원본 payload·역할·
  개인 시나리오를 기록하지 않고, 에이전트가 감사 기록을 조회할
  수단을 만들지 않는다.
- Tool 노출 제한과 MCP의 1차 검사는 최종 권한 판정이 아니다.
  Backend가 capability와 무관하게 역할·생존·phase·version·대상·deadline을
  다시 검증한다는 경계를 코드 주석에 명시한다.
- MCP runtime은 DB·Redis에 직접 접속하지 않고 영구 게임 상태를
  소유하지 않는다. 메모리의 세션 binding·제한된 audit outbox는
  보안 제어 상태이며 프로세스 재시작 시 폐기한다.

### WU-M1A. PostgreSQL·Redis 기반 준비 (migration 전)

- **범위:** 팀이 승인한 로컬·관리형 PostgreSQL·Redis 실행 환경과
  비밀값을 제외한 운영 기록. 저장소 신규 인프라 파일은 별도
  승인 전 생성하지 않는다.
- **내용:** PostgreSQL 인스턴스와 `Team4_Proj` DB를 만들고,
  `DATABASE_MIGRATION_URL`을 사용할 migrator role과 Backend의
  `DATABASE_URL`을 사용할 runtime role을 분리한다.
  runtime role에는 `CREATE`·`ALTER`·`DROP`·role 관리 권한을 주지 않는다.
  Redis를 기동하고 재시작·health·인증·네트워크 제한 절차를 확정한다.
  **이 WU에서 Backend migration을 실행하지 않는다.**
- **완료 기준:** 두 DB role의 접속 가능 여부와 권한 분리, Redis `PING`,
  재시작 후 health를 확인하고 실제 URL·계정명·비밀번호가 출력물에
  없음. Backend에는 runtime 설정 key와 접근 가능 여부만 안전한 채널로
  전달할 준비가 된 상태.
- **금지:** migrator 자격증명을 Backend runtime·MCP runtime에 주입,
  MCP runtime의 DB·Redis 직접 접근, Redis를 영구 데이터 원본으로 사용.

### WU-M1B. Backend migration 적용·권한 인수 검증

- **선행 조건:** Backend CP-B2가 순방향 migration 파일과 runtime 접속
  계약을 전달한 후에만 시작한다. WU-M1A의 선행 환경 준비와 분리한다.
- **범위:** WU-M1A에서 준비한 실 PostgreSQL·Redis 환경의 수동 인수 검증.
  Backend 소유 파일을 수정하지 않는다.
- **내용:** migrator role로 `backend.app.infrastructure.migrations`를 실행·재실행하고,
  적용 파일명·저장소 revision·schema 검증 결과만 기록한다. 그 뒤
  runtime role로 Backend persistence·lock smoke를 수행하고 DDL 권한이
  거부되는지 확인한다.
- **완료 기준:** migration 최초 적용·재실행 성공, runtime 연결·
  Backend smoke 성공, runtime DDL 거부, Redis health 성공, 비밀정보 비노출.
- **금지:** migration SQL·runner·repository·Redis application 코드 수정,
  실제 접속 문자열을 문서·commit·채팅에 복사.

### WU-M2. 골격 + 계약 schema + fake 엔진

- **범위 파일:** `core/config.py`, `schemas/contracts.py`,
  `ports/engine_port.py`, `integrations/engine/__init__.py`,
  `integrations/engine/fake.py`, `tests/__init__.py`, `tests/test_contracts.py`
- **내용:** env 로딩(secret 32자 검증, placeholder 거부 — backend
  `core/config.py`의 검증 패턴 참고하되 import하지 말고 자체 구현),
  5장 요청·응답·오류 계약의 pydantic(또는 dataclass) 모델,
  Engine Protocol과 fake 구현. fake는 `mystery-v1` 6~9명, `DETECTIVE`,
  blind mafia, `scenario-v1`, 확정 Phase enum, `server_time`·`server_deadline_at`,
  Resource 8종·accepted/거부 action·audit sink 응답을 재현한다.
  확정 Phase enum은 아래 순서와 이름을 그대로 사용한다.

  ```text
  ROLE_REVEAL | DAY_ANNOUNCEMENT | DAY_DISCUSSION | NIGHT_ACTION
  | NIGHT_RESOLUTION | DAY_VOTE | DAY_REVOTE | VOTE_RESOLUTION
  | FINAL_DISCUSSION | FINAL_VOTE | FINAL_RESOLUTION | FINISHED
  ```

- **완료 기준:** 공개·개인 시나리오 allowlist, 중첩 추가 필드 차단,
  `FACTION`·팀원 필드 차단, Phase·version·서버 시각·deadline·오류 모델 테스트 통과.

### WU-M3. 인증된 transport·세션 bootstrap·capability 생명주기

- **범위 파일:** `core/config.py`, `core/session.py`, `core/transport_auth.py`,
  `server.py`, `__main__.py`, `tests/test_session_isolation.py`,
  `tests/test_bootstrap.py`, `tests/test_transport_auth.py`,
  `tests/test_capability_rotation.py`
- **내용:** 로컬 개발은 loopback `127.0.0.1:8100` Streamable HTTP
  transport의 `/mcp`만 허용한다. 운영은 TLS 종단 뒤의 private 네트워크에
  배치하고 평문 HTTP·미인증 원격 bootstrap을 거부한다. Backend Agent Manager는
  상위 계약의 별도 `MCP_SERVER_AUTH_SECRET` bootstrap 자격증명으로 인증한 뒤에만
  game·actor·phase·
  `state_version`·ruleset·scenario version·capability·만료시각을 세션에 귀속한다.
  `session_id`는 서버가 발급하며 Tool 인자가 아니다.
- agent turn이 완료·취소되거나 phase·`state_version`이 바뀌면 인증된 control
  경로로 capability를 교체하고 기존 token을 즉시 폐기한다. 시간 제한 phase의
  capability 만료는 `server_deadline_at`을 넘길 수 없다. actor 사망·만료·game
  종료·연결 해제·서버 재시작
  시 세션을 폐기하고 Backend가 새로 bootstrap하게 한다.
- GM capability는 정체를 별도로 구분하되 공개 Resource 외 접근을
  추가로 허용하지 않는다.
- **완료 기준:** bootstrap 인증 실패, 세션 없음, turn 완료와 phase/version 불일치,
  deadline 이후 만료·폐기 token, `server_time` monotonic anchor와 host wall-clock
  skew에서도 조기 거부 없음, 재시작 후 기존 세션 거부, GM private 접근 거부
  테스트 통과.

### WU-M4. Resource 8종 + 시나리오 컨텍스트

- **범위 파일:** `services/context_service.py`,
  `api/resources/game_resources.py`, `server.py`, `tests/test_resources.py`
- **Resource:**
  - `mafia://rules/mystery-v1`
  - `mafia://scenarios/scenario-v1/{scenario_id}`
  - `mafia://games/{game_id}/public-state`
  - `mafia://games/{game_id}/public-timeline`
  - `mafia://games/{game_id}/agents/me`
  - `mafia://games/{game_id}/agents/me/private-state`
  - `mafia://games/{game_id}/agents/me/allowed-actions`
  - `mafia://personas/{persona_id}`
- **내용:** 모든 Resource는 fake Engine `/context`를 통해 가져오고 세션의
  game·actor·version과 URI를 대조한다. `public-state`는 공개 시나리오와
  phase·round·deadline·생존/사망 상태를 포함하고, `private-state`는 현재 actor의
  역할·`alibi`·`observation`·자신의 조사 결과·행동 접수 정보만 포함한다.
  마피아의 `me`도 teammate를 반환하지 않으며 `persona_id`는 현재 actor에 배정된
  값만 허용한다. 시나리오 URI는 세션 게임에 저장된 현재 `scenario_id`와 정확히
  같은 경우에만 공개 allowlist 필드를 반환하고 다른 ID나 pack version은 거부한다.
- `allowed-actions`는 phase·round·`state_version`·`server_time`·
  `server_deadline_at`·Tool·
  유효 대상을 포함한다. 서버 deadline이 지난 시간 제한 phase에서는
  행동 Tool을 노출하지 않는다. `round=0`의
  `DAY_ANNOUNCEMENT → DAY_DISCUSSION`에서는
  투표를 노출하지 않고 `NIGHT_ACTION(round=1)`로 이동한다. round 1~4는
  표준 밤·낮 루프다. 5번째 `NIGHT_RESOLUTION` 뒤 `DAY_ANNOUNCEMENT`에서 결과를
  공개하고 표준 승패가 미확정이면
  `FINAL_DISCUSSION → FINAL_VOTE → FINAL_RESOLUTION`을 노출한다.
- GM 세션은 `rules`·현재 `scenario`·`public-state`·`public-timeline`만 성공해야 한다.
- **완료 기준:** Resource 8종 정상, 공개/개인 시나리오 격리,
  blind-mafia, GM public-only, 세션·URI 교차 접근, deadline 후 행동 미노출
  테스트 통과.

### WU-M5. Tool 6종 + phase·deadline 검증

- **범위 파일:** `services/action_service.py`, `api/tools/game_tools.py`,
  `server.py`, `tests/test_tools.py`
- **내용:** `game.speak/vote/kill/investigate/protect/pass`. speak 길이
  1~200·제어문자, 대상 UUID, 세션 phase/version, 시간 제한 phase의
  `server_deadline_at`을 1차 검증한 후 `/actions`로 전달한다. `proposal_id`는
  인증된 transport의
  안정적 call id에서 생성·재사용하여 응답 유실 후 재시도에도 바뀌지
  않게 한다. 에이전트·Tool 입력으로 받지 않는다.
- 첫날 `round=0` 낮에는 `game.vote`를, `FINAL_VOTE` 외 최종 단계에서는
  투표 Tool을 노출하지 않는다. `DETECTIVE`만 `game.investigate`를,
  현재 actor가 마피아일 때만 `game.kill`을 제안할 수 있지만 Backend가 모두
  다시 검증한다. `game.pass`는 현재 토론 turn의 `PASS` 제안이며 phase 전환을
  MCP가 직접 수행하지 않는다.
- 거부 응답은 허용된 `code`·제한된 `reason_summary`만 노출하고
  내부 상세·token·Engine payload를 포함하지 않는다.
- **완료 기준:** Tool 6종 정상·거부, actor·session·token·deadline 입력
  위조 차단, 첫날·최종 phase Tool 노출, 만료 전/후 경계, 동일
  `proposal_id` 재시도 테스트 통과.

### WU-M6. 감사 sink + 제한된 outbox

- **범위 파일:** `core/audit.py`, `ports/engine_port.py`,
  `integrations/engine/fake.py`, `services/context_service.py`,
  `services/action_service.py`, `server.py`, `tests/test_audit.py`
- **내용:** 모든 bootstrap·capability 교체/폐기·Resource·Tool·거부를
  상위 계약의 인증된 Backend audit sink로 전달한다. 허용 필드는
  batch의 `instance_id`·`audit_schema_version`과 record의 안정적 `audit_id`,
  `request_id`, `trace_id`, `event_id`, `game_id`, `actor_player_id_hash`,
  `session_id_hash`, `operation`, `resource_or_tool`, `allowed`, `reason_code`,
  `occurred_at`으로 제한한다. 결과 game `event_id`와 감사 `audit_id`를 혼용하지
  않으며 `(instance_id, audit_id)`를 멱등 key로 재사용한다.
- sink 일시 장애 시 비밀 필드가 없는 event만 크기·개수·보유 시간이
  제한된 메모리 outbox에 넣고 exponential backoff·jitter로 재시도한다.
  MVP 상한은 record당 4 KiB, 1,000건 또는 총 4 MiB 중 먼저 도달한 값,
  최대 보유 15분, backoff 0.5초 시작·최대 30초, 종료 flush 최대 3초다.
  MCP runtime이 DB·Redis를 outbox로 사용하지 않는다. queue가 가득 차면
  Engine 호출 전 새 Resource·Tool을 `GAME_PERSISTENCE_UNAVAILABLE`로
  fail-closed한다. Engine이 이미 확정한 행동은 audit 실패로 되돌리거나 실패
  응답으로 바꾸지 않고, 해당 감사 event를 bounded retry·운영 경고 대상으로 남긴다.
  프로세스 종료 시 제한 시간 동안 flush한 뒤 미전달 건수만 민감정보 없는 운영
  로그에 남긴다.
- **완료 기준:** sink 성공, 일시 실패 후 순서 보존 재전송,
  동일 audit ID 중복의 멱등 처리와 payload 변조 거부, record·건수·총 byte·보유
  시간·backoff·종료 flush 한계의 fake-clock 검증, queue 한계 fail-closed, secret·token·
  prompt·payload·역할·알리바이·관찰 미포함 테스트 통과.

### WU-M7. 실제 Engine HMAC 클라이언트

- **범위 파일:** `core/config.py`, `server.py`,
  `integrations/engine/client.py`, `tests/test_engine_client.py`
- **내용:** 5장 인증(별도 secret, canonical
  `timestamp.request_id.raw_body`)으로 `/context`·`/actions`·audit sink를
  호출한다. 로컬 loopback 외의 운영 `ENGINE_API_URL`은 TLS를 요구한다.
  연결·응답 timeout은 Engine의 `server_deadline_at`보다 짧은 남은 예산으로
  제한하고, 안전한 재시도는 동일 `request_id`·`proposal_id`·audit event id를
  재사용한다. Engine 5xx의 내부 상세를 에이전트에 노출하지 않는다.
- **완료 기준:** mock transport로 raw-body 서명, timestamp·request id,
  TLS 정책, deadline 예산, 동일 id 재시도,
  `INVALID_INTERNAL_SIGNATURE`·`ACTION_ALREADY_SUBMITTED`·
  `ACTION_DEADLINE_EXPIRED`·`ACTION_NOT_ALLOWED`·`STALE_CAPABILITY`·
  `CONTRACT_VERSION_MISMATCH`·`AGENT_TEMPORARILY_UNAVAILABLE`·
  `GAME_PERSISTENCE_UNAVAILABLE`·timeout 변환 테스트 통과.
  실 네트워크 자동 테스트는 실행하지 않는다.
- **CP-M7 병행 작업:** Backend CP-B4 이후 로컬 Backend를 기동해
  bootstrap → Resource → Tool → audit sink 왕복을 각 1회 수동 확인한다.
  계약 불일치는 코드 수정 전에 문서 이슈로 보고한다.

### WU-M8. 격리·capability·감사 강화 (카나리)

- **범위 파일:** `core/session.py`, `core/audit.py`,
  `schemas/contracts.py`, `services/context_service.py`, `services/action_service.py`,
  `tests/test_session_isolation.py`
- **내용:** 상위 계약의 격리 규칙을 종합 검증한다.
  - 세션 A가 세션 B의 게임·agent Resource에 접근 시 거부
  - phase/version 교체 전·만료·폐기 capability와 다른 게임 token 거부
  - fake Engine에 agent별 역할·알리바이·관찰 카나리를 심고 다른
    세션의 Resource·Tool·audit event에서 발견되지 않음을 확인
  - blind mafia 세션과 GM 세션에 다른 역할·개인 시나리오가 없음을 확인
  - 비간섭성: B의 비공개 상태만 바꿔도 A의 Resource 응답은 불변
- **완료 기준:** 카나리·비간섭성·교차 세션·capability 생명주기·
  blind-mafia·GM public-only·audit 비노출 테스트 전부 통과.

---

## 5. 중간 merge·테스트 체크포인트

| 체크포인트 | 포함 WU | merge 전 필수 검증 | 통합 상대 |
|---|---|---|---|
| **CP-M0 계약 확인** | (코드 없음) | 5·6장 리뷰 의견 제출 | 3인 합의 |
| **CP-M1A 인프라 기반** | M1A | migrator/runtime role 분리 + Redis health + 비밀정보 비노출 | **Backend CP-B2의 선행 환경** |
| **CP-M1B migration 인수** | M1B | migration 최초·재실행 + runtime DDL 거부 + persistence·lock smoke | **Backend CP-B2 산출물 수신 후** |
| **CP-M2 계약·fake** | M2 | contracts focused + 전체 회귀 | 없음 (독립) |
| **CP-M3 안전한 세션** | M3 | bootstrap·TLS 정책·capability 생명주기 거부 경로 + 회귀 | 없음 (fake) |
| **CP-M4 Resource** | M4 | 8종 Resource + scenario·blind-mafia·GM 격리 + 회귀 | 없음 (fake) |
| **CP-M5 Tool** | M5 | 6종 Tool + phase·version·deadline·idempotency 거부 경로 + 회귀 | 없음 (fake) |
| **CP-M6 감사** | M6 | sink·outbox 재시도 + queue 한계 + 민감정보 비노출 + 회귀 | 없음 (fake) |
| **CP-M7 Engine 연동** | M7 | HMAC client 회귀 + 실 Backend bootstrap/Resource/Tool/audit 왕복 | **Backend CP-B4 이후** |
| **CP-M8 격리 완성** | M8 | 전체 회귀 + 카나리·비간섭성·capability 폐기 | Backend CP-B5와 함께 CP-ALL |

### 중간 테스트 규칙

- coding AI agent 세션 하나에는 WU 하나만 지시하고, WU마다 focused,
  CP merge 직전 전체 회귀(3.4)를 수행한다.
- CP-M1A는 migration 없이 완료해 Backend CP-B2의 기반을 제공한다.
  CP-M1B는 Backend CP-B2 산출물을 받은 후에만 수행하며, 두 CP를
  하나의 선행 조건으로 묶지 않는다. CP-M1B를 기다리는 동안 CP-M2~M6은
  fake로 독립 진행할 수 있다.
- CP-M1B에서 MCP 담당자가 Backend 담당자와 함께 실 서비스의
  migration·runtime 권한·persistence·lock·health 결과를 공동 기록한다.
- CP-M7 merge 후 `develop`에서 Backend 기동 → MCP 기동 → 인증 bootstrap
  → Resource 1종 → Tool 1종 → audit sink 수신 스모크를 실행하고
  결과를 Backend 담당자와 공유한다.
- Backend 원인 실패는 임의 수정하지 않고 원인·영향만 보고.

---

## 6. 고위험 항목 (AGENTS.MD 테스트 규칙 직접 적용)

이 서버의 핵심 기능 자체가 보안 경계이므로, 다음은 **구현과 동시에 거부
경로 테스트를 작성**한다.

- 세션 위조·교차 세션 접근·타 게임 capability 사용 거부
- 미인증 bootstrap·운영 평문 HTTP·만료·폐기·phase/version 불일치 거부
- actor 관련 입력 필드 차단
- Engine 응답의 중첩 allowlist 필터와 `FACTION`·마피아 팀원 필드 차단
- 다른 플레이어 시나리오 컨텍스트·GM private 정보 노출 부재
- 서버 deadline 만료 후 행동 Tool 거부와 안정적 `proposal_id` 재시도
- 감사 sink/outbox 장애·재시도·한계 경로와 감사 event의 민감정보 부재
- Engine 장애 시 에이전트에게 내부 상세 미노출
- migrator/runtime DB role 분리와 MCP runtime의 DB·Redis 자격증명 부재

## 7. 완료 보고 양식 (WU·CP 공통)

```text
[WU-M6 완료]
- 변경 파일: (목록)
- 실행 검증: uv run pytest mcp_server/mafia_game/tests → NN passed / ruff OK
- 격리 불변식 확인: (4.0 항목별 해당 테스트 이름)
- 생략 검증과 이유: 실 Backend 왕복은 CP-M7에서 수행 예정
- 범위 밖 변경: 없음
- 계약 이슈: (있으면 구현 계획서 장·절 지목)
- README 갱신 필요 여부: (실행 방법·env 변경 유무)
```
