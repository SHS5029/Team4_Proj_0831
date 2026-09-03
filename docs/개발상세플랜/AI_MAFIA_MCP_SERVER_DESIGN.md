# AI 마피아 MVP MCP Server·Data Infrastructure 개발 설계서

**문서 상태:** 구현 기준 확정안

**대상 패키지:** `mcp_server/mafia_game`

**최종 갱신:** 2026-09-03

## 1. 목적과 정본 우선순위

이 문서는 Mafia Game MCP runtime과 MCP·Data Infrastructure 작업 단위의 구현 구조,
선행조건, 검증 방법과 완료 증거를 정의한다. 제품 규칙, 저장 계약과 wire schema를
새로 정의하는 문서가 아니다.

| 계약 영역 | 정본 |
|---|---|
| 제품 규칙·소유권·WU·CP | [AI_MAFIA_MASTER_PLAN.md](AI_MAFIA_MASTER_PLAN.md) |
| PostgreSQL·Redis·transaction·migration | [AI_MAFIA_DB_DESIGN.md](AI_MAFIA_DB_DESIGN.md) |
| 내부 Engine HTTP·MCP wire·5개 Resource `data` schema | [AI_MAFIA_API_SPEC.md](AI_MAFIA_API_SPEC.md) |
| 섹터 간 최소 연결 형식 | [AI_MAFIA_INDEPENDENT_CONTRACT.md](AI_MAFIA_INDEPENDENT_CONTRACT.md) |
| 사용자·관리자 화면 | [AI_MAFIA_SCREEN_FLOW.md](AI_MAFIA_SCREEN_FLOW.md) |
| 현재 구현 상태·실행 명령 | [루트 README](../../README.md) |

충돌 시 `AGENTS.MD`, 영역별 정본, 이 설계서 순으로 판정한다. 특히 다섯 MCP
Resource의 상세 `data` field, enum, nullable, union과 길이 제약은 API 명세 8.2절과
그 절이 명시적으로 참조하는 API 공통 모델만 정본이다. 이 문서의 매핑과 예시는
이해를 돕는 비규범 자료이며 fixture나 validator를 만드는 근거로 단독 사용하지 않는다.
구현 validator는 API 정본을 코드로 옮기되 별도 문서 계약을 만들지 않는다.

한 coding AI agent 세션은 마스터플랜의 WU 한 개 이하만 구현한다. 이 문서 전체를 한
세션에 구현하도록 지시하지 않는다.

## 2. 확정 결정

1. Backend 규칙 엔진이 유일한 authoritative game engine이다. MCP runtime은 게임을
   판정하거나 상태를 저장하지 않고 Backend 내부 Engine API만 호출한다.
2. AI player는 `public`, `me`, `turn`, `persona` Resource와 capability가 허용한 행동
   Tool만 사용한다.
3. AI GM은 `public`, `gm-guide` Resource만 읽고 행동 Tool을 갖지 않는다. 생성한
   narration은 MCP proposal 경로가 아니라 LLM adapter에서 Backend Agent Manager로
   직접 반환된다.
4. `agent_jobs` reservation 한 건마다 새 capability, 일회성 MCP 세션 개설
   토큰(bootstrap token)과 새 MCP session을 만든다. terminal 처리 뒤 모두 폐기하며
   reconnect에도 이전 값을 재사용하지 않는다.
5. proposal 전송 결과가 불명확해 재시도한다면 같은 `proposal_id`와 같은 body를
   사용한다. 새 상태로 version이나 target을 자동 보정하지 않는다.
6. MCP runtime은 PostgreSQL·Redis에 직접 접근하지 않고 Backend `event_outbox`도
   사용하지 않는다. WU-M5는 별도 영속 outbox가 아닌 allowlist 구조화 운영 로그와
   redaction을 구현한다.
7. MCP·Data 담당자의 PostgreSQL·Redis 책임은 실행 환경, 계정·권한, Backend 작성
   migration의 실행·재실행과 health 확인이다. schema·migration SQL·repository·Redis
   application code는 Backend 소유다.

## 3. 범위와 비범위

### 3.1 포함 범위

- MCP Streamable HTTP endpoint `${MAFIA_MCP_URL}`의 `/mcp` session
- 세션 개설 토큰 서명 검증과 Engine consume
- job·subject·capability에 고정된 session memory
- 다섯 Resource의 URI 등록, Engine scope 변환과 폐쇄형 응답 검증
- 네 행동 Tool의 입력 검증과 Engine proposal adapter
- Engine HMAC 요청 생성, 오류 정규화와 취소 전파
- 모든 MCP 경로의 allowlist 구조화 로그와 중앙 redaction
- fake Engine 기반 독립 계약 테스트와 실제 Backend 통합 검증
- PostgreSQL·Redis 실행 환경, 계정·권한, migration 실행·health runbook

