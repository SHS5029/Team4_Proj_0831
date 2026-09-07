# AI 마피아 MVP DB·Redis 설계서

**상위 계약:** [AI_MAFIA_MASTER_PLAN.md](AI_MAFIA_MASTER_PLAN.md)

**API 계약:** [AI_MAFIA_API_SPEC.md](AI_MAFIA_API_SPEC.md)

**대상 버전:** `mystery-v1` / `scenario-v1`

이 문서는 PostgreSQL 영구 원본, Redis 파생 상태, transaction, lock, idempotency,
보존과 migration 계약의 유일한 정본이다. 컬럼명이나 제약을 바꾸면 API schema와
게임 엔진 fixture를 같은 변경에서 갱신한다.

## 1. 설계 원칙

- PostgreSQL이 사용자, 게임 상태, 비공개 역할, 행동, 이벤트와 확정 결과의 원본이다.
- Redis는 lock, 공개 projection cache와 event fan-out만 담당한다. Redis 자료는
  언제든 PostgreSQL에서 재구성할 수 있어야 한다.
- Frontend와 MCP runtime은 PostgreSQL·Redis에 직접 접근하지 않는다.
- client가 관찰할 수 있는 game state mutation은 한 게임 행을 잠그고 하나의
  PostgreSQL transaction에서 상태, `state_version`, event, command receipt와
  outbox를 함께 commit한다. Agent reservation이나 다른 AI의 미해소 비공개 제출처럼
  client projection을 바꾸지 않는 내부 기록은 `state_version`을 올리지 않는다.
- 외부 LLM·MCP·HTTP 호출 중 DB transaction이나 Redis game lock을 유지하지 않는다.
- 서버 RNG 결과는 생성 즉시 영구 저장하고 같은 논리 작업에서 다시 추첨하지 않는다.
- UUID `user_id`는 사용자 구분값일 뿐 인증 증명이 아니다.
- LLM token·비용·timeout 설정과 사용량 테이블은 MVP schema에 넣지 않는다.

## 2. 식별자·시각·버전 규칙

2026-09-07 이전 밤 저장값의 호환은 `phase=NIGHT_ACTION`, `1 <= day_number <= 5`,
`round=day_number-1` 조합에만 적용한다. 읽기·엔진 복원에서 `round=day_number`로
해석하고 다음 정상 쓰기에서 저장값을 정규화한다. 기존 window UUID의 제출과
deadline·과거 원장은 보존한다. 그 외 과거 상태의 밤 번호나 행동을 추정하거나
일괄 migration하지 않는다. 신규 게임은 첫 밤 진입부터 round 1을 저장한다.

| 항목 | 계약 |
|---|---|
| 기본 ID | PostgreSQL `uuid`, 서버 생성 객체는 `gen_random_uuid()` |
| `user_id` | 브라우저가 생성한 UUID v4, API와 domain에서 version까지 검증 |
| 시각 | `timestamptz`, PostgreSQL `CURRENT_TIMESTAMP`, UTC 직렬화 |
| 문자열 enum | `text` 또는 `varchar`와 `CHECK`, 대문자 고정 값 |
| 상태 버전 | 게임별 양의 `bigint`, client-visible 상태 전이 commit당 정확히 1 증가 |
| 내부 이벤트 순서 | 게임별 양의 `bigint`, `(game_id, sequence)` unique, API 비노출 |
| Front batch 순서 | 게임별 양의 `bigint`, client-visible transaction마다 1 증가 |
| payload | version이 있는 JSON object만 허용, 임의 raw model 출력 금지 |

`state_version`은 화면 동기화와 optimistic concurrency의 기준이다. 이벤트가 여러 개
생겨도 한 command transaction의 결과라면 같은 결과 `state_version`을 가질 수 있다.
`sequence`는 모든 내부 event에서 증가하지만 Front에 노출하지 않는다. 사용자에게
보이는 PUBLIC event와 인간 본인의 PLAYER event에는 client-visible transaction 단위의
연속 `front_sequence`와 그 batch 안의 `operation_index`를 배정한다. 다른
Agent의 private event는 둘 다 NULL이므로 sequence gap이나 활동 timing을 노출하지
않는다.

## 3. 관계 개요

```text
users 1 --- N games 1 --- N game_players
                  |          |--- N player_scenario_facts
                  |          |--- N action_submissions
                  |
                  |--- N action_windows
                  |          |--- 0..1 action_window_resolutions
                  |--- N agent_jobs --- N agent_capabilities
                  |--- N game_events --- 0..1 event_outbox
                  |--- N command_receipts
                  |--- N game_snapshots
                  |--- 0..1 game_feedback per user

scenario_catalog 1 --- N scenario_templates
agent_personas 1 --- N game_players
internal_request_nonces: 내부 인증 replay 원장
```

## 4. PostgreSQL schema

아래 표는 목표 logical schema다. 실제 migration은 같은 제약을 SQL로 구현하고
repository가 DB 오류를 공개 API 오류 코드로 변환한다.

### 4.1 `users`

UUID만으로 사용자를 구분하는 최소 레코드다.

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK, API에서 받은 UUID v4, DB default 없음 |
| `created_at` | `timestamptz` | NOT NULL, 최초 쓰기 시각 |
| `last_seen_at` | `timestamptz` | NOT NULL, 최근 성공 요청 시각 |

- 이메일, 표시명, avatar, provider subject, password, 사용자 role을 저장하지 않는다.
- 최초 쓰기 요청은 `INSERT ... ON CONFLICT (id) DO UPDATE`로 `last_seen_at`만 갱신한다.
- 읽기 요청의 알 수 없는 UUID는 사용자를 암묵 생성하지 않고 빈 목록 또는 소유권
  없음으로 처리한다.
- 관리자 UUID는 DB role이 아니라 Backend의 `ADMIN_USER_IDS` 설정에서 관리한다.

현재 `001_create_oauth_schema.sql`이 만든 추가 프로필 컬럼과
`oauth_identities`는 전환 완료 전까지 legacy object로만 존재할 수 있다. 새 코드가
읽거나 쓰지 않으며, 실제 데이터 보존 여부를 확인한 순방향 cleanup migration에서
제거한다. 기존 적용 이력이 있는 migration 파일 자체는 수정하지 않는다.

### 4.2 `scenario_catalog`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `varchar(64)` | PK, 고정 scenario ID |
| `version` | `varchar(32)` | NOT NULL, `scenario-v1` |
| `title` | `varchar(120)` | NOT NULL |
| `background` | `text` | NOT NULL, 공개 사건 설명 |
| `victim` | `varchar(120)` | NOT NULL |
| `locations` | `jsonb` | NOT NULL, 4~5개 문자열 배열 |
| `active` | `boolean` | NOT NULL |
| `content_hash` | `char(64)` | NOT NULL, 승인 콘텐츠 checksum |
| `approved_at` | `timestamptz` | NULL이면 배포 후보에서 제외 |
| `created_at` | `timestamptz` | NOT NULL |

