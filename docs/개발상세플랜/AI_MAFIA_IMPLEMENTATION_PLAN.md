# AI 마피아 MVP 상세 구현 계획서 (3인 섹터 분담)

**문서 상태:** 구현 착수용 상세 계획 (추후 수정 가능)
**기준 문서:** [AI 마피아 MVP 최종 통합 플랜](../플랜/AI_MAFIA_MVP_FINAL_PLAN.md)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 계획서의 모든 작업에 적용
**분담:** 3인 — Front 섹터, Backend 섹터, MCP Server 섹터
**섹터별 작업 지침서 (착수 전 필독):**
[Front](SECTOR_PLAN_FRONT.md) ·
[Backend](SECTOR_PLAN_BACKEND.md) ·
[MCP Server](SECTOR_PLAN_MCP.md)

이 문서는 최종 통합 플랜을 실제 작업 단위로 쪼개고, 섹터 간 병렬 작업이
가능하도록 **API 명세와 DB 설계서를 계약으로 먼저 고정**한다. 명세 변경이
필요하면 임의로 바꾸지 말고 3인 합의 후 이 문서를 먼저 갱신한 뒤 코드를
수정한다. 각 섹터의 작업 단위(WU) 분해, coding AI agent 사용 규칙(한 세션
= WU 1개 이하), 중간 merge·테스트 체크포인트는 섹터 지침서가 확정한다.

---

## 0. 공통 작업 지침 (AGENTS.MD 요약 — 전 섹터 필수)

아래 지침은 [AGENTS.MD](../../AGENTS.MD)의 요약이며, 충돌 시 AGENTS.MD 원문이
우선한다. 세 섹터 담당자 모두 작업 시작 전에 원문을 읽어야 한다.

### 0.1 브랜치와 Git

1. `main` 직접 커밋 금지, `origin/main` 직접 푸시 금지. 섹터별 작업 브랜치에서
   작업하고 검토 절차를 거쳐 병합한다.
   - 권장 브랜치 이름: `feat/front-<기능>`, `feat/backend-<기능>`,
     `feat/mcp-<기능>`
2. 사용자가 명시적으로 승인하지 않은 커밋은 만들지 않는다. 구현 요청은 파일
   변경 승인일 뿐 커밋·푸시 승인이 아니다.
3. 커밋 전 현재 브랜치와 변경 파일을 확인하고 타인 소유 변경을 덮어쓰지 않는다.
4. `git reset --hard`, 강제 푸시, 광범위 삭제는 명확한 요청과 대상 확인 없이
   실행하지 않는다.

### 0.2 커밋 메시지

`fix`, `update`, `work` 같은 단어만 있는 메시지는 금지. 최소한 다음이 드러나야
한다: **변경 목적 / 변경한 기능·파일·데이터 경계 / 실행한 테스트·lint 또는
검증을 생략한 이유.**

### 0.3 코드와 주석

1. 새로 작성·수정하는 모든 주석과 docstring은 **한국어**로, 구현 반복이 아니라
   의도·경계 조건·보안 이유·유지보수 주의점을 설명한다.
2. 기존 구조와 명명 규칙을 따르고, 요청 범위 밖 대규모 리팩터링을 섞지 않는다.
3. 인증 claim, DB 값, 사용자 입력, LLM/MCP 출력 등 외부 데이터는 신뢰하지 말고
   검증·정규화·escape 후 사용한다.

### 0.4 파일·디렉터리 구조

1. 구조를 임의로 생성·삭제·이동·개명하지 않는다. 이 계획서 4~6장에 명시된
   신규 파일 목록이 승인 범위이며, 그 밖의 구조 변경은 사전 고지·합의가 필요하다.
2. 구조를 변경한 경우 루트 README의 프로젝트 구조에 반드시 반영한다.

### 0.5 비밀정보

1. API 키, OAuth secret, 쿠키 secret, DB 비밀번호, token, 실제 `.env`·
   `secrets.toml`·Google OAuth JSON을 절대 커밋하지 않는다.
2. 비밀값을 코드, 테스트 fixture, 스냅샷, 로그, 오류 메시지, 문서, 커밋
   메시지에 복사하지 않는다. 예제에는 placeholder만 사용한다.
3. 노출 의심 시 값을 다시 출력하지 말고 즉시 알리고 폐기·재발급한다.

### 0.6 테스트와 검증 (위험도 비례)

- 문서·주석·스타일 변경: 자동 테스트 생략 가능, diff·링크 직접 확인.
- 한 파일·한 기능 변경: 가장 작은 관련 테스트, lint, import 확인만 실행.
- 일반 기능·버그 수정: 개발 중 focused test, 완료 직전 전체 회귀 1회.
- **인증·권한·보안·데이터 삭제·공개 계약·동시성(이 프로젝트의 게임 소유권,
  비공개 역할 격리, lock, 관리자 권한 전부 해당): 실패·거부 경로 테스트를
  먼저 또는 함께 작성하고 전체 회귀를 실행한다.**
- 외부 Cloud/유료 API 자동 테스트는 mock·fake·synthetic으로 대체한다.
  **유료 LLM을 회귀 테스트에서 호출하지 않는다.**
- 무관한 기존 테스트 실패는 원인·영향만 보고하고 임의 수정하지 않는다.

전체 회귀 명령 (완료 보고 기준):

```bash
uv run pytest
uv run python -m compileall -q backend frontend_user frontend_admin mcp_server
uv run ruff check .
```

### 0.7 README와 완료 점검

모든 작업은 완료 전에 루트 README.md를 현재 구현과 일치하게 갱신한다.
완료 전 점검: 범위 밖 파일 미변경 / 비밀정보 미포함 / 위험도에 맞는 검증 실행 /
README 갱신 / 구조 임의 변경 없음 / 승인 없는 커밋·푸시 없음.

---

## 1. 섹터 분담과 소유 경계

