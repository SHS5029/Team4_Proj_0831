# AI 마피아 MVP API 명세서

**상위 계약:** [AI_MAFIA_MASTER_PLAN.md](AI_MAFIA_MASTER_PLAN.md)

**데이터 계약:** [AI_MAFIA_DB_DESIGN.md](AI_MAFIA_DB_DESIGN.md)

**화면 소비자:** [AI_MAFIA_SCREEN_FLOW.md](AI_MAFIA_SCREEN_FLOW.md)

**MCP 구현 설계:** [AI_MAFIA_MCP_SERVER_DESIGN.md](AI_MAFIA_MCP_SERVER_DESIGN.md)

**HTTP prefix:** `/api/v1`

이 문서는 일반 사용자 Front, 관리자 Front, Backend와 Mafia Game MCP 사이의 API
정본이다. 구현 완료 시 FastAPI가 생성하는 `/openapi.json`과 이 문서의 path, enum,
필수 field와 오류 코드가 일치해야 한다. 별도 수기 OpenAPI YAML은 관리하지 않는다.

## 1. 공통 규칙

### 1.1 전송과 형식

- JSON request·response는 UTF-8 `application/json`을 사용한다.
- 모든 시각은 UTC RFC 3339 문자열이며 예시는 `2026-09-02T12:34:56.123Z` 형식이다.
- 사용자·게임·player·window·command·event 같은 runtime ID는 canonical hyphen UUID
  문자열이다. `scenario_id`, `persona_id`처럼 정적 카탈로그 ID는 문서에 등록된
  대문자 snake case 또는 안정적인 문자열 key다.
- 알 수 없는 request field는 `422 VALIDATION_ERROR`로 거부한다.
- pagination은 opaque `cursor`와 `limit`을 사용하며 `limit` 기본 20, 최대 100이다.
- 사용자 입력 문자열은 제어 문자를 거부하고 Unicode NFC, 줄바꿈과 연속 공백을
  계약에 맞게 정규화한다. 화면 출력에서도 HTML escape한다.
- 공개 오류에는 stack trace, DB 정보, secret, prompt와 비공개 게임 상태를 넣지 않는다.

### 1.2 요청 header

| Header | 대상 | 계약 |
|---|---|---|
| `X-User-Id` | `/api/v1` 사용자·관리자 API | 필수 UUID v4, 사용자 구분값이며 인증 증명 아님 |
| `X-Request-Id` | 모든 HTTP API | 선택 UUID, 없으면 Backend가 생성 |
| `Idempotency-Key` | 변경하는 공개 `/api/v1` `POST` | 필수 UUID v4, terminal 응답 전까지 같은 값을 재사용 |
| `Last-Event-ID` | SSE reconnect | 마지막으로 적용한 Front sequence 문자열 |

일반 Front가 보내는 `Authorization`, OIDC token, email, `acting_user_id`, timestamp
서명과 HMAC header는 정의하지 않는다. Front는 URL·body에 `user_id`를 중복 전달하지
않는다.

### 1.3 사용자 UUID 수명주기

1. Front가 브라우저 첫 실행에 UUID v4를 생성해 same-origin local storage에 저장한다.
2. Front 서버는 읽은 UUID를 `X-User-Id`로 Backend에 전달한다.
3. 게임 생성 또는 feedback 같은 최초 쓰기에서 Backend가 최소 사용자 행을 멱등 생성한다.
4. 사용자가 UUID 복구 값을 바꾸면 이후 요청부터 새 UUID scope만 보인다.
5. UUID만 아는 사용자는 그 UUID의 게임을 요청할 수 있다. 따라서 MVP는 접근이 통제된
   개발·사설 환경에서만 사용한다.

### 1.4 성공 envelope

일반 JSON 성공 응답은 다음 envelope를 사용한다.

```json
{
  "data": {},
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z"
  }
}
```

목록 응답은 `data.items`, `data.next_cursor`를 사용한다. 다음 page가 없으면
`next_cursor`는 `null`이다.

### 1.5 오류 envelope

```json
{
  "error": {
    "code": "STALE_STATE_VERSION",
    "message": "게임 상태가 변경되었습니다. 최신 상태를 불러오세요.",
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "retryable": true,
    "details": {
      "current_state_version": 12
    }
  }
}
```

`message`는 안전한 고정 한국어 문구다. Front는 분기와 분석에 `code`만 사용한다.

| HTTP | 코드 | 의미 |
|---:|---|---|
| 400 | `MISSING_USER_ID` | `X-User-Id` 누락 |
| 400 | `INVALID_REQUEST` | JSON·query 조합 오류 |
| 403 | `ADMIN_ACCESS_DENIED` | 관리자 allowlist 불일치 |
| 403 | `PLAYER_DEAD` | 사망한 인간의 발언·투표·밤 행동 command |
| 403 | `ACTION_NOT_ALLOWED` | 현재 actor·role에 허용되지 않은 행동 |
| 404 | `GAME_NOT_FOUND` | game 없음 또는 다른 UUID 소유, 구분하지 않음 |
| 404 | `RESOURCE_NOT_FOUND` | 기타 리소스 없음 |
| 409 | `STALE_STATE_VERSION` | expected version 불일치 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 같은 key를 다른 요청에 사용 |
| 409 | `ACTION_ALREADY_SUBMITTED` | 같은 window에 다른 key로 두 번째 제출 |
| 409 | `WINDOW_CLOSED` | 마감·해소·취소된 window |
| 409 | `INVALID_PHASE` | command와 phase 불일치 |
| 409 | `GAME_BUSY` | 짧은 동시 해소 또는 저장 충돌 |
| 409 | `GAME_ALREADY_ENDED` | 종료 게임 변경 시도 |
| 409 | `GAME_NOT_SAVED` | 진행 게임에 `RESUME` 시도 |
| 409 | `FEEDBACK_ALREADY_SUBMITTED` | 같은 게임의 두 번째 game feedback |
| 422 | `VALIDATION_ERROR` | UUID version, enum, 길이·대상 검증 실패 |
| 429 | `RATE_LIMITED` | 인프라 보호 제한 |
| 503 | `DEPENDENCY_UNAVAILABLE` | DB·Redis·MCP 등 필수 경계 장애 |

### 1.6 Idempotency와 optimistic concurrency

- `POST /games`, `/games/{game_id}/commands`, `/feedback`은 `Idempotency-Key`가
  필수다.
- Backend는 principal, route scope, key와 canonical request hash를 영구 저장한다.
- key unique 범위는 현재 `X-User-Id` 전체다. request hash는 대문자 method, concrete
  path의 `game_id`, canonical query와 정규 JSON body를 포함한다.
- 동일 요청 replay는 현재 UUID의 소유권을 다시 확인한 뒤 최초 HTTP status와 불변
  terminal 결과를 반환하고 `meta.replayed=true`를 동적으로 추가한다.
- receipt에는 snapshot, 현재 legal action, 상대 시간과 `deadline_at`을 저장하지 않는다.
  replay 뒤 현재 상태가 필요하면 GET 또는 sync를 호출한다.
- 같은 key와 다른 request hash는 `409 IDEMPOTENCY_KEY_REUSED`다.
- game command body는 `expected_state_version`을 필수로 가진다.
- version 불일치 command를 자동 재적용하지 않는다. Front가 sync한 뒤 사용자의
  의도를 다시 확인한다.
- 다른 AI의 미해소 private submission과 Agent reservation은 Front projection을
  바꾸지 않으므로 공개 `state_version`을 올리지 않는다. phase 해소·공개 event 또는
  인간 본인 private 상태가 바뀔 때 version을 올린다.

## 2. 공통 모델

### 2.1 Enum

```text
GameStatus = IN_PROGRESS | SAVED | COMPLETED | FAILED

GamePhase = ROLE_REVEAL | DAY_DISCUSSION | NIGHT_ACTION |
            DAY_VOTE | REVOTE | FINAL_DISCUSSION |
            FINAL_ACCUSATION | ENDED

Role = MAFIA | DETECTIVE | DOCTOR | CITIZEN
Faction = MAFIA | CITIZEN

LegalAction = BEGIN_GAME | SPEAK | PASS | SUBMIT_NIGHT_ACTION |
              SUBMIT_VOTE | SAVE_AND_EXIT | RESUME | FAST_FORWARD
```

### 2.2 공개 player

```json
{
  "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
  "seat": 1,
  "display_name": "플레이어 1",
  "kind": "HUMAN",
  "alive": true,
  "revealed_role": null,
  "eliminated_phase": null,
  "eliminated_round": null
}
```

