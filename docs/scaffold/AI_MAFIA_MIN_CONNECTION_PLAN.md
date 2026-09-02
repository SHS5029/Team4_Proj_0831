# AI 마피아 최소 인프라 연결 계획 `scaffold-infra-v1`

상태: 구현 착수용 확정 계획

이 문서는 실제 게임 규칙을 구현하기 전에 PostgreSQL, Redis, LLM, SSE가 서로
연결되는지만 검증하기 위한 계획이다. 역할 배정, 승패 판정, 프롬프트 품질,
운영자 기능은 포함하지 않는다. 최소 영속 테이블은
`scaffold_games`, `scaffold_operations`, `scaffold_events`로 고정한다.

## 1. 현재 구현과 목표

현재는 Backend의 게임 저장소가 메모리 기반이며, SSE는 연결 확인용 smoke 응답이다.
MCP는 FastMCP Streamable HTTP 서버로 동작하고, Backend에는 MCP Client와 dummy
game API가 있다. 따라서 기존 API와 MCP 계약을 유지하면서 저장·이벤트·LLM 호출
경로만 실제 연결한다.

목표 구조는 다음과 같다.

```text
Frontend
  └─ Backend REST / SSE
       ├─ PostgreSQL: 게임·operation·event 원본
       ├─ Redis: lock·operation projection·event fan-out
       ├─ LLM Adapter: dummy provider 우선
       └─ MCP Client ── Streamable HTTP ── Game MCP Server
                                             └─ Backend Context Port
```

DB와 Redis는 Backend만 직접 접근한다. MCP는 DB·Redis credential을 갖지 않고
Backend가 제공하는 context projection만 조회한다. LLM Adapter도 Backend에
위치하며 MCP Server는 LLM을 호출하지 않는다. LLM은 proposal만 만들고 최종
상태 변경은 Backend가 수행한다.

## 2. 최소 연결 범위

### 포함

- `scaffold-v1` 게임 생성·조회·`PING` command의 PostgreSQL 저장
- PostgreSQL `scaffold_games`, `scaffold_operations`, `scaffold_events` 저장
- Backend 재시작 후 game, operation, event 조회
- Redis ping, game lock, operation 상태 projection, event publish smoke
- Redis 장애 시 game·operation 조회의 PostgreSQL fallback
- Backend LLM dummy adapter 호출 및 MCP context 조회 왕복
- MCP proposal을 Backend가 수신하고 검증하는 왕복
- DB event 또는 Redis event가 Frontend SSE로 전달되는 흐름
- SSE heartbeat, `Last-Event-ID`, 연결 실패 시 polling fallback

### 제외

- 실제 외부 LLM provider와 비용·품질 최적화
- 실제 마피아 규칙 및 role/private 정보 판정
- MCP의 DB·Redis 직접 접근
- 다중 worker와 고가용성 lock 보장
- 관리자 KPI, 결과, 메모, 평점

## 3. 단계별 구현 계획

### 1단계 — 공통 설정과 연결 수명주기

- `.env`의 `DATABASE_URL`, `REDIS_URL`, `LLM_PROVIDER`, `MAFIA_MCP_URL`,
  `MCP_INTERNAL_SECRET`을 Backend 설정에서 읽는다.
- 앱 시작 시 PostgreSQL pool, Redis client, MCP client를 생성하고 종료 시 정리한다.
- `/health`는 process liveness로 유지하고, DB·Redis·MCP 상태는 별도 dependency
  health 결과로 구분한다.
- `LLM_PROVIDER=dummy`를 기본값으로 하여 외부 API key 없이 연결 테스트를 가능하게 한다.

완료 기준: 잘못된 DB·Redis 설정은 명확한 오류를 내고, dummy 설정에서는 Backend가
기동·종료되며 secret이 로그에 출력되지 않는다.

### 2단계 — PostgreSQL 원본 저장

- 기존 [002 migration](../../backend/migrations/002_create_scaffold_game_schema.sql)을
  실제 실행 경로에 포함한다.
- migration에 `scaffold_events` 테이블을 추가한다. 필드는 `id`, `game_id`,
  `sequence`, `event_type`, `payload`, `state_version`, `created_at`이며
  `(game_id, sequence)`를 UNIQUE로 둔다.
- `scaffold_games`, `scaffold_operations`, `scaffold_events`의 최소 row를
  저장·조회하는 PostgreSQL repository를 추가한다. 실제 참가자·역할은 이 단계에
  저장하지 않으므로 `game_players`는 후속 `basic-v1` 단계로 미룬다.
- 한 command transaction은 `scaffold_games` 조회 및 version 검증, event 추가,
  operation 갱신을 하나의 transaction으로 처리한다.
- commit 전에는 SSE나 Redis event를 발행하지 않는다.
- 기존 in-memory repository는 테스트 fake로만 남기고 기본 실행 저장소에서 제외한다.

완료 기준: 게임 생성 → Backend 재시작 → game·operation·event 조회가 성공하고,
동일 `game_id`와 `sequence`의 event가 중복 저장되지 않는다.

### 3단계 — Redis 보조 연결

- Redis adapter를 추가하여 다음 최소 기능만 구현한다.

| 기능 | key | 목적 |
|---|---|---|
| lock | `team4:game:{game_id}:lock` | 동시에 같은 game command 실행 방지 |
| operation | `team4:operation:{operation_id}:status` | 빠른 상태 조회 |
| event | `team4:game:{game_id}:events` | SSE 전달용 임시 fan-out |

- lock은 `SET NX EX`와 소유 token으로 획득·해제한다.
- operation과 event payload는 JSON으로 직렬화하고 TTL을 적용한다.
- Redis 장애·timeout 시 game과 operation은 PostgreSQL에서 조회한다.
- Redis에는 seed, 전체 snapshot, private role을 저장하지 않는다.

