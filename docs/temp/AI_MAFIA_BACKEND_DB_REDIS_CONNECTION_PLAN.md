# AI 마피아 Backend–DB·Redis 연결 구현 계획서

**문서 상태:** Integration MVP의 2번 임시 실행 계획
**작성일:** 2026-09-04
**선행 단위:** Frontend–Backend 연결 구현
**후속 단위:** Backend–LLM 연결, Backend–MCP 연결

이 문서는 PostgreSQL과 Redis를 Backend에 연결하고 실제 왕복·장애·복구를 증명하기
위한 임시 계획이다. DB schema, API, Redis key, 보존 정책의 정본을 대체하지 않는다.
계약을 변경해야 할 경우 [DB 설계 정본](../개발상세플랜/AI_MAFIA_DB_DESIGN.md),
[API 정본](../개발상세플랜/AI_MAFIA_API_SPEC.md)과 섹터 간 합의를 먼저 갱신한다.
한 coding AI 세션은 이 계획의 WU 하나만 수행한다.

## 1. 목표

Frontend 요청을 받은 Backend가 PostgreSQL을 영구 원본으로 사용하고, Redis를 짧은
잠금·공개 projection cache·event fan-out 보조 계층으로 사용하는 것을 실제 process
환경에서 확인한다.

```text
Frontend
  → Backend 공개 API
  → PostgreSQL transaction
       ├─ game state
       ├─ state_version
       ├─ event
       ├─ command receipt
       └─ event_outbox
  → Redis lock/cache/stream
  → Backend 응답 또는 SSE/polling sync
```

이번 단위의 완료는 게임 규칙이나 Agent가 완성되었다는 뜻이 아니다. 실제 Engine·LLM·
MCP 연결 없이도 DB와 Redis 경계가 올바르게 동작하는지 확인하는 단계다.

## 2. 책임과 경계

### Backend 소유

- PostgreSQL schema에 대응하는 forward-only migration SQL
- PostgreSQL connection, transaction, repository, row mapping
- Redis client, game lock, public cache, event stream, outbox publisher
- DB·Redis 오류를 API 오류와 readiness 상태로 변환
- synthetic/fake 테스트와 실제 연결 smoke 실행 명령

### MCP/Data 운영 소유

- PostgreSQL·Redis process 기동·중지
- DB, DDL migrator, DML runtime 계정과 권한 준비
- Backend가 작성한 migration의 이름순 실행·재실행
- 실제 연결 URL을 비밀 채널로 전달하고 health 결과 공유

MCP runtime과 Frontend는 PostgreSQL·Redis에 직접 접근하지 않는다. MCP runtime은
후속 단위에서 Backend 내부 API만 호출한다.

## 3. 정합성 원칙

1. PostgreSQL이 사용자, 게임 상태, 비공개 역할, 행동, 이벤트와 결과의 원본이다.
2. Redis 자료는 모두 PostgreSQL에서 재생성할 수 있어야 한다.
3. 상태 변경, `state_version`, event, receipt, outbox는 하나의 PostgreSQL
   transaction에서 함께 확정한다.
4. Redis lock만으로 중복 mutation을 막지 않는다. PostgreSQL row lock, unique 제약,
   idempotency receipt가 최종 방어선이다.
5. 외부 LLM·MCP 호출 중에는 PostgreSQL transaction이나 Redis game lock을 유지하지
   않는다.
6. Redis 장애가 PostgreSQL 원본의 commit/rollback을 바꾸지 않도록 한다.

## 4. 현재 코드와 이번 단위의 처리

| 영역 | 현재 코드 | 이번 단위 처리 |
|---|---|---|
| PostgreSQL | `infrastructure/postgres.py`, `transaction.py`, repository 다수 | 실제 DB 연결과 canonical table 조회·저장 확인 |
| Migration | `backend/migrations/001~004` | 기존 파일 수정 없이 빈 DB·기존 DB 재실행 검증 |
| Redis lock | `infrastructure/redis/lock.py` | 실제 acquire/release와 token 보호 확인 |
| Redis cache | `infrastructure/redis/cache.py` | 공개 projection만 저장·조회·TTL 확인 |
| Redis stream | `infrastructure/redis/streams.py` | event ID batch fan-out과 bounded trim 확인 |
| Outbox | `outbox_repository.py`, `outbox_service.py` | commit 이후 publish, 실패 재처리 확인 |
| Health | `routers/health_router.py` | PostgreSQL·Redis readiness 실제 응답 확인 |
| Legacy Redis | `infrastructure/redis/scaffold.py` | 호환 경로만 유지, canonical 기능에 재사용하지 않음 |

## 5. 권장 의존 방향

```text
Router
  → Application Service
    → Repository / Transaction Manager
      → PostgreSQL
    → Redis lock/cache/stream
      → event_outbox publisher
```