| 섹터 | 담당 디렉터리 (소유) | 주요 산출물 |
|---|---|---|
| **Front** | `frontend_user/`, `frontend_admin/` | 홈·생성·진행·불러오기·결과 화면, 관리자 KPI·로그·피드백 화면, API client 확장 |
| **Backend** | `backend/` (app 전체, migrations) | 게임 규칙 엔진, 상태 머신, 게임·관리자 API, DB·Redis, Agent Manager, LLM client, MCP client·capability 정책 |
| **MCP Server** | `mcp_server/mafia_game/` | 게임 컨텍스트 MCP 서버(Resource/Tool), 세션·격리·감사 로그, Backend 내부 API 소비 |

### 1.1 공유 파일 규칙

- `pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`는 공유 파일이다.
  수정 시 변경 내용을 다른 섹터에 고지한다.
- `backend/app/mcp/`(MCP client·capability)는 Backend 소유지만 **계약 협의는
  MCP 섹터와 공동**으로 한다. 계약 변경은 이 문서 5장(내부 API)과 6장(MCP
  명세) 갱신이 선행 조건이다.
- 다른 섹터 소유 디렉터리는 수정하지 않는다. 필요한 변경은 이슈/메시지로
  해당 섹터에 요청한다.

### 1.2 섹터 간 계약 (병렬 작업의 전제)

```text
Front  ──(2장 사용자·관리자 REST API + 3장 SSE)──▶  Backend
Backend ──(5장 내부 Engine API, HMAC 서명)──────▶  MCP Server가 호출
AI Agent(Backend가 구동) ──(6장 MCP Resource/Tool)──▶ MCP Server
```

- Front는 Backend 완성 전 **fake API client**(테스트 더블)로 화면을 개발한다.
- MCP Server는 Backend 완성 전 **fake Engine API**(로컬 stub)로 개발한다.
- Backend는 실제 LLM 없이 **fake LLM client**로 엔진·Agent Manager를 개발한다.

### 1.3 프로세스와 포트

| 프로세스 | 실행 명령 | 포트 |
|---|---|---:|
| Backend API | `uv run uvicorn backend.app.main:app --port 8000` | 8000 |
| 사용자 앱 | `uv run streamlit run frontend_user/app.py --server.port 8501` | 8501 |
| 관리자 앱 | `uv run streamlit run frontend_admin/app.py --server.port 8502` | 8502 |
| 게임 MCP 서버 | `uv run python -m mcp_server.mafia_game` (구현 시 확정) | 8100 |

---

## 2. 사용자·관리자 API 명세 (Front ↔ Backend 계약)

### 2.0 공통 규약

**인증(MVP 결정):** 브라우저가 Backend를 직접 호출하지 않는다. Streamlit
서버(신뢰된 내부 프로세스)가 기존 HMAC 내부 서명
(`X-Internal-Timestamp`, `X-Internal-Request-Id`, `X-Internal-Signature`,
canonical = `timestamp.request_id.raw_body`)으로 Backend를 호출하고, 행위
사용자는 서명된 요청 body의 `acting_user_id`(UUID, provision 응답의 내부
`user_id`)로 전달한다. Backend는 `acting_user_id`가 활성 사용자인지, 대상
게임의 소유자인지 항상 재검증한다. 서명이 곧 사용자 인증은 아니므로 이 방식은
Streamlit 서버를 신뢰 경계로 하는 MVP 한정 결정이며, 사용자 직접 호출이
필요해지는 시점에 짧은 수명 access token으로 교체한다(교체 지점:
`frontend_user/core/api_client.py`, `backend/app/infrastructure/security/`).

**공통 요청 필드 (GET 제외):**

```json
{
  "acting_user_id": "018f6f7c-0496-758e-981f-05985cb67210"
}
```

GET 요청은 body가 없으므로 `X-Acting-User-Id` 헤더로 전달하며 이 헤더도
서명 canonical에 포함한다: `timestamp.request_id.acting_user_id.raw_body`
(GET은 raw_body를 빈 문자열로 계산). 기존 identity API의 canonical은 바꾸지
않고, 게임 API 전용 서명 규칙으로 `backend/app/infrastructure/security/`에
추가한다.

**공통 오류 응답:**

```json
{
  "code": "GAME_STATE_CONFLICT",
  "message": "요청한 버전이 현재 게임 상태보다 오래되었습니다.",
  "details": {"expected_version": 17, "current_version": 19},
  "trace_id": "trace-uuid"
}
```

| HTTP | code | 의미 |
|---:|---|---|
| 401 | `INVALID_INTERNAL_SIGNATURE` | HMAC·timestamp·request id 검증 실패 |
| 403 | `INACTIVE_USER` | 비활성 사용자 |
| 403 | `ADMIN_ACCESS_DENIED` | 관리자 role 없음 |
| 404 | `GAME_NOT_FOUND` | 없는 게임 **또는 소유하지 않은 게임(동일 응답)** |
| 409 | `GAME_STATE_CONFLICT` | `expected_version` 불일치 |
| 422 | `ACTION_NOT_ALLOWED` | 현재 단계·역할에서 불가한 행동 |
| 422 | `INVALID_GAME_REQUEST` | schema·값 검증 실패 |
| 503 | `AGENT_TEMPORARILY_UNAVAILABLE` | LLM/MCP 일시 장애 (재시도 안내) |
| 503 | `GAME_PERSISTENCE_UNAVAILABLE` | DB/Redis 저장 실패 |

**공통 enum:**

```text
GameStatus  = CREATED | IN_PROGRESS | PAUSED | FINISHED
Phase       = ROLE_REVEAL | NIGHT_ACTION | NIGHT_RESOLUTION | DAY_ANNOUNCEMENT
            | DAY_DISCUSSION | DAY_VOTE | DAY_REVOTE | VOTE_RESOLUTION | FINISHED
Role        = MAFIA | POLICE | DOCTOR | CITIZEN        (종료 전 타인 역할 비공개)
Faction     = MAFIA | CITIZEN
Winner      = MAFIA | CITIZEN | null
PlayerKind  = HUMAN | AI
Visibility  = PUBLIC | PRIVATE | FACTION | SYSTEM
Command     = SPEAK | CAST_VOTE | NIGHT_KILL | NIGHT_INVESTIGATE | NIGHT_PROTECT
            | PASS | SAVE_AND_EXIT | FAST_FORWARD | ADVANCE_PHASE
FeedbackCategory = FUN | AI_QUALITY | RULE_ERROR | PERFORMANCE | ETC
FeedbackStatus   = NEW | REVIEWING | RESOLVED | WONT_FIX
```

