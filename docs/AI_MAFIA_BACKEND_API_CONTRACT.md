# AI 마피아 Backend API 계약 `minimum-v1`

상태: 구현 전 확정 계약  
소유자: Backend  
소비자: `frontend_user`, `frontend_admin`  
기준일: 2026-09-02

이 문서만 읽어도 Frontend를 Backend와 독립적으로 개발할 수 있도록 모든 HTTP 진입점,
헤더, 요청·응답, 오류와 상태 변경 규칙을 정의한다. 게임 규칙은
[게임 규칙·로직](AI_MAFIA_GAME_RULES.md), 저장 구조는
[DB·Redis 설계](AI_MAFIA_DATA_REDIS_DESIGN.md)를 따른다. Frontend는 DB, Redis, LLM,
MCP에 직접 접근하지 않는다.

기계 판독 가능한 Swagger/OpenAPI 3.1 원본은
[AI_MAFIA_BACKEND_OPENAPI.yaml](AI_MAFIA_BACKEND_OPENAPI.yaml)이다. 이 문서의 JSON
예시와 YAML schema는 동일한 계약이며, 구현 시 OpenAPI를 기준으로 Swagger UI를 생성한다.

## 1. 전역 계약

### 1.1 전송

- Base URL은 배포 환경 설정으로 주입한다. 모든 경로는 `/api/v1`로 시작한다.
- 일반 요청·응답은 `application/json; charset=utf-8`, 이벤트는 `text/event-stream`이다.
- 시간은 UTC ISO-8601 문자열(`2026-09-02T12:00:00Z`), ID는 UUID 문자열이다.
- 요청 실패에도 `trace_id`를 반환한다. 서버가 `X-Trace-Id`를 수용하면 UUID 형식일 때만
  사용하고, 아니면 새 값을 발급한다.
- 모든 상태 변경 요청은 body의 UUID `idempotency_key`를 필수로 한다.
- 게임 상태 변경 요청은 body의 `expected_version`을 필수로 한다. 현재 값과 다르면
  상태를 변경하지 않고 `409 GAME_STATE_CONFLICT`를 반환한다.

### 1.2 호출자 식별

모든 `/api/v1/games` 요청은 다음 헤더를 필수로 한다.

```http
X-User-Id: 8d155bef-9814-4a11-89b6-2d87af1d65f1
```

Backend는 UUID 형식만 검증한다. 이는 MVP 개발용 소유자 식별자이며 인증·권한 증명이
아니다. 헤더 누락·형식 오류는 `400 INVALID_USER_ID`다. 타 사용자 게임은 존재 여부를
추측할 수 없도록 항상 `404 RESOURCE_NOT_FOUND`다.

### 1.3 공통 오류

```json
{"code":"GAME_STATE_CONFLICT","message":"게임 상태가 변경되었습니다.","details":{"current_version":18},"trace_id":"uuid"}
```

`code` 허용값은 `INVALID_REQUEST`, `INVALID_USER_ID`, `RESOURCE_NOT_FOUND`,
`GAME_STATE_CONFLICT`, `ACTION_NOT_ALLOWED`, `IDEMPOTENCY_CONFLICT`,
`NOTES_VERSION_CONFLICT`, `FEEDBACK_ALREADY_EXISTS`, `VALIDATION_ERROR`,
`RATE_LIMITED`, `DEPENDENCY_UNAVAILABLE`이다. 오류에는 role 전체, prompt, token,
DB URL, secret, 원문 개인정보를 넣지 않는다.

## 2. 사용자 게임 API

## 2.0 기존 서비스 진입점

아래 endpoint는 게임 API와 별개로 현재 저장소에 이미 구현된 identity 연결 계약이다.

