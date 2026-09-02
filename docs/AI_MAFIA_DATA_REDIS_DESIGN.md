# AI 마피아 DB·Redis 설계 `minimum-v1`

상태: 구현 전 확정 스키마. PostgreSQL이 유일한 원본이며 Redis는 복구 가능한 임시 데이터만 가진다.

## 1. 공통 규칙

모든 PK는 UUID, 시각은 `timestamptz` UTC, 외부 문자열은 trim·길이 검증한다. role·seed·prompt·private payload는 공개 projection과 분리한다. `users`는 기존 OIDC 테이블과 호환하며 게임 MVP의 개발용 user_id FK는 선택적으로 연결한다.

## 2. PostgreSQL 전체 테이블과 필드

| table | field: type | 역할·제약 |
|---|---|---|
| `users` | `id uuid PK`; `email varchar(320) NULL`; `display_name varchar(80)`; `is_active boolean`; `created_at`; `updated_at` | 내부 사용자와 접근 상태; email은 연결키 아님 |
| `oauth_identities` | `id uuid PK`; `user_id uuid FK users`; `provider varchar(32)`; `provider_subject varchar(255)`; `profile_json jsonb`; `last_login_at`; `created_at`; `updated_at` | 외부 계정 연결; `(provider,provider_subject)` UNIQUE |
| `game_sessions` | `id uuid PK`; `owner_user_id uuid NULL FK users`; `ruleset_version varchar(32)`; `status varchar(16)`; `phase varchar(32)`; `round int`; `state_version bigint`; `seed_ciphertext bytea`; `phase_started_at`; `phase_deadline_at`; `created_at`; `updated_at`; `finished_at` | 게임 현재 상태·소유권·낙관적 version; seed 암호문 |
| `game_players` | `id uuid PK`; `game_id uuid FK`; `user_id uuid NULL FK`; `kind varchar(8)`; `agent_id uuid NULL`; `display_name varchar(80)`; `role varchar(32)`; `faction varchar(16)`; `alive boolean`; `seat_no smallint`; `persona_id uuid NULL`; `created_at`; `updated_at` | 참가자·역할 원본; game 내 seat·user 유일 |
| `game_events` | `id uuid PK`; `game_id uuid FK`; `sequence bigint`; `event_type varchar(48)`; `actor_player_id uuid NULL`; `target_player_id uuid NULL`; `visibility varchar(16)`; `payload jsonb`; `state_version bigint`; `created_at` | append-only 사실; `(game_id,sequence)` UNIQUE; visibility로 필터 |
| `game_snapshots` | `id uuid PK`; `game_id uuid FK`; `state_version bigint`; `snapshot_json jsonb`; `created_at` | immutable 복구 checkpoint; 최신 version index |
| `game_operations` | `id uuid PK`; `game_id uuid FK`; `command varchar(32)`; `status varchar(16)`; `accepted_version bigint`; `result_version bigint NULL`; `request_fingerprint char(64)`; `error_code varchar(64) NULL`; `created_at`; `updated_at` | 비동기 명령·polling 원본 |
| `api_idempotency_records` | `id uuid PK`; `scope varchar(64)`; `idempotency_key uuid`; `request_fingerprint char(64)`; `response_status smallint`; `response_json jsonb`; `created_at`; `expires_at` | 재전송 응답; `(scope,idempotency_key)` UNIQUE |
| `game_notes` | `game_id uuid FK`; `user_id uuid FK`; `content varchar(2000)`; `notes_version bigint`; `created_at`; `updated_at`; `PK(game_id,user_id)` | 사용자 개인 메모; agent·관리자 노출 금지 |
| `agent_personas` | `id uuid PK`; `persona_id varchar(64)`; `version int`; `display_name varchar(80)`; `speech_style varchar(280)`; `backstory varchar(2000)`; `params jsonb`; `created_at` | 게임 시작 시 참조하는 불변 persona; 수치 0~1 |
| `agent_runs` | `id uuid PK`; `game_id uuid FK`; `agent_id uuid`; `phase varchar(32)`; `provider varchar(16)`; `status varchar(16)`; `input_hash char(64)`; `output_json jsonb NULL`; `error_code varchar(64) NULL`; `latency_ms int NULL`; `input_tokens int NULL`; `output_tokens int NULL`; `created_at`; `finished_at` | LLM 관측·비용; prompt 원문 저장 금지 |
| `game_feedback` | `id uuid PK`; `game_id uuid FK`; `user_id uuid FK`; `rating smallint`; `created_at` | FINISHED 후 1~5 평점; `(game_id,user_id)` UNIQUE |
| `audit_logs` | `id uuid PK`; `trace_id uuid`; `game_id uuid NULL`; `actor_id_hash varchar(64)`; `severity varchar(16)`; `action varchar(64)`; `summary varchar(500)`; `metadata jsonb`; `created_at` | 운영 감사·KPI; secret·prompt·private role 금지 |

`agent_id`는 AI 참가자 식별자이고 `game_players.id`와 다르다. FK 삭제는 기본 `RESTRICT`로 게임 원본을 보존하며 보존 기간 purge 작업만 별도 수행한다.

## 3. transaction·복구

명령 하나는 game row lock → version·규칙 검증 → event append → snapshot(필요 시) → operation update를 같은 transaction에서 수행한다. commit 전 SSE를 발행하지 않는다. 재기동 시 최신 snapshot 이후 event를 replay하고 불일치하면 자동 진행하지 않고 `PAUSED`로 안전 정지한다.

## 4. Redis key 계약

| key | 값 | TTL | 장애 시 |
|---|---|---:|---|
| `team4:game:{game_id}:lock` | random lock token | 30초 heartbeat | DB lock |
| `team4:operation:{operation_id}:status` | status projection | 15분 | DB polling |
| `team4:game:{game_id}:events` | SSE fan-out sequence/payload | 1시간 | DB replay |
| `team4:idempotency:{scope}:{key}` | fingerprint/response | 24시간 | PostgreSQL |
| `team4:rate:{subject}:{bucket}` | sliding-window counter | 2분 | 보수적으로 거부 |

Redis에는 seed, 전체 snapshot, private role, 메모를 저장하지 않는다. Redis가 없어도 게임·복구·operation 조회는 PostgreSQL로 가능하고 실시간은 polling으로 대체한다.

## 5. 보존·migration 완료 기준

`PAUSED` 30일, `FINISHED` 90일, `audit_logs` 180일 보존 후 별도 purge한다. 사용자 즉시 삭제 API는 MVP에 없다. migration은 번호 순서로 추가하고 기존 identity migration은 수정하지 않는다. FK·UNIQUE·index 존재, 2회 실행 무변경, rollback, 민감 payload 차단 fixture를 통과해야 한다.
