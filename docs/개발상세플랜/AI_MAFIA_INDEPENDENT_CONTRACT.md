# AI 마피아 섹터 공통 형식 계약

이 문서는 Frontend, Backend, MCP·Data 담당자가 서로의 내부 구현을 몰라도 연결할
수 있도록 섹터 간에 노출되는 최소 형식만 정의한다. 제품 규칙은
[AI_MAFIA_MASTER_PLAN.md](AI_MAFIA_MASTER_PLAN.md), DB·Redis는
[AI_MAFIA_DB_DESIGN.md](AI_MAFIA_DB_DESIGN.md), HTTP·MCP의 상세 계약은
[AI_MAFIA_API_SPEC.md](AI_MAFIA_API_SPEC.md), 화면 동작은
[AI_MAFIA_SCREEN_FLOW.md](AI_MAFIA_SCREEN_FLOW.md)를 따른다.
MCP 구현 구조와 WU 실행 절차는
[AI_MAFIA_MCP_SERVER_DESIGN.md](AI_MAFIA_MCP_SERVER_DESIGN.md)를 참고하되, 다섯
Resource의 상세 `data` schema는 API 명세 8.2절과 그 절이 명시적으로 참조하는 API
공통 모델만 정본으로 사용한다.

이 문서는 게임 규칙, DB schema, 화면 설계, 테스트 시나리오 또는 구현 순서를
중복해서 정의하지 않는다. 아래 형식에 없는 사항은 해당 정본을 기준으로 한다.

## 1. 공통 표기

| 항목 | 공통 형식 |
|---|---|
| 규칙 버전 | `mystery-v1` |
| 시나리오 버전 | `scenario-v1` |
| schema 버전 | 정수 `1` |
| ID | canonical hyphen UUID 문자열 |
| 사용자 식별 | UUID v4, `X-User-Id` header |
| 시간 | UTC RFC 3339 문자열 |
| JSON | UTF-8 `application/json` |
| 알 수 없는 field | 거부 |

모든 문자열은 해당 API 정본의 정규화 규칙을 적용한다. 오류 message는 표시용이고
분기 기준은 오류 `code`다.

## 2. 섹터 경계

| 섹터 | 외부에 제공하는 것 | 직접 사용하지 않는 것 |
|---|---|---|
| Frontend | 사용자 화면, `X-User-Id`, 공개 API 요청 | DB, Redis, MCP, 게임 판정 |
| Backend | 공개 API, 내부 Engine API, authoritative 상태 | 화면 렌더링, MCP의 DB 접근 |
| MCP·Data | MCP session·Resource·Tool, 인프라 health | 게임 판정, DB·Redis 직접 접근을 하는 MCP runtime |

Backend만 phase, role, 생존, 승패, state version과 RNG 결과를 확정한다. Frontend와
MCP는 상태를 재판정하지 않는다.

## 3. Frontend–Backend 공통 형식

### 3.1 Header

| Header | 적용 | 형식 |
|---|---|---|
| `X-User-Id` | 공개 사용자·관리자 API | UUID v4 |
| `X-Request-Id` | 모든 HTTP API | 선택 UUID, 없으면 Backend 생성 |
| `Idempotency-Key` | 변경하는 공개 POST | 필수 UUID v4 |
| `Last-Event-ID` | SSE 재연결 | 마지막 `front_sequence` 문자열 |

사용자 UUID는 URL이나 JSON body에 중복하지 않는다. canonical MVP에는 Front의
`Authorization`, OIDC token, Front HMAC을 사용하지 않는다.

Cross-origin Front 연결은 API 정본의 CORS 정책을 사용한다. 기본 개발 origin은
`http://127.0.0.1:8501`, `http://127.0.0.1:8502`이고 허용 request header는
`X-User-Id`, `X-Request-Id`, `Idempotency-Key`, `Last-Event-ID`, `Content-Type`이다.
배포 시 origin은 명시적 allowlist로 관리하며 wildcard origin과 credentials 인증은
사용하지 않는다. same-origin proxy를 선택하면 proxy가 이 header와 SSE stream을
그대로 전달한다.

### 3.2 성공·오류 envelope

모든 JSON 성공 응답은 다음 형식을 사용한다.

