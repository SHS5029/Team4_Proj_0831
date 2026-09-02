# AI 에이전트 마피아 MVP 구현 설계 초안

> **[대체됨]** 이 문서는 [AI_MAFIA_MVP_FINAL_PLAN.md](AI_MAFIA_MVP_FINAL_PLAN.md)로
> 통합·대체되었습니다. 내용이 충돌하면 최종 플랜을 우선합니다. 통합 시
> 변경된 항목은 [통합·수정 내역](AI_MAFIA_PLAN_INTEGRATION_NOTES.md)을
> 참고하세요.
> 정확한 `basic-v1` 규칙과 상태 전이는 [게임 규칙·로직](AI_MAFIA_GAME_RULES.md)을
> 기준으로 합니다.
> MVP 평점은 결과 화면의 1~5 단일 평점 저장만 지원하며, 이 초안의 서술형
> 피드백·카테고리·상태 관리 내용은 구현 기준이 아닙니다.
> 이 문서의 본문에 남은 세부 표와 경로는 과거 참고 기록으로만 보존합니다.

게임 MVP의 로그인·인증은 범위에서 제외되었으며, 사용자 구분은
`docs/AI_MAFIA_API_CONTRACT.md`의 `X-User-Id` 계약을 따른다. 이 문서의 로그인
관련 본문은 기존 저장소 전제이며 구현 기준으로 사용하지 않는다.

**문서 상태:** 구현 전 합의용 초안 (최종 플랜으로 대체됨)  
**기준일:** 2026년 9월 1일  
**대상 구조:** `frontend_user` + `frontend_admin` + `backend` + `mcp_server`

## 1. 제품 정의

이 MVP는 소셜 디덕션 게임의 가장 큰 진입장벽인 최소 인원 문제를 해결하기 위해
**1명의 인간 플레이어와 여러 AI 플레이어가 한 판을 완주하는 기본 마피아 게임**을
제공한다.

첫 버전은 경찰, 의사, 마피아, 시민만 사용한다. 역할 규칙, 인원 구성, 페르소나와
시나리오를 데이터로 분리해 이후 새 직업, 사용자 제작 규칙, 다인 플레이와 AI 게임
마스터의 동적 사건으로 확장할 수 있게 한다.

### MVP 성공 가설

- 로그인한 사용자가 다른 사람을 기다리지 않고 1분 안에 게임을 시작할 수 있다.
- AI마다 말투, 공격성, 기만 성향과 추론 능력이 달라 반복 플레이가 달라진다.
- 규칙 엔진이 승패와 정보 공개를 결정하고 LLM은 대화와 선택만 담당한다.
- 사용자는 진행 중인 게임을 저장하고 나중에 동일한 상태에서 이어 할 수 있다.
- 운영자는 KPI, 실패 로그와 사용자 피드백으로 게임 품질을 판단할 수 있다.

### MVP 범위

- Google OIDC 로그인 후 사용자 홈 진입
- 4~8명 게임 생성: 인간 1명, 나머지는 AI
- 기본 역할 자동 배정과 비공개 역할 안내
- 밤 행동, 낮 토론, 투표, 처형, 승패 판정
- AI 플레이어 페르소나와 중재 에이전트
- 자동 저장, 수동 저장, 저장 게임 불러오기
- 결과 화면과 최소 게임 통계
- 관리자 KPI 대시보드, 로그, 사용자 피드백 화면
- Backend가 LLM, MCP, PostgreSQL, Redis를 단독으로 연결·관리하는 경계

MVP 이후에는 인간 다인 플레이, 음성 채팅, 사용자 제작 역할·시나리오, 동적 사건,
랭킹·친구·길드·결제, 완성형 신고·제재 기능을 검토한다.

## 2. 핵심 설계 원칙

1. **규칙은 코드가 결정한다.** LLM이 역할 배정, 유효 행동, 생존 상태나 승패를
   변경할 수 없다.
2. **비공개 정보는 최소 공개한다.** 각 에이전트에는 자신의 역할과 해당 시점에 알
   수 있는 사건만 전달한다.
3. **게임 기록은 이벤트 중심으로 남긴다.** PostgreSQL 이벤트와 스냅샷이 복구의
   기준이며 Redis는 가속과 실행 조정에만 사용한다.
4. **Frontend는 Backend만 호출한다.** 두 Frontend가 DB, Redis, LLM 또는 MCP 서버에
   직접 연결하지 않는다.