### 2.1 `POST /api/v1/games` — 게임 생성

요청:

```json
{
  "acting_user_id": "uuid",
  "player_count": 6,
  "ruleset_version": "basic-v1"
}
```

- `player_count`: 5~9 정수. 범위 밖은 422 `INVALID_GAME_REQUEST`.
- 생성 시 인간 1명 + AI `player_count - 1`명, 역할 무작위 배정, persona preset
  무작위 배정을 한 트랜잭션으로 수행한다. random seed는 서버에만 기록한다.

응답 `201` — 아래 2.3의 GameStateView와 동일 구조 (본인 역할 포함).

### 2.2 `GET /api/v1/games?status=saved` — 저장 게임 목록

본인 소유의 `IN_PROGRESS`·`PAUSED` 게임만 반환한다.

```json
{
  "games": [
    {
      "game_id": "uuid",
      "status": "PAUSED",
      "phase": "DAY_DISCUSSION",
      "round": 2,
      "player_count": 6,
      "alive_count": 5,
      "created_at": "2026-09-01T05:00:00Z",
      "saved_at": "2026-09-01T05:12:00Z"
    }
  ]
}
```

### 2.3 `GET /api/v1/games/{game_id}` — 현재 상태 (GameStateView)

**호출 사용자 권한에 맞게 필터한** 상태를 반환한다. 응답에 다른 참가자의
역할, 경찰 조사 결과, 보호 대상, random seed를 절대 포함하지 않는다
(인간이 마피아인 경우 같은 진영 마피아 표시는 허용).

```json
{
  "game_id": "uuid",
  "status": "IN_PROGRESS",
  "phase": "DAY_DISCUSSION",
  "round": 2,
  "state_version": 17,
  "ruleset_version": "basic-v1",
  "you": {
    "player_id": "uuid",
    "seat": 3,
    "role": "CITIZEN",
    "faction": "CITIZEN",
    "alive": true,
    "teammates": []
  },
  "players": [
    {"player_id": "uuid", "seat": 1, "display_name": "냉정한 분석가",
     "kind": "AI", "alive": true,
     "revealed_role": null}
  ],
  "allowed_commands": [
    {"command": "SPEAK", "max_length": 200},
    {"command": "PASS"}
  ],
  "timeline": [
    {"sequence": 41, "type": "MODERATOR_ANNOUNCEMENT",
     "message": "아침이 밝았습니다. 어젯밤 희생자는 없었습니다.",
     "created_at": "..."},
    {"sequence": 42, "type": "PLAYER_SPEECH", "player_id": "uuid",
     "message": "...", "created_at": "..."}
  ],
  "private_events": [
    {"sequence": 12, "type": "ROLE_ASSIGNED", "payload": {"role": "CITIZEN"}}
  ],
  "saved_at": "2026-09-01T05:12:00Z"
}
```

- `timeline`은 PUBLIC 이벤트만, `private_events`는 본인 PRIVATE(+ 마피아인
  경우 FACTION) 이벤트만 담는다. `revealed_role`은 처형·사망으로 공개된
  역할만 채운다.
- `?since_sequence=41` 쿼리로 증분 조회를 지원한다(폴링 대비).

### 2.4 `POST /api/v1/games/{game_id}/commands` — 행동 제출

```json
{
  "acting_user_id": "uuid",
  "command": "CAST_VOTE",
  "target_player_id": "uuid-or-null",
  "message": null,
  "expected_version": 17,
  "idempotency_key": "uuid"
}
```

- `SPEAK`: `message` 필수(최대 200자, escape는 렌더링 시), 대상 없음.
- `CAST_VOTE`: `target_player_id` 필수, 자기 자신 지정 시 422.
- `NIGHT_*`: 본인 역할·단계 검증. 불일치 시 422 `ACTION_NOT_ALLOWED`.
- `SAVE_AND_EXIT`: agent run이 끝난 안전 지점에서 `PAUSED` 전환.
- `FAST_FORWARD`: 인간 사망 후에만 허용, 결과까지 자동 진행.
- `ADVANCE_PHASE`: 버튼형 턴제에서 인간이 다음 진행을 승인(AI 발언 재생 등).
- 같은 `idempotency_key` 재전송은 첫 결과를 그대로 반환한다(24h 캐시).

응답 `200`: 반영 후 GameStateView. 이후 진행(AI 턴 등)은 SSE/폴링으로 수신.

### 2.5 `GET /api/v1/games/{game_id}/events` — SSE 구독

`text/event-stream`. 폴링 대체 수단이며 Front는 SSE 실패 시 2.3 증분 조회로
폴백한다.

```text
event: game_update
data: {"game_id":"uuid","state_version":18,"phase":"DAY_VOTE",
       "new_public_events":[...],"agent_status":"IDLE"}
```

`agent_status`: `IDLE | THINKING | FALLBACK` — AI 처리 중 표시용.

### 2.6 `GET /api/v1/games/{game_id}/result` — 종료 결과

`FINISHED` 게임만. 그 외에는 409 `GAME_STATE_CONFLICT`.

```json
{
  "game_id": "uuid",
  "winner": "CITIZEN",
  "rounds": 3,
  "players": [
    {"player_id": "uuid", "seat": 1, "display_name": "...", "kind": "AI",
     "role": "MAFIA", "faction": "MAFIA", "alive": false,
     "eliminated_by": "VOTE", "eliminated_round": 2}
  ],
  "timeline_highlights": [
    {"round": 1, "type": "NIGHT_KILL_RESOLVED", "summary": "..."}
  ],
  "human_summary": {"survived": false, "vote_accuracy": 0.67}
}
```

### 2.7 `POST /api/v1/feedback`

```json
{
  "acting_user_id": "uuid",
  "game_id": "uuid-or-null",
  "rating": 4,
  "category": "AI_QUALITY",
  "content": "정규화·검증된 자유 입력 (최대 2000자)"
}
```