### 3.2 비범위

- 게임 규칙·대상·승패·fallback 결과의 자체 판정
- DB schema, migration SQL, repository와 Redis key·lock·publisher 구현
- PostgreSQL·Redis·embedding/vector 저장소를 호출하는 MCP adapter
- Backend `event_outbox` 소비·수정 또는 MCP 전용 DB·queue·audit outbox
- LLM Provider 호출, prompt 조립, GM 결과 저장과 Agent worker scheduling
- Front 공개 API, 화면, OAuth·사용자 인증 구현
- 자동 Provider failover, token·비용·예산·조정 가능한 LLM timeout

현재 `mcp_server/mafia_game`은 예약 package이며 실행 entrypoint, Resource, Tool,
Engine adapter와 테스트가 아직 없다. 일부 예약 `__init__.py`의 여행 도메인 placeholder와
`integrations/database`, `integrations/redis`, `integrations/embedding` 디렉터리는 구현
권한을 뜻하지 않는다. 삭제·이동·이름 변경이 필요하면 착수 전 정본과 README를 먼저
갱신하고 구조 변경 합의를 거친다.

현재 Backend scaffold client는 `8010/mcp` 기본값과 `game_ping`, `game_get_context`,
`game_submit_proposal` placeholder Tool을 사용하며 세션 개설 토큰·capability header가
없다.
목표 계약은 `8100/mcp`, 다섯 Resource와 네 Tool이다. `WU-B6`·`WU-B7`과 `WU-M6`에서
target client로 교체하며 MCP runtime에 legacy Tool alias를 추가해 이 scaffold를
유지하지 않는다.

## 4. 시스템 경계와 의존 방향

```text
Browser
  -> Frontend
    -> Backend public API
      -> authoritative game engine / Agent Manager / LLM adapter
          |                         |
          | 세션 개설 토큰 + capability | GM_NARRATION direct return
          v                         v
        Mafia Game MCP ----------> Backend internal Engine API
          Resource / Tool             validate / persist / fallback

PostgreSQL <-> Backend repository
Redis      <-> Backend cache·lock·publisher

MCP·Data 담당자 -> PostgreSQL·Redis 실행 환경·계정·migration·health 운영
MCP runtime     -X-> PostgreSQL·Redis
```

Backend는 LLM·MCP 외부 호출 동안 PostgreSQL transaction이나 Redis game lock을
보유하지 않는다. MCP 장애 때 동일 audience의 검증된 snapshot을 다시 투영하거나
규칙 기반 fallback을 확정하는 주체도 Backend Agent Manager다.

### 4.1 package 의존 방향

```text
api -> services -> ports <- integrations
           |
         domain

schemas와 core는 위 계층이 공유하는 검증·설정·오류·보안 정책을 제공한다.
```

| 계층 | 책임 | 금지 사항 |
|---|---|---|
| `api` | Streamable HTTP, initialize, Resource·Tool 등록과 protocol 변환 | Engine 규칙 판정 |
| `services` | 세션 개설 인증, Resource 조회, proposal 제출 orchestration | HTTP SDK·DB 세부 구현 결합 |
| `ports` | Engine transport, clock, ID 생성기, 안전한 log sink 추상 경계 | concrete client 생성 |
| `integrations` | 서명된 HTTP Engine adapter | DB·Redis·embedding adapter 사용 |
| `domain` | session subject, capability binding, 허용 operation의 순수 불변식 | MCP·HTTP import |
| `schemas` | 정본 wire 입력·응답의 폐쇄형 validation | 정본 밖 field·enum 추가 |
| `core` | 설정 allowlist, 고정 오류, HMAC·redaction 공통 정책 | secret·payload log |

`OPEN-01`은 다음과 같이 확정한다.

- `mcp_server/`를 독립 프로젝트 루트로 사용하고 Python import package는
  `mafia_game`으로 고정한다. `mcp_2`는 후속 예약 package로 유지하며 Mafia Game
  runtime이나 배포 산출물에 포함하지 않는다.
- composition root는 `mcp_server/mafia_game/main.py`, module 실행 진입점은
  `mcp_server/mafia_game/__main__.py`다. 표준 실행 명령은
  `uv run python -m mafia_game.main`이다.