5. **에이전트 실패를 격리한다.** 제한 시간 초과나 잘못된 응답에는 규칙 기반 기본
   행동을 적용하고 운영 로그를 남긴다.
6. **확장은 등록 방식으로 한다.** 역할, 페르소나, 규칙 세트와 MCP 도구를 등록형
   계약으로 분리한다.

## 3. 전체 시스템 구조

```text
┌────────────────────┐       ┌────────────────────┐
│ User Streamlit     │       │ Admin Streamlit    │
│ login/home/game    │       │ KPI/log/feedback   │
└─────────┬──────────┘       └─────────┬──────────┘
          │ HTTPS + 사용자 세션/권한               │
          └────────────────┬──────────────────────┘
                           ▼
                 ┌───────────────────┐
                 │ FastAPI Backend   │
                 │ API + Game Engine │
                 │ Agent Manager     │
                 └───┬────┬────┬─────┘
                     │    │    │
          ┌──────────┘    │    └───────────┐
          ▼               ▼                ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ PostgreSQL   │ │ Redis        │ │ LLM Provider │
  │ 원본/이벤트  │ │ lock/cache   │ │ 구조화 응답  │
  └──────────────┘ └──────────────┘ └──────┬───────┘
                                           │ 허용 목록만
                                           ▼
                                  ┌──────────────────┐
                                  │ Game Context MCP │
                                  │ resource/tool    │
                                  └──────────────────┘
```

### 저장소 디렉터리별 책임

| 위치 | MVP 책임 |
|---|---|
| `frontend_user/app.py` | 로그인과 애플리케이션 페이지 전환 진입점 |
| `frontend_user/app_pages/` | 홈, 게임 생성, 게임 진행, 불러오기, 결과 화면 |
| `frontend_user/core/api_client.py` | 사용자용 Backend API 호출의 단일 경계 |
| `frontend_admin/app.py` | 관리자 메뉴와 권한 확인 진입점 |
| `frontend_admin/app_pages/` | KPI, 로그, 피드백 화면 |
| `frontend_admin/core/api_client.py` | 관리자 전용 API 호출과 오류 변환 |
| `backend/app/routers/` | 사용자 게임·피드백·관리자 HTTP 계약 |
| `backend/app/services/` | 게임 생성/진행/저장, 조회, 관리자 유스케이스 |
| `backend/app/models/` | 게임 상태, 역할, 행동, 이벤트와 페르소나 도메인 |
| `backend/app/repositories/` | PostgreSQL 게임·피드백·로그 저장 |
| `backend/app/agent/` | 플레이어·중재 에이전트 실행 조율 |
| `backend/app/llm_provider/` | 모델 공급자 독립 구조화 호출과 제한 시간 |
| `backend/app/mcp/` | 허용 MCP 서버·도구 등록, 호출 정책과 감사 기록 |
| `backend/app/infrastructure/redis/` | 게임 lock, 실행 상태, event stream, idempotency |
| `mcp_server/` | Backend가 허용한 게임 컨텍스트 resource/tool 제공 |

기존 `tour`, `weather` MCP 예약 패키지는 삭제하거나 마피아 기능과 섞지 않는다.
게임 MCP를 구현할 때 `mcp_server` 아래 독립 패키지를 추가하고 구조 변경 전 이름과
범위를 다시 합의한다.

## 4. 사용자 화면과 전환

Streamlit 화면은 URL만으로 상태를 신뢰하지 않고 Backend가 반환한 현재 게임 상태를
기준으로 그린다. 새로 고침해도 `game_id`로 복구할 수 있어야 한다.

```text
로그인
  └─ 성공 → 홈
             ├─ 게임 생성 → 인원 설정 → 게임 진행 ─┬─ 승패 확정 → 결과
             │                                      └─ 저장 → 홈
             └─ 게임 불러오기 → 저장 목록 → 게임 진행
```

### 4.1 홈

- 로그인 사용자 이름과 환영 문구
- `새 게임 만들기`, `저장한 게임 불러오기` 버튼
- 진행 중 저장본의 마지막 저장 시각과 `이어하기` 바로가기
- 보조 동작으로 로그아웃 유지

### 4.2 게임 생성