응답 `201 {"feedback_id": "uuid"}`.

### 2.8 관리자 API (`frontend_admin` 전용)

관리자 권한은 `acting_user_id`가 `user_roles`에 `ADMIN` role을 가진 활성
사용자일 때만 허용한다. 실패 시 403 `ADMIN_ACCESS_DENIED`. 일반 사용자용
서명·세션을 관리자 권한 근거로 재사용하지 않는다.

| Method | Endpoint | 쿼리/바디 | 응답 요지 |
|---|---|---|---|
| `GET` | `/api/v1/admin/kpis` | `?period=today\|7d\|30d` | 신규 게임 수, 완주율, 평균 시간·라운드, 재개율, 인원별 승률, LLM 성공/timeout/fallback률, 평균 token·비용, 피드백 평균·미처리 |
| `GET` | `/api/v1/admin/logs` | `?from&to&trace_id&game_id&severity&event_type&page&size` | 민감 필드 제거된 감사·오류 로그 페이지 |
| `GET` | `/api/v1/admin/feedback` | `?status&category&page&size` | 피드백 목록과 집계 |
| `PATCH` | `/api/v1/admin/feedback/{feedback_id}` | `{"status": "REVIEWING"}` | 상태 변경 결과 |

로그 응답에는 전체 prompt, 비공개 역할 목록, 비밀정보를 포함하지 않는다.

---

## 3. DB 설계서 (Backend 소유, 추후 수정 가능)

### 3.0 원칙

- PostgreSQL이 영구 원본. Redis는 lock·cache·stream 전용(10장 최종 플랜 준수).
- 신규 schema는 `backend/migrations/002_create_mafia_game_schema.sql`부터
  기존 001 컨벤션(단일 트랜잭션, `IF NOT EXISTS`, 재실행 가능, 한국어 주석,
  `updated_at` 트리거 재사용)을 따른다.
- 검색·무결성 필드는 열로, 규칙별 확장 데이터는 검증된 JSONB로 둔다.
- 종료 전 비공개 정보(역할, 조사 결과)는 API 계층에서 필터하며, DB 접근은
  repository를 통해서만 한다.

### 3.1 테이블 정의

#### `game_sessions` — 게임 헤더

| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | uuid | PK, `gen_random_uuid()` | 게임 식별자 |
| `owner_user_id` | uuid | NOT NULL, FK→`users(id)` | 소유 사용자 |
| `status` | text | NOT NULL, CHECK in (`CREATED`,`IN_PROGRESS`,`PAUSED`,`FINISHED`) | 게임 상태 |
| `phase` | text | NOT NULL, CHECK (Phase enum) | 현재 단계 |
| `round` | int | NOT NULL DEFAULT 0, CHECK ≥0 | 라운드(밤 기준 증가) |
| `winner` | text | NULL, CHECK in (`MAFIA`,`CITIZEN`) | 승리 진영 |
| `player_count` | int | NOT NULL, CHECK 5~9 | 전체 인원 |
| `ruleset_version` | text | NOT NULL | 규칙 버전(`basic-v1`) |
| `state_version` | int | NOT NULL DEFAULT 0 | optimistic lock 버전 |
| `random_seed` | text | NOT NULL | 재현용 seed. **API 응답 금지** |
| `saved_at` | timestamptz | NULL | 마지막 저장 시각 |
| `created_at` / `updated_at` | timestamptz | NOT NULL DEFAULT now | 001 트리거 재사용 |

인덱스: `(owner_user_id, status)` — 저장 목록 조회.

#### `game_players` — 참가자와 비공개 역할

| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | uuid | PK | 참가자 식별자 (`player_id`) |
| `game_id` | uuid | NOT NULL, FK→`game_sessions` ON DELETE CASCADE | |
| `user_id` | uuid | NULL, FK→`users(id)` | 인간이면 사용자, AI면 NULL |
| `kind` | text | NOT NULL, CHECK in (`HUMAN`,`AI`) | |
| `seat` | int | NOT NULL, UNIQUE(game_id, seat) | 발언 순서 좌석 |
| `display_name` | text | NOT NULL, 길이 1~40 | 표시 이름 |
| `role` | text | NOT NULL, CHECK in (`MAFIA`,`POLICE`,`DOCTOR`,`CITIZEN`) | **비공개.** 응답 필터 필수 |
| `faction` | text | NOT NULL, CHECK in (`MAFIA`,`CITIZEN`) | |
| `alive` | boolean | NOT NULL DEFAULT true | |
| `eliminated_by` | text | NULL, CHECK in (`VOTE`,`NIGHT_KILL`) | |
| `eliminated_round` | int | NULL | |
| `persona_id` | uuid | NULL, FK→`agent_personas` | AI만 |
| `created_at` / `updated_at` | timestamptz | | |

제약: `kind='HUMAN'`이면 `user_id NOT NULL AND persona_id IS NULL`,
`kind='AI'`이면 `user_id IS NULL` (CHECK).

#### `game_events` — append-only 게임 기록

| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | uuid | PK | |
| `game_id` | uuid | NOT NULL, FK CASCADE | |
| `sequence` | bigint | NOT NULL, UNIQUE(game_id, sequence) | 게임 내 단조 증가 |
| `type` | text | NOT NULL | 이벤트 유형 (3.2 목록) |
| `visibility` | text | NOT NULL, CHECK in (`PUBLIC`,`PRIVATE`,`FACTION`,`SYSTEM`) | |
| `audience_player_id` | uuid | NULL, FK→`game_players` | PRIVATE 대상 |
| `audience_faction` | text | NULL, CHECK in (`MAFIA`) | FACTION 대상 |
| `payload` | jsonb | NOT NULL DEFAULT '{}' | 유형별 데이터 |
| `created_at` | timestamptz | NOT NULL | |

제약(CHECK): `visibility='PRIVATE'`→`audience_player_id NOT NULL`,
`visibility='FACTION'`→`audience_faction NOT NULL`. UPDATE/DELETE 금지는
repository 규율로 강제(트리거는 후속 검토).
인덱스: `(game_id, sequence)`, `(game_id, visibility, sequence)`.