```json
{
  "data": {},
  "meta": {
    "request_id": "uuid",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

모든 JSON 오류 응답은 다음 형식을 사용한다.

```json
{
  "error": {
    "code": "STALE_STATE_VERSION",
    "message": "고정된 한국어 안내 문구",
    "request_id": "uuid",
    "retryable": true,
    "details": {}
  }
}
```

`replayed`는 idempotency replay일 때만 `true`다. 같은 idempotency key와 같은
request hash는 최초 terminal 결과를 반환하고, 다른 hash는
`IDEMPOTENCY_KEY_REUSED`다. 게임 변경 command는 `expected_state_version`을
사용하며 Backend는 불일치 요청을 자동 재적용하지 않는다.

### 3.3 공개 요청 형식

| 목적 | Method | Path |
|---|---|---|
| liveness | GET | `/health` |
| readiness | GET | `/ready` |
| 게임 생성 | POST | `/api/v1/games` |
| 게임 목록 | GET | `/api/v1/games` |
| snapshot 조회 | GET | `/api/v1/games/{game_id}` |
| command 제출 | POST | `/api/v1/games/{game_id}/commands` |
| delta 조회 | GET | `/api/v1/games/{game_id}/sync` |
| SSE 구독 | GET | `/api/v1/games/{game_id}/events` |
| feedback 제출 | POST | `/api/v1/feedback` |
| 관리자 조회 | GET | `/api/v1/admin/*` |

게임 생성 body는 `player_count`, `ruleset_version`, `scenario_version`을 사용한다.
게임 변경 body는 discriminated union의 `type`과 `expected_state_version`을
사용한다. command별 field, 허용 phase와 validation은 API 정본을 따른다.

### 3.4 Snapshot·sync 형식

snapshot은 `data.game`, `data.scenario`, `data.players`, `data.me`,
`data.action_window` 구조를 사용한다. `me`에는 현재 인간 본인의 private
projection만 포함한다.

Polling과 SSE는 다음 공통 sync 형식을 사용한다.

```json
{
  "game_id": "uuid",
  "mode": "DELTA",
  "from_state_version": 12,
  "state_version": 13,
  "last_sequence": 43,
  "operations": [
    {
      "schema_version": 1,
      "front_sequence": 43,
      "operation_index": 0,
      "state_version": 13,
      "type": "APPEND_PUBLIC_EVENT",
      "payload": {}
    }
  ],
  "snapshot": null
}
```

`DELTA`에서는 `snapshot=null`, `SNAPSHOT`에서는 `operations=[]`다. 하나의
`front_sequence`는 `operation_index=0`부터 연속된 하나의 batch다. Front는
`(game_id, front_sequence, operation_index)`로 중복을 제거하고 gap이나 알 수
없는 operation을 발견하면 부분 적용하지 않고 snapshot을 다시 요청한다.

Polling은 `after_state_version`과 `after_sequence`를 함께 전송하고, SSE는 같은
`after_sequence`를 `Last-Event-ID`로 전송한다. 두 transport는 동일한
Front-visible cursor와 operation batch를 공유한다.

허용 operation 이름은 `SET_GAME_STATE`, `REPLACE_PLAYERS`, `SET_PRIVATE_STATE`,
`SET_ACTION_WINDOW`, `CLEAR_ACTION_WINDOW`, `APPEND_PUBLIC_EVENT`,
`APPEND_PRIVATE_EVENT`, `SET_RESULT`다. operation payload 상세는 API 정본의
operation 표를 사용한다.

## 4. Backend–MCP 공통 형식

### 4.1 내부 Engine API

MCP runtime이 호출하는 private API는 다음 세 path를 사용한다.

```text
GET  /internal/v1/agent-context?scope=public|me|turn|persona|gm-guide
POST /internal/v1/mcp-bootstrap/consume
POST /internal/v1/agent-proposals
```

내부 요청에는 `X-Engine-Timestamp`, `X-Engine-Nonce`, `X-Engine-Signature`,
`X-Agent-Capability` header가 필요하다. MCP는 capability를 opaque 값으로만
전달하고 해석·검증하지 않는다.

context response의 공통 field는 `context_version`, `game_id`, `subject_type`,
`subject_id`, `phase`, `state_version`, `window_id`, `scope`, `data`다.
proposal request의 공통 field는 `proposal_id`, `game_id`, `agent_id`,
`window_id`, `expected_state_version`, `proposal`이다. proposal type은
`SPEAK`, `PASS`, `NIGHT_ACTION`, `VOTE` 중 하나다.

### 4.2 MCP session·Resource·Tool

- endpoint는 `${MAFIA_MCP_URL}` 전체 값을 사용하며 `/mcp`를 중복하지 않는다.
- Streamable HTTP initialize 뒤 `Mcp-Session-Id`를 사용한다.
- session은 하나의 `agent_job_id`, `game_id`, `subject_type`, `subject_id`에 고정한다.
- bootstrap 성공 전에는 session을 활성화하지 않는다.
- Agent Manager는 job마다 새 capability·bootstrap·session을 만들고 terminal 상태에서
  폐기한다. reconnect도 소비한 bootstrap, 기존 capability와 session ID를 재사용하지
  않는다.
- Resource URI는 다음 값만 사용한다.

```text
mafia://session/public
mafia://session/me
mafia://session/turn
mafia://session/persona
mafia://session/gm-guide
```

- Tool 이름은 `propose_speech`, `propose_pass`, `propose_night_action`,
  `propose_vote`만 사용한다.
- Tool input에는 `game_id`, `agent_id`, role, phase, version을 넣지 않는다.
- MCP는 Tool input을 검증한 뒤 Backend proposal API로 전달한다.
- GM session은 `public`, `gm-guide` Resource만 사용하고 행동 Tool은 사용하지
  않는다.
- GM narration은 LLM adapter에서 Backend Agent Manager로 직접 반환하며 MCP Tool과
  `/internal/v1/agent-proposals`를 호출하지 않는다. Backend가 fencing과 공개 범위를
  재검증해 `PUBLIC` event 또는 고정 fallback을 확정한다.
- MCP runtime은 Backend의 `event_outbox`를 읽거나 쓰지 않고 자체 영속 audit
  outbox도 만들지 않는다. MCP 감사 범위는 API 정본 9.4절의 metadata
  allowlist를 적용한 구조화 운영 로그와 redaction 검증으로 한정한다.

## 5. 변경 규칙

이 문서에 정의된 형식, field, enum 또는 경계를 변경할 때는 구현보다 먼저 이
문서와 영향을 받는 정본을 함께 갱신한다. 섹터 담당자는 정해진 공통 형식을
준수하되 내부 모듈, 저장 방식, UI 구조와 테스트 방식은 각자 결정한다.

이 문서의 목적은 세 섹터가 같은 연결 형식을 사용하도록 하는 것이며, 각 섹터의
기능 구현 계획이나 상세 검증 목록을 정하는 것이 아니다.