- 독립 의존성과 개발 도구는 `mcp_server/pyproject.toml`과 `mcp_server/uv.lock`,
  package 단위 검증은 `mcp_server/tests/`가 소유한다. 저장소 루트의 회귀 검증과
  Backend MCP client 의존성은 루트 project가 계속 소유한다.
- 기존 계층 디렉터리는 이동하거나 이름을 바꾸지 않는다. 최상위
  `mcp_server/__init__.py`의 제거 여부는 별도 구조 변경 합의 전까지 현 상태를
  유지하되 runtime code에서 `mcp_server.mafia_game`과 `mafia_game` 두 import 경로를
  혼용하지 않는다.
- Python 3.12와 MCP SDK 1.29.1 동작을 구현 기준으로 삼고 독립 lockfile로 재현한다.
  SDK minor 변경은 session·auth·teardown 계약 테스트를 통과한 뒤 반영한다.

## 5. 주체와 capability 표면

| 주체 | `subject_id` | Resource | Tool | 결과 경로 |
|---|---|---|---|---|
| `AI_PLAYER` | 자기 `player_id` | `public`, `me`, `turn`, `persona` 중 capability allowlist | 현재 job에 허용된 행동 Tool | MCP → Engine proposal → Backend 판정 |
| `GM` | `game_id`와 같은 UUID | `public`, `gm-guide` | 없음 | LLM adapter → Agent Manager 직접 반환 |

URI, query와 Tool input으로 다른 agent를 선택할 수 없다. 공개 대화와 Resource 안의
자연어는 모두 불신 데이터이며 system instruction이나 capability 범위를 바꾸지 못한다.

## 6. job별 단기 session 수명주기

```text
1. Backend Tx A
   agent_jobs reservation + fencing token
   -> job-bound opaque capability + 세션 개설 토큰과 그 nonce 발급

2. Agent Manager -> MCP initialize
   Authorization: Bearer <token>
   X-Agent-Capability: <raw capability>

3. MCP
   세션 개설 토큰 서명·claim·만료 검증
   -> Engine HMAC으로 세션 개설 토큰 consume
   -> 성공한 경우에만 ACTIVE session

4. ACTIVE
   Resource read
   -> AI_PLAYER: 허용 Tool 0~1회
   -> GM: Tool 없이 LLM adapter direct-return

5. Backend Tx B 또는 scheduler
   lease·fencing·window·state 재검증
   -> success / fallback / stale / failed
   -> capability revoke

6. Agent Manager와 MCP
   session 종료 시도 + session memory 폐기
```

### 6.1 session 상태

| 상태 | 진입 조건 | 허용 작업 | 종료 조건 |
|---|---|---|---|
| `PENDING` | initialize 요청 수신 | 세션 개설 토큰 검증·consume만 | consume 성공 또는 거부 |
| `ACTIVE` | Engine consume 성공 | allowlist Resource·Tool | job terminal, revoke, 만료, 연결 종료 |
| `CLOSED` | terminal 또는 보안 경계 위반 | 없음 | 최종 상태 |

- raw capability는 해당 session memory와 Engine 요청 header에서만 사용한다.
- 세션 개설 토큰 consume 전 Resource·Tool 목록과 호출을 허용하지 않는다.
- phase, window 또는 state version이 바뀌면 기존 capability와 결과는 stale이다.
- 성공뿐 아니라 fallback, stale, failed(호출 취소 포함)와 lease 만료 경로에서도
  revoke·memory 폐기를 수행한다.
- 연결 단절 뒤 소비한 세션 개설 토큰, raw capability와 `Mcp-Session-Id`를 다시 사용하지
  않는다. 같은 lease의 job을 계속할 자격이 Backend에 남아 있을 때만 새 세 값을
  발급한다.
- `OPEN-02`는 stateful `StreamableHTTPSessionManager`와 전용 Starlette 세션 개설
  middleware를 사용하는 것으로 확정한다. SDK private attribute를 수정하거나
  stateless mode로 session binding을 우회하지 않는다.
- 최초 initialize 요청은 bearer 세션 개설 토큰과 `X-Agent-Capability`를 함께 검증하고
  Engine consume 성공 뒤에만 session transport와 `ACTIVE` memory를 노출한다. 같은
  활성 session의 후속 HTTP 요청은 최초와 같은 bearer를 보내되 capability header를
  다시 보내지 않는다. 후속 bearer는 같은 session owner인지 확인하는 용도이며
  세션 개설 토큰 consume을 다시 실행하지 않는다.