- Router는 입력·응답 envelope와 HTTP status만 담당한다.
- Service는 소유권, state version, transaction 순서와 Redis 보조 동작을 조정한다.
- Repository는 SQL과 row mapping만 담당한다.
- Redis adapter는 key, TTL, token 검증과 serialization만 담당한다.
- PostgreSQL transaction 안에서 Redis network 호출을 필수 성공 조건으로 만들지 않는다.

## 6. 구현 단위

### WU-BR-01 — 환경·접속·readiness 확인

대상:

- `backend/app/core/config.py`
- `backend/app/infrastructure/postgres.py`
- `backend/app/routers/health_router.py`
- `backend/app/infrastructure/redis/*`

작업:

- Backend runtime의 PostgreSQL·Redis 환경 변수와 기본값을 확인한다.
- PostgreSQL `SELECT 1`, Redis `PING`을 실제 process에 수행한다.
- `/health`는 process 상태, `/ready`는 PostgreSQL·Redis 준비 상태를 반환한다.
- 실제 비밀번호·DSN·secret은 문서와 로그에 남기지 않는다.

완료 기준:

- 정상 환경에서 두 dependency가 `ok`로 표시된다.
- PostgreSQL 또는 Redis 하나가 중단되면 `/ready`가 준비되지 않은 상태를 반환한다.
- Backend가 migration 전용 DSN을 runtime 환경에서 사용하지 않는다.

### WU-BR-02 — Migration·계정·권한 검증

대상:

- `backend/migrations/001~004`
- `backend/app/infrastructure/migrations.py`
- DB 설계 정본의 migration 검증 query

작업:

- 빈 DB에 migration을 이름순으로 적용한다.
- 기존 DB에 같은 migration을 재실행해 멱등성을 확인한다.
- canonical table, FK, CHECK, unique index와 seed 수를 검증한다.
- DDL migrator와 DML runtime 계정의 허용·거부 권한을 확인한다.
- 적용된 migration 파일은 수정하지 않는다. 변경이 필요하면 새 번호의 forward-only
  migration과 정본 합의를 별도로 만든다.

완료 기준:

- 빈 DB와 기존 DB upgrade가 모두 성공한다.
- migration 재실행이 중복 데이터나 오류를 만들지 않는다.
- runtime 계정이 schema 변경을 수행하지 못하고 필요한 DML만 수행한다.

### WU-BR-03 — Canonical Repository 실제 왕복

대상:

- `user_repository.py`
- `scenario_repository.py`
- `game_repository.py`
- `player_repository.py`
- `action_repository.py`
- `event_repository.py`
- `receipt_repository.py`
- `snapshot_repository.py`
- `agent_repository.py`
- `outbox_repository.py`

작업:

- synthetic UUID와 seed 데이터를 사용해 생성·조회·수정·삭제 경계를 확인한다.
- row mapping 결과가 API가 허용한 public/me/private projection을 넘지 않는지 확인한다.
- repository가 입력 문자열을 SQL 문장으로 조합하지 않고 bound parameter를 사용하는지
  점검한다.
- role, scenario fact, action submission, event가 다른 게임으로 섞이지 않는지 확인한다.

완료 기준:

- canonical table의 생성·조회·row lock·event 저장 왕복이 실제 PostgreSQL에서 성공한다.
- 다른 user/game의 데이터가 조회되지 않는다.
- repository 단위 테스트와 실제 DB smoke 결과가 모두 남는다.

### WU-BR-04 — Transaction·Idempotency·Concurrency

대상:

- `backend/app/infrastructure/transaction.py`
- 관련 game/command/receipt/event/outbox service와 repository

작업:

- 게임 생성 transaction에서 state, initial event, receipt, outbox를 함께 commit한다.
- command transaction에서 `idempotency key`와 `expected_state_version`을 검증한다.
- 동일 요청 동시 실행, stale version, 중간 repository 실패를 재현한다.
- 실패 시 상태·event·receipt·outbox가 모두 rollback되는지 확인한다.

완료 기준:

- 동일 idempotency 요청은 한 번만 mutation을 확정한다.
- 동시 command 중 하나만 성공하고 나머지는 명시된 busy/stale 오류가 된다.
- 실패 transaction 뒤 재시도가 데이터 중복 없이 성공한다.

### WU-BR-05 — Redis Lock·Public Cache

대상:

- `backend/app/infrastructure/redis/lock.py`
- `backend/app/infrastructure/redis/cache.py`

작업:

- `mafia:v1:lock:game:{game_id}` key와 bounded TTL을 사용한다.
- lock release 시 소유 token이 일치할 때만 삭제한다.
- `mafia:v1:public:{game_id}:{state_version}`에 공개 projection만 저장한다.
- TTL 만료와 malformed JSON을 cache miss로 처리한다.
- Redis lock 실패가 성공한 mutation으로 위장되지 않는지 확인한다.

완료 기준:

- 같은 game lock 동시 획득은 하나만 성공한다.
- 다른 token으로 lock을 삭제할 수 없다.
- Redis cache가 없어져도 PostgreSQL snapshot으로 응답을 재구성한다.
- private role, seed, prompt, raw LLM response가 Redis에 저장되지 않는다.

### WU-BR-06 — Outbox·Event Stream Fan-out

대상:

- `backend/app/repositories/outbox_repository.py`
- `backend/app/services/outbox_service.py`
- `backend/app/infrastructure/redis/streams.py`
- event/sync service

작업:

- PostgreSQL commit 후에만 outbox event를 Redis stream으로 publish한다.
- stream에는 `front_sequence`와 event ID batch pointer만 넣는다.
- publish 실패는 outbox row를 삭제하지 않고 retry 가능한 상태로 남긴다.
- 중복 publish와 Redis stream trim 뒤 PostgreSQL backfill을 확인한다.
- wakeup pub/sub 유실 시 DB polling으로 복구한다.

완료 기준:

- rollback된 event가 Redis에 발행되지 않는다.
- Redis stream을 놓쳐도 `/sync`가 PostgreSQL event로 복구된다.
- 중복 event는 Front sync 계층에서 deduplicate할 수 있는 sequence를 유지한다.

### WU-BR-07 — Backend–PostgreSQL–Redis 실제 통합 검증

선행 조건: `WU-BR-01`부터 `WU-BR-06`까지의 focused 검증 완료

작업:

- 실제 PostgreSQL·Redis를 기동한 상태에서 Backend를 실행한다.
- Frontend 연결 단위에서 사용하는 `/health`, `/ready`, 게임 생성·조회·sync API를
  실제 HTTP로 호출한다.
- 하나의 mutation에 대해 PostgreSQL commit, outbox 기록, Redis cache/stream 결과를
  함께 확인한다.
- Redis 중단, PostgreSQL 중단, outbox publish 실패를 각각 주입한다.
- 복구 후 PostgreSQL 원본에서 snapshot/event를 재구성한다.

최종 완료 기준:

- Backend 공개 API → PostgreSQL → Redis → sync 응답 왕복이 실제 process로 재현된다.
- Redis 장애가 영구 상태를 손상시키지 않는다.
- PostgreSQL 장애나 transaction 실패가 부분 성공을 만들지 않는다.
- 실제 secret·DSN을 출력하지 않고 재현 가능한 실행 명령과 결과만 기록한다.

## 7. Redis key와 데이터 보안

| 용도 | key | 저장 내용 | 원본 |
|---|---|---|---|
| 게임 lock | `mafia:v1:lock:game:{game_id}` | 무작위 소유 token | PostgreSQL 정합성 |
| 공개 cache | `mafia:v1:public:{game_id}:{state_version}` | 공개 snapshot JSON | PostgreSQL snapshot/event |
| event stream | `mafia:v1:events:{game_id}` | sequence와 event ID 배열 | PostgreSQL game_events |
| outbox wakeup | `mafia:v1:outbox:wakeup` | outbox ID 힌트 | PostgreSQL event_outbox |
| health | `mafia:v1:health` | synthetic marker | health check |

Redis에 평문으로 저장하지 않는 값:

- role, scenario fact, private context, seed
- LLM prompt와 raw response
- DB password, API key, internal secret
- 다른 사용자의 식별 가능한 상세 정보

## 8. 테스트 계획

### 자동 테스트

- PostgreSQL repository는 fake cursor와 bound parameter 검증을 유지한다.
- Transaction은 commit/rollback, 중복 요청, 동시성 대역을 검증한다.
- Redis는 FakeRedis로 lock token, TTL, malformed cache, stream field를 검증한다.
- 장애 테스트는 DB error, Redis error, publish error와 재시도를 포함한다.

### 실제 smoke

- `SELECT 1`, migration 상태, canonical table 접근
- Redis `PING`, lock acquire/release, cache set/get, stream publish
- Backend `/health`, `/ready`, game create/read/sync HTTP 왕복
- Redis flush 후 PostgreSQL에서 snapshot/event 재구성

자동 테스트는 비밀정보와 외부 유료 서비스를 사용하지 않는다. 실제 DB·Redis smoke의
접속 값과 계정 정보는 완료 보고에 기록하지 않는다.

## 9. 다음 단위와의 인계

이 단위에서는 LLM 호출과 MCP session/tool을 구현하지 않는다. 다음 단위가 사용할
Backend 경계는 다음으로 고정한다.

```text
Agent/LLM/MCP 외부 호출
  → Backend 내부 service
  → PostgreSQL의 agent_jobs/capabilities/proposals
  → transaction + event_outbox
  → Redis는 lock/cache/fan-out 보조
```

다음 단위에서 Agent job을 추가할 때도 외부 호출 중 DB transaction과 Redis game lock을
점유하지 않으며, 늦은 결과는 lease/fencing token과 state version으로 거부한다.