`UNIQUE(version, id)`를 둔다. `locations`는 JSON array, 원소 1~80자, 전체 4~5개를
seed loader와 테스트에서 검증한다.

### 4.3 `scenario_templates`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `scenario_id` | `varchar(64)` | FK `scenario_catalog(id)`, RESTRICT |
| `template_kind` | `varchar(16)` | `ALIBI` 또는 `OBSERVATION` |
| `template_key` | `varchar(64)` | 시나리오 안에서 안정적인 key |
| `text_template` | `varchar(240)` | NOT NULL, 한 문장 |
| `subject_mode` | `varchar(16)` | `NONE`, `SEAT`, `ANONYMOUS` |
| `active` | `boolean` | NOT NULL |
| `created_at` | `timestamptz` | NOT NULL |

- `UNIQUE(scenario_id, template_kind, template_key)`를 둔다.
- 각 scenario는 활성 `ALIBI` 9개 이상, `OBSERVATION` 9개 이상이어야 한다.
- `subject_mode=SEAT`이면 template에 검증된 좌석 placeholder가 하나 있어야 한다.
- role, faction 또는 범인을 직접 나타내는 필드는 두지 않는다.

### 4.4 `agent_personas`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `varchar(64)` | PK, 안정적인 preset ID |
| `version` | `varchar(32)` | NOT NULL |
| `display_name` | `varchar(40)` | NOT NULL |
| `speech_style` | `varchar(240)` | NOT NULL |
| `backstory` | `varchar(500)` | NOT NULL |
| `parameters` | `jsonb` | NOT NULL, 승인된 10개 수치 field |
| `active` | `boolean` | NOT NULL |
| `content_hash` | `char(64)` | NOT NULL |
| `created_at` | `timestamptz` | NOT NULL |

수치 field는 모두 0.0~1.0이며 `reasoning_skill`은 `mystery-v1` preset 전체에서 같은
값이어야 한다. seed loader와 테스트가 key 누락·추가 및 범위를 검증한다.

### 4.5 `games`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK, 서버 생성 |
| `owner_user_id` | `uuid` | NOT NULL, FK `users(id)`, RESTRICT |
| `status` | `varchar(16)` | `IN_PROGRESS`, `SAVED`, `COMPLETED`, `FAILED` |
| `phase` | `varchar(32)` | 허용 phase enum |
| `round` | `smallint` | 0~5, 현재 또는 마지막 밤 번호 |
| `day_number` | `smallint` | 1~6 |
| `state_version` | `bigint` | NOT NULL, 1 이상 |
| `next_event_sequence` | `bigint` | NOT NULL, 다음 sequence, 1 이상 |
| `next_front_sequence` | `bigint` | NOT NULL, 인간 Front용 다음 batch sequence |
| `player_count` | `smallint` | 6~9 |
| `mafia_count` | `smallint` | 인원별 역할표와 일치 |
| `ruleset_version` | `varchar(32)` | `mystery-v1` |
| `scenario_version` | `varchar(32)` | `scenario-v1` |
| `scenario_id` | `varchar(64)` | FK `scenario_catalog(id)`, RESTRICT |
| `scenario_content_hash` | `char(64)` | 생성 당시 승인 콘텐츠 hash |
| `seed_ciphertext` | `bytea` | NOT NULL, AES-256-GCM ciphertext |
| `seed_nonce` | `bytea` | NOT NULL, game별 고유 nonce |
| `seed_key_id` | `varchar(64)` | NOT NULL, 암호화 key 식별자 |
| `agent_config_version` | `varchar(64)` | NOT NULL, prompt·model 조합 버전 |
| `fast_forward_enabled` | `boolean` | NOT NULL, 기본 false, 인간 사망 뒤만 true |
| `winner` | `varchar(16)` | NULL 또는 `CITIZEN`, `MAFIA` |
| `win_reason` | `varchar(32)` | NULL 또는 표준·최종 판정 코드 |
| `saved_at` | `timestamptz` | NULL 또는 저장 시각 |
| `finished_at` | `timestamptz` | NULL 또는 최초 종료 commit 시각 |
| `created_at` | `timestamptz` | NOT NULL |
| `updated_at` | `timestamptz` | NOT NULL |

허용 `phase`:

```text
ROLE_REVEAL
DAY_DISCUSSION
NIGHT_ACTION
DAY_VOTE
REVOTE
FINAL_DISCUSSION
FINAL_ACCUSATION
ENDED
```

제약:

- `status=COMPLETED`이면 `phase=ENDED`, `winner`, `win_reason`, `finished_at`이 모두
  NOT NULL이다.
- `status=SAVED`이면 열려 있던 window의 `deadline_at`은 NULL이다. timed window만
  `remaining_ms_on_save`가 NOT NULL이고 untimed 발언 window는 NULL을 유지한다.
- `status=IN_PROGRESS`인 동안 `finished_at`은 NULL이다.
- `fast_forward_enabled=true`이면 인간 player가 사망 상태여야 한다.
- `finished_at`은 최초 종료 transaction에서만 설정하고 replay로 변경하지 않는다.
- `idx_games_owner_updated(owner_user_id, updated_at DESC, id DESC)`를 둔다.
- `idx_games_status_updated(status, updated_at DESC)`는 관리자 목록에 사용한다.

### 4.6 `game_players`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK, 서버 생성 player ID |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `user_id` | `uuid` | 인간 좌석만 FK `users(id)`, AI는 NULL |
| `kind` | `varchar(8)` | `HUMAN` 또는 `AI` |
| `seat` | `smallint` | 1~9 |
| `display_name` | `varchar(40)` | 게임 안의 표시명 |
| `role` | `varchar(16)` | `MAFIA`, `DETECTIVE`, `DOCTOR`, `CITIZEN` |
| `faction` | `varchar(16)` | `MAFIA` 또는 `CITIZEN` |
| `alive` | `boolean` | NOT NULL |
| `persona_id` | `varchar(64)` | AI만 FK `agent_personas(id)`, 인간은 NULL |
| `eliminated_phase` | `varchar(32)` | NULL 또는 탈락 phase |
| `eliminated_round` | `smallint` | NULL 또는 1~5 |
| `created_at` | `timestamptz` | NOT NULL |
| `updated_at` | `timestamptz` | NOT NULL |

- `UNIQUE(game_id, seat)`와 `UNIQUE(game_id, id)`를 둔다.
- `UNIQUE(game_id, user_id) WHERE user_id IS NOT NULL`을 둔다.
- 게임마다 `kind=HUMAN`이 정확히 한 행인지 생성 transaction과 검증 query에서
  확인한다.
- `kind=HUMAN`이면 `user_id`가 있고 `persona_id`는 없다. AI는 그 반대다.
- role은 API projection layer를 통과하기 전 비공개 field로 취급한다.

### 4.7 `player_scenario_facts`