- 정상 종료는 Streamable HTTP `DELETE /mcp`와 `Mcp-Session-Id`를 사용한다. Tool의
  terminal 결과, Backend의 종료 요청, capability·세션 개설 토큰 만료, transport 종료,
  process shutdown에서도 같은 멱등 cleanup을 호출한다.
- stateful session idle TTL은 30초로 고정한다. 세션 개설 토큰 `exp` 또는 Backend
  capability 거부가 더 먼저 도달하면 TTL과 관계없이 즉시 닫는다. session memory는
  파일·DB·Redis·event store에 저장하지 않는다.
- consume 응답을 받지 못하면 성공을 추측하거나 같은 세션 개설 토큰을 다시 consume하지
  않고 해당 transport와 memory를 폐기한다. fresh credential 조정은 `OPEN-07`의
  Backend 절차를 따른다.
- 종료 실패가 기존 자격을 다시 유효하게 만들 수는 없다.

## 7. Resource 설계

### 7.1 URI 매핑

아래 표는 routing 매핑일 뿐 `data` schema 정의가 아니다.

| MCP URI | Engine 요청 | 허용 subject | 용도 | schema 정본 |
|---|---|---|---|---|
| `mafia://session/public` | `scope=public` | AI_PLAYER, GM | 공개 game·scenario·player·event | API 8.2.1 |
| `mafia://session/me` | `scope=me` | AI_PLAYER | 자기 role·개인 사실·private event | API 8.2.2 |
| `mafia://session/turn` | `scope=turn` | AI_PLAYER | 현재 window·Tool·target·deadline | API 8.2.3 |
| `mafia://session/persona` | `scope=persona` | AI_PLAYER | 배정된 검증 persona | API 8.2.4 |
| `mafia://session/gm-guide` | `scope=gm-guide` | GM | 공개 event 또는 고정 문구 guide | API 8.2.5 |

AI_PLAYER와 GM이 공유하는 URI는 `public` 하나다. GM의 Resource 목록에 `me`, `turn`,
`persona`가 나타나거나 Tool 목록이 비어 있지 않으면 계약 위반이다.

### 7.2 adapter 처리 순서

1. 현재 session이 `ACTIVE`인지 확인한다.
2. URI를 상수 registry에서 Engine scope로 변환한다.
3. subject와 capability resource allowlist를 교차 확인한다.
4. session capability로 Engine HMAC 요청을 보낸다.
5. 공통 envelope의 job subject, scope, window와 version 일치를 확인한다.
6. API 8.2절의 해당 폐쇄형 `data` validator를 통과시킨다.
7. URI가 같은 `application/json` text content 한 개로 직렬화한다.

Engine이 unknown field나 audience 금지 field를 반환하면 silent strip하지 않고
Resource read를 fail-closed한다. session 밖 authoritative cache를 두지 않으며 다른
subject의 응답을 재사용하지 않는다.

### 7.3 매핑 예시

```text
AI player가 mafia://session/turn을 읽음
-> registry가 scope=turn으로 변환
-> GET /internal/v1/agent-context?scope=turn
-> API 8.2 공통 envelope와 8.2.3 data validator 통과
-> 같은 URI의 application/json content 반환
```

```text
GM이 mafia://session/me를 직접 요청
-> subject/URI allowlist에서 즉시 거부
-> Engine private projection 호출 0회
-> payload 없는 고정 protocol 오류만 반환
```

예시의 생략된 payload를 fixture로 복원하지 않는다. 실제 fixture field와 값은 항상 API
명세 8.2절에서 생성한다.

## 8. Tool과 Engine proposal

| MCP Tool | Engine proposal type | 모델 입력 | 허용 window |
|---|---|---|---|
| `propose_speech` | `SPEAK` | `message`, `public_rationale` | 자기 발언 차례 |
| `propose_pass` | `PASS` | 없음 | 자기 발언 차례 |
| `propose_night_action` | `NIGHT_ACTION` | `target_player_id` | 생존 특수 역할의 밤 |
| `propose_vote` | `VOTE` | `target_player_id` | 일반·재·최종 투표 |

Tool input은 폐쇄형이다. `game_id`, `agent_id`, role, phase, window와 version은 모델
입력으로 받지 않고 session과 capability에서 가져온다.

처리 순서:

1. MCP schema로 Tool input의 타입·길이·unknown field를 검사한다.
2. 첫 Engine 전송 전에 UUID v4 `proposal_id`를 한 번 만든다.
3. session binding과 input으로 API 8.4절 proposal을 조립한다.
4. 새 HMAC timestamp·nonce·signature와 capability로 Engine에 전달한다.
5. Engine의 terminal 결과만 MCP Tool 결과로 변환한다.
6. terminal 결과 뒤에는 추가 Tool을 거부하고 session 종료 절차로 이동한다.