#### `game_snapshots` — 저장·복구

| 열 | 타입 | 제약 |
|---|---|---|
| `game_id` | uuid | FK CASCADE, PK(game_id, version) |
| `version` | int | 저장 시점 `state_version` |
| `state` | jsonb | 전체 엔진 상태 직렬화(역할 포함, **SYSTEM 등급**) |
| `checksum` | text | state 정규화 SHA-256 |
| `last_event_sequence` | bigint | 이 snapshot이 반영한 마지막 이벤트 |
| `created_at` | timestamptz | |

복구 규칙: checksum 불일치 또는 `last_event_sequence` < 최신 이벤트면
snapshot 이후 이벤트를 재생해 상태를 재구성한다.

#### `agent_personas` — 버전 고정 페르소나 프리셋

| 열 | 타입 | 제약 |
|---|---|---|
| `id` | uuid | PK |
| `name` | text | NOT NULL, UNIQUE(name, version) |
| `version` | int | NOT NULL DEFAULT 1 |
| `parameters` | jsonb | NOT NULL — 10개 수치(0.0~1.0)와 `display_name`,`speech_style`,`backstory` |
| `active` | boolean | NOT NULL DEFAULT true |
| `created_at` / `updated_at` | timestamptz | |

시드 데이터: 차분한 분석가, 성급한 리더, 조용한 관찰자, 친화적 중재자,
능숙한 블러퍼 5종을 migration에서 INSERT … ON CONFLICT DO NOTHING으로 등록.

#### `agent_runs` — LLM 호출 품질·비용 지표

| 열 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | run 식별자 |
| `game_id` / `player_id` | uuid FK | 대상 |
| `phase` | text | 실행 단계 |
| `status` | text CHECK in (`SUCCESS`,`TIMEOUT`,`INVALID_OUTPUT`,`FALLBACK`,`ERROR`) | |
| `latency_ms` | int | |
| `prompt_tokens` / `completion_tokens` | int | 사용량 |
| `model_code` | text | 예: `openai:gpt-4.1-mini` |
| `error_code` | text NULL | 실패 분류. **프롬프트·응답 원문 저장 금지** |
| `created_at` | timestamptz | |

#### `user_feedback`

| 열 | 타입 | 제약 |
|---|---|---|
| `id` | uuid PK / `user_id` uuid FK NOT NULL / `game_id` uuid FK NULL | |
| `rating` | int NOT NULL CHECK 1~5 | |
| `category` | text CHECK in (`FUN`,`AI_QUALITY`,`RULE_ERROR`,`PERFORMANCE`,`ETC`) | |
| `content` | text, 길이 ≤2000 | 저장 전 정규화 |
| `status` | text CHECK in (`NEW`,`REVIEWING`,`RESOLVED`,`WONT_FIX`) DEFAULT `NEW` | |
| `created_at` / `updated_at` | timestamptz | |

#### `user_roles` — 관리자 권한 (신규)

| 열 | 타입 | 제약 |
|---|---|---|
| `user_id` | uuid FK→`users` CASCADE | PK(user_id, role) |
| `role` | text CHECK in (`ADMIN`) | |
| `granted_at` | timestamptz NOT NULL | |

관리자 부여는 운영자가 SQL로 직접 수행(MVP에는 부여 API 없음).

#### `audit_logs` — 관리자·보안·MCP 감사

| 열 | 타입 | 설명 |
|---|---|---|
| `id` uuid PK / `trace_id` text | 요청 상관관계 |
| `actor_type` | text CHECK in (`USER`,`ADMIN`,`AGENT`,`SYSTEM`) | |
| `actor_id_hash` | text | 원본 id 대신 해시 |
| `action` | text | 예: `MCP_TOOL_CALL`,`MCP_DENIED`,`ADMIN_FEEDBACK_UPDATE` |
| `target_type` / `target_id` | text | 예: `GAME`, game_id |
| `allowed` | boolean | 허용/거부 |
| `metadata` | jsonb | 민감 필드 제거된 요약만 |
| `created_at` | timestamptz | |

### 3.2 game_events `type` 초기 목록

```text
PUBLIC : GAME_CREATED, PHASE_CHANGED, PLAYER_SPEECH, MODERATOR_ANNOUNCEMENT,
         VOTE_RESULT, REVOTE_STARTED, PLAYER_EXECUTED(역할 공개 포함),
         PLAYER_KILLED, NO_DEATH, GAME_FINISHED
PRIVATE: ROLE_ASSIGNED, INVESTIGATION_RESULT, ACTION_ACCEPTED
FACTION: MAFIA_TEAM_REVEALED, MAFIA_KILL_PROPOSED
SYSTEM : NIGHT_ACTIONS_RAW, RESOLUTION_DETAIL, AGENT_FALLBACK, SEED_RECORDED
```

### 3.3 Redis Key 설계 (최종 플랜 10장 그대로 채택)

`team4:game:{game_id}:lock`(30s) / `:runtime`(30m) / `:events`(stream) /
`team4:idempotency:{user_id}:{key}`(24h) / `team4:agent:{run_id}:status`(15m) /
`team4:rate:{user_id}`. lock token 소유자만 해제, DB commit 전 cache 갱신 금지.

---

## 4. Backend 섹터 상세 계획

### 4.1 신규 파일 (승인된 구조 변경 범위)

```text
backend/app/models/game.py            # 게임 도메인: 역할표, 상태 머신, 판정
backend/app/models/persona.py         # 페르소나 값 객체와 검증
backend/app/services/game_service.py  # 생성·명령·저장·조회 유스케이스
backend/app/services/admin_service.py # KPI·로그·피드백 유스케이스
backend/app/repositories/game_repository.py
backend/app/repositories/feedback_repository.py
backend/app/repositories/admin_repository.py
backend/app/routers/game_router.py
backend/app/routers/feedback_router.py
backend/app/routers/admin_router.py
backend/app/routers/engine_internal_router.py   # 5장 내부 Engine API
backend/app/schemas/game_schema.py
backend/app/schemas/admin_schema.py
backend/app/agent/manager.py          # Agent Manager 실행 루프
backend/app/agent/context.py          # 에이전트별 최소 컨텍스트·격리 검사
backend/app/agent/prompts.py          # 공통 제약/개성 프롬프트 2계층
backend/app/llm/providers.py          # OpenAI·Gemini 어댑터 (+fake)
backend/app/mcp/capability.py         # game/agent/phase capability 발급
backend/app/infrastructure/redis/client.py
backend/app/infrastructure/redis/locks.py
backend/migrations/002_create_mafia_game_schema.sql
backend/tests/test_game_rules.py, test_game_state_machine.py,
  test_game_api.py, test_game_repository.py, test_snapshot_replay.py,
  test_agent_manager.py, test_context_isolation.py, test_admin_api.py,
  test_engine_internal_api.py, test_redis_locks.py
```