게임 생성 시 결정된 개인 문장을 snapshot으로 고정한다.

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `player_id` | `uuid` | FK `game_players(id)`, CASCADE |
| `fact_kind` | `varchar(16)` | `ALIBI` 또는 `OBSERVATION` |
| `template_id` | `uuid` | FK `scenario_templates(id)`, RESTRICT |
| `rendered_text` | `varchar(240)` | 생성 당시 확정 문장 |
| `subject_player_id` | `uuid` | 명시 대상 관찰만, 같은 game player |
| `created_at` | `timestamptz` | NOT NULL |

`UNIQUE(game_id, player_id, fact_kind)`로 좌석별 각 한 건을 보장한다. 익명 관찰은
`subject_player_id=NULL`을 유지하며 런타임에 임의 이름을 붙이지 않는다.
`(game_id, player_id)`와 `(game_id, subject_player_id)`는 각각
`game_players(game_id, id)`를 참조하는 복합 FK다.

### 4.8 `action_windows`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `window_kind` | `varchar(24)` | `SPEECH`, `NIGHT`, `VOTE`, `REVOTE`, `FINAL_VOTE` |
| `phase` | `varchar(32)` | 생성 당시 phase |
| `round` | `smallint` | 0~5 |
| `cycle` | `smallint` | 현재 MVP에서는 기본 순환 1만 사용 |
| `turn_player_id` | `uuid` | 개별 발언 차례만 설정 |
| `opened_state_version` | `bigint` | window를 연 버전 |
| `status` | `varchar(16)` | `OPEN`, `PAUSED`, `RESOLVING`, `RESOLVED`, `CANCELLED` |
| `opened_at` | `timestamptz` | NOT NULL |
| `deadline_at` | `timestamptz` | 발언 외 window의 서버 마감, 저장 중 NULL |
| `remaining_ms_on_save` | `integer` | timed window 저장에만 설정, 0 이상 |
| `resolved_at` | `timestamptz` | NULL 또는 확정 시각 |

- 게임당 `status IN ('OPEN','PAUSED','RESOLVING')`인 window는 하나만 허용하는 부분 unique
  index를 둔다.
- `UNIQUE(game_id, id)`와 `(game_id, turn_player_id) -> game_players(game_id, id)`
  복합 FK로 다른 게임 player가 발언 차례에 들어가지 못하게 한다.
- 밤은 20초, 투표 계열은 30초다. DB가 초 단위를 설정값으로 저장하지 않고 실제
  `opened_at`·`deadline_at`을 원본으로 보존한다.
- `status=OPEN`인 window만 제출을 받는다.

### 4.9 `action_submissions`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `window_id` | `uuid` | FK `action_windows(id)`, CASCADE |
| `actor_player_id` | `uuid` | FK `game_players(id)`, CASCADE |
| `action_type` | `varchar(24)` | `SPEAK`, `PASS`, `ATTACK`, `INVESTIGATE`, `PROTECT`, `VOTE` |
| `target_player_id` | `uuid` | 대상 행동만 같은 game player |
| `message` | `varchar(200)` | `SPEAK`만 1~200자 |
| `source` | `varchar(16)` | `HUMAN`, `AGENT`, `AUTO` |
| `observed_state_version` | `bigint` | 제출 검증 시점의 game version |
| `submitted_at` | `timestamptz` | NOT NULL |

- `UNIQUE(window_id, actor_player_id)`로 첫 유효 제출만 허용한다.
- `(game_id, window_id) -> action_windows(game_id, id)`,
  `(game_id, actor_player_id) -> game_players(game_id, id)`와
  `(game_id, target_player_id) -> game_players(game_id, id)` 복합 FK를 사용한다.
- role·phase·생존·대상·deadline은 INSERT 전 engine이 검사하고 DB 제약은 game/actor
  소속과 필수 field 조합을 다시 막는다.
- 자동 선택도 별도 행으로 저장해 replay 시 재사용한다.

### 4.10 `action_window_resolutions`

window의 최종 집계와 결정적 RNG 결과를 한 번만 저장한다.

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `window_id` | `uuid` | UNIQUE, 같은 game의 `action_windows` 복합 FK |
| `resolution_type` | `varchar(24)` | `NIGHT`, `VOTE`, `REVOTE`, `FINAL_VOTE` |
| `resolution_source` | `varchar(24)` | `SUBMISSIONS`, `FACTION_AUTO`, `TIE_RNG` 등 |
| `resolved_target_player_id` | `uuid` | 결과 대상이 있을 때 같은 game player |
| `result_payload` | `jsonb` | 승인된 집계·공개/비공개 결과 구조 |
| `rng_proof_hash` | `char(64)` | RNG를 쓴 경우 입력 commitment hash |
| `resolved_state_version` | `bigint` | 해소 결과 game version |
| `resolved_at` | `timestamptz` | NOT NULL |

- 생존 마피아 중 한 명만 제출하면 미제출 마피아의 `AUTO` submission을 만들지 않고
  그 제출을 최종 공격으로 사용한다.
- 생존 마피아 전원이 미제출이면 actor 없는 진영 단위 자동 공격을
  `resolution_source=FACTION_AUTO`와 결과 target으로 한 번 기록한다.
- 탐정·의사·투표 미제출은 player별 `AUTO` submission을 만든다.
- 동률 후보, 후보별 득표수와 최종 target은 `result_payload`의 versioned schema로
  저장하되 공개 전에는 개별 표를 projection하지 않는다.
- `(game_id, window_id) -> action_windows(game_id, id)`와
  `(game_id, resolved_target_player_id) -> game_players(game_id, id)` 복합 FK를 사용한다.

### 4.11 `game_events`

4.10절 `result_payload`의 현재 v1은 `schema_version=1`, `round`, `phase`를 공통으로
가진다. NIGHT에는 API 2.5절 nights의 필드, VOTE·REVOTE·FINAL_VOTE에는 votes의
필드와 `tied` boolean, `needs_revote` boolean, `tied_candidates` UUID 배열,
`final_target_player_id` UUID 또는 null을 저장한다. 배열 item의 actor/target/is_auto
및 조사 결과 형식은 API 2.5절을 따른다. 해소 시점에 입력과 자동 선택·최종 결과를
같은 transaction에서 보존하며 종료 전 공개 projection은 개인 선택을 제외한다.
기존 원장이 없는 게임은 과거 선택을 임의로 보충하지 않는다.


| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `sequence` | `bigint` | 게임별 증가 순서 |
| `front_sequence` | `bigint` | Front-visible transaction의 batch cursor, 아니면 NULL |
| `operation_index` | `smallint` | Front batch 안의 0부터 시작하는 순서, 아니면 NULL |
| `state_version` | `bigint` | 이벤트를 만든 결과 버전 |
| `event_type` | `varchar(64)` | 등록된 event type |
| `audience` | `varchar(16)` | `PUBLIC`, `PLAYER`, `ADMIN` |
| `audience_player_id` | `uuid` | `PLAYER`일 때만 같은 game player |
| `schema_version` | `smallint` | payload schema 버전, 1부터 시작 |
| `operation_type` | `varchar(32)` | Front-visible event의 API operation type, 아니면 NULL |
| `payload` | `jsonb` | operation 또는 내부 event의 versioned 구조화 payload |
| `created_at` | `timestamptz` | NOT NULL |