MCP 성공은 Backend 규칙 엔진이 proposal을 검증·반영했다는 응답이지 MCP가 판정했다는
뜻이 아니다. role·phase·target·deadline·중복·state version은 Backend가 다시
검증한다.

응답 유실로 같은 살아 있는 job에서 다시 전송한다면 `proposal_id`와 canonical body는
동일하고 HMAC nonce만 새 값이어야 한다. body 변경, 새 target 선택, version rebase와
다른 job에서의 ID 재사용은 금지한다. session 자체가 유실된 경우 Agent Manager가
Backend의 job 상태를 먼저 조정하며 MCP가 결과를 추측하지 않는다.

## 9. AI GM direct-return

```text
MCP public + gm-guide
  -> Backend LLM adapter가 GM에게 제공
  -> GM_NARRATION structured result
  -> Backend Agent Manager 직접 반환
  -> schema·guide reference·PUBLIC 범위·lease/fencing/window/state 재검증
  -> PUBLIC event 또는 고정 한국어 fallback
```

- GM session에는 Tool이 하나도 없고 `/internal/v1/agent-proposals`를 호출하지 않는다.
- GM 결과 schema의 정본은 API 10.2절이다. MCP package에 중복 schema나 GM submit Tool을
  만들지 않는다.
- GM이 읽는 event는 이미 `PUBLIC` projection이어야 한다. 공격자, 보호 대상, 조사
  결과, 개별 투표와 role-conditioned target은 전달하지 않는다.
- 공개 텍스트의 prompt injection은 명령이 아니라 game data로 처리한다.
- 잘못됐거나 늦은 GM 결과의 교정·fallback·저장은 Backend 책임이다.

## 10. 내부 Engine HTTP adapter

MCP가 호출하는 path는 세 개뿐이다.

```text
GET  /internal/v1/agent-context?scope=...
POST /internal/v1/mcp-bootstrap/consume
POST /internal/v1/agent-proposals
```

모든 요청은 API 8.1절의 canonical HMAC을 사용한다. adapter는 대문자 method, raw path,
정렬된 canonical query, raw body hash, timestamp와 UUID v4 nonce를 정확히 서명한다.
signature는 padding 없는 base64url이고 constant-time 비교는 Backend가 수행한다.

MCP는 opaque capability를 decode하거나 자체 권한 token으로 검증하지 않는다. 세션
개설 토큰 서명 검증은 session 개설 권한 확인이고, Engine은 capability hash·job·subject·
allowlist·expiry·revoke와 현재 DB 상태의 최종 판정자다. `MCP_SERVER_AUTH_SECRET`과
`ENGINE_INTERNAL_API_SECRET`은 방향과 용도가 다르며 같은 값을 쓰지 않는다.

## 11. 오류·fallback·재접속

| 상황 | MCP 처리 | Backend 처리 |
|---|---|---|
| 세션 개설 토큰 누락·변조·만료·replay | session 비활성, 고정 거부 | 새 job 자격 검토 또는 fallback |
| capability denied·stale | 상세 이유를 숨긴 고정 거부 | 현재 reservation·상태 판정 |
| Resource schema/audience 위반 | fail-closed, payload 비노출 | 검증된 동일 audience snapshot 또는 fallback |
| Tool input 오류 | Engine 호출 전 고정 validation 오류 | 필요 시 한 번 교정 후 fallback |
| Engine timeout·5xx·disconnect | 상태 추측·자체 fallback 금지 | job/receipt 조정 후 retry 또는 fallback |
| proposal 응답 유실 | 동일 ID·body만 재전송 가능 | idempotency terminal 결과 반환 |
| MCP session 유실 | 기존 자격 재사용 금지 | 살아 있는 job만 fresh reconnect |
| GM 출력 오류·late result | 관여하지 않음 | 교정 1회, fencing 검사, 고정 문구 또는 stale |
| logger/sink 장애 | 게임 payload spool 금지 | 게임 상태와 무관하게 운영 경보 |

`OPEN-03`은 다음 고정 매핑으로 확정한다. HTTP 인증 오류 body는 표의 `공개 code`만
가진 `{"error":"<code>"}`이고, JSON-RPC 오류는 표의 숫자 code와 고정 한국어
message만 가지며 `data`를 넣지 않는다.