- 전체 인원 4~8명 선택, 기본값 6명
- 기본 규칙과 예상 역할 구성 표시
- AI 수는 자동으로 `전체 인원 - 1`
- 시작 시 Backend가 게임, 참가자와 역할을 한 트랜잭션으로 생성

| 전체 인원 | 마피아 | 경찰 | 의사 | 시민 |
|---:|---:|---:|---:|---:|
| 4 | 1 | 1 | 1 | 1 |
| 5 | 1 | 1 | 1 | 2 |
| 6 | 1 | 1 | 1 | 3 |
| 7 | 2 | 1 | 1 | 3 |
| 8 | 2 | 1 | 1 | 4 |

역할은 인간에게도 무작위 배정한다. 운영 재현을 위한 random seed는 서버에 기록하되
일반 응답에는 노출하지 않는다.

### 4.3 게임 진행

- 상단: 라운드, 현재 단계, 생존자 수, 저장 상태
- 중앙: 중재자의 안내와 공개 대화 타임라인
- 하단: 현재 역할과 단계에 허용된 인간 행동
- 사이드 패널: 생존 참가자, 공개된 사망자와 메모
- `저장하고 나가기`와 마지막 자동 저장 시각

인간이 탈락하면 공개 정보만 보는 관전 상태로 전환한다. `AI 진행 보기`와 `결과까지
빠르게 진행`을 제공해 대기 시간을 줄인다.

### 4.4 불러오기와 결과

불러오기 화면에는 본인 소유의 `IN_PROGRESS` 또는 `PAUSED` 저장본만 표시한다.
생성일, 마지막 저장일, 라운드와 생존 인원을 보여 주며 Backend가 소유권과 snapshot
version을 다시 확인한다.

결과 화면에는 승리 진영, 전체 역할, 밤 희생·치료·조사·투표의 주요 타임라인,
인간의 생존 여부와 투표 적중률을 표시한다. `한 판 더`, `홈으로`, `피드백 남기기`를
제공한다.

## 5. 관리자 화면

관리자 앱은 일반 사용자용 내부 서명을 관리자 권한으로 재사용하지 않는다. OIDC 사용자와
내부 관리자 role을 Backend가 함께 확인한 뒤 읽기 권한을 부여한다.

### 5.1 KPI·대시보드

- 오늘/7일/30일 신규 게임 수와 완주율
- 평균 게임 시간과 평균 라운드 수
- 저장 후 재개율
- 인원수별 시민/마피아 승률
- 인간 역할별 승률과 첫날 탈락률
- LLM 성공률, timeout률, fallback률, 평균 응답 시간
- 게임당 평균 token 사용량과 추정 비용
- 피드백 평균 점수와 미처리 건수

### 5.2 로그와 피드백

로그는 기간, trace id, game id, user id 해시, 심각도와 이벤트 유형으로 필터한다.
에이전트 오류, MCP 거부, 상태 전이 충돌과 저장 실패를 우선 조회한다. 전체 prompt,
비공개 역할 목록과 비밀정보는 노출하지 않고 민감 필드를 제거한 요약만 보관한다.

피드백은 별점, 분류, 내용, game id, 작성일과 처리 상태를 가진다. 분류는 `재미`,
`AI 품질`, `규칙 오류`, `성능`, `기타`, 상태는 `NEW`, `REVIEWING`, `RESOLVED`,
`WONT_FIX`로 시작한다. MVP 관리자는 조회와 상태 변경만 할 수 있다.

## 6. 게임 규칙과 상태 머신

### 6.1 역할

| 역할 | 진영 | 밤 행동 | 승리 조건 |
|---|---|---|---|
| 마피아 | 마피아 | 생존자 1명 제거 선택 | 마피아 수가 시민 진영 수 이상 |
| 경찰 | 시민 | 생존자 1명의 마피아 여부 조사 | 모든 마피아 제거 |
| 의사 | 시민 | 생존자 1명 보호 | 모든 마피아 제거 |
| 시민 | 시민 | 없음 | 모든 마피아 제거 |

MVP는 의사의 자기 보호와 연속 동일 대상 보호를 허용한다. 마피아가 두 명이면 각자의
선택을 다수결로 정하고 동률이면 서버의 결정적 규칙으로 한 명을 선택한다. 규칙은
`ruleset_version`에 묶어 저장본 복구 중 바뀌지 않게 한다.

### 6.2 상태 전이