### 4.2 작업 순서 (최종 플랜 14장 단계와 대응)

아래 B1~B5는 [Backend 섹터 지침서](SECTOR_PLAN_BACKEND.md)의 WU-B1~B7로
세분화되어 있다. coding AI agent 세션은 WU 단위로만 지시한다.

1. **B1. 규칙 엔진(LLM·DB 없음)** — `models/game.py`에 순수 함수형 상태 머신.
   역할 배정(seed 결정적), 밤 해소(보호=공격 취소), 투표·재투표·무처형,
   승패 판정. fake agent로 5~9명 전 구성 자동 완주 테스트.
   *완료 기준: 규칙 단위 테스트 전부 통과, 유료 API 0회.*
2. **B2. 영속화** — migration 002, repository, event append + optimistic
   version + snapshot 저장·복구(checksum·재생), Redis lock·idempotency.
   *완료 기준: 동시 명령 충돌(409), Redis 장애 시 PostgreSQL 원본 보존 테스트.*
3. **B3. 사용자 API** — 2장 명세 구현. 소유권·필터링(타인 역할 제거)·
   idempotency·SSE. *완료 기준: 2장의 오류 표 전 경로 테스트,
   비공개 정보 미포함 응답 스냅샷 테스트.*
4. **B4. Agent Manager + LLM + MCP client** — fake LLM으로 루프 완성 후
   providers 연결. 컨텍스트 격리 검사(카나리), timeout·교정 1회·fallback,
   `agent_runs` 기록, capability 발급과 5장 내부 API 제공.
   *완료 기준: fallback 표 전 항목 테스트, 격리 비간섭성 테스트.*
5. **B5. 관리자 API** — `user_roles` 검증, KPI 집계, 로그 민감 필드 제거.
   *완료 기준: ADMIN 거부 경로, 민감 필드 부재 테스트.*

### 4.3 Backend 고위험 주의 (AGENTS.MD 0.6 적용)

게임 소유권, 역할 비공개, lock 동시성, 관리자 권한은 **실패·거부 경로
테스트를 구현과 함께** 작성한다. seed·역할·prompt를 로그에 남기지 않는다.

---

## 5. 내부 Engine API (Backend ↔ MCP Server 계약)

MCP 서버는 DB에 직접 접근하지 않고 Backend의 내부 HTTP API만 호출한다.
인증은 기존 HMAC 방식과 동일 canonical(`timestamp.request_id.raw_body`)에
**별도 secret `ENGINE_INTERNAL_API_SECRET`**을 사용한다(Front용과 분리).
모든 요청에 Backend가 발급한 `capability_token`(불투명 문자열, game/agent/
phase 범위 포함)을 body로 요구하며 Backend가 매 호출 재검증한다.

베이스 경로: `/internal/v1/engine` (외부 공개 금지, 문서화도 내부 한정).

| Method | Endpoint | 용도 |
|---|---|---|
| `POST` | `/internal/v1/engine/context` | agent별 허용 컨텍스트 조회 (Resource 데이터 원천) |
| `POST` | `/internal/v1/engine/actions` | Tool 행동 제안 제출 → 엔진 최종 검증·반영 |

### 5.1 `POST /context`

요청: `{"capability_token": "...", "resource": "allowed-actions"}`
(`resource` ∈ `rules | public-state | public-timeline | me | private-state |
allowed-actions | persona`)

응답은 Backend가 **agent별 View로 필터 완료한** JSON. 예(`allowed-actions`):

```json
{
  "game_id": "uuid", "agent_player_id": "uuid",
  "phase": "NIGHT_ACTION",
  "actions": [
    {"tool": "game.kill", "required": true,
     "valid_targets": ["uuid1", "uuid2"]},
    {"tool": "game.end_turn", "required": false}
  ],
  "state_version": 17
}
```

### 5.2 `POST /actions`

```json
{
  "capability_token": "...",
  "tool": "game.vote",
  "arguments": {"target_player_id": "uuid"},
  "proposal_id": "uuid"
}
```

- `actor`는 항상 capability에서 결정한다. arguments에 actor 관련 필드가
  있으면 422로 거부한다.
- 응답: `{"accepted": true, "event_id": "uuid"}` 또는
  `{"accepted": false, "code": "ACTION_NOT_ALLOWED", "reason_summary": "..."}`
- `proposal_id`는 중복 제출 방지(idempotency).
- Backend는 역할·생존·페이즈·대상·중복을 **capability와 무관하게 다시 검증**
  하고(이중 검증), 결과를 `audit_logs`에 기록한다.

---

## 6. MCP Server 섹터 상세 계획 (`mcp_server/mafia_game`)

### 6.1 신규 파일 (승인된 구조 변경 범위)

```text
mcp_server/mafia_game/__main__.py              # 서버 기동 진입점 (포트 8100)
mcp_server/mafia_game/server.py                # MCP 서버 생성·의존성 조립
mcp_server/mafia_game/api/resources/game_resources.py
mcp_server/mafia_game/api/tools/game_tools.py
mcp_server/mafia_game/core/config.py           # env 로딩(secret 검증)
mcp_server/mafia_game/core/session.py          # 세션↔agent 고정, me 해석
mcp_server/mafia_game/core/audit.py            # 감사 로그 전달
mcp_server/mafia_game/services/context_service.py   # Resource 유스케이스
mcp_server/mafia_game/services/action_service.py    # Tool 제안 유스케이스
mcp_server/mafia_game/ports/engine_port.py     # Engine API Protocol
mcp_server/mafia_game/integrations/engine/client.py # 5장 API HMAC 클라이언트
mcp_server/mafia_game/integrations/engine/fake.py   # 개발·테스트용 fake 엔진
mcp_server/mafia_game/schemas/contracts.py     # 입출력 계약 검증
mcp_server/mafia_game/tests/ (test_resources.py, test_tools.py,
  test_session_isolation.py, test_audit.py)
```