- `GET /health` — 200 `{"status":"ok"}`. DB·Redis 상태를 의미하지 않는 process liveness다.
- `POST /api/v1/identity/provision` — Frontend가 내부 HMAC 헤더와 함께 호출한다. 요청은
  `provider`(1~64자), `provider_subject`(1~512자), `email`(nullable, 최대 320자),
  `email_verified`(boolean), `display_name`(nullable, 최대 120자),
  `avatar_url`(nullable HTTPS 절대 URL, 최대 2048자)이며 추가 필드는 금지한다.
  성공 200 응답은 `user_id,provider,provider_subject,email,display_name,avatar_url,
  is_active,created_at,last_login_at`의 사용자 projection이다. 서명 실패는 401/403,
  schema는 422, 비활성 사용자는 403 `INACTIVE_USER`, 저장소 장애는 503
  `IDENTITY_PERSISTENCE_UNAVAILABLE`이다. 실제 HMAC 원문·헤더 규칙은 기존
  `ARCHITECTURE_REFACTOR_PLAN.md`와 Backend security module이 소유한다.

### 2.1 게임 생성

`POST /api/v1/games` — 201

요청 필드: `player_count` 정수 5~9, `ruleset_version`은 `basic-v1`,
`idempotency_key` UUID.

```json
{"player_count":6,"ruleset_version":"basic-v1","idempotency_key":"uuid"}
```

응답 필드: `game_id`, `status=IN_PROGRESS`, `phase=ROLE_REVEAL`, `state_version=1`,
현재 사용자의 `player`, 공개 가능한 `players`. 현재 사용자에게만 `player.role`을
반환하며 다른 참가자 role은 종료 전 절대 반환하지 않는다.

### 2.2 게임 목록

`GET /api/v1/games?status=IN_PROGRESS&cursor=<opaque>&limit=20` — 200

`status`는 `IN_PROGRESS|PAUSED|FINISHED`, `limit` 기본 20·최대 50이다. 응답은
`{"items":[GameSummary],"next_cursor":string|null}`이며 summary는
`game_id,status,phase,round,living_player_count,player_count,state_version,created_at,updated_at`
을 가진다. 최신 수정순이며 cursor는 Backend가 서명한 opaque 값이다.

### 2.3 현재 게임 상태

`GET /api/v1/games/{game_id}` — 200

응답은 `game_id,status,phase,round,state_version,phase_started_at,
phase_deadline_at,current_turn_player_id,your_player,players,public_events,
private_events,allowed_commands,valid_targets,revote_target_player_ids,
active_operation,updated_at`을 가진다. `your_player`에는 현재 사용자의
`player_id,role,alive`, `players`에는 공개 `player_id,display_name,kind,alive`만 포함한다.
`valid_targets`는 `{"command":"CAST_VOTE","player_ids":["uuid"]}` 배열이다.

### 2.4 게임 명령

`POST /api/v1/games/{game_id}/commands` — 202

```json
{"command":"CAST_VOTE","target_player_id":"uuid","message":null,"mode":null,"expected_version":18,"idempotency_key":"uuid"}
```

추가 필드는 거부한다. 사용하지 않는 선택 필드는 생략하거나 `null`이어야 한다.

| command | 허용 phase | 필수 입력 |
|---|---|---|
| `BEGIN_GAME` | `ROLE_REVEAL` | 없음 |
| `SPEAK` | `DAY_DISCUSSION`에서 내 차례 | `message` 1~280자 |
| `CAST_VOTE` | `DAY_VOTE`, `DAY_REVOTE` | `target_player_id` |
| `KILL` | `NIGHT_ACTION`, 인간이 마피아 | `target_player_id` |
| `INVESTIGATE` | `NIGHT_ACTION`, 인간이 탐정 | `target_player_id` |
| `PROTECT` | `NIGHT_ACTION`, 인간이 의사 | `target_player_id` |
| `PAUSE` | 안전 지점 | 없음 |
| `RESUME` | `PAUSED` | 없음 |
| `FAST_FORWARD` | 인간 탈락 후 | `mode=NEXT_PHASE|UNTIL_FINISHED` |