- `UNIQUE(game_id, sequence)`를 둔다.
- `UNIQUE(game_id, front_sequence, operation_index) WHERE front_sequence IS NOT NULL`
  을 둔다.
- `idx_game_events_sync(game_id, front_sequence, operation_index)` 부분 index를 둔다.
- `(game_id, audience_player_id) -> game_players(game_id, id)` 복합 FK를 사용한다.
- `PUBLIC` event는 개인 역할·개별 투표·밤 행동을 포함할 수 없다.
- `PLAYER` event는 정확한 `audience_player_id`가 필요하다.
- 하나의 client-visible transaction에서 만든 PUBLIC event와 인간 대상 PLAYER event는
  같은 `front_sequence`를 사용하고 index를 연속 배정한다. game의
  `next_front_sequence`는 transaction당 한 번 증가한다. AI 대상·ADMIN event는
  두 Front field가 모두 NULL이다.
- `front_sequence`가 있으면 `operation_type`도 반드시 있고 payload는 API 명세의 해당
  operation payload다. Front field가 없는 private event의 `operation_type`은 NULL이다.
- phase·player·private view·window·public/private event·result 변경을 각각
  `SET_GAME_STATE`, `REPLACE_PLAYERS`, `SET_PRIVATE_STATE`, `SET_ACTION_WINDOW`,
  `CLEAR_ACTION_WINDOW`, `APPEND_PUBLIC_EVENT`, `APPEND_PRIVATE_EVENT`, `SET_RESULT` event로
  영구 저장한다. 따라서 Redis가 없어도 DB event만으로 delta batch를 재구성한다.
- payload에 seed, key, prompt, raw model response와 chain-of-thought를 넣지 않는다.
- event는 append-only이며 UPDATE·DELETE 권한을 runtime 계정에 주지 않는다.

주요 event type:

```text
GAME_CREATED, GAME_BEGAN, PHASE_CHANGED, TURN_OPENED,
PLAYER_SPOKE, PLAYER_PASSED, NIGHT_RESOLVED, PLAYER_DIED,
INVESTIGATION_RESULT, NIGHT_ACTION_ACCEPTED, VOTE_RESOLVED, PLAYER_EXECUTED,
FAST_FORWARD_ENABLED, GAME_SAVED, GAME_RESUMED, GAME_ENDED, GAME_FAILED
```

### 4.12 `command_receipts`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `principal_type` | `varchar(16)` | `USER` 또는 `AGENT` |
| `principal_id` | `uuid` | 사용자 또는 player ID, system은 고정 namespace UUID |
| `idempotency_key` | `uuid` | 요청의 `Idempotency-Key` |
| `route_scope` | `varchar(120)` | method와 concrete game ID를 포함한 route 식별자 |
| `game_id` | `uuid` | 생성 전에는 NULL 가능 |
| `request_hash` | `char(64)` | method·concrete path·canonical query·정규 JSON의 SHA-256 |
| `result_state_version` | `bigint` | 성공 게임 mutation 결과 |
| `http_status` | `smallint` | terminal 응답 status |
| `result_body` | `jsonb` | ID·version 등 불변 terminal 결과, snapshot·deadline 금지 |
| `created_at` | `timestamptz` | NOT NULL |

- `UNIQUE(principal_type, principal_id, idempotency_key)`를 둔다. 한 principal이 같은
  key를 다른 route나 game에 재사용할 수 없다.
- 같은 key와 같은 hash는 현재 principal의 소유권을 다시 검사한 뒤 불변 terminal
  결과를 반환한다. `meta.replayed`는 현재 HTTP 응답에서 동적으로 붙인다.
- 같은 key를 다른 hash에 사용하면 `IDEMPOTENCY_KEY_REUSED`를 반환한다.
- 성공 여부가 불명확한 중간 상태를 저장하지 않는다. DB 오류로 transaction이
  rollback되면 receipt도 없어 재시도할 수 있다.
- 공개 API의 `USER` key는 `Idempotency-Key` header, 내부 proposal의 `AGENT` key는
  body `proposal_id`다. MCP 세션 개설 토큰(bootstrap token)은 game command가 아니며
  nonce ledger를 사용한다.

### 4.13 `game_snapshots`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `state_version` | `bigint` | snapshot 대상 버전 |
| `last_front_sequence` | `bigint` | snapshot에 포함된 마지막 Front-visible event |
| `schema_version` | `smallint` | serializer 버전 |
| `state_ciphertext` | `bytea` | AES-256-GCM 전체 engine snapshot |
| `nonce` | `bytea` | snapshot별 고유 nonce |
| `key_id` | `varchar(64)` | 사용 key 식별자 |
| `checksum` | `char(64)` | 복호화 후 canonical payload hash |
| `created_at` | `timestamptz` | NOT NULL |

`UNIQUE(game_id, state_version)`을 둔다. snapshot이 없거나 checksum이 맞지 않으면
normalized table과 event로 재구성하고 새 snapshot을 쓴다. 공개 API에 ciphertext나
복호화한 전체 객체를 직접 반환하지 않는다.

### 4.14 `agent_jobs`

외부 호출 전에 영구 reservation을 남겨 동일 turn을 중복 실행하지 않는다.

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `player_id` | `uuid` | AI player job만 같은 game player, GM은 NULL |
| `window_id` | `uuid` | 같은 game의 `action_windows` 복합 FK |
| `job_kind` | `varchar(24)` | `SPEECH`, `NIGHT_ACTION`, `VOTE`, `GM_NARRATION` |
| `reserved_state_version` | `bigint` | reservation 당시 버전 |
| `status` | `varchar(16)` | `RESERVED`, `SUCCEEDED`, `FALLBACK`, `STALE`, `FAILED` |
| `lease_token` | `uuid` | 현재 worker fencing token |
| `lease_expires_at` | `timestamptz` | 고정 engine lease 만료 시각 |
| `normalized_result` | `jsonb` | 검증된 player proposal 또는 GM narration, 없으면 NULL |
| `failure_code` | `varchar(64)` | 비밀 없는 분류 코드 |
| `created_at` | `timestamptz` | NOT NULL |
| `completed_at` | `timestamptz` | terminal 상태 시각 |

- AI player job은 `UNIQUE(window_id, player_id, job_kind) WHERE player_id IS NOT NULL`,
  GM job은 `UNIQUE(window_id, job_kind) WHERE player_id IS NULL`을 둔다.
- `GM_NARRATION`일 때만 `player_id`가 NULL이고 나머지 job은 player가 필수다.
- `(game_id, player_id) -> game_players(game_id, id)`와
  `(game_id, window_id) -> action_windows(game_id, id)` 복합 FK를 사용한다.
- Provider명·model 버전은 game의 `agent_config_version`으로 재현한다.
- `normalized_result`는 API 명세 10.1절 player 결과 또는 10.2절 GM 결과의 폐쇄형
  schema만 저장한다.