패키지 이름은 예약명 `mcp_1`에서 `mafia_game`으로 변경 완료(2026-09-01,
사용자 승인). README도 게임 컨텍스트 MCP 책임으로 갱신되어 있다.

기존 계층(`api/ services/ ports/ integrations/ core/ schemas/`)을 그대로
사용하며 새 최상위 디렉터리를 만들지 않는다. `mcp_2`는 건드리지 않는다.

### 6.2 Resource / Tool 구현 명세 (최종 플랜 8장 준수)

Resources — 모두 5장 `/context`를 호출해 반환하고, MCP 서버는 자체 상태를
갖지 않는다:

```text
mafia://rules/basic-v1
mafia://games/{game_id}/public-state
mafia://games/{game_id}/public-timeline
mafia://games/{game_id}/agents/me
mafia://games/{game_id}/agents/me/private-state
mafia://games/{game_id}/agents/me/allowed-actions
mafia://personas/{persona_id}
```

Tools — 모두 5장 `/actions`로 전달하는 **행동 제안**이며 상태를 직접 바꾸지
않는다:

| Tool | 입력 | MCP 서버 1차 검증 |
|---|---|---|
| `game.speak` | `{"message": str}` | 길이 1~200, 제어문자 제거 |
| `game.vote` | `{"target_player_id": str}` | UUID 형식 |
| `game.kill` | `{"target_player_id": str}` | UUID 형식 |
| `game.investigate` | `{"target_player_id": str}` | UUID 형식 |
| `game.protect` | `{"target_player_id": str}` | UUID 형식 |
| `game.end_turn` | `{}` | — |

핵심 규칙:

- `agent_id`·`actor_id`를 Tool 입력으로 받지 않는다. 세션이 actor를 결정한다.
- 다른 `agent_id` 조회 API를 제공하지 않는다(`me`만 존재).
- 현재 phase·역할에 맞는 Tool만 노출하되(allowed-actions 기반), 노출 제한을
  권한 검사로 삼지 않는다 — 최종 판정은 Backend(이중 검증).
- Engine 응답을 그대로 통과시키지 말고 schema 검증 후 허용 필드만 반환한다.
- 모든 Resource 조회·Tool 호출을 감사 로그로 남긴다(요청 id, game, agent,
  작업, 허용 여부). 에이전트가 감사 로그를 조회할 수단은 없다.

### 6.3 작업 순서

아래 M1~M4는 [MCP 섹터 지침서](SECTOR_PLAN_MCP.md)의 WU-M1~M5로 세분화되어
있다(격리 불변식 WU-M0 포함). coding AI agent 세션은 WU 단위로만 지시한다.

1. **M1. 골격+fake 엔진** — server, 세션 고정, fake engine으로 Resource 7종.
2. **M2. Tool 6종** — 1차 검증, `/actions` 전달, 거부 응답 정제.
3. **M3. 실제 Engine 연결** — HMAC 클라이언트, capability 전달, 오류 변환.
4. **M4. 격리·감사 강화** — 세션 격리 테스트(다른 게임/agent 접근 거부),
   카나리 유출 테스트, 감사 로그 검증.

*완료 기준: fake 엔진 기반 전체 테스트 통과(외부 호출 0), 세션 위조·타
agent 조회 시도 전부 거부 경로 테스트 존재.*

---

## 7. Front 섹터 상세 계획

### 7.1 신규 파일 (승인된 구조 변경 범위)

```text
frontend_user/app_pages/home_page.py        # 홈: 새 게임/이어하기/불러오기
frontend_user/app_pages/game_create_page.py # 인원 5~9 선택, 역할표 안내
frontend_user/app_pages/game_play_page.py   # 진행: 타임라인·행동·관전·저장
frontend_user/app_pages/game_load_page.py   # 저장 목록
frontend_user/app_pages/game_result_page.py # 결과·피드백 진입
frontend_user/core/game_api.py              # 2장 게임 API 클라이언트
frontend_user/core/game_view.py             # GameStateView 파싱·표시 모델
frontend_user/components/game_ui.py         # 타임라인·좌석·행동 버튼 렌더링
frontend_user/tests/ (test_game_api.py, test_game_view.py,
  test_game_pages_smoke.py)

frontend_admin/app_pages/kpi_page.py
frontend_admin/app_pages/logs_page.py
frontend_admin/app_pages/feedback_page.py
frontend_admin/core/admin_api.py
frontend_admin/tests/ (신설: test_admin_api.py, test_admin_pages_smoke.py)
```

`frontend_user/app.py`는 로그인 후 `home_page`로 라우팅하도록 최소 수정한다
(기존 login_page 동작 보존).

### 7.2 구현 규칙

- 화면 상태의 근거는 항상 Backend 응답(GameStateView)이다. URL·세션만 믿지
  않고 새로 고침 시 `game_id`로 재조회한다.
- 모든 사용자·AI 발언, 표시 이름은 렌더링 전 HTML escape한다(기존
  `components/ui.py` 패턴 재사용).
- 진행 화면은 `ADVANCE_PHASE` 버튼형 턴제. SSE 가능 시 사용, 실패 시
  `?since_sequence` 폴링 폴백.
- 오류 코드별 고정 안내: 409→새로고침 유도, 503(AGENT)→재시도 버튼,
  503(PERSISTENCE)→저장 실패 안내(입력 보존).
- API client는 fake transport 주입이 가능해야 하며 테스트는 mock으로만 실행.
- 관리자 앱은 로그인 후 `acting_user_id`로 관리자 API를 호출하고 403이면
  기능 화면을 렌더링하지 않는다(fail-closed).