`revealed_role`은 처형된 player 또는 게임 종료 뒤에만 설정한다. 밤 사망자는 종료
전까지 `null`이다.

### 2.3 action window

```json
{
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "kind": "VOTE",
  "cycle": 1,
  "paused": false,
  "opened_state_version": 17,
  "server_time": "2026-09-02T12:34:56.123Z",
  "deadline_at": "2026-09-02T12:35:26.123Z",
  "remaining_ms": 30000,
  "turn_player_id": null,
  "has_submitted": false,
  "legal_actions": ["SUBMIT_VOTE", "SAVE_AND_EXIT"],
  "valid_targets": [
    {
      "player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08",
      "display_name": "플레이어 2"
    }
  ]
}
```

진행 중 발언 window에는 규칙상 마감이 없으므로 `deadline_at`과 `remaining_ms`가
`null`이다. 진행 중 밤·투표 계열은 둘 다 값이 있고 `paused=false`다.
`status=SAVED` snapshot은 기존 window를 `paused=true`로 유지하며 `deadline_at=null`,
timed window의 동결된 `remaining_ms`만 값으로 반환한다. untimed window는 두 시간
field가 모두 `null`이다. 저장 상태의 top-level `legal_actions`는 `RESUME`만 포함하고
window 안의 `legal_actions`는 빈 배열이다. Front countdown은 표시용이며 제출 가능
여부는 Backend 응답이 결정한다.

`action_window` 자체는 nullable이다. `ROLE_REVEAL`, window 사이의 안정 상태,
`COMPLETED`, `FAILED`에는 `null`일 수 있다. `status=SAVED`에서 저장 당시 window가
없었다면 역시 `null`이며 top-level `legal_actions=["RESUME"]`만 반환한다.

### 2.4 snapshot

```json
{
  "game": {
    "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
    "status": "IN_PROGRESS",
    "phase": "DAY_DISCUSSION",
    "round": 1,
    "day_number": 2,
    "state_version": 12,
    "last_sequence": 42,
    "ruleset_version": "mystery-v1",
    "scenario_version": "scenario-v1",
    "player_count": 6,
    "mafia_count": 1,
    "fast_forward_enabled": false,
    "updated_at": "2026-09-02T12:34:56.123Z"
  },
  "scenario": {
    "scenario_id": "BLACKOUT_STUDIO",
    "title": "정전된 방송국",
    "background": "생방송을 준비하던 방송국에서 PD가 사망했습니다.",
    "victim": "생방송 PD",
    "locations": ["스튜디오", "조정실", "분장실", "대기실", "장비실"]
  },
  "players": [
    {
      "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
      "seat": 1,
      "display_name": "플레이어 1",
      "kind": "HUMAN",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08",
      "seat": 2,
      "display_name": "플레이어 2",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "e15f18b6-ea20-477e-9d99-8a22dc6048f5",
      "seat": 3,
      "display_name": "플레이어 3",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "b2177718-e0eb-43b4-a585-225da47ced78",
      "seat": 4,
      "display_name": "플레이어 4",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "c38f59b7-c26c-4638-9980-31a26cffd997",
      "seat": 5,
      "display_name": "플레이어 5",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "d46579fc-9520-4a29-9d9d-d804e7986fc5",
      "seat": 6,
      "display_name": "플레이어 6",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    }
  ],
  "me": {
    "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
    "role": "DETECTIVE",
    "alive": true,
    "spectator": false,
    "alibi": "정전 당시 조정실에서 방송 장비를 확인하고 있었다.",
    "observation": "정전 직전 누군가 장비실 방향으로 이동하는 것을 봤다.",
    "private_events": []
  },
  "action_window": {
    "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
    "kind": "SPEECH",
    "cycle": 1,
    "paused": false,
    "opened_state_version": 12,
    "server_time": "2026-09-02T12:34:56.123Z",
    "deadline_at": null,
    "remaining_ms": null,
    "turn_player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
    "has_submitted": false,
    "legal_actions": ["SPEAK", "PASS", "SAVE_AND_EXIT"],
    "valid_targets": []
  },
  "legal_actions": ["PASS", "SPEAK", "SAVE_AND_EXIT"],
  "public_events": [],
  "result": null
}
```

- 일반 사용자 snapshot은 소유 게임의 인간 player 비공개 정보만 포함한다.
- 다른 player의 role, 알리바이, 관찰, 조사, 보호, 공격과 개별 투표를 넣지 않는다.
- AI GM context와 MCP resource는 이 Front snapshot을 재사용하지 않고 audience별
  projection을 별도로 만든다.
- 사망한 인간도 이미 허용됐던 자기 role·알리바이·관찰·private event는 계속 받지만
  다른 player의 private 정보는 종료 전 받지 않는다.
- 종료 snapshot의 `result`에는 2.5절의 전체 role·action 공개 기록을 넣는다.

### 2.5 종료 결과

`result`는 `status=COMPLETED`에서만 object이며 그 전에는 `null`이다.

```json
{
  "winner": "CITIZEN",
  "win_reason": "ALL_MAFIA_ELIMINATED",
  "finished_at": "2026-09-02T12:34:56.123Z",
  "players": [
    {
      "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
      "display_name": "플레이어 1",
      "role": "DETECTIVE",
      "alive": true,
      "eliminated_phase": null,
      "eliminated_round": null
    }
  ],
  "nights": [
    {
      "round": 1,
      "attack_choices": [],
      "resolved_attack_target_player_id": null,
      "protect_player_id": null,
      "investigations": [],
      "killed_player_id": null
    }
  ],
  "votes": [
    {
      "round": 1,
      "phase": "DAY_VOTE",
      "ballots": [],
      "counts": [],
      "eliminated_player_id": null
    }
  ],
  "public_event_ids": []
}
```

`win_reason` enum:

```text
ALL_MAFIA_ELIMINATED
MAFIA_PARITY
FINAL_MAFIA_SELECTED
FINAL_NON_MAFIA_SELECTED
```

`attack_choices`, `investigations`와 `ballots`는 종료 뒤 공개되는 actor·target·자동 선택
여부의 구조화 배열이다. 내부 추론, prompt와 raw model response는 포함하지 않는다.

## 3. 상태 확인

### 3.1 `GET /health`

프로세스 liveness만 확인한다. DB·Redis를 호출하지 않는다.

```json
{
  "status": "ok"
}
```

### 3.2 `GET /ready`

Backend가 새 요청을 받을 준비가 됐는지 확인한다.

```json
{
  "status": "ready",
  "dependencies": {
    "postgresql": "ok",
    "redis": "ok"
  }
}
```

Provider와 MCP health는 게임 생성 준비를 막지 않는다. 실제 Agent turn에서 실패하면
규칙 fallback을 사용한다. readiness 응답은 secret, URL과 오류 원문을 포함하지 않는다.

## 4. 사용자 게임 API

### 4.1 `POST /api/v1/games`

새 게임을 만들고 역할 공개 상태를 반환한다. `X-User-Id`, `Idempotency-Key` 필수다.

Request:

```json
{
  "player_count": 6,
  "ruleset_version": "mystery-v1",
  "scenario_version": "scenario-v1"
}
```

Validation:

- `player_count`는 6~9다.
- 두 version은 현재 지원 값과 정확히 일치해야 한다.
- 사용자별 직전 성공 게임 scenario를 제외하고 seed로 결정한다.
- 같은 사용자의 동시 create는 직렬화한다.

Response `201`:

```json
{
  "data": {
    "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
    "status": "IN_PROGRESS",
    "phase": "ROLE_REVEAL",
    "round": 0,
    "state_version": 1,
    "snapshot_url": "/api/v1/games/d9ae9b5d-1d17-4f80-8f1a-276bfe170412"
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

생성만으로 첫날 발언은 시작하지 않는다. Front는 성공 뒤 `snapshot_url`을 GET해 역할
화면을 그리고 별도 `BEGIN_GAME`을 제출한다. create replay가 과거 snapshot을 반환하지
않으므로 이미 진행된 game도 현재 상태로 열린다.

### 4.2 `GET /api/v1/games`

현재 UUID가 소유한 게임을 최신 갱신 순으로 반환한다.

Query:

| 이름 | 값 |
|---|---|
| `status` | 선택, `IN_PROGRESS`, `SAVED`, `COMPLETED`, `FAILED` |
| `cursor` | 선택 opaque cursor |
| `limit` | 선택 1~100 |

Response `200` item:

```json
{
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "status": "SAVED",
  "phase": "NIGHT_ACTION",
  "round": 2,
  "day_number": 2,
  "state_version": 21,
  "scenario_title": "정전된 방송국",
  "player_count": 6,
  "human_alive": true,
  "winner": null,
  "can_resume": true,
  "updated_at": "2026-09-02T12:34:56.123Z"
}
```

알 수 없는 UUID는 `200` 빈 목록을 받는다.

### 4.3 `GET /api/v1/games/{game_id}`

현재 authoritative snapshot을 반환한다. 다른 UUID 소유 게임은 존재 여부를 숨기기
위해 `404 GAME_NOT_FOUND`다.

Response `200`: `data`는 2.4절 snapshot이다.

### 4.4 `POST /api/v1/games/{game_id}/commands`

모든 게임 변경의 단일 endpoint다. `Content-Type`과 `type`으로 union member를
구분한다. 성공은 `200`이며 비동기 operation ID를 만들지 않는다.

공통 성공 응답:

```json
{
  "data": {
    "command_id": "d57fac33-4f83-46fb-99dd-1d27fd724b5c",
    "command_type": "SPEAK",
    "accepted_state_version": 12,
    "result_state_version": 13,
    "sync_url": "/api/v1/games/d9ae9b5d-1d17-4f80-8f1a-276bfe170412/sync"
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

`command_id`는 요청 `Idempotency-Key`와 같은 UUID다.
`accepted_state_version`은 request를 검증한 mutation 이전 version이고
`result_state_version`은 성공 commit 뒤 version이다. 응답은 snapshot을 포함하지 않으며
Front는 `sync_url` 또는 game GET으로 현재 상태를 확인한다.

#### `BEGIN_GAME`

```json
{
  "type": "BEGIN_GAME",
  "expected_state_version": 1
}
```

`ROLE_REVEAL`에서만 허용하며 `DAY_DISCUSSION`, day 1, round 0으로 전환한다.

#### `SPEAK`

```json
{
  "type": "SPEAK",
  "expected_state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "message": "조정실 근처에 있던 사람의 설명을 먼저 듣고 싶습니다."
}
```

현재 인간 player의 `DAY_DISCUSSION` 또는 `FINAL_DISCUSSION` 발언 차례에만 허용한다.
정규화한 본문은 1~200자다.

#### `PASS`

```json
{
  "type": "PASS",
  "expected_state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069"
}
```

현재 인간 발언 차례에만 허용한다.

#### `SUBMIT_NIGHT_ACTION`

```json
{
  "type": "SUBMIT_NIGHT_ACTION",
  "expected_state_version": 20,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "target_player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08"
}
```

Backend가 인간의 저장 role로 `ATTACK`, `INVESTIGATE`, `PROTECT`를 결정한다. client가
role이나 action subtype을 보내지 않는다. 시민, 사망자와 이미 제출한 actor는 거부한다.

#### `SUBMIT_VOTE`

```json
{
  "type": "SUBMIT_VOTE",
  "expected_state_version": 27,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "target_player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08"
}
```

`DAY_VOTE`, `REVOTE`, `FINAL_ACCUSATION`에서만 허용한다. 후보는 snapshot의
`valid_targets` 중 하나여야 하고 자기 자신은 선택할 수 없다.

#### `SAVE_AND_EXIT`

```json
{
  "type": "SAVE_AND_EXIT",
  "expected_state_version": 27
}
```

게임이 `IN_PROGRESS`이고 window가 `RESOLVING`이 아닌 안정 상태에서 허용한다. 열린
timed window가 있으면 남은 서버 시간을 snapshot에 저장한다. 진행 중 Agent 결과는
state/version 재검증 뒤 stale 처리하고 저장 결과를 바꾸지 않는다.

#### `RESUME`

```json
{
  "type": "RESUME",
  "expected_state_version": 28
}
```

`status=SAVED`에서만 허용한다. timed window에 저장된 남은 시간이 있을 때만 새
`deadline_at`을 만든다. untimed 발언 window는 deadline 없이 복원하고
`ROLE_REVEAL`처럼 window가 없던 상태는 `action_window=null`을 유지한다. phase, role과
scenario는 저장 당시 값을 복원한다.

#### `FAST_FORWARD`

```json
{
  "type": "FAST_FORWARD",
  "expected_state_version": 31
}
```

인간 player가 사망한 진행 게임에서만 허용한다. Backend는 관전자의 행동을 대신
제출하지 않고 `fast_forward_enabled=true`를 영구 저장한 뒤 남은 AI turn을 자동 진행
모드로 바꾼다. `FAST_FORWARD_ENABLED` event와 이후 진행은 sync/SSE로 전달한다.

### 4.5 command 허용표

| 조건 | 허용 command |
|---|---|
| `ROLE_REVEAL`, 인간 생존 | `BEGIN_GAME`, `SAVE_AND_EXIT` |
| 인간의 발언 차례 | `SPEAK`, `PASS`, `SAVE_AND_EXIT` |
| 다른 player 발언 차례 | `SAVE_AND_EXIT` |
| `NIGHT_ACTION`, 인간 특수 역할·미제출 | `SUBMIT_NIGHT_ACTION`, `SAVE_AND_EXIT` |
| `NIGHT_ACTION`, 시민 또는 제출 완료 | `SAVE_AND_EXIT` |
| 투표 phase, 인간 생존·미제출 | `SUBMIT_VOTE`, `SAVE_AND_EXIT` |
| `SAVED` | `RESUME` |
| 인간 사망·진행 중 | `FAST_FORWARD`, `SAVE_AND_EXIT` |
| `COMPLETED`·`FAILED` | 없음 |

## 5. 동기화 API

### 5.1 operation 모델

polling과 SSE는 같은 operation 모델을 사용한다.

```json
{
  "schema_version": 1,
  "front_sequence": 43,
  "operation_index": 0,
  "state_version": 13,
  "type": "APPEND_PUBLIC_EVENT",
  "payload": {
    "event_id": "a7dd582b-bcad-4d91-b045-1c771128e380",
    "event_type": "PLAYER_SPOKE",
    "created_at": "2026-09-02T12:34:56.123Z",
    "data": {
      "player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08",
      "message": "조정실에 있었습니다."
    }
  }
}
```

허용 operation type:

```text
SET_GAME_STATE
REPLACE_PLAYERS
SET_PRIVATE_STATE
SET_ACTION_WINDOW
CLEAR_ACTION_WINDOW
APPEND_PUBLIC_EVENT
APPEND_PRIVATE_EVENT
SET_RESULT
```

Front는 `(game_id, front_sequence, operation_index)`를 기준으로 operation을 한 번만
적용한다. 하나의 client-visible transaction은 Front sequence 한 개와 index 0부터
연속인 operation batch가 된다. 이 값은 PUBLIC event와 인간 본인의 private event에만
배정된다. 다른 AI의 private event는 Front sequence나 공개 `state_version`을 올리지
않는다. 알 수 없는 type·`schema_version`, sequence gap 또는 batch index gap이 있으면
batch 일부를 적용하지 않고 snapshot을 다시 요청한다.

operation payload 계약:

| Type | payload 필수 field |
|---|---|
| `SET_GAME_STATE` | `status`, `phase`, `round`, `day_number`, `state_version`, `fast_forward_enabled` |
| `REPLACE_PLAYERS` | `players` 공개 player 배열 |
| `SET_PRIVATE_STATE` | `me`, 현재 인간 본인 projection |
| `SET_ACTION_WINDOW` | 2.3절 action window |
| `CLEAR_ACTION_WINDOW` | `window_id` |
| `APPEND_PUBLIC_EVENT` | 아래 `PublicEvent` |
| `APPEND_PRIVATE_EVENT` | 아래 `PrivateEvent`, 현재 인간 대상만 |
| `SET_RESULT` | 2.5절 종료 결과 |

`PublicEvent` 공통 field는 UUID `event_id`, 아래 enum `event_type`, UTC RFC 3339
`created_at`, 폐쇄형 object `data`이고 모두 필수다.

| `event_type` | `data` 필수 field |
|---|---|
| `GAME_BEGAN` | `message` |
| `TURN_OPENED` | `player_id`, `cycle`, `prompt` nullable |
| `PLAYER_SPOKE` | `player_id`, `message` |
| `PLAYER_PASSED` | `player_id` |
| `NIGHT_RESOLVED` | `round`, `killed_player_id` nullable |
| `VOTE_RESOLVED` | `round`, `phase`, `counts`, `tied`, `needs_revote` |
| `PLAYER_EXECUTED` | `player_id`, `revealed_role` |
| `FAST_FORWARD_ENABLED` | `enabled` true |
| `GAME_SAVED`·`GAME_RESUMED` | `phase`, `round` |
| `GAME_ENDED` | `winner`, `win_reason` |

`PublicEvent`와 각 `data` object는 표에 적힌 field만 갖는 폐쇄형 union이다.
`GAME_BEGAN.message`는 마스터플랜 3.4절의 고정 시작 문구다. player 관련 ID는 같은
game의 공개 player UUID다. `PLAYER_SPOKE.message`는 공백 정규화 뒤 1~200자,
`TURN_OPENED.cycle`은 1~2이고 nullable `prompt`가 있으면 마스터플랜 3.4절의 전원
`PASS` 고정 질문이다. `NIGHT_RESOLVED`와 `VOTE_RESOLVED.round`는 1~5,
저장·재개 event의 `round`는 0~5다. `NIGHT_RESOLVED.killed_player_id`는 UUID 또는
`null`, `PLAYER_EXECUTED.revealed_role`은 2.1절 `Role`이다.
`VOTE_RESOLVED.phase`는 `DAY_VOTE`, `REVOTE`, `FINAL_ACCUSATION` 중 하나다.
`VOTE_RESOLVED.counts`는 `target_player_id` UUID와 `vote_count` 0 이상 정수만 가진
폐쇄형 item 배열이다. 해소 당시 유효 후보를 좌석 오름차순으로 한 번씩 포함하고 각
count는 생존 투표자 수 이하이며 합계는 확정된 유효 표 수와 같다. actor, 자동 선택
여부와 개별 ballot은 종료 전 포함하지 않는다.
`GAME_ENDED.winner`는 2.1절 `Faction`, `win_reason`은 2.5절 enum이다.

현재 인간에게 허용하는 `PrivateEvent`는
`INVESTIGATION_RESULT {round, target_player_id, is_mafia}`와
`NIGHT_ACTION_ACCEPTED {round, action_type, target_player_id}`다. 다른 player의 private
event는 operation으로 만들지 않는다.

각 operation은 PostgreSQL `game_events.operation_type`, `schema_version`과 `payload`에
동일한 형태로 영구 저장된다. 한 visible transaction이 여러 operation을 만들면 같은
`front_sequence`와 연속 index를 사용하므로 Redis stream이 trim돼도 DB에서 완전한
batch를 다시 만들 수 있다.

### 5.2 sync envelope

```json
{
  "data": {
    "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
    "mode": "DELTA",
    "from_state_version": 12,
    "state_version": 12,
    "last_sequence": 42,
    "operations": [],
    "snapshot": null
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z"
  }
}
```

- `mode=DELTA`면 `snapshot=null`이고 `operations`에 0개 이상의 완전한 batch가
  sequence·index 순으로 들어간다.
- `mode=SNAPSHOT`이면 `snapshot`이 있고 `operations=[]`다. 같은 snapshot을 operation에
  중복하지 않는다.
- 변경이 없어도 `200`, `mode=DELTA`, `operations=[]`을 반환한다.
- `operations=[]`이면 `state_version`과 `last_sequence`는 요청 client 위치에서
  전진하지 않는다. version이 증가한 응답은 대응하는 operation batch가 반드시 있다.

### 5.3 `GET /api/v1/games/{game_id}/sync`

Query:

| 이름 | 필수 | 의미 |
|---|---|---|
| `after_state_version` | 예 | client가 마지막으로 적용한 version, 0 이상 |
| `after_sequence` | 예 | snapshot의 마지막 Front sequence, 0 이상 |

delta가 보존 범위 밖이거나 client version이 서버보다 크면 authoritative snapshot
mode로 응답한다. 소유권과 audience filter는 snapshot endpoint와 동일하다. snapshot의
`last_sequence`와 그 다음 SSE 구독 지점이 하나의 Front-visible sequence를 사용하므로
최초 GET과 SSE 연결 사이의 event도 재요청할 수 있다.

### 5.4 `GET /api/v1/games/{game_id}/events`

`text/event-stream` SSE endpoint다.

```text
id: 43
event: game_sync
data: {"game_id":"...","mode":"DELTA","from_state_version":12,"state_version":13,"last_sequence":43,"operations":[...],"snapshot":null}
```

- `Last-Event-ID`가 있으면 해당 Front sequence 다음부터 재개한다.
- 보존 범위 밖이면 첫 `game_sync` data를 `mode=SNAPSHOT`으로 보낸다.
- 하나의 SSE `game_sync` event는 한 `front_sequence`의 모든 operation을 index 순서로
  포함한다. 같은 batch 일부만 전송하지 않는다.
- heartbeat는 SSE comment로 보내며 game operation으로 처리하지 않는다.
- 연결이 끊겨도 게임 deadline은 계속된다.
- SSE 실패 시 Front는 동일 sync endpoint polling으로 전환한다.
- SSE와 polling이 동시에 같은 Front sequence를 전달해도 client deduplication으로 한 번만
  적용한다.

## 6. 피드백 API

### 6.1 `POST /api/v1/feedback`

`feedback_type` discriminated union이다. `X-User-Id`, `Idempotency-Key`가 필수다.

일반 피드백:

```json
{
  "feedback_type": "GENERAL",
  "rating": 4,
  "comment": "게임 흐름을 더 빠르게 확인할 수 있으면 좋겠습니다.",
  "tags": ["UX"]
}
```

게임별 피드백:

```json
{
  "feedback_type": "GAME",
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "rating": 5,
  "comment": "추리 과정이 재미있었습니다.",
  "tags": ["BALANCE", "DIALOGUE"]
}
```

Validation:

- `rating`은 1~5다.
- `comment`는 선택이며 정규화 후 1~1000자다.
- tag는 서버 등록 allowlist이고 중복 없이 최대 5개다.
- `GAME`은 현재 UUID가 소유하고 `COMPLETED`인 game만 허용한다.
- 한 사용자는 한 game에 `GAME` feedback을 한 건만 작성한다.
- 피드백은 게임 상태, Agent prompt나 자동 밸런스 조정 입력으로 사용하지 않는다.

Response `201`:

```json
{
  "data": {
    "feedback_id": "e2ee137c-04cb-451c-b913-928d102a8c34",
    "feedback_type": "GAME",
    "created_at": "2026-09-02T12:34:56.123Z"
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

## 7. 관리자 API

모든 endpoint는 `X-User-Id`가 `ADMIN_USER_IDS`에 정확히 등록돼야 한다. allowlist가
비어 있거나 파싱에 실패하면 전부 `403 ADMIN_ACCESS_DENIED`다. 관리자 API는
loopback·사설망 전용이며 MVP에서 read-only다.

### 7.1 `GET /api/v1/admin/games`

Query: `status`, `phase`, `cursor`, `limit`.

Item:

```json
{
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "owner_user_id": "8a2ab744-aea3-4b36-b975-ec73364b4a43",
  "status": "IN_PROGRESS",
  "phase": "NIGHT_ACTION",
  "round": 2,
  "state_version": 21,
  "player_count": 6,
  "open_window_kind": "NIGHT",
  "updated_at": "2026-09-02T12:34:56.123Z"
}
```

### 7.2 `GET /api/v1/admin/games/{game_id}`

진행 상태, version, public events, window metadata와 비밀 없는 failure code를 반환한다.
진행 중인 role, 개인 사실, 개별 행동·투표, seed와 Agent private context는 관리자에게도
반환하지 않는다. 종료 뒤에는 일반 종료 결과 범위만 볼 수 있다.

### 7.3 `GET /api/v1/admin/metrics`

Query `from`, `to`는 최대 31일 범위다.

```json
{
  "data": {
    "games_created": 120,
    "games_completed": 93,
    "games_saved": 12,
    "completion_rate": 0.775,
    "average_rounds": 3.2,
    "wins_by_faction": {"CITIZEN": 49, "MAFIA": 44},
    "auto_action_count": 18,
    "feedback_average": 4.1
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z"
  }
}
```

LLM token·비용·timeout·예산 metric은 제공하지 않는다.

## 8. Backend 내부 Engine API

MCP runtime만 호출하는 별도 private network endpoint다. 일반 Front와 브라우저에
route와 secret을 노출하지 않는다.

### 8.1 요청 인증

필수 header:

```text
X-Engine-Timestamp: 1788352496
X-Engine-Nonce: 53c505b1-6273-4dbf-81bf-746c562fe900
X-Engine-Signature: <base64url HMAC-SHA256>
X-Agent-Capability: <opaque random capability>
```

canonical 서명 입력:

```text
METHOD\n
PATH\n
CANONICAL_QUERY\n
SHA256_HEX(RAW_BODY)\n
TIMESTAMP\n
NONCE
```

- `METHOD`는 대문자, `PATH`는 percent decode를 하지 않은 absolute path다.
- `CANONICAL_QUERY`는 RFC 3986 percent-encoding 뒤 encoded key, encoded value 순으로
  정렬하고 `key=value`를 `&`로 연결한다. 중복 key도 제거하지 않는다.
- body가 없으면 빈 byte string의 SHA-256 hex를 사용한다. timestamp는 10진 Unix
  seconds, nonce는 UUID v4다. signature는 padding 없는 base64url이다.
- `ENGINE_INTERNAL_API_SECRET`으로 HMAC-SHA256 서명하고 constant-time으로 비교한다.
- Backend 수신 시각과 timestamp 차이는 최대 60초다. 서명 검증 뒤 PostgreSQL
  `internal_request_nonces`에 `scope=ENGINE_HMAC`, nonce와 request hash를 INSERT한다.
  unique 충돌은 replay다. Redis는 이미 소비된 nonce cache로만 사용할 수 있고 장애가
  나도 PostgreSQL 판정을 계속한다.
- capability는 Backend CSPRNG가 만든 32-byte padding 없는 base64url 문자열이다.
  Backend는 hash와 `agent_job_id`, `game_id`, `subject_type`, `subject_id`, `phase`,
  `state_version`, `window_id`, 허용 resource·tool, 만료·폐기 상태만 저장한다. raw
  token은 MCP에 한 번 전달하고 DB·log에 남기지 않는다.
- MCP는 capability를 opaque 값으로 보관·전달할 뿐 내용을 decode하거나 검증하지
  않는다. `MCP_SERVER_AUTH_SECRET`도 capability 발급·검증에 사용하지 않는다.
- capability 유효 기간은 현재 phase/window와 보안상 최대 120초 중 이른 값까지다.
  이는 LLM timeout 설정이 아니라 내부 권한의 수명이다.
- HMAC 검증 뒤 Backend가 capability hash, 미폐기, 만료, allowlist와 현재 DB 상태를
  다시 비교한다.
- 실패 이유를 상세히 구분해 외부로 노출하지 않는다.

### 8.2 `GET /internal/v1/agent-context`

Query `scope=public|me|turn|persona|gm-guide` 중 capability가 허용한 하나를 사용한다.

Response:

```json
{
  "context_version": 1,
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "subject_type": "AI_PLAYER",
  "subject_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
  "phase": "DAY_DISCUSSION",
  "state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "scope": "turn",
  "data": {
    "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
    "window_kind": "SPEECH",
    "cycle": 1,
    "opened_state_version": 12,
    "server_time": "2026-09-02T12:34:56.123Z",
    "deadline_at": null,
    "turn_player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
    "allowed_tools": ["propose_speech", "propose_pass"],
    "valid_targets": []
  }
}
```

이 절과 여기서 명시적으로 참조하는 이 API 명세의 공통 모델이 다섯 MCP Resource
`data` 상세 schema의 유일한 정본이다. MCP 구현 설계서나 fixture가 이 schema를 다시
정의해서는 안 된다. 공통 envelope와 모든 하위 object는 폐쇄형이며 명시되지 않은
field를 거부한다. 모든 field는 필수이고, 아래에서 `nullable`로 적은 field만 JSON
`null`을 허용한다. UUID는 canonical hyphen 형식, 시각은 UTC RFC 3339 형식이다.

| 공통 field | 계약 |
|---|---|
| `context_version` | 정수 상수 `1` |
| `game_id` | capability가 고정한 game UUID |
| `subject_type` | `AI_PLAYER` 또는 `GM` |
| `subject_id` | AI player는 자기 `player_id`, GM은 `game_id`와 같은 UUID |
| `phase` | 2.1절 `GamePhase` |
| `state_version` | 1 이상의 정수, capability 발급 버전과 일치 |
| `window_id` | 현재 `agent_jobs.window_id` UUID |
| `scope` | query 및 MCP Resource URI에 대응하는 고정값 |
| `data` | 아래 scope별 폐쇄형 object |

`subject_type`별 허용표는 다음과 같다. 허용되지 않은 scope는 존재 여부를 구분하지
않고 `403 CAPABILITY_DENIED`로 거부하며, 다른 agent ID를 query로 선택할 수 없다.

| subject | `public` | `me` | `turn` | `persona` | `gm-guide` |
|---|---:|---:|---:|---:|---:|
| `AI_PLAYER` | 허용 | 허용 | 허용 | 허용 | 거부 |
| `GM` | 허용 | 거부 | 거부 | 거부 | 허용 |

#### 8.2.1 `scope=public` data

모든 subject에게 같은 game·`state_version`이면 같은 projection을 반환한다. envelope의
subject field 외에는 요청 주체에 따라 달라지는 값이 없어야 한다.

| field | 타입·제약 |
|---|---|
| `game` | 아래에 명시한 공개 game 폐쇄형 object |
| `scenario` | 아래에 명시한 scenario 폐쇄형 object |
| `players` | 아래에 명시한 공개 player 6~9개, `seat` 오름차순 |
| `public_events` | 5.1절 `PublicEvent` 0개 이상, Engine 확정 순서 |

`game`은 `game_id`, `status`, `phase`, `round`, `day_number`, `state_version`,
`last_sequence`, `ruleset_version`, `scenario_version`, `player_count`, `mafia_count`,
`fast_forward_enabled`, `updated_at`만 가진다. `round`는 0~5, `day_number`는 1~6,
`state_version`은 1 이상, `last_sequence`는 0 이상이다. `player_count`는 6~9이고
`mafia_count`는 6~7명이면 1, 8~9명이면 2다. 두 version 값은 각각
`mystery-v1`, `scenario-v1`이다.

`scenario`는 `scenario_id` 1~64자, `title` 1~120자, 비어 있지 않은 `background`,
`victim` 1~120자와 `locations`만 가진다. `locations`는 서로 다른 1~80자 문자열
4~5개다. 공개 player는 `player_id`, `seat` 1~9, `display_name` 1~40자,
`kind=HUMAN|AI`, `alive`, nullable `revealed_role`(2.1절 `Role`), nullable
`eliminated_phase`(2.1절 `GamePhase`), nullable `eliminated_round`(1~5)만 가진다.
배열 안의 `player_id`와 `seat`는 각각 중복되지 않고
`HUMAN`은 정확히 한 명이다. 처형 전·종료 전 role 공개 조건은 2.2절을 따른다.

진행 중 `alive=true` player의 세 탈락 field는 모두 `null`이다. `alive=false`이면
`eliminated_phase`는 `NIGHT_ACTION`, `DAY_VOTE`, `REVOTE`, `FINAL_ACCUSATION` 중 하나고
`eliminated_round`는 non-null이다. 밤 사망자의 `revealed_role`은 종료 전 `null`,
투표로 처형된 player는 즉시 non-null이다. `game.status=COMPLETED`이면 생존 여부와
관계없이 모든 player의 `revealed_role`이 non-null이다.

`game.game_id`, `game.phase`, `game.state_version`은 공통 envelope의 같은 값과 반드시
일치한다. `public_events`에는 `PUBLIC` audience event만 넣고 진행 중 개별 투표,
공격자, 보호 대상, 조사 결과와 다른 player의 role·알리바이·관찰을 넣지 않는다.
`event_id`는 배열 안에서 중복되지 않는다. Front의 종료 `result`는 MCP `public`
Resource에 넣지 않는다.

`VOTE_RESOLVED.data.counts`는 5.1절의 item·정렬·합계 계약을 그대로 사용한다.

#### 8.2.2 `scope=me` data

`AI_PLAYER` 전용이며 다음 field만 포함한다.

| field | 타입·제약 |
|---|---|
| `player_id` | UUID, envelope의 `subject_id`와 같음 |
| `role` | 2.1절 `Role` |
| `alive` | boolean |
| `alibi` | 공백 정규화된 한 문장, 1~240자 |
| `observation` | 공백 정규화된 한 문장, 1~240자 |
| `private_events` | 아래 `PrivateEvent` 0개 이상, Engine 확정 순서 |

`PrivateEvent` 공통 field는 `event_id`, `event_type`, `created_at`, `data`이고 모두
필수다. 허용 union은 다음 두 종류뿐이다.

| `event_type` | `data` 필수 field |
|---|---|
| `INVESTIGATION_RESULT` | `round` 1~5, `target_player_id` UUID, `is_mafia` boolean |
| `NIGHT_ACTION_ACCEPTED` | `round` 1~5, `action_type=ATTACK\|INVESTIGATE\|PROTECT`, `target_player_id` UUID |

`data`도 폐쇄형이다. 이 subject에게 발생한 event만 반환하며, 마피아가 둘이어도 다른
마피아의 role·action·응답 여부를 포함하지 않는다. `event_id`는 배열 안에서 중복되지
않는다.

#### 8.2.3 `scope=turn` data

`AI_PLAYER`의 현재 job 전용이며 다음 field만 포함한다.

| field | 타입·제약 |
|---|---|
| `window_id` | UUID, envelope의 `window_id`와 같음 |
| `window_kind` | `SPEECH`, `NIGHT`, `VOTE`, `REVOTE`, `FINAL_VOTE` |
| `cycle` | 정수 1~2; `SPEECH`의 추가 순환만 2 |
| `opened_state_version` | 1 이상의 정수 |
| `server_time` | 응답 생성 시각 |
| `deadline_at` | `SPEECH`이면 `null`, 나머지는 UTC RFC 3339 시각 |
| `turn_player_id` | `SPEECH`이면 subject UUID, 나머지는 `null` |
| `allowed_tools` | 아래 matrix와 정확히 같은 Tool 이름 배열 |
| `valid_targets` | 아래 target 0~8개, 좌석 오름차순 |

target object는 `player_id` UUID와 `display_name` 1~40자만 가진다. 숨은 role이나
현재 선택 수는 넣지 않는다. `player_id`는 배열 안에서 중복되지 않고 같은 `public`
projection의 생존 player와 일치한다. 자기 자신 제외 규칙을 적용하되 의사의 `NIGHT`
target에만 자기 자신을 허용한다.

| `window_kind` | `allowed_tools` | `valid_targets` |
|---|---|---|
| `SPEECH` | `propose_speech`, `propose_pass` | 빈 배열 |
| `NIGHT` | `propose_night_action` | Backend가 role·생존 상태로 확정한 대상 |
| `VOTE`, `REVOTE`, `FINAL_VOTE` | `propose_vote` | Backend가 해당 투표에 확정한 후보 |

`phase`와 `window_kind` 조합은 각각 `DAY_DISCUSSION|FINAL_DISCUSSION`→`SPEECH`,
`NIGHT_ACTION`→`NIGHT`, `DAY_VOTE`→`VOTE`, `REVOTE`→`REVOTE`,
`FINAL_ACCUSATION`→`FINAL_VOTE`만 허용한다. `allowed_tools`는 표의 순서로 중복 없이
직렬화한다. `SPEECH`의 `valid_targets`는 비어 있고 나머지 window는 1~8개다.
`opened_state_version`은 envelope `state_version` 이하이고 timed window의
`deadline_at`은 성공 응답의 `server_time`보다 뒤여야 한다.

MCP는 이 값을 근거로 게임 규칙을 다시 계산하지 않는다. capability와 Engine이 허용한
현재 Tool만 노출하고 제출 시 Backend가 role·phase·target·deadline·version을 다시
검증한다.

#### 8.2.4 `scope=persona` data

`AI_PLAYER` 전용이며 서버에 등록되고 game에 배정된 preset 한 개만 반환한다.

| field | 타입·제약 |
|---|---|
| `persona_id` | 1~64자 안정 ID |
| `version` | 1~32자 |
| `display_name` | 1~40자 |
| `speech_style` | 1~240자 |
| `backstory` | 1~500자 |
| `parameters` | 아래 10개 field만 가진 폐쇄형 object |

`parameters`는 `sociability`, `assertiveness`, `suspicion`, `deception`,
`risk_tolerance`, `memory_recall`, `reasoning_skill`, `emotionality`,
`cooperativeness`, `verbosity`를 정확히 한 번씩 포함한다. 모든 값은 0.0~1.0의
유한 number이고, `reasoning_skill`은 `mystery-v1`의 모든 preset에서 같은 승인 값이다.
persona는 말투와 표현 성향만 바꾸며 규칙·정보 권한·추론 능력을 바꾸지 않는다.

#### 8.2.5 `scope=gm-guide` data

`GM` 전용이며 다음 폐쇄형 union이다.

| field | 타입·제약 |
|---|---|
| `narration_kind` | `PUBLIC_EVENT` 또는 `FIXED_MESSAGE` |
| `source_public_event` | 5.1절 `PublicEvent` 한 개 또는 `null` |
| `fixed_message_key` | 아래 고정 key 또는 `null` |

`PUBLIC_EVENT`이면 `source_public_event`만 object이고 `fixed_message_key=null`이다.
`FIXED_MESSAGE`이면 `source_public_event=null`이고 `fixed_message_key`는 다음 중 하나다.

| `fixed_message_key` | 제품 문구 정본 |
|---|---|
| `GAME_INTRO` | 마스터플랜 3.4절 게임 시작 안내 |
| `ALL_PASS_FOLLOW_UP` | 마스터플랜 3.4절 전원 `PASS` 후 고정 질문 |
| `FINAL_ACCUSATION_NOTICE` | 마스터플랜 3.8절 최종 지목 안내 |

`source_public_event`는 현재 GM job을 연 원인 event와 일치하고 같은
`state_version`의 `public.data.public_events`에 같은 `event_id`와 내용으로 존재해야
한다. 이 scope에는 role별 action, 후보 target, 공격자, 보호 대상, 조사 결과, 개별
투표와 private event를 넣지 않는다. Backend projection이 알 수 없는 field나 금지
field를 반환하면 MCP는 조용히 제거해 전달하지 않고 해당 Resource read를
fail-closed한다.

### 8.3 `POST /internal/v1/mcp-bootstrap/consume`

MCP runtime이 bootstrap token과 opaque capability를 받은 직후 Engine HMAC으로
호출한다.

```json
{
  "bootstrap_token": "<signed bootstrap token>"
}
```

Backend는 bootstrap signature, claim의 `agent_job_id`·subject·capability hash와
저장된 capability 및 현재 job reservation을 다시 검증한다. 이 요청의
`X-Agent-Capability` header가 유일한 capability 원문이며 body에 중복하지 않는다.
header hash가 bootstrap claim·DB hash와 모두 같아야 한다. token nonce를 PostgreSQL
`internal_request_nonces`에
`scope=MCP_BOOTSTRAP`으로 INSERT한다. 성공 응답은 `{"status":"CONSUMED"}`이며
재사용·만료·capability 불일치는 fail-closed한다. MCP는 이 성공 뒤에만 session을
활성화한다.

### 8.4 `POST /internal/v1/agent-proposals`

Request:

```json
{
  "proposal_id": "184e0e1d-3083-489d-a2f4-6639f61e59e1",
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "agent_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "expected_state_version": 12,
  "proposal": {
    "type": "SPEAK",
    "message": "공개된 발언의 앞뒤가 맞지 않는 부분을 확인하고 싶습니다.",
    "target_player_id": null,
    "public_rationale": "공개 발언의 모순을 확인하는 질문"
  }
}
```

허용 proposal type은 `SPEAK`, `PASS`, `NIGHT_ACTION`, `VOTE`다. Backend는 capability,
reservation, current state와 domain 규칙을 모두 재검증한다.
`proposal_id`가 내부 idempotency key다. 같은 agent가 같은 ID·body를 재전송하면 저장된
terminal 결과를 반환하고 다른 body에 재사용하면 `409 IDEMPOTENCY_KEY_REUSED`다.
별도 `Idempotency-Key` header는 사용하지 않는다.

Response `200`:

```json
{
  "proposal_id": "184e0e1d-3083-489d-a2f4-6639f61e59e1",
  "status": "ACCEPTED",
  "result_state_version": 13
}
```

MCP Tool 성공은 게임 행동의 무조건 성공이 아니라 Backend가 proposal을 검증·반영한
결과다. 만료·폐기·phase·version·subject·audience 불일치를 외부에서 구분하지 않고
`403 CAPABILITY_DENIED`로 거부한다. 상세 분류는 비밀 없는 내부 운영 log에만 남긴다.

## 9. Mafia Game MCP 계약

### 9.1 transport와 session

- endpoint는 `${MAFIA_MCP_URL}` 전체 값이며 기본 개발 예시는
  `http://127.0.0.1:8100/mcp`다.
- MCP Streamable HTTP initialize로 session을 만들고 `Mcp-Session-Id`를 사용한다.
- Backend Agent Manager가 `MCP_SERVER_AUTH_SECRET`으로 서명한 일회성 bootstrap token을
  `Authorization: Bearer <token>`으로 보낸다. raw shared secret 자체를 보내지 않는다.
- bootstrap token은 먼저 key 정렬·공백 없는 UTF-8 canonical JSON을 padding 없는
  base64url `encoded_payload`로 만든 뒤
  `encoded_payload.base64url(HMAC-SHA256(MCP_SERVER_AUTH_SECRET, ASCII(encoded_payload)))`
  로 직렬화한다. claim은
  `token_type=MCP_BOOTSTRAP`, `agent_job_id`, `game_id`, `subject_type`, `subject_id`,
  `capability_hash`, `iat`, 최대 120초 `exp`와 UUID nonce다.
- claim object는 폐쇄형이다. `capability_hash`는 raw capability byte string의
  SHA-256 lowercase hex 64자이며, `iat`와 `exp`는 UTC Unix seconds 정수다.
  `iat <= current_time < exp`이고 `1 <= exp - iat <= 120`인 경우만 허용하며 clock
  leeway를 적용하지 않는다. 운영 host는 동기화된 시스템 시계를 사용한다.
- initialize HTTP 요청의 `X-Agent-Capability` header에 raw opaque capability를 정확히
  한 번 전달한다. MCP는 해당 header를 session memory에만 보관하고 bootstrap
  signature를 확인한 뒤 8.3절 consume까지 성공해야 session을 연다.
- 최초 initialize 이후 같은 활성 session의 HTTP 요청은 동일 bearer bootstrap을
  계속 보내 session owner를 증명하되 `X-Agent-Capability`는 다시 보내지 않는다.
  MCP는 후속 bearer에 대해 서명·claim·만료와 session owner 일치를 검사하지만 이미
  성공한 bootstrap consume을 반복하지 않는다. 다른 bearer, 만료 bearer 또는
  capability header 재전송은 session을 닫고 고정 오류로 거부한다.
- session은 정확히 한 `agent_job_id`, `game_id`, `subject_type`과 `subject_id`에
  묶인다. AI player는 `subject_type=AI_PLAYER`, GM은 `subject_type=GM`이다.
- AI player의 `subject_id`는 해당 `player_id`다. GM은 별도 player row를 만들지 않고
  `subject_id`에 현재 `game_id` UUID를 그대로 사용한다.
- Backend Agent Manager는 `agent_jobs` reservation 한 건마다 새 capability, 새
  bootstrap nonce·token과 새 MCP initialize session을 만든다. 같은 subject·phase·
  window·state라도 다른 job에 이 셋을 재사용하지 않는다.
- job이 성공, fallback, stale, 실패(호출 취소 포함) 또는 lease 만료로 끝나면 Backend는
  capability를 폐기하고 session 종료를 시도한다. MCP는 session memory의 capability와
  subject binding을 제거한다. phase·window·state version 변화도 기존 capability를
  즉시 폐기하며 늦은 결과를 새 상태에 자동 rebase하지 않는다.
- transport가 끊기면 소비한 bootstrap token이나 기존 `Mcp-Session-Id`를 다시 쓰지
  않는다. 같은 job lease 안에서 재접속할 수 있을 때도 기존 capability를 먼저
  폐기하고 새 capability·bootstrap·session으로 시작한다. Backend가 job의 현재 상태를
  확인할 수 없으면 재접속하지 않고 정의된 fallback을 수행한다.
- 정상 session 종료는 `DELETE /mcp`와 `Mcp-Session-Id`를 사용한다. MCP는 Tool
  terminal 결과, 명시적 DELETE, transport 종료, bootstrap·capability 만료와 process
  shutdown에서 session memory를 멱등 폐기한다. idle 요청이 30초 동안 없으면 session을
  종료하며 event store나 외부 저장소로 session을 복원하지 않는다.
- bootstrap consume 응답이 유실되면 해당 initialize와 session을 실패로 닫고 같은
  token을 다시 consume하지 않는다. Backend만 job 상태를 확인한 뒤 살아 있는 job에
  fresh capability·bootstrap·session을 발급할 수 있다.
- 운영은 검증된 TLS를 사용한다. loopback 개발만 평문 HTTP를 허용한다.

### 9.2 Resource

session이 agent를 이미 고정하므로 URI에서 다른 agent ID를 받지 않는다.

| URI | Engine `scope` | 허용 subject | `data` 정본 |
|---|---|---|---|
| `mafia://session/public` | `public` | AI_PLAYER, GM | 8.2.1절 |
| `mafia://session/me` | `me` | AI_PLAYER | 8.2.2절 |
| `mafia://session/turn` | `turn` | AI_PLAYER | 8.2.3절 |
| `mafia://session/persona` | `persona` | AI_PLAYER | 8.2.4절 |
| `mafia://session/gm-guide` | `gm-guide` | GM | 8.2.5절 |

AI GM session은 `public`과 `gm-guide`만 사용할 수 있다. `me`, `turn`, `persona`와
모든 행동 Tool capability를 받지 않는다.

Resource read는 요청 URI와 같은 URI, MIME type `application/json`인 text content를
정확히 한 개 반환한다. text의 JSON은 8.2절 공통 envelope와 해당 `data` schema 전체다.
MCP는 Engine 응답의 subject·scope·version과 폐쇄형 schema를 확인한 뒤 그대로
직렬화하며, 알 수 없거나 금지된 field를 임의로 제거해서 성공 응답으로 바꾸지 않는다.

### 9.3 Tool

| Tool | 입력 | 허용 상황 |
|---|---|---|
| `propose_speech` | `message`, `public_rationale` | 자기 발언 차례 |
| `propose_pass` | 없음 | 자기 발언 차례 |
| `propose_night_action` | `target_player_id` | 생존 특수 역할의 밤 |
| `propose_vote` | `target_player_id` | 일반·재·최종 투표 |

- `game_id`, `agent_id`, role, phase와 version을 Tool input으로 받지 않는다. session과
  capability에서 가져온다.
- MCP는 입력 schema를 검사한 뒤 내부 Engine API에 전달할 뿐 게임 상태를 직접
  변경하지 않는다.
- 응답에는 `proposal_id`, `status`, `result_state_version`과 고정 오류 코드만 담는다.
- Engine의 terminal 결과를 반환한 뒤 해당 job session은 추가 Tool 호출을 받지 않고
  종료 절차로 이동한다. Backend의 window별 첫 유효 submission 제약이 최종 중복을
  막는다.
- MCP는 Tool 호출을 처음 전달하기 전에 UUID v4 `proposal_id`를 한 번 생성한다.
  Engine 응답이 유실되어 같은 살아 있는 job에서 재시도한다면 동일
  `proposal_id`와 byte-equivalent proposal body를 사용하고 Engine HMAC nonce만 새로
  만든다. 다른 body로 ID를 재사용하거나 stale version·window를 자동 갱신하지 않는다.

#### 9.3.1 고정 오류 매핑

initialize 단계의 HTTP 오류 body는 `{"error":"<code>"}` 하나만 사용한다.
JSON-RPC 오류는 숫자 `code`와 고정 한국어 `message`만 가지며 `data`, upstream body,
exception text와 stack trace를 포함하지 않는다.

| 경계 | 조건 | HTTP/JSON-RPC | 공개 code |
|---|---|---:|---|
| initialize | bearer 또는 capability header 누락·형식 오류 | HTTP 401 | `AUTH_REQUIRED` |
| initialize | bootstrap 서명·claim·만료·replay·mismatch 또는 consume 거부 | HTTP 403 | `BOOTSTRAP_DENIED` |
| session | 알 수 없거나 닫힌 `Mcp-Session-Id` | HTTP 404 | `SESSION_NOT_FOUND` |
| protocol | JSON-RPC 또는 Tool 폐쇄형 입력 오류 | `-32602` | `VALIDATION_ERROR` |
| handler | 비활성 session 또는 terminal 뒤 호출 | `-32001` | `SESSION_NOT_ACTIVE` |
| Engine | capability·subject·scope·phase·window·version 거부와 존재 은닉 대상 404 | `-32002` | `CAPABILITY_DENIED` |
| Engine | timeout·연결 단절·429·5xx | `-32003` | `DEPENDENCY_UNAVAILABLE` |
| Engine | 성공 응답 schema 위반 또는 예상하지 않은 4xx | `-32004` | `UPSTREAM_CONTRACT_VIOLATION` |
| proposal | 같은 `proposal_id`의 body conflict | `-32005` | `PROPOSAL_CONFLICT` |
| handler | 분류되지 않은 내부 실패 | `-32603` | `INTERNAL_ERROR` |

취소는 상위 task로 전파하고 session cleanup을 수행한다. 취소 원문을 별도 protocol
payload로 변환하지 않는다.

### 9.4 구조화 운영 로그와 redaction

이 절은 initialize, bootstrap consume, Resource, Tool, Engine adapter와 session 종료의
성공·거부·예외 경로 모두에 적용한다.

- 구조화 record가 가질 수 있는 application field는 `request_id`, `correlation_id`,
  `operation`, `status`, `duration_ms`, `error_class`뿐이다. `error_class`는 비밀 없는
  폐쇄형 분류이고 exception message를 그대로 사용하지 않는다. 두 ID는 검증된 UUID만
  기록하며 임의 header 문자열을 그대로 복사하지 않는다.
- Resource·Tool request·response payload, target player, game·agent·player ID, private
  context, capability, bootstrap token, signature, secret, HTTP header, prompt, raw model
  response, exception 전문·stack과 chain-of-thought를 로그에 남기지 않는다.
- logger와 sink의 표준 process metadata는 허용하되 application payload를 자동
  직렬화하지 않는다. formatter·sink 장애도 금지값을 임시 파일이나 spool에 쓰는
  근거가 아니다.
- MCP runtime은 application DB·Redis·queue 기반의 영속 audit outbox를 만들지 않고
  Backend `event_outbox`를 읽거나 쓰지 않는다. sink 종류와 보존 기간은 배포 운영
  정책이며 MCP wire 계약이 아니다.

## 10. Agent 구조화 출력

### 10.1 AI player 결과

LLM adapter가 AI player의 구조화 결과를 Agent Manager에 반환하는 경로에서도
8.4절과 같은 proposal union을 사용한다.

```json
{
  "type": "SPEAK",
  "target_player_id": null,
  "message": "어젯밤 공개 결과를 바탕으로 다시 확인해 보겠습니다.",
  "public_rationale": "공개 정보만 사용한 질문"
}
```

- 추가 field와 자연어 wrapper를 허용하지 않는다.
- 내부 추론 전문을 요청하거나 field로 받지 않는다.
- schema 오류에는 교정을 한 번만 요청하고 이후 fallback한다.
- 모델·prompt 설정은 Backend 배포 설정이며 사용자·관리자 API로 변경하지 않는다.
- timeout, token 상한, token·비용 반환 field와 관련 endpoint는 MVP에 없다.
- Agent Manager는 외부 호출과 별도로 reservation부터 최대 15초인 고정 worker
  lease와 fencing token을 사용한다. timed window의 남은 시간이 더 짧으면 그 시각을
  쓴다. lease 만료 뒤 결과는 버리고 scheduler가 `PASS`, 자동 선택 또는 고정 GM
  문구를 확정한다. 이 lease는 조정 가능한 LLM timeout API나 metric이 아니다.

### 10.2 AI GM 직접 반환 결과

AI GM은 MCP `public`, `gm-guide` Resource를 읽기만 한다. LLM adapter는 다음
폐쇄형 결과를 MCP Tool이나 `/internal/v1/agent-proposals`를 거치지 않고 Backend
Agent Manager에 직접 반환한다.

```json
{
  "type": "GM_NARRATION",
  "narration_kind": "PUBLIC_EVENT",
  "source_event_id": "a7dd582b-bcad-4d91-b045-1c771128e380",
  "fixed_message_key": null,
  "message": "밤이 지나고 모두가 다시 모였습니다. 다행히 희생자는 없었습니다."
}
```

| field | 타입·제약 |
|---|---|
| `type` | 상수 `GM_NARRATION` |
| `narration_kind` | `PUBLIC_EVENT` 또는 `FIXED_MESSAGE` |
| `source_event_id` | UUID 또는 `null` |
| `fixed_message_key` | 8.2.5절 고정 key 또는 `null` |
| `message` | 공백 정규화된 한 문단의 plain text, 1~400자 |

`PUBLIC_EVENT`이면 `source_event_id`가 현재 `gm-guide.source_public_event.event_id`와
같고 `fixed_message_key=null`이다. `FIXED_MESSAGE`이면 `source_event_id=null`이고
`fixed_message_key`가 현재 guide와 같으며 `message`는 마스터플랜의 해당 고정 문구와
정확히 일치해야 한다.

Backend Agent Manager는 추가 field·자연어 wrapper, guide reference 불일치, 금지된
private 사실과 길이 위반을 거부한다. 교정은 한 번만 허용하며 그 뒤에는 Backend의
고정 한국어 문구를 사용한다. 검증된 결과라도 현재 job의 lease token·fencing token,
window와 `state_version`을 다시 확인한 뒤에만 `PUBLIC` event로 저장한다. 늦은 결과는
`STALE`로 끝내고 공개하지 않는다.

## 11. 보안·비간섭성 요구

- 다른 사용자 소유 game은 `404`로 통일해 존재 여부를 숨긴다.
- UUID가 일치해도 command마다 game owner, human player, alive, phase, role, target,
  deadline, window와 state version을 검증한다.
- Front snapshot, sync와 SSE는 모두 같은 audience projection 함수를 사용한다.
- 마피아가 둘이어도 상대 마피아 role과 action을 어떤 private payload에도 넣지 않는다.
- 게임 진행 중 AI GM에는 role, 공격자, 보호 대상, 조사 결과와 개별 투표를 전달하지
  않는다. 종료 뒤 공개된 role도 `gm-guide`에는 넣지 않고 `public.players`로만 제공한다.
- 관리자 allowlist는 일반 game 소유권을 우회하는 사용자 기능으로 사용하지 않는다.
- redirect URL, callback, OIDC metadata와 OAuth endpoint는 API 표면에서 제거한다.
- Backend 공개·내부 HTTP log에는 request ID, route, status, duration, game ID와
  분류 오류만 남기고 사용자 입력 본문과 private payload를 기본 기록하지
  않는다. MCP runtime log에는 9.4절의 더 엄격한 allowlist를 적용한다.
- Backend의 `event_outbox`는 MCP 감사 로그 저장소가 아니며 MCP runtime은 이를
  직접 소비하거나 갱신하지 않는다.

## 12. 계약 테스트

- `/openapi.json` snapshot에서 path, union discriminator, enum과 필수 header 확인
- UUID 누락·잘못된 version, 다른 소유자와 관리자 allowlist 거부
- create replay와 사용자별 직전 scenario 제외 동시성
- 모든 command의 phase·role·alive·target·deadline success/reject matrix
- 같은 idempotency key replay와 다른 body 재사용 충돌
- stale version과 같은 window 동시 제출
- sync no-change `200 operations=[]`, delta, snapshot fallback
- SSE reconnect, duplicate Front sequence와 polling 전환
- 진행·종료 시점별 role·밤 행동·개별 투표 비노출
- feedback union과 게임별 unique
- Engine canonical query/body HMAC, 60초 timestamp, 120초 nonce replay,
  stale capability와 agent 간 비간섭성
- 5개 Resource의 공통 envelope·scope별 exact key·nullable·union 검증과 unknown field
  fail-closed 처리
- 같은 public projection의 subject 비의존성, 다른 AI의 `me`·`persona` 비간섭성과
  `turn` target의 role 비노출
- GM session에 `me`, `turn`, `persona`, role-conditioned target과 행동 Tool이 없고
  `public`, `gm-guide`만 있는지 확인
- GM 구조화 결과가 Agent Manager로 직접 반환되고 MCP Tool·proposal API 호출은 0회인지,
  잘못된 guide reference·private 사실·late fencing 결과가 fallback 또는 stale인지 확인
- job마다 capability hash·bootstrap nonce·MCP session ID가 다르고 성공·fallback·stale·
  실패(호출 취소 포함)·lease 만료 뒤 이전 값과 소비된 bootstrap이 거부되는지 확인
- reconnect가 새 capability·bootstrap·session을 사용하고 이전 state/window 결과를
  자동 rebase하지 않는지 확인
- MCP session 고정, Resource allowlist와 Tool proposal 재검증
- 같은 `proposal_id`·같은 body의 불명확 응답 재시도는 mutation 한 번과 terminal
  결과 replay가 되고 다른 body 재사용은 충돌하는지 확인
- MCP 구조화 로그의 metadata allowlist와 payload·target·capability·token·signature·
  ID·header·prompt·raw response·exception 전문 비기록 검증
- LLM token·비용·timeout field와 API가 노출되지 않는지 확인
