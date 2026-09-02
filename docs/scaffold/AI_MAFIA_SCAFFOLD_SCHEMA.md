# AI 마피아 연결 뼈대 JSON Schema 계약 `scaffold-v1`

이 문서의 `scaffold-v1`은 연결 검증용 임시 계약이다. 실제 게임 기능 구현 때 `basic-v1` 계약으로 교체하며 두 ruleset을 같은 endpoint에서 혼용하지 않는다.

## 1. 공통 타입

```json
{
  "uuid": "00000000-0000-4000-8000-000000000001",
  "time": "2026-09-02T12:00:00Z"
}
```

모든 JSON object는 별도 표기가 없는 한 `additionalProperties=false`다. 문자열은 trim 후 검증하고 ID는 UUID, 시간은 UTC ISO-8601이다.

## 2. `POST /api/v1/games`

Request:

```json
{
  "player_count": 5,
  "ruleset_version": "scaffold-v1",
  "idempotency_key": "00000000-0000-4000-8000-000000000010"
}
```

| field | type | required | rule |
|---|---|---|---|
| `player_count` | integer | yes | 5~9 |
| `ruleset_version` | string | yes | `scaffold-v1` only |
| `idempotency_key` | UUID | yes | 같은 요청 재전송 허용 |

Response 201:

```json
{
  "game_id": "00000000-0000-4000-8000-000000000011",
  "status": "IN_PROGRESS",
  "phase": "ROLE_REVEAL",
  "state_version": 1,
  "player": {
    "player_id": "00000000-0000-4000-8000-000000000012",
    "kind": "HUMAN",
    "role": null,
    "alive": true
  },
  "players": []
}
```

## 3. `GET /api/v1/games/{game_id}`

Response 200:

```json
{
  "game_id": "uuid",
  "status": "IN_PROGRESS",
  "phase": "ROLE_REVEAL",
  "state_version": 1,
  "players": [],
  "public_events": [],
  "private_events": [],
  "allowed_commands": ["PING", "BEGIN_GAME", "PAUSE"],
  "active_operation": null,
  "updated_at": "2026-09-02T12:00:00Z"
}
```

필수 field는 `game_id,status,phase,state_version,players,public_events,private_events,allowed_commands,active_operation,updated_at`이다. 뼈대에서는 role을 항상 `null`로 반환한다.

## 4. `POST /api/v1/games/{game_id}/commands`

Request:

```json
{
  "command": "PING",
  "expected_version": 1,
  "idempotency_key": "00000000-0000-4000-8000-000000000012"
}
```

`command` enum은 `PING|BEGIN_GAME|PAUSE|RESUME`이며, `target_player_id`, `message`, `mode`는 뼈대 계약에서 금지한다. `expected_version`은 1 이상 정수다.

Response 202:

```json
{
  "accepted": true,
  "operation_id": "00000000-0000-4000-8000-000000000013",
  "state_version": 2,
  "phase": "ROLE_REVEAL",
  "status": "COMPLETED"
}
```

## 5. operation·MCP

Operation response:

```json
{
  "operation_id": "uuid",
  "game_id": "uuid",
  "command": "PING",
  "status": "COMPLETED",
  "accepted_version": 1,
  "result_version": 2,
  "error_code": null,
  "created_at": "2026-09-02T12:00:00Z",
  "updated_at": "2026-09-02T12:00:00Z"
}
```

MCP `game_submit_proposal` request/response:

```json
// request arguments
{"action":"PING","expected_version":1}

// result data
{"proposal_id":"uuid","action":"PING","state_version":1,"accepted":true}
```

MCP errors use `MCP_NOT_AUTHORIZED|MCP_INVALID_ACTION|MCP_CONTEXT_UNAVAILABLE|MCP_VERSION_CONFLICT`.