- token, 비용, timeout, prompt, private context와 raw response 컬럼은 두지 않는다.
- `RESERVED`는 `normalized_result`, `failure_code`, `completed_at`이 모두 NULL이다.
  `SUCCEEDED`는 검증된 `normalized_result`와 `completed_at`이 있고
  `failure_code=NULL`이다. `FALLBACK`은 결정적 fallback `normalized_result`, 원인
  `failure_code`, `completed_at`이 모두 있다. `STALE`과 `FAILED`는
  `normalized_result=NULL`이고 `failure_code`, `completed_at`이 non-null이다. migration
  CHECK와 repository transition이 이 조합을 함께 강제한다.
- `job_kind=GM_NARRATION`의 `normalized_result.type`은 `GM_NARRATION`, `SPEECH`는
  `SPEAK|PASS`, `NIGHT_ACTION`은 `NIGHT_ACTION`, `VOTE`는 `VOTE`여야 한다.
- 외부 호출 뒤 다시 game을 잠그고 lease token, window, version과 deadline이 그대로일
  때만 AI player proposal을 submission으로, GM narration을 `PUBLIC` event로 반영한다.
  GM 결과는 action submission이나 MCP Tool proposal로 저장하지 않는다. 검증에
  실패하거나 fencing 조건이 바뀌었으면 `STALE` 또는 정의된 fallback으로 끝낸다.
- lease는 reservation 시각부터 15초 또는 action window deadline 중 이른 시각까지다.
  이 값은 코드의 고정 안전 상수이며 환경 변수나 관리자 설정이 아니다.
- scheduler는 만료된 lease 하나를 조건부 UPDATE로 인수해 fallback을 확정한다. 늦게
  돌아온 이전 worker는 fencing token이 달라 결과를 반영할 수 없다. lease는 고정된
  장애 복구 장치이며 환경에서 조정하는 LLM timeout이나 측정 KPI가 아니다.

### 4.15 `agent_capabilities`

Backend가 발급하고 Engine API가 검증하는 opaque capability 원장이다. MCP는 token을
전달만 하며 서명 key나 claim 검증 권한을 갖지 않는다.

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `token_hash` | `char(64)` | UNIQUE, raw 32-byte token의 SHA-256 |
| `agent_job_id` | `uuid` | NOT NULL, FK `agent_jobs(id)`, job별 권한 경계 |
| `game_id` | `uuid` | FK `games(id)`, CASCADE |
| `subject_type` | `varchar(16)` | `AI_PLAYER` 또는 `GM` |
| `subject_player_id` | `uuid` | AI player만 같은 game player, GM은 NULL |
| `phase` | `varchar(32)` | 발급 당시 phase |
| `state_version` | `bigint` | 발급 당시 game version |
| `window_id` | `uuid` | 같은 game window, 없으면 NULL |
| `allowed_resources` | `jsonb` | 등록된 resource key 배열 |
| `allowed_tools` | `jsonb` | 등록된 Tool key 배열, GM은 빈 배열 |
| `expires_at` | `timestamptz` | 현재 window 또는 보안 수명까지 |
| `revoked_at` | `timestamptz` | 교체·종료 시각, 아니면 NULL |
| `created_at` | `timestamptz` | NOT NULL |

- raw capability는 CSPRNG 32-byte를 padding 없는 base64url로 표현하며 DB·log에 저장하지
  않는다.
- AI player 행은 `(game_id, subject_player_id) -> game_players(game_id, id)` 복합 FK를
  사용하고 GM 행은 `subject_player_id=NULL`이어야 한다.
- `agent_job_id`가 가리키는 job의 game, player/GM, window와 발급 당시 version은
  capability의 같은 field와 일치해야 한다.
  `UNIQUE(agent_job_id) WHERE revoked_at IS NULL`로 job마다 활성 capability를 하나만
  허용한다. reconnect는 기존 행을 먼저 폐기한 뒤 같은 job에 새 행을 만든다.
- wire claim의 GM `subject_id`는 별도 player가 아니라 해당 `game_id`와 같은 UUID다.
  Backend는 `subject_type=GM`, `subject_id=game_id`, DB player NULL 조합만 허용한다.
- Engine API는 raw token hash, 미폐기, 만료, game·subject·phase·version·window와
  resource·Tool allowlist를 현재 상태와 모두 비교한다.
- job 성공·fallback·stale·실패(호출 취소 포함)·lease 만료, phase/window 교체와 game
  종료 시 이전 capability를 revoke한다.

### 4.16 `internal_request_nonces`

내부 HMAC과 MCP 세션 개설 토큰 replay 차단의 영구 원장이다.

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `scope` | `varchar(24)` | `ENGINE_HMAC` 또는 `MCP_BOOTSTRAP` |
| `nonce` | `uuid` | 요청·token nonce |
| `request_hash` | `char(64)` | canonical request 또는 세션 개설 토큰 claim hash |
| `expires_at` | `timestamptz` | replay 거부 종료 시각 |
| `created_at` | `timestamptz` | NOT NULL |

`PRIMARY KEY(scope, nonce)`가 최종 일회성 보장이다. signature 검증 뒤 실제 context 조회나
mutation 전에 INSERT하고 unique 충돌을 replay로 거부한다. 만료 행은 별도 bounded
cleanup job이 삭제하며 보안 판정은 Redis 존재 여부에 의존하지 않는다.

### 4.17 `event_outbox`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `bigserial` | PK |
| `game_event_id` | `uuid` | UNIQUE, FK `game_events(id)`, CASCADE |
| `available_at` | `timestamptz` | NOT NULL |
| `published_at` | `timestamptz` | NULL 또는 publish 완료 시각 |
| `attempt_count` | `integer` | 0 이상 |
| `last_error_code` | `varchar(64)` | 비밀 없는 오류 분류 |

outbox에는 event payload 복사본을 두지 않는다. publisher는 같은
`front_sequence`에서 commit된 event를 index 순으로 묶어 Redis stream에 batch pointer
한 건을 발행한다. publish 중복은 Front sequence로 제거한다. Front field가 없는
private event는 SSE stream에 발행하지 않는다.

`event_outbox`와 publisher는 Backend game event 전달을 위한 영속 상태와 실행
로직이며 MCP 감사 로그 저장소가 아니다.
MCP runtime은 이 table·publisher·Redis stream을 직접 읽거나 쓰지 않으며,
별도의 영속 audit outbox를 소유하지 않는다.

### 4.18 `feedback`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `uuid` | PK |
| `user_id` | `uuid` | FK `users(id)`, RESTRICT |
| `feedback_type` | `varchar(16)` | `GENERAL` 또는 `GAME` |
| `game_id` | `uuid` | `GAME`만 FK `games(id)`, RESTRICT |
| `rating` | `smallint` | 1~5 |
| `comment` | `varchar(1000)` | NULL 또는 trim 후 1~1000자 |
| `tags` | `jsonb` | 등록된 문자열 tag 배열 |
| `created_at` | `timestamptz` | NOT NULL |