Redis event는 영구 queue가 아니라 실시간 fan-out 보조 수단이다. 누락된 event의
원본은 항상 PostgreSQL `scaffold_events`에서 조회한다.

완료 기준: Redis가 실행 중이면 lock·operation·event가 기록되고, Redis를 중지해도
game GET과 operation GET은 PostgreSQL로 성공한다.

### 4단계 — LLM·MCP 최소 왕복

- Backend의 `LLM Adapter`는 우선 deterministic dummy response를 반환한다.
- Backend MCP Client는 `game_get_context`와 `game_submit_proposal`만 호출한다.
- MCP Server는 DB·Redis를 조회하지 않고 Backend Context Port를 호출한다.
- Context Port는 `game_id`, `viewer_player_id`, `state_version`을 검증하고
  dummy 공개 context를 반환한다.
- LLM proposal에는 `action`, `target_player_id`(선택), `source_state_version`을
  포함한다.
- 호출 순서는 `LLM Adapter → MCP Client → game_get_context → LLM Adapter의
  proposal 생성 → Backend 검증`으로 고정한다. MCP Server 내부에는 LLM Adapter를
  두지 않는다.
- Backend는 proposal을 받아 version·action·소유권만 검증한 뒤 실제 game 상태를
  변경하지 않고 receipt만 저장한다.

완료 기준: Backend LLM dummy → MCP Client → MCP Context Port → Backend proposal
검증 → receipt 왕복이 성공하며, MCP 중단 시 게임 원본 데이터는 변경되지 않는다.

### 5단계 — Redis event와 SSE

- Backend transaction commit 후에만 Redis event를 publish한다.
- SSE 연결 시 Redis fan-out 구독을 먼저 시작한 뒤 `Last-Event-ID` 이후의
  PostgreSQL event를 replay한다. replay와 실시간 수신 사이의 중복은
  `game_id + sequence` 기준으로 제거한다.
- SSE event의 `id`는 `scaffold_events.sequence`, `event`는 `game.state_changed`로
  고정한다.
- 30초마다 heartbeat를 보내고, Frontend는 45초 무응답 시 재연결한다.
- Redis를 사용할 수 없으면 짧은 주기의 PostgreSQL event polling으로 fallback한다.
- Frontend의 연결 상태는 `connected`, `reconnecting`, `polling`, `error`로 표시한다.

SSE 수신자는 마지막으로 정상 처리한 sequence를 `Last-Event-ID`로 재전송한다.
서버는 중복 전송을 보장하지 않으며, Frontend는 이미 처리한 동일 sequence를
화면 상태에 다시 적용하지 않는다. Redis에서 sequence가 누락되면 PostgreSQL
event를 재조회한다.

완료 기준: `PING` command 후 Frontend가 event를 수신하고, 연결을 끊었다가
`Last-Event-ID`로 재연결하면 누락된 event를 빠짐없이 수신하며 동일 sequence를
중복 적용하지 않는다.

## 4. 최소 파일 범위

기존 파일을 대규모로 재구성하지 않고 다음 모듈만 추가·연결한다.

| 위치 | 책임 |
|---|---|
| `backend/app/infrastructure/postgres/` | pool·transaction·repository adapter |
| `backend/app/infrastructure/redis/` | Redis client·lock·projection·publish |
| `backend/app/llm/` | dummy LLM adapter와 공통 proposal interface |
| `backend/app/mcp/` | MCP client와 Context/Proposal port |
| `backend/app/routers/` | health·SSE·기존 scaffold API 연결 |
| `backend/tests/` | DB·Redis·MCP·SSE contract test |
| `frontend_user/core/` | SSE client와 polling fallback |
| `frontend_user/app_pages/` | 연결 상태와 event 표시 |

MCP 서버는 현재 FastMCP 실행 구조를 유지하고, 실제 DB·Redis 모듈은 추가하지 않는다.

## 5. 최소 검증 시나리오

```text
PostgreSQL migration
→ Backend 기동
→ Redis ping
→ MCP initialize
→ game 생성
→ game row 저장 확인
→ PING command
→ operation/event 저장
→ Redis publish
→ Frontend SSE 수신
→ SSE 재연결 및 Last-Event-ID replay
→ Backend 재시작 후 game/operation 조회
→ Redis 중단 후 PostgreSQL fallback
```

외부 LLM은 사용하지 않고 dummy adapter로 검증한다. 실제 MCP SDK가 설치된 환경에서는
MCP 통합 테스트를 실행하며, SDK가 없는 환경에서는 해당 테스트를 skip하고 나머지
계약 테스트를 실행한다.

## 6. 최종 완료 기준

- PostgreSQL에 저장된 game이 Backend 재시작 후 유지된다.
- Redis가 lock·operation·event 보조 기능을 수행한다.
- Redis 장애 시 원본 조회가 중단되지 않는다.
- Backend의 dummy LLM이 MCP를 통해 context를 받고 proposal을 반환한다.
- Backend만 proposal을 검증하고 상태 변경 권한을 가진다.
- Frontend가 SSE event와 heartbeat를 수신한다.
- SSE 재연결 시 `Last-Event-ID` 이후 event를 replay한다.
- Frontend는 이미 처리한 동일 `game_id + sequence` event를 중복 적용하지 않는다.
- 모든 검증은 secret 없이 local dependency 또는 fake/dummy provider로 재현된다.

이 완료 기준을 통과한 뒤에만 실제 LLM provider, basic-v1 규칙, role, 결과 기능을
착수한다.