```text
CREATED
  → ROLE_REVEAL
  → NIGHT_ACTION
  → NIGHT_RESOLUTION
  → DAY_ANNOUNCEMENT
  → DAY_DISCUSSION
  → DAY_VOTE
  → VOTE_RESOLUTION
       ├─ 승패 미확정 → NIGHT_ACTION
       └─ 승패 확정 → FINISHED
```

요청에는 `expected_version`과 idempotency key를 포함한다. Backend는 게임별 lock에서
소유권·상태·version·행동을 검증하고, event append와 snapshot 저장을 완료한 뒤에만
Redis cache와 event stream을 갱신한다. 이전 version 요청은 `409`로 응답한다.

### 6.3 밤과 낮 처리

밤에는 마피아 대상, 의사 보호, 경찰 조사를 받은 뒤 공격과 보호가 같으면 사망을
취소한다. 경찰 결과는 해당 경찰의 private event로만 저장한다. 중재자는 사망 여부만
공개하며 보호 대상과 조사 결과를 누설하지 않는다.

낮에는 밤 결과 공개, 제한된 공개 발언, 생존자 투표, 처형과 승패 판정을 진행한다.
최다 득표 동률이면 처형하지 않는다. 매 밤과 투표 해소 뒤 시민 또는 마피아 승리
조건을 확인한다.

## 7. 에이전트 설계

**플레이어 에이전트**는 자신의 승리 조건에 맞게 발언, 밤 행동과 투표를 선택한다.
각 에이전트의 메모리는 분리한다.

**중재 에이전트**는 규칙 엔진이 만든 공개 결과를 자연어로 전달하고 발언 순서를
안내한다. 상태를 직접 변경하거나 숨겨진 역할을 조회하지 않는다.

**Agent Manager**는 Backend 내부에서 에이전트 컨텍스트, LLM/MCP 호출, timeout,
재시도, fallback과 사용량 기록을 조정한다.

### 7.1 페르소나 파라미터

모든 수치 값은 기본적으로 0.0~1.0이며 API schema와 도메인 양쪽에서 검증한다.

| 파라미터 | 의미 |
|---|---|
| `sociability` | 발언 빈도와 대화 참여도 |
| `assertiveness` | 주장을 강하게 표현하는 정도 |
| `suspicion` | 작은 모순도 의심하는 정도 |
| `deception` | 마피아일 때 거짓 정보를 사용하는 정도 |
| `risk_tolerance` | 불확실한 대상에게 행동하는 정도 |
| `memory_recall` | 과거 발언과 투표를 활용하는 정도 |
| `reasoning_skill` | 증거를 연결하고 모순을 찾는 수준 |
| `emotionality` | 압박에 반응하는 표현 강도 |
| `cooperativeness` | 타인의 의견을 수용하는 정도 |
| `verbosity` | 한 번에 말하는 길이 |

문자열은 `display_name`, `speech_style`, `backstory`로 제한하고 길이와 허용 문자를
검증한다. MVP는 차분한 분석가, 성급한 리더, 조용한 관찰자, 친화적 중재자, 능숙한
블러퍼 같은 서버 등록 프리셋을 무작위 배정한다.

### 7.2 입력 컨텍스트와 구조화 출력

각 에이전트에는 현재 라운드·단계·규칙 버전, 자신의 role과 생존 상태, persona,
공개 사건, 자기 private event, 허용 action과 생존자만 전달한다. 다른 참가자의 role,
다른 경찰 결과, 보호 대상과 random seed는 넣지 않는다. 공개 채팅의 명령문은 시스템
지시가 아닌 데이터로 표시한다.

```json
{
  "action": "SPEAK",
  "target_player_id": null,
  "message": "어젯밤 투표를 바꾼 이유를 듣고 싶어요.",
  "public_rationale": "공개된 투표 기록의 변화를 확인하려는 질문"
}
```

- 내부 chain-of-thought는 요청하거나 저장하지 않는다.
- 응답은 action, 대상 생존 여부, 글자 수와 안전 정책을 다시 검증한다.
- 잘못된 응답에는 교정 요청을 한 번만 하고 규칙 기반 fallback을 사용한다.
- 단계별 제한 시간과 token 상한을 둔다.

### 7.3 실패 fallback