- `GAME`이면 요청 사용자가 소유하고 종료된 game이어야 한다.
- `UNIQUE(user_id, game_id) WHERE feedback_type='GAME'`로 게임별 한 건을 보장한다.
- `GENERAL`이면 `game_id`는 NULL이다.
- 사용자 note나 게임 engine input으로 사용하지 않는다.

### 4.19 `admin_audit_events`

| 컬럼 | 타입 | 제약·의미 |
|---|---|---|
| `id` | `bigserial` | PK |
| `admin_user_id` | `uuid` | allowlist를 통과한 요청 UUID |
| `action` | `varchar(64)` | read action 분류 |
| `target_game_id` | `uuid` | 상세 조회만 설정 |
| `request_id` | `uuid` | 상관관계 ID |
| `created_at` | `timestamptz` | NOT NULL |

IP 원문, header 전체, 비밀값과 응답 payload는 저장하지 않는다. 관리자 API가 read-only인
MVP에서도 접근 흔적을 남긴다.

## 5. 핵심 transaction

### 5.1 사용자 최초 쓰기와 게임 생성

```text
BEGIN
  pg_advisory_xact_lock(hash(USER, user_id, idempotency_key))
  기존 command_receipt 조회, 있으면 hash·소유권 확인 후 불변 결과 반환
  INSERT users(id) ... ON CONFLICT UPDATE last_seen_at
  pg_advisory_xact_lock(hash(user_id))
  SELECT 직전 성공 game의 scenario_id
  검증된 scenario·persona·template 후보 로드
  seed 생성 및 암호화
  games INSERT(state_version=1, phase=ROLE_REVEAL)
  game_players, player_scenario_facts INSERT
  GAME_CREATED event와 outbox INSERT
  command_receipt INSERT
COMMIT
```

scenario·role·persona·개인 문장 선택은 transaction 전에 seed로 계산할 수 있지만
직전 scenario 조회 이후 결과가 바뀌지 않도록 사용자 advisory lock 안에서 최종
후보를 확정한다. seed 평문은 transaction 완료 뒤 메모리에서 제거한다. 동일 create가
동시에 들어와도 idempotency advisory lock을 먼저 잡으므로 두 번째 transaction은 첫
commit 뒤 receipt를 읽고 같은 game ID를 반환한다.

### 5.2 사용자 command

```text
BEGIN
  pg_advisory_xact_lock(hash(USER, user_id, idempotency_key))
  기존 command_receipt 조회
  receipt가 있으면 request hash와 현재 소유권 확인 후 불변 결과 반환
  SELECT game FOR UPDATE
  owner, status, expected_state_version 검증
  action_window, player, role, alive, target, deadline 검증
  action_submission 또는 phase 결과 INSERT/UPDATE
  games.state_version = state_version + 1
  game_events, event_outbox, command_receipt INSERT
COMMIT
```

이미 같은 actor가 window에 제출한 경우 새 state mutation을 만들지 않는다. 같은
idempotency key면 소유권 재검사 후 기존 불변 결과를, 다른 key면
`ACTION_ALREADY_SUBMITTED`를 반환한다. Front command 응답에는 저장 당시 snapshot이나
deadline을 넣지 않고 성공 뒤 sync로 현재 상태를 읽는다.

모든 public mutation은 idempotency advisory lock, receipt 조회, domain lock 순서를
같게 유지한다. feedback도 같은 순서를 쓰며 game feedback이면 그 뒤 대상 game을
검증한다. hash 충돌은 무관 요청을 일시 직렬화할 뿐 unique receipt가 정확성을
보장한다.
request hash의 concrete path에는 command 대상 `game_id`가 들어간다. 따라서 같은 key와
같은 body를 다른 game에 보내도 receipt replay가 아니라 `IDEMPOTENCY_KEY_REUSED`다.

### 5.3 action window 해소

한 worker만 `OPEN -> RESOLVING` 조건부 UPDATE에 성공해야 한다. 이어서 같은
transaction에서 탐정·의사·투표의 누락 actor에만 `AUTO` submission을 만든다.
마피아는 제출 조합에 따라 기존 제출 하나 또는 `FACTION_AUTO` resolution 한 건을
사용한다. 그 뒤 투표·밤 결과, 사망, 승패, 다음 phase, event와 snapshot을 확정한다.
transaction 실패 시 window는 다시 `OPEN`이며 저장 결과가 없으므로 안전하게
재시도한다.

### 5.4 Agent 외부 호출

일반·재·최종 투표는 인간 제출과 독립적으로 모든 AI job을 병렬 실행하며 완료되는
표부터 별도 transaction으로 누적한다. 미해소 AI 표는 `action_submissions`와 receipt만
저장하고 공개 상태·version·event를 바꾸지 않는다. 마지막 표는 기존 게임 행 잠금과
window·deadline 검증 안에서 한 번만 해소한다. 다른 AI의 실패는 이미 commit한 표에
영향을 주지 않으며 마감 시 누락된 actor만 AUTO로 채운다.

AI 판단의 버전은 인간의 같은 window 첫 투표 직전 버전으로 유지할 수 있다. 현재
버전이 정확히 한 단계 높고 해당 HUMAN VOTE의 observed version이 일치하는 경우만
예약·완료·적용에서 허용한다. 이 증거가 없는 stale version은 거부한다. 저장·재개로
버전이 달라진 미제출 job은 이전 lease가 끝난 후 기존 결과를 버리고 새로 판단한다.

```text
Tx A: window·version 검증 -> lease token을 가진 agent_jobs RESERVED
      -> job-bound capability와 세션 개설 토큰의 nonce 발급 -> COMMIT
외부: job별 새 MCP session에서 context 조회 -> 선택 LLM Provider 호출
      -> player proposal 또는 GM narration schema 검증
Tx B: game FOR UPDATE -> lease token·reservation·window·version 재검증
      -> player submission 또는 GM PUBLIC event/fallback/stale 확정
      -> capability revoke -> event/outbox -> COMMIT
```

Tx A와 Tx B 사이에는 DB transaction과 Redis game lock을 잡지 않는다. 같은 job의
동시 worker는 unique 제약으로 하나만 reservation에 성공한다. lease가 먼저 만료되면
scheduler가 fencing token을 교체하고 `PASS`, 자동 행동 또는 고정 GM 문구를 확정한다.
Agent Manager는 terminal 경로에서 session 종료를 시도하고, reconnect가 필요하면 이전
capability를 폐기한 뒤 같은 살아 있는 job에 새 capability와 세션 개설 토큰을 발급한다.

### 5.5 내부 요청 인증

Engine HMAC signature와 timestamp를 먼저 검증한 뒤 짧은 transaction에서
`internal_request_nonces`를 INSERT한다. unique 충돌은 replay다. 이어 같은 요청에서
`agent_capabilities.token_hash`를 잠그지 않는 조회로 검사하고 game을 읽거나 proposal
mutation transaction을 연다. nonce INSERT가 성공한 뒤 domain 검증이 실패해도 같은
wire 요청을 재사용할 수 없으며 caller는 새 nonce로 교정 요청을 만든다.