### 7.3 작업 순서

아래 F1~F5는 [Front 섹터 지침서](SECTOR_PLAN_FRONT.md)의 WU-F1~F8로
세분화되어 있다. coding AI agent 세션은 WU 단위로만 지시한다.

1. **F1. game_api + fake transport** — 2장 명세 그대로 클라이언트·모델.
2. **F2. 홈·생성·불러오기** — fake 데이터로 화면 완성.
3. **F3. 진행·결과 화면** — 타임라인, 행동 버튼, 관전·빠른 진행, 저장.
4. **F4. Backend 연동** — 실제 API 전환, 오류 안내, SSE/폴링.
5. **F5. 관리자 화면** — KPI·로그·피드백 3화면과 fail-closed 권한 처리.

---

## 8. 마일스톤과 통합 순서

각 섹터는 별도 시스템에서 개발한 뒤 통합 브랜치로 merge한다. 섹터별 작업
단위(WU)·coding AI agent 사용 규칙·체크포인트(CP) 상세는 섹터 지침서를
따른다.

- Front: [SECTOR_PLAN_FRONT.md](SECTOR_PLAN_FRONT.md) (WU-F1~F8, CP-F0~F4)
- Backend: [SECTOR_PLAN_BACKEND.md](SECTOR_PLAN_BACKEND.md) (WU-B1~B7, CP-B0~B5)
- MCP: [SECTOR_PLAN_MCP.md](SECTOR_PLAN_MCP.md) (WU-M1~M5, CP-M0~M4)

| 마일스톤 | Front | Backend | MCP | 통합 검증 |
|---|---|---|---|---|
| **M-A 계약 고정** | CP-F0 | CP-B0 | CP-M0 | 이 문서 리뷰 3인 합의 |
| **M-B 단독 완성** | CP-F1~F2 (fake) | CP-B1~B2 | CP-M1~M2 (fake) | 섹터별 focused+회귀 통과 |
| **M-C 1차 통합** | CP-F3 | CP-B3, CP-B4 | CP-M3 | 인간 1 + fake LLM로 한 판 완주 |
| **M-D 에이전트 통합** | 진행 UX 다듬기 | CP-B5(B6) | CP-M4 | 실제 LLM 수동 1회(비용 승인 후), 회귀는 fake |
| **M-E 관리자·알파** | CP-F4 | CP-B5(B7) | 감사 보강 | 5~9명 자동 시뮬레이션, 최종 플랜 15장 완료 조건 |

### 8.1 중간 merge 절차 (전 섹터 공통)

1. 섹터 브랜치(`feat/<섹터>-<기능>`)에서 CP 단위로만 merge를 요청한다.
   CP를 건너뛴 대량 merge는 금지한다.
2. merge 전: `develop`을 자기 브랜치에 반영해 충돌을 자기 쪽에서 해소하고
   전체 회귀(`uv run pytest` + compileall + ruff)를 통과시킨다.
3. merge 후: `develop`에서 통합 스모크를 실행하고 결과를 팀에 공유한다.
   - CP-B3/CP-F3 이후: Backend 기동 → `/health` 200 → 게임 생성 1회
   - CP-B4/CP-M3 이후: Backend + MCP 기동 → Resource 1종 조회 성공
4. 통합 스모크 실패 시 원인 섹터가 수정 브랜치로 후속 조치한다. 다른
   섹터 코드를 임의 수정하지 않는다.
5. `main` 병합은 M-C 이후 사용자 승인 시에만.

### 8.2 섹터 간 의존 순서 (병렬 계획의 기준)

```text
CP-B3(사용자 API) ──▶ CP-F3(Front 실연동)
CP-B4(내부 Engine API) ──▶ CP-M3(MCP 실연동)
CP-B5 + CP-M4 ──▶ M-E 통합 알파
그 외 모든 CP는 fake 기반으로 상호 독립 진행 가능
```

## 9. 계약 변경 절차 (추후 수정 가능 원칙)

1. 변경 제안자는 이 문서의 해당 절(2·3·5·6장)을 수정하는 diff를 먼저 공유한다.
2. 영향 섹터 담당자 동의 후 문서를 갱신하고, 그 다음 코드에 반영한다.
3. DB 변경은 기존 migration 수정이 아니라 **새 번호의 순방향 SQL 추가**로만.
4. 변경 이력은 이 장 아래 표에 기록한다.

| 날짜 | 변경 | 사유 | 합의 |
|---|---|---|---|
| 2026-09-01 | 초판 작성 | — | — |
| 2026-09-01 | `mcp_server/mcp_1` → `mcp_server/mafia_game` 개명 | 예약명 대신 담당 게임 도메인이 드러나는 이름 사용 | 사용자 승인 |
| 2026-09-02 | 섹터별 작업 지침서 3종 분리, 8장을 CP 기반 중간 merge·통합 스모크 절차로 개정 | 별도 시스템 개발 후 merge 전제의 세부 지침과 AI agent 세션 범위(WU 1개 이하) 강제 | 사용자 요청 |

## 10. 환경 변수 (전 섹터 공통, `.env.example` 참조)

| 변수 | 사용 섹터 | 용도 |
|---|---|---|
| `DATABASE_URL` / `DATABASE_NAME` | Backend | PostgreSQL |
| `INTERNAL_API_SECRET` | Front·Backend | Front→Backend HMAC (기존) |
| `ENGINE_INTERNAL_API_SECRET` | Backend·MCP | MCP→Backend 내부 HMAC (**Front용과 다른 값**) |
| `REDIS_URL` | Backend | lock·cache·stream |
| `LLM_PROVIDER` / `OPENAI_*` / `GEMINI_*` | Backend | LLM 이중 공급자 |
| `LLM_TIMEOUT_SECONDS` / `GAME_MAX_TOKENS_PER_RUN` | Backend | run 제한 |
| `MAFIA_MCP_URL` | Backend | MCP 서버 주소 (8100) |
| `ENGINE_API_URL` | MCP | Backend 내부 API 주소 (8000) |

모든 secret은 32자 이상 무작위 값, `.env`에만 보관, 로그·응답 출력 금지.