| 실패 | MVP fallback |
|---|---|
| AI 발언 timeout | 해당 발언 건너뛰기 |
| AI 투표·밤 행동 실패 | 결정적 무작위 유효 후보 선택 |
| 중재 문장 실패 | 규칙 엔진의 고정 한국어 템플릿 |
| MCP 조회 실패 | 저장된 snapshot 컨텍스트만 사용 |
| Redis 장애 | 새 agent turn 중단, PostgreSQL 원본 보존 |
| LLM 공급자 전체 장애 | 게임을 `PAUSED`로 저장하고 재개 안내 |

## 8. MCP 서버 초안

MCP는 규칙 엔진을 대신하지 않고 에이전트가 허용된 컨텍스트를 읽고 제한된 행동을
제안하는 표준 경계로 사용한다. Backend가 `game_id`, `agent_id`, phase를 기준으로
capability를 발급하고 허용 목록 밖의 호출을 거부한다.

### Resources

| URI 예시 | 내용 |
|---|---|
| `mafia://rules/basic-v1` | 현재 규칙과 승리 조건 |
| `mafia://games/{id}/public-timeline` | 해당 게임의 공개 사건과 발언 |
| `mafia://games/{id}/agents/{agent_id}/memory` | 자기 역할과 private event |
| `mafia://personas/{persona_id}` | 검증된 페르소나 설정 |

### Tools

| Tool | 용도 | 주요 검증 |
|---|---|---|
| `get_allowed_actions` | 현재 가능한 행동 조회 | game/agent/phase 일치 |
| `submit_night_action` | 밤 역할 행동 제안 | 역할, 생존, 대상, 중복 |
| `submit_vote` | 낮 투표 제안 | 생존자, 대상, 현재 단계 |
| `publish_statement` | 공개 발언 제안 | 길이, 횟수, 안전 정책 |
| `recall_public_events` | 제한 범위 사건 회상 | 공개 event만 반환 |

Tool은 상태를 직접 변경하지 않고 Game Service가 검증할 **행동 제안**을 반환한다.
실제 event append와 상태 전이는 Backend 트랜잭션에서만 수행한다.

## 9. 데이터 모델 초안

PostgreSQL을 영구 원본으로 사용한다. 검색·무결성 필드는 열로, 규칙별 확장 데이터는
검증된 JSONB로 둔다.

| 테이블 | 주요 필드 | 목적 |
|---|---|---|
| `game_sessions` | id, user_id, status, phase, round, winner, ruleset_version, state_version, timestamps | 현재 게임 헤더 |
| `game_players` | id, game_id, user_id nullable, kind, seat, role, faction, alive, persona_id | 인간·AI 참가자와 비공개 역할 |
| `game_events` | id, game_id, sequence, type, visibility, audience_player_id, payload, created_at | append-only 게임 기록 |
| `game_snapshots` | game_id, version, state, checksum, created_at | 빠른 저장·복구 |
| `agent_personas` | id, version, name, parameters, active | 버전 고정 페르소나 |
| `agent_runs` | id, game_id, player_id, phase, status, latency_ms, token_usage, model_code, error_code | 품질·비용 지표 |
| `user_feedback` | id, user_id, game_id nullable, rating, category, content, status, timestamps | 사용자 의견 |
| `audit_logs` | id, trace_id, actor_type, actor_id_hash, action, target_type, target_id, metadata, created_at | 관리자·보안 감사 |

이벤트 공개 범위는 모든 참가자용 `PUBLIC`, 지정 에이전트용 `PRIVATE`, 마피아 합의용
`FACTION`, 규칙·복구용 `SYSTEM`으로 분리한다. 결과 전에는 전체 역할을 반환하지 않는다.

중요 사용자 행동과 phase 종료 직후 자동 저장한다. `저장하고 나가기`는 agent run이
끝난 안전 지점에서 `PAUSED`로 전환한다. snapshot checksum과 마지막 event sequence가
다르면 이벤트 재생으로 복구한다. 검증 후 채택된 발언과 행동만 원본으로 저장한다.

## 10. Redis 사용 초안

| Key/채널 예시 | 용도 | TTL |
|---|---|---:|
| `team4:game:{game_id}:lock` | 중복 턴 방지 | 30초, 갱신 가능 |
| `team4:game:{game_id}:runtime` | snapshot 읽기 cache | 30분 |
| `team4:game:{game_id}:events` | Frontend 갱신 Stream | 소비 후 정리 |
| `team4:idempotency:{user_id}:{key}` | 명령 재전송 방지 | 24시간 |
| `team4:agent:{run_id}:status` | LLM/MCP 진행 상태 | 15분 |
| `team4:rate:{user_id}` | 생성·LLM 호출 제한 | 정책별 |