MCP 세션 개설 토큰 consume도 `scope=MCP_BOOTSTRAP`으로 같은 원장을 사용한다. Redis
nonce key는 이미 본 요청을 빠르게 거르는 cache일 뿐 DB INSERT를 생략하는 근거가
아니다.

### 5.6 저장·재개

- 저장은 game을 잠근다. 열린 timed window라면
  `deadline_at - transaction_timestamp()`를 0 이상 millisecond로 clamp해
  `remaining_ms_on_save`에 저장한다. untimed 발언 window와 `ROLE_REVEAL`은 남은 시간
  값을 만들지 않는다.
- `deadline_at`을 NULL로 만들고 window를 `PAUSED`, game을 `status=SAVED`로 바꾼 뒤
  `saved_at`과 snapshot을 같은 transaction에서 기록한다.
- 재개는 저장된 남은 시간이 있는 window에만
  `deadline_at=transaction_timestamp()+remaining_ms`를 설정한다. untimed window는
  deadline 없이 복원한다. window를 `OPEN`, game을 `IN_PROGRESS`로 바꾸고 남은 시간
  field를 비운다.
- 같은 save/resume idempotency key replay는 시간을 다시 계산하지 않는다.

## 6. Redis 계약

key prefix는 환경별 namespace 뒤 `mafia:v1`을 사용한다. 운영 환경끼리 같은 Redis
DB와 prefix를 공유하지 않는다.

| Key | 자료형 | 값 | 수명·복구 |
|---|---|---|---|
| `mafia:v1:lock:game:{game_id}` | string | 무작위 lock token | 짧은 TTL, token 일치 release, DB lock이 최종 정합성 보장 |
| `mafia:v1:public:{game_id}:{state_version}` | string JSON | 공개 snapshot projection | 짧은 TTL, PostgreSQL에서 재생성 |
| `mafia:v1:conversation:{db_scope}:{game_id}` | string JSON | 공개 사건·발언 전체, state_version·내부/Front cursor·checksum | 7일 TTL, 누락·손상·버전 차이는 PostgreSQL 전체 이력에서 복구 |
| `mafia:v1:events:{game_id}` | stream | Front-visible batch sequence와 event ID 배열 | bounded trim, PostgreSQL event로 backfill |
| `mafia:v1:outbox:wakeup` | pub/sub | 새 outbox 존재 알림 | 유실 허용, DB polling 병행 |
| `mafia:v1:nonce:engine:{nonce}` | string | 이미 소비된 Engine nonce cache | 최대 120초, PostgreSQL ledger가 원본 |
| `mafia:v1:nonce:mcp-bootstrap:{nonce}` | string | 이미 소비된 세션 개설 토큰의 nonce cache | 최대 120초, PostgreSQL ledger가 원본 |
| `mafia:v1:health` | string | synthetic health marker | health check에서만 사용 |

대화 캐시는 정본 공개 projection을 거친 `public_events` 전체를 내부 event 순서대로
보관한다. 최근 N개로 자르지 않으며 DB 접속 대상의 비밀정보 없는 식별자로 namespace를
분리한다. 캐시는 소유권·Agent scope 확인 후 현재 DB cursor와 정확히 일치할 때만 읽는다.
늦은 읽기 결과는 더 높은 버전을 덮지 못하도록 원자적으로 저장하고, checksum·형식이
잘못된 값은 사용하지 않는다. mutation commit 뒤와 snapshot·공개 Agent context 조회 때
갱신한다. Redis 장애는 DB commit을 실패로 뒤집지 않으며 다음 조회에서 backfill한다.
로컬 실행은 루트 `.env`의 `REDIS_URL`을 사용한다. 공개 발언에 스스로 밝힌 역할이나
조사 주장은 대화 내용으로 저장하되, 비공개 역할·개인 행동 원장은 복사하지 않는다.

### 6.1 금지 데이터

Redis에는 다음을 평문으로 저장하지 않는다.

- 게임 seed와 암호화 key
- 다른 플레이어의 role·알리바이·관찰·조사·보호·공격·개별 투표
- 전체 engine snapshot
- LLM prompt·raw response·token·비용
- MCP·Engine secret과 capability 원문

SSE fan-out stream은 같은 `front_sequence`의 event ID를 index 순서로 묶은 pointer만
담는다. Backend가 요청 UUID를 인간 player로 다시 확인한 후 원자적인 operation batch로
projection한다. AI private event와 ADMIN event는 이 stream에 넣지 않는다.

### 6.2 lock 규칙

- 획득은 `SET key token NX PX <bounded-ms>`다.
- 해제와 연장은 Lua에서 현재 token 일치 여부를 검사한다.
- Redis lock만으로 중복 mutation을 막지 않는다. PostgreSQL row lock, unique 제약과
  `state_version`이 최종 방어선이다.
- lock 획득 실패는 짧은 retry hint가 있는 `GAME_BUSY`로 반환한다.
- Redis 장애 시 새 Agent turn과 fan-out 최적화를 중단할 수 있지만 이미 열린 게임의
  PostgreSQL 상태를 손상시키지 않는다.
- 내부 nonce replay는 PostgreSQL unique ledger가 최종 판정한다. Redis가 없으면
  cache precheck만 생략하고 PostgreSQL 검증을 계속한다.

## 7. RNG와 암호화

- 게임 seed는 서버 CSPRNG로 생성한다.
- 역할·scenario·persona·template·자동 대상 선택은
  `HMAC-SHA256(seed, purpose|round|window_id|candidate_ids)`에서 파생한 결정적 값을
  사용한다.
- candidate ID는 안정적으로 정렬하고 purpose string을 종류마다 다르게 사용한다.
- 최종 선택 결과를 해당 normalized table과 event에 저장한다.
- seed와 전체 snapshot은 AES-256-GCM으로 암호화한다. nonce는 암호화마다 새로 생성하고
  재사용하지 않는다.
- 암호화 key는 환경 비밀 저장소에서 주입하며 DB에는 `key_id`만 저장한다.
- Backend는 저장소 밖의 권한 제한 `GAME_STATE_KEYRING_FILE`에서 key ID별 32-byte key를
  읽고 `GAME_STATE_ACTIVE_KEY_ID`로 신규 암호화 key를 선택한다. 기존 record가 참조하는
  key는 모든 해당 game의 보존 기간 동안 keyring에서 제거하지 않는다.
- keyring은 `{"version":1,"keys":{"key-id":"BASE64URL_32_BYTE_KEY"}}` 구조의 JSON이며
  실제 파일은 Git에 넣지 않는다. startup에서 active ID 존재, base64url decode와 정확한
  32-byte 길이를 검사하고 실패하면 game write를 fail-closed한다.