| 경계 | 조건 | HTTP/JSON-RPC | 공개 code |
|---|---|---:|---|
| initialize | bearer 또는 capability header 누락·형식 오류 | HTTP 401 | `AUTH_REQUIRED` |
| initialize | 세션 개설 토큰 서명·claim·만료·replay·mismatch 또는 consume 거부 | HTTP 403 | `BOOTSTRAP_DENIED` |
| session | 알 수 없거나 이미 닫힌 `Mcp-Session-Id` | HTTP 404 | `SESSION_NOT_FOUND` |
| protocol | JSON-RPC 또는 Tool 폐쇄형 입력 오류 | `-32602` | `VALIDATION_ERROR` |
| handler | 비활성 session 또는 terminal 뒤 추가 호출 | `-32001` | `SESSION_NOT_ACTIVE` |
| Engine | capability·subject·scope·phase·window·version 거부와 존재 은닉 대상 404 | `-32002` | `CAPABILITY_DENIED` |
| Engine | timeout·연결 단절·429·5xx | `-32003` | `DEPENDENCY_UNAVAILABLE` |
| Engine | 성공 응답의 envelope·폐쇄형 schema 위반 또는 예상하지 않은 4xx | `-32004` | `UPSTREAM_CONTRACT_VIOLATION` |
| proposal | 같은 `proposal_id`의 body conflict | `-32005` | `PROPOSAL_CONFLICT` |
| handler | 위 분류에 포함되지 않은 내부 실패 | `-32603` | `INTERNAL_ERROR` |

Engine response body, exception text와 stack은 어떤 매핑에서도 agent에게 전달하지 않는다.
취소는 상위 task로 전파한 뒤 session cleanup을 수행하며 임의 오류 payload로 바꾸지 않는다.

## 12. 구조화 로그와 redaction

API 9.4절의 application allowlist만 사용한다. 적용 범위는 initialize, consume,
Resource, Tool, Engine adapter, teardown의 성공·거부·예외 전체다.

허용 대상:

- request·correlation ID
- operation 이름
- status
- duration
- 비밀 없는 폐쇄형 error class

두 log ID는 검증된 UUID만 사용하고 임의 header 문자열을 그대로 기록하지 않는다.

금지 대상:

- Resource·Tool request/response payload와 target
- game·agent·player ID 및 private context
- capability, 세션 개설 토큰, signature, secret과 HTTP header
- prompt, raw model response, exception 전문·stack, chain-of-thought
- DB·Redis·queue·파일 spool을 이용한 MCP 영속 audit outbox

테스트는 marker를 각 중첩 field와 exception에 주입하고 모든 log record를 캡처해 key
allowlist와 marker 부재를 검사한다. logger 실패 경로도 payload를 fallback file에 쓰지
않아야 한다. sink 제품과 보존 정책은 `OPEN-04`이며 wire 계약과 분리한다.

## 13. 설정·secret·network