lock token 소유자만 lock을 해제하고 긴 작업은 heartbeat로 연장한다. DB commit 전에
cache를 성공으로 갱신하지 않는다. Redis는 영구 게임 원본으로 사용하지 않는다.

## 11. Backend API 초안

게임 API는 OIDC에서 연결된 내부 사용자를 검증하고 요청 body의 `user_id`는 권한 근거로
신뢰하지 않는다. 기존 공통 오류와 trace id 계약을 유지한다.

### 사용자 API

| Method | Endpoint | 용도 |
|---|---|---|
| `POST` | `/api/v1/games` | 인원수와 ruleset으로 새 게임 생성 |
| `GET` | `/api/v1/games?status=saved` | 본인의 저장 게임 목록 |
| `GET` | `/api/v1/games/{game_id}` | 권한에 맞게 필터한 현재 상태 |
| `POST` | `/api/v1/games/{game_id}/commands` | 행동, 투표, 저장, 빠른 진행 |
| `GET` | `/api/v1/games/{game_id}/events` | SSE 진행 이벤트 구독 |
| `GET` | `/api/v1/games/{game_id}/result` | 종료 게임 결과 |
| `POST` | `/api/v1/feedback` | 별점과 정규화한 내용 저장 |

명령 요청 예시는 다음과 같다.

```json
{
  "command": "CAST_VOTE",
  "target_player_id": "8d155bef-9814-4a11-89b6-2d87af1d65f1",
  "message": null,
  "expected_version": 17,
  "idempotency_key": "018f6f7c-0496-758e-981f-05985cb67210"
}
```

### 관리자 API

| Method | Endpoint | 용도 |
|---|---|---|
| `GET` | `/api/v1/admin/kpis` | 기간별 집계 KPI |
| `GET` | `/api/v1/admin/logs` | 필터·페이지 기반 운영 로그 |
| `GET` | `/api/v1/admin/feedback` | 피드백 목록과 집계 |
| `PATCH` | `/api/v1/admin/feedback/{feedback_id}` | 처리 상태 변경 |

주요 오류는 `GAME_NOT_FOUND`, `GAME_STATE_CONFLICT`, `ACTION_NOT_ALLOWED`,
`AGENT_TEMPORARILY_UNAVAILABLE`, `GAME_PERSISTENCE_UNAVAILABLE`,
`ADMIN_ACCESS_DENIED`로 시작한다. 없거나 소유하지 않은 게임은 같은 응답으로 처리한다.

## 12. 보안·운영 경계

- 기존 HMAC은 서버 간 무결성 수단이지 사용자·관리자 권한 증명이 아니다.
- 게임 API에는 검증 가능한 사용자 세션 또는 짧은 수명의 Backend access token을
  추가하고 모든 조회에서 소유권을 검사한다.
- 관리자 권한은 DB의 명시적 role과 공급자 identity를 함께 확인한다.
- 사용자 발언, 피드백, LLM/MCP 결과는 검증하고 HTML 렌더링 전에 escape한다.
- MCP 서버·tool·resource는 allowlist와 game/agent capability를 확인한다.
- prompt injection 문자열은 명령이 아닌 데이터로 전달한다.
- 비밀정보, 전체 prompt, chain-of-thought와 다른 참가자 private 정보를 로그에 남기지
  않는다.
- 모델·prompt·persona·ruleset 버전을 기록해 장애를 재현한다.
- 비용·속도 제한을 사용자, 게임, agent run 단위로 적용한다.
- 자유 채팅의 사용자 입력과 AI 출력에 최소 안전 필터를 적용한다.

## 13. Agent Manager 실행 흐름

```text
사용자 명령 또는 phase 시작
  → 게임별 Redis lock 획득
  → PostgreSQL 최신 version 확인
  → 규칙 엔진이 허용 행동과 대상 계산
  → 에이전트별 최소 컨텍스트 구성
  → MCP 허용 범위 설정
  → LLM 구조화 결정 요청
  → schema·규칙·안전 정책 검증
  → 실패 시 교정 1회 또는 fallback
  → game event append + snapshot commit
  → Redis cache/event stream 갱신
  → Frontend에 새 version 전달
```