- rotation은 새 active key 추가, 신규 write 전환, 기존 ciphertext background
  재암호화, 참조 0건 확인, 이전 key 폐기 순서로 수행한다.
- 복호화 실패나 key 없음은 임의 재추첨하지 않고 game을 `FAILED`로 격리한다.

## 8. 일관성 불변식

- 게임마다 인간 player는 정확히 한 명이고 `owner_user_id`와 연결된다.
- 역할 수는 인원별 역할표와 정확히 일치한다.
- 마피아 둘에게 서로의 role을 알려주는 event·projection은 존재하지 않는다.
- 한 action window와 actor 조합에는 submission이 최대 한 건이다.
- 게임에는 열린 window가 최대 하나다.
- 종료 게임의 상태와 `finished_at`은 replay로 바뀌지 않는다.
- 같은 seed·version·후보에는 같은 선택 결과가 나온다.
- 내부 event sequence는 game row의 `next_event_sequence`에서 할당한다. client-visible
  transaction은 별도 `next_front_sequence`에서 gap 없는 batch 번호 하나를 할당하고
  여러 operation을 0부터 시작하는 index로 묶는다.
- 다른 AI의 private submission·event는 state version과 Front sequence를 바꾸지 않는다.
- public event와 cache에는 비공개 field가 없다.
- 저장 중 deadline은 없고 재개 후 새 deadline은 저장된 남은 시간을 사용한다.
- 사용자별 직전 scenario 제외는 성공적으로 생성된 game만 기준으로 한다.
- 모든 game/player/window 조합은 복합 FK로 같은 game 소속을 강제한다.
- 활성 capability는 정확히 한 agent job에 묶이고 job마다 하나뿐이며, terminal job의
  capability는 모두 폐기된다.

## 9. Migration 전략

### 9.1 소유권과 실행

runner는 `DATABASE_MIGRATION_URL`을 필수 DDL 접속값으로 사용하며 runtime DSN으로
대체하지 않는다. Backend 설정에서는 선택 필드이고 repr에 포함하지 않는다.
일반 `from_env`/`get_settings`는 DDL 환경키를 조회·보관하지 않고 CLI의
`from_migration_env`만 별도 설정으로 읽는다. runtime 설정 캐시를 재사용하지 않는다.
실행 전에 DDL URL의 percent-decoded DB path를 runtime effective DSN의 path와
대소문자까지 비교하고 다르면 접속하지 않는다. 프록시를 허용하므로 host·port가
동일한 서버를 뜻하는지까지 보장하지는 않는다. URL의 `dbname`·`host`·`user`·
`password` 등 접속 대상을 덮어쓰는 query는 거부하고 `sslmode` 같은 일반 옵션과
정상 DDL URL 원문은 보존한다. 실행 프로세스는 비교용 runtime DSN도 읽되 SQL
실행에는 DDL DSN만 전달하고 어느 값도 로그에 출력하지 않는다.

- Backend가 `backend/migrations/`의 순방향 SQL과 검증 query를 작성한다.
- MCP·Data 담당자가 DDL 계정으로 이름순 실행하고 재실행·health 결과를 공유한다.
- Backend runtime 계정에는 schema 변경 권한을 주지 않는다.
- 적용된 `001_create_oauth_schema.sql`과 `002_create_scaffold_game_schema.sql`을 수정하지
  않는다.

### 9.2 전환 순서

1. 다음 번호 migration에서 canonical table, index, constraint와 seed loader를 만든다.
2. 사용자 UUID-only repository와 canonical game API로 traffic을 전환한다.
3. identity route·OIDC Front와 scaffold route가 더 이상 읽고 쓰지 않는지 확인한다.
4. 보존할 실제 데이터가 없고 명시적 검토가 끝난 환경에서만 별도 순방향 migration으로
   `oauth_identities`, legacy profile field와 `scaffold_*` table을 제거한다.
5. destructive cleanup 전 backup, row count, FK dependency와 rollback 절차를 기록한다.

초기 개발 DB라도 기존 migration 파일을 다시 쓰는 대신 forward-only 전환을 사용한다.
cleanup 승인이 나기 전 legacy object는 사용 금지 상태이며 새 foreign key가 참조하지
않는다.

### 9.3 migration 검증

- 빈 DB 최초 실행과 이미 001·002가 적용된 DB 업그레이드를 모두 검증한다.
- 같은 migration 재실행이 성공하고 중복 seed data를 만들지 않아야 한다.
- runtime 계정으로 DDL과 event UPDATE·DELETE가 거부되는지 확인한다.
- 5개 scenario, scenario별 18개 이상 template와 승인 hash를 확인한다.
- `NOT VALID` FK를 사용했다면 검증 완료 없이 checkpoint를 통과하지 않는다.

## 10. 보존과 삭제

| 데이터 | MVP 기본 정책 |
|---|---|
| 진행·저장 게임 | 사용자가 재개할 수 있도록 유지 |
| 종료 게임·event·feedback | 명시적 운영 정책 승인 전 자동 삭제하지 않음 |
| Redis cache·stream | bounded TTL/trim, 원본 아님 |
| command receipt | 게임과 함께 유지해 장기 replay도 중복 mutation 방지 |
| admin audit | 운영 환경 정책에 따라 별도 보존 기간 승인 필요 |
| legacy identity data | cleanup migration 승인 전 접근 금지 보존 |

MVP에는 사용자 삭제 API가 없다. 실제 개인정보를 수집하지 않더라도 UUID와 게임 기록
삭제 정책은 공개 인터넷 배포 전에 별도로 정해야 한다.

## 11. 검증 목록

- 6~9명 role count와 player 제약
- user 동시 게임 생성 시 직전 scenario 제외 직렬화
- command replay, key/body 충돌, stale version, 같은 actor 동시 제출
- deadline 직전·동시·직후 서버 시각 경계
- 밤 행동 동시 해소와 자동 선택 재현성
- 일반·재·최종 투표 동률과 결과 재현성
- 다섯 번째 밤 `finished_at` 최초 한 번 설정
- save/resume 남은 시간과 snapshot checksum
- Redis flush 뒤 PostgreSQL 재구성
- outbox 중복 publish와 SSE event deduplication
- 다른 Agent private event 사이에도 Front sequence가 연속이며 timing side channel이
  생기지 않는지 확인
- Engine HMAC nonce와 MCP 세션 개설 토큰의 nonce에 대한 PostgreSQL unique replay
  거부, cleanup과 Redis
  cache 장애 시 원본 판정 유지
- job별 capability 활성 uniqueness, reconnect 교체와 모든 terminal 경로의 revoke
- GM narration이 action submission을 만들지 않고 fencing 재검증 뒤 `PUBLIC` event로만
  반영되는지 확인
- Agent worker crash, lease 인수와 늦은 fencing token 결과 거부
- 다른 player·GM·admin projection의 비공개 정보 비간섭성
- DB 오류, 암호화 key 없음과 Redis 장애의 rollback·fail-closed 경로
- token·비용·LLM timeout 컬럼·로그가 생성되지 않는 schema 검토