| 프로세스 | 허용 설정 |
|---|---|
| Backend | `MAFIA_MCP_URL`, `MCP_REQUIRE_TLS`, `MCP_TLS_CA_FILE`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET` 등 Backend allowlist |
| MCP runtime | `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`, 비밀이 아닌 listen·TLS 설정 |
| migration | `DATABASE_MIGRATION_URL`, `DATABASE_NAME` |

- MCP runtime에는 DB·Redis·LLM 자격증명을 주입하지 않는다.
- 실제 secret, DSN, token과 인증서 개인키를 문서·fixture·log·Git에 넣지 않는다.
- `${MAFIA_MCP_URL}`은 `/mcp`를 포함한 전체 endpoint이며 client가 경로를 중복하지
  않는다.
- Backend→MCP 운영 연결은 검증된 TLS를 사용한다. 평문 HTTP는 loopback 개발에서만
  허용하고 downgrade나 검증 실패 시 fail-open하지 않는다.
- MCP→Engine TLS 종료, CA/mTLS 여부와 MCP listen 인증서 환경변수명은 `OPEN-05`다.
- MCP 자체 liveness/readiness endpoint와 readiness 기준은 `OPEN-06`이다. 정본 변경 전
  임의 공개 endpoint를 추가하지 않는다.

## 14. 테스트 전략

### 14.1 독립 개발 원칙

WU-M2~WU-M5의 자동 테스트는 실제 Backend, PostgreSQL, Redis와 유료 LLM 없이 synthetic
fixture와 fake Engine port를 사용한다. fixture는 API 정본에서 만들고 정본 밖 field,
enum과 상태 전이를 계약으로 추가하지 않는다.

fake Engine은 다음 결과를 script할 수 있어야 한다.

- 세션 개설 토큰 consume 성공·거부·지연·응답 유실
- scope별 정상 context와 unknown/private field가 섞인 잘못된 context
- proposal accepted, 동일 replay, body conflict, capability deny와 dependency failure
- timeout, cancellation과 connection loss
- 호출 path·header 존재·body hash를 검증할 수 있는 비밀 없는 호출 기록

### 14.2 필수 검증 matrix

| 축 | 최소 검증 |
|---|---|
| 세션 개설 토큰 | canonical signature, claim, expiry, nonce replay, capability hash mismatch |
| lifecycle | job마다 다른 capability·nonce·session, 모든 terminal revoke, fresh reconnect |
| subject | 2×5 Resource 허용표, 다른 subject 선택 거부 |
| Resource | 5개 exact schema, unknown field fail-closed, public subject 비의존성 |
| noninterference | 다른 AI role·사실·event·persona, GM private field와 target 비노출 |
| Tool | closed input, 현재 allowlist, target, stale version, Backend 재검증 |
| idempotency | 같은 proposal ID/body terminal replay, 다른 body conflict, 새 HMAC nonce |
| GM | Resource 두 개·Tool 0개, direct-return, guide mismatch, late fencing fallback |
| 장애 | Engine 4xx·5xx·timeout, MCP restart, session loss, 취소 전파 |
| 로그 | 전 경로 key allowlist, payload·ID·secret·exception marker 부재 |
| 경계 | MCP process에 DB·Redis client·credential 없음, Engine 세 path만 호출 |

SDK-level Streamable HTTP test, fake Engine 계약 test와 실제 Backend 통합 test를
분리한다. 실제 Provider smoke는 이 설계의 필수 게이트가 아니다.

## 15. WU 실행 계획

### 15.1 의존 순서

```text
CP-0 -> WU-M1A -> WU-B2 -> WU-M1B -> CP-2

CP-0 -> WU-M2 -> WU-M3 -> WU-M4 -> WU-M5 --\
                                             +-> WU-M6 -> WU-M7 -> WU-M8 -> CP-6
WU-B6 + WU-B7 -------------------------------/      |
                                                    CP-4