응답은 `accepted,operation_id,state_version,phase,status`이며 `status`는
`QUEUED|COMPLETED`다. 202는 LLM 완료가 아니라 명령 수락을 의미한다. 동일 key와
동일 정규화 요청은 최초 응답을 재반환하고, 다른 요청은 `409 IDEMPOTENCY_CONFLICT`다.

### 2.5 operation 조회

`GET /api/v1/games/{game_id}/operations/{operation_id}` — 200

응답: `operation_id,game_id,command,status,accepted_version,result_version,
error_code,created_at,updated_at`. `status`는 `QUEUED|RUNNING|COMPLETED|FAILED|PAUSED`다.
소유하지 않은 operation은 404다.

### 2.6 이벤트 스트림

`GET /api/v1/games/{game_id}/events` — SSE 200  
요청 헤더: 선택 `Last-Event-ID`(정수 sequence).

이벤트 이름은 `game.state_changed`, `game.public_event`, `game.private_event`,
`operation.status`다. SSE id는 `game_events.sequence`이며 재연결 시 이후 공개·현재
사용자용 private 이벤트만 전송한다. 30초 heartbeat가 있으며 Frontend는 45초 무응답
시 재연결한다.

### 2.7 결과·메모·평점

- `GET /api/v1/games/{game_id}/result` — `FINISHED`에서만 200. 응답은
  `winner,finish_reason,rounds,duration_seconds,human_survived,human_vote_accuracy,
  my_rating,players,timeline`이다. 종료 전은 409다.
- `GET /api/v1/games/{game_id}/notes` — 200. 없으면 `content="",notes_version=0,updated_at=null`.
- `PUT /api/v1/games/{game_id}/notes` — 200. 요청은
  `content` 0~2000자, `expected_notes_version`, `idempotency_key`; 응답은
  `game_id,user_id,content,notes_version,updated_at`이다.
- `POST /api/v1/games/{game_id}/feedback` — `FINISHED`에서만 201. 요청은
  `rating` 정수 1~5와 `idempotency_key`; 응답은 `feedback_id,game_id,rating,created_at`.
  사용자·게임당 1건이며 중복은 409다.

## 3. 관리자 API

MVP에서는 `X-User-Id`를 operator 식별자로 기록하지만 관리자 인증·권한은 구현 범위
밖이다. 로컬·내부 테스트에서만 사용한다.

- `GET /api/v1/admin/kpis?from=YYYY-MM-DD&to=YYYY-MM-DD` — 기간, 표본 수와
  `new_games,completion_rate,average_duration_seconds,average_rounds,resume_rate,
  llm_success_rate,llm_timeout_rate,llm_fallback_rate,average_llm_latency_ms,
  total_tokens,estimated_cost_usd,average_feedback_rating,breakdowns` 반환.
- `GET /api/v1/admin/logs?from=&to=&severity=&action=&game_id=&trace_id=&cursor=&limit=` —
  `items,next_cursor`; item은 `log_id,trace_id,game_id,actor_id_hash,severity,action,summary,created_at`.
- `GET /api/v1/admin/feedback?rating=&cursor=&limit=` — item은
  `feedback_id,game_id,rating,created_at`.

관리자 목록 limit은 최대 50, 날짜 범위는 UTC `[from 00:00, to+1일 00:00)`다.
prompt 원문·전체 role·메모 원문은 반환하지 않는다.

## 4. 구현·검증 경계

Backend는 모든 명령에 대해 phase, turn, role, alive, target, 중복과 version을
재검증하고 DB transaction에서 event와 snapshot을 함께 확정한다. Frontend가 임의로
상태를 계산하거나 허용되지 않은 버튼을 활성화해도 Backend가 최종 거부한다.

독립 개발 완료 조건은 OpenAPI가 이 문서의 path·schema·오류 code와 일치하고,
정상·권한 없음·version 충돌·중복 요청·의존성 장애 fixture를 가진 contract test가
통과하는 것이다.