독립적인 밤 행동은 동시에 요청할 수 있지만 DB 반영은 게임별 lock 안에서 한 번에
처리한다. 낮 대화는 이전 발언이 다음 에이전트 컨텍스트에 포함되므로 좌석 순서대로
진행한다. 중재 에이전트는 공개 event가 확정된 뒤 호출한다.

## 14. 구현 단계

### 0단계: 계약 고정

- 기본 규칙, 역할표, 의사와 투표 동률 규칙 합의
- 사용자 게임 API 인증 방식 결정
- LLM 공급자와 게임당 비용 상한 결정
- 게임용 MCP 패키지 이름과 배포 단위 합의

### 1단계: LLM 없는 규칙 엔진

- 게임 도메인과 상태 머신
- 결정적 random seed 역할 배정
- 밤/낮/투표/승패 단위 테스트
- fake agent 한 판 자동 완주 테스트

### 2단계: DB·Redis 저장

- 순방향 PostgreSQL migration과 repository
- event append, optimistic version, snapshot 저장·복구
- Redis lock, idempotency와 실행 상태
- Redis 장애와 동시 명령 충돌 테스트

### 3단계: 사용자 화면과 API

- 로그인 후 홈 전환
- 생성, 진행, 저장 목록과 결과 페이지
- SSE 또는 짧은 polling으로 agent 상태 표시
- 오류별 재시도·복구 안내

### 4단계: 플레이어/중재 에이전트와 MCP

- persona preset과 분리된 private memory
- 구조화 LLM client, 제한 시간, 비용 기록
- 게임 MCP resource/tool과 capability 정책
- JSON 오류, timeout, 정보 누설, prompt injection 테스트

### 5단계: 관리자와 관측성

- 관리자 인증/권한과 세 API
- KPI 집계, 로그 필터, 피드백 상태 관리
- trace id로 요청부터 agent run까지 연결
- 비용·오류율 알림 기준

### 6단계: 알파 검증

- 4~8명 구성별 다수 자동 시뮬레이션
- 진영·역할별 승률과 게임 길이 분석
- 재미, AI 자연스러움, 억울한 탈락 피드백 수집
- 모델과 persona 조정 전후 지표 비교

## 15. 테스트와 완료 기준

필수 자동 테스트는 역할 배정 불변식, 단계별 행동 거부, 의사·경찰·마피아 밤 처리,
투표 동률, 승패 경계, snapshot/event 재생, optimistic lock, idempotency, Redis lock,
게임 소유권, 관리자 권한, 에이전트 정보 누설, LLM/MCP 실패 fallback, 입력 escape와
민감 로그 제거를 포함한다.

통합 테스트는 생성 → 역할 확인 → 밤 → 낮 → 투표 → 저장 → 재개 → 결과 흐름과
관리자 KPI 집계를 synthetic 데이터와 fake LLM/MCP로 검증한다. 유료 LLM을 기본 회귀
테스트에서 호출하지 않는다.

MVP 완료 조건은 다음과 같다.

- 로그인한 사용자 한 명이 4~8명 게임을 생성·완주한다.
- AI마다 서로 다른 persona가 적용된다.
- 네 역할의 행동, 투표와 승패는 규칙 엔진으로 동작한다.
- 프로세스 재시작 후 저장 게임을 이어 할 수 있다.
- 인간 탈락 후 관전 또는 빠른 진행으로 결과를 확인한다.
- LLM/MCP 실패가 게임 상태를 훼손하지 않는다.
- 관리자만 KPI, 정제된 로그와 피드백을 조회한다.
- 소유권, 비공개 역할과 관리자 권한 거부 경로가 테스트된다.
- 전체 테스트, compileall과 lint가 통과하고 README가 구현과 일치한다.

## 16. 구현 전 결정이 필요한 항목

1. 인간 역할을 완전 무작위로 둘지 첫 판에는 시민 진영만 제공할지
2. AI 발언을 버튼 단위 턴제로 할지 제한 시간 안에 자동 재생할지
3. 게임당 token·비용 상한과 목표 플레이 시간
4. 저장본 보존 기간과 사용자 삭제 기능 제공 시점

초기 권장값은 **역할 완전 무작위, 발언 버튼형 턴제, 10~15분 목표, 저장본 30일
보존**이다. 턴제는 한 명 플레이에서 읽는 속도를 보장하고 예상하지 못한 LLM 연속
호출과 비용을 제어하기 쉽다.