```

각 WU는 별도 구현 세션과 별도 검증 기록을 사용한다. 선행 WU가 없으면 fake 경계로
독립 개발할 수 있는 범위만 수행하고 실제 통합 완료로 표시하지 않는다.

### 15.2 WU별 경계

| WU | 선행조건 | 산출물 | 검증 | 명시적 비산출물 |
|---|---|---|---|---|
| `WU-M1A` | DB 정본·환경 합의 | PostgreSQL·Redis 인스턴스, DDL/DML 계정, health 증거 | 계정별 연결·권한 allow/deny, Redis health | migration SQL·repository·Redis app 코드 변경 |
| `WU-M1B` | WU-M1A, WU-B2 migration | 이름순 실행·재실행 기록, schema version 증거 | 빈 DB·기존 DB upgrade, 재실행, runtime DDL·event 수정 거부 | 적용 migration 수정, 임의 DDL, 실제 DSN 기록 |
| `WU-M2` | CP-0, secret 분리, fake Engine | Streamable HTTP server, initialize·세션 개설 토큰 consume | 정상 initialize, 누락·변조·만료·replay·mismatch 거부 | Resource·Tool, DB·Redis, 게임 판정 |
| `WU-M3` | WU-M2, API 8.2·9.2 | job/subject session, 다섯 Resource adapter | 2×5 허용표, exact schema, agent/GM 비간섭성 | 별도 문서 schema 재정의, Front snapshot 재사용, Tool |
| `WU-M4` | WU-M3, API 8.4·9.3 | 네 Tool, proposal 조립과 Engine adapter | 입력·phase·target·stale·idempotency·응답 유실 | 규칙 판정, DB mutation, GM Tool |
| `WU-M5` | WU-M2~WU-M4 operation/error 경로 | 중앙 allowlist log와 redaction | 성공·거부·예외 marker 캡처, 허용 key 검사 | DB·queue·spool·audit outbox, event_outbox 소비 |
| `WU-M6` | WU-B6·WU-B7, WU-M2~WU-M5, 통합 network | 실제 Backend↔MCP job 왕복 증거 | initialize→consume→Resource→Tool, GM read-only·direct-return, Backend 최종 판정 | 공개 API·DB schema 변경, 유료 Provider 강제 |
| `WU-M7` | WU-M6 정상 경로 | fault/reconnect 결과 | stale·expired·revoked, Engine 장애, restart, fresh reconnect, redaction | 기존 자격 재사용, authoritative cache, MCP fallback 판정 |
| `WU-M8` | WU-M1A·WU-M1B·WU-M2~WU-M7 | 기동·중지·migration·health·TLS·rotation runbook과 release evidence | 제3자 clean 재현, positive·negative·권한·장애 확인 | 실제 secret·DSN 기록, Backend migration 수정 |

### 15.3 WU별 완료 증거

모든 WU 완료 보고는 다음 중 해당 항목을 비밀 없이 남긴다.

- 변경 파일과 각 변경의 정본 근거
- 실행 명령, exit 결과와 focused·회귀 검증 범위
- positive, reject, fault와 noninterference matrix 결과
- fake·실제 dependency 구분과 외부 API 과금 여부
- redaction 캡처와 forbidden marker 검사 결과
- 실제 session roundtrip의 ID·payload·secret 제거 trace
- 인프라 계정 권한과 health 결과
- 생략한 테스트와 위험도 기반 사유

WU-M2~WU-M5는 fake Engine 독립 증거, WU-M6은 실제 Backend 계약, WU-M7은 장애 주입,
WU-M8은 제3자 runbook 재현을 각각 완료 근거로 삼는다.

## 16. 구현 결정 등록부

아래 항목은 확정 정본 밖 구현 세부다. 해당 WU 전에 owner가 결정하고 wire·환경 변수·
파일 구조에 영향이 있으면 정본과 README를 먼저 갱신한다.

| ID | 상태 | 결정 항목 | owner | 적용 WU |
|---|---|---|---|---|
| `OPEN-01` | RESOLVED | `mcp_server` 독립 project, `mafia_game.main` composition root와 package-local lock/test | MCP | WU-M2 |
| `OPEN-02` | RESOLVED | stateful manager, initialize 전 consume, DELETE·terminal cleanup, idle TTL 30초 | MCP·Backend | WU-M2, WU-M7 |
| `OPEN-03` | RESOLVED | 11절과 API 9.3.1절의 고정 HTTP·JSON-RPC 오류 매핑 | 공통 | WU-M2~WU-M4 |

남은 OPEN 항목은 다음과 같다.

| ID | 결정 항목 | owner | 차단 WU | 결정 전 금지 |
|---|---|---|---|---|
| `OPEN-04` | 구조화 log sink와 운영 보존 기간 | 운영·MCP | WU-M5, WU-M8 | payload spool·영속 outbox |
| `OPEN-05` | MCP→Engine TLS 종료·CA·mTLS와 설정 이름 | 운영·공통 | WU-M6, WU-M8 | TLS 검증 우회 |
| `OPEN-06` | MCP liveness/readiness endpoint와 판정 기준 | MCP·운영 | WU-M8 | 임의 공개 health API 추가 |
| `OPEN-07` | 세션 개설 토큰 consume 응답 유실의 Backend 조정 절차 | Backend·MCP | WU-M7 | 소비 token 재사용 |
| `OPEN-08` | session-local context cache 허용 범위 | 공통 | WU-M3, WU-M7 | cross-job·authoritative cache |

남은 `OPEN`은 확정 계약을 약화하지 않는다. 결정 전 기본값은 fail-closed, no cache,
no persistent spool과 fresh credential이다.

## 17. 구현 착수·완료 체크리스트

### 착수

- [ ] 이번 세션의 WU가 하나 이하인가
- [ ] `AGENTS.MD`와 해당 정본·이 설계서를 읽었는가
- [ ] 선행 WU와 필요한 OPEN 결정이 닫혔는가
- [ ] 현재 branch와 사용자 소유 변경을 확인했는가
- [ ] 실제 secret·유료 API 없이 검증할 fake 경계를 준비했는가

### 완료

- [ ] MCP runtime이 DB·Redis·`event_outbox`에 접근하지 않는가
- [ ] Resource validator가 API 8.2절과 일치하고 별도 문서 정본을 만들지 않았는가
- [ ] AI_PLAYER/GM allowlist와 GM Tool 0개를 negative test로 증명했는가
- [ ] job terminal·reconnect에서 capability와 session memory가 폐기되는가
- [ ] proposal retry가 같은 ID·body이고 stale rebase가 없는가
- [ ] 로그가 API 9.4 allowlist만 가지는가
- [ ] 위험도에 맞는 검증 결과와 생략 사유를 기록했는가
- [ ] 루트 README와 package README가 실제 구현 상태·명령과 일치하는가
- [ ] 사용자 승인 없이 commit·push하지 않았는가
