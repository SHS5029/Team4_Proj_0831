# AI 마피아 MVP 최종 통합 플랜

**문서 상태:** 확정 통합본 (구현 기준 문서)
**기준일:** 2026년 9월 2일
**규칙 세트:** `mystery-v1`
**시나리오 세트:** `scenario-v1`
**통합 원본:** `docs/초기기획안/mafia_game_rules.md`,
`docs/초기기획안/mafia_game_scenarios.md`,
`docs/초기기획안/mafia_game_plan.md`, `docs/플랜/AI_MAFIA_MVP_PLAN.md`,
`docs/규칙/ai_mafia_game_engine분리규칙.md`
**변경 근거:** 통합 과정의 충돌 항목과 결정 사유는
[통합·수정 내역](AI_MAFIA_PLAN_INTEGRATION_NOTES.md)에 기록되어 있다.

이 문서는 기획 문서를 현재 저장소 구조에 맞춰 검증·통합한 최종 MVP 플랜이다.
게임 진행·역할·승패와 시나리오 내용은 `mafia_game_rules.md`와
`mafia_game_scenarios.md`가 제품 정본이고, 시스템 경계·저장·보안·작업 순서는
이 문서와 개발상세플랜이 구현 정본이다. 두 계층이 충돌하면 어느 한쪽을 임의로
우선하지 않고 계약 변경 절차로 함께 고친 뒤 구현한다.

## 1. 제품 정의

소셜 디덕션 게임의 최소 인원 문제를 해결하기 위해 **1명의 인간 플레이어와
여러 AI 플레이어가 한 판을 완주하는 기본 마피아 게임**을 제공한다.

첫 버전은 **마피아, 탐정, 의사, 시민** 네 역할과 다섯 개의 경량 사건
시나리오를 사용한다. 시나리오는 복잡한 사건 퍼즐이 아니라 대화의 배경이며,
각 플레이어에게 짧은 알리바이와 관찰 정보 하나씩만 제공한다. 역할 규칙,
인원 구성, 페르소나와 시나리오를 버전 고정 데이터로 분리해 확장할 수 있게 한다.

### MVP 성공 가설

- 로그인한 사용자가 다른 사람을 기다리지 않고 1분 안에 게임을 시작할 수 있다.
- AI마다 말투, 공격성, 기만 표현이 달라 반복 플레이가 달라진다. MVP 밸런스
  검증 중에는 추론 능력과 정보 접근 권한을 동일하게 고정한다.
- 규칙 엔진(Backend)이 승패와 정보 공개를 결정하고 LLM은 대화와 선택만 담당한다.
- 사용자는 진행 중인 게임을 저장하고 나중에 동일한 상태에서 이어 할 수 있다.
- 운영자는 KPI, 실패 로그와 사용자 피드백으로 게임 품질을 판단할 수 있다.

### MVP 범위

- Google OIDC 로그인 후 사용자 홈 진입 (현재 구현된 로그인 흐름 재사용)
- **6~9명** 게임 생성: 인간 1명, 나머지는 AI
- 기본 역할 자동 배정과 비공개 역할 안내
- `scenario-v1` 다섯 사건 중 하나와 seed 기반 알리바이·관찰 정보 배정
- 첫날 무처형 낮, 밤 행동, 턴 기반 낮 토론, 투표·재투표, 처형, 최대 5밤과
  최종 지목(`FINAL_ACCUSATION`) 판정
- AI 플레이어 페르소나와 AI GM(공개 진행 안내 전용)
- 자동 저장, 수동 저장, 저장 게임 불러오기
- 결과 화면과 최소 게임 통계
- 관리자 KPI 대시보드, 로그, 사용자 피드백 화면
- Backend가 LLM·MCP·PostgreSQL·Redis application 연결을 단독 관리하고,
  PostgreSQL·Redis 실행 환경의 구축·기동·migration 실행은 MCP 섹터가 담당하는 경계

### MVP 제외 (후속 확장)

- 복잡한 추리극 요소: 동적 사건 진실 생성, 다단계 핵심 단서, 정확한 시간표,
  인물 관계도, Red Herring, 장소 조사와 AI GM의 범행 해설
  (`../초기기획안/mafia_game_plan.md`의 확장 기획)
- 인간 다인 플레이, 음성 채팅, 사용자 제작 역할·시나리오
- 랭킹·친구·길드·결제, 완성형 신고·제재

## 2. 핵심 설계 원칙

1. **규칙은 코드가 결정한다.** LLM이 역할 배정, 유효 행동, 생존 상태나 승패를
   변경할 수 없다. 메인 게임 엔진(Backend)이 유일한 진실 공급원이다.
2. **비공개 정보는 처음부터 격리한다.** AI에게 비밀을 보여준 뒤 누설하지
   말라고 지시하지 않는다. 각 에이전트에는 자신의 역할과 해당 시점에 알 수
   있는 사건만 전달한다.
3. **게임 기록은 이벤트 중심으로 남긴다.** PostgreSQL 이벤트와 스냅샷이
   복구의 기준이며 Redis는 가속과 실행 조정에만 사용한다.
4. **Frontend는 Backend만 호출한다.** 두 Frontend가 DB, Redis, LLM 또는 MCP
   서버에 직접 연결하지 않는다.
5. **에이전트 실패를 격리한다.** 제한 시간 초과나 잘못된 응답에는 규칙 기반
   기본 행동을 적용하고 운영 로그를 남긴다.
6. **확장은 등록 방식으로 한다.** 역할, 페르소나, 규칙 세트와 MCP 도구를
   등록형 계약으로 분리한다.
7. **시간과 무작위 결과는 서버가 확정한다.** 행동 마감 시각과 seed를 저장하고,
   지연·재전송·재접속으로 이미 확정된 자동 선택을 다시 뽑지 않는다.
8. **AI GM은 공개 상태만 본다.** 전체 역할표와 야간 행동 원본은 Backend만
   보유하며, GM에는 공개가 확정된 이벤트와 안전한 고정 템플릿 입력만 전달한다.

## 3. 전체 시스템 구조

```text
┌────────────────────┐       ┌────────────────────┐
│ frontend_user      │       │ frontend_admin     │
│ login/home/game    │       │ KPI/log/feedback   │
└─────────┬──────────┘       └─────────┬──────────┘
          │ HTTPS + 사용자 세션/권한               │
          └────────────────┬──────────────────────┘
                           ▼
                 ┌───────────────────┐
                 │ FastAPI Backend   │
                 │ API + Game Engine │
                 │ Agent Manager     │
                 └─┬──────┬──────┬──────────┬─┘
                   │      │      │          │ 인증 bootstrap·허용 Tool/Resource
                   ▼      ▼      ▼          ▼
          ┌───────────┐ ┌─────┐ ┌──────────┐ ┌────────────────────┐
          │PostgreSQL │ │Redis│ │LLM       │ │mcp_server/         │
          │원본/이벤트│ │조정 │ │Provider  │ │mafia_game          │
          └───────────┘ └─────┘ └──────────┘ └─────────┬──────────┘
                                                       │ 서명된 context/action/audit
                                                       └──────▶ Backend 내부 Engine API
```

위 그림은 runtime 통신 경계다. Backend가 DML 최소 권한 runtime 계정으로
PostgreSQL·Redis에 직접 연결하며 MCP 서버가 데이터 프록시가 되지 않는다. 팀
Agent Manager가 LLM과 MCP를 각각 호출하며 LLM 공급자가 MCP에 직접 연결하지
않는다. MCP는 인증된 세션에서 Backend 내부 Engine API만 호출한다.
역할상 PostgreSQL·Redis 인스턴스의 설치, 생성, 기동, 중지, DDL 전용 migrator와
runtime 계정·권한 준비, migration 실행과 health 확인은 MCP 섹터가 담당한다.
Backend 섹터는 DB schema·migration SQL·repository와 Redis client·lock 동작을
작성한다. migration 자격정보를 Backend runtime에 제공하지 않는다.
현재 migration runner가 runtime `DATABASE_URL`을 공유하므로 Backend 영속화 WU에서
별도 실행 경로가 `DATABASE_MIGRATION_URL`만 읽도록 먼저 분리한다. `.env.example`은
설정 카탈로그로만 사용하고 각 runtime에는 README의 프로세스별 allowlist만 주입한다.

### 3.1 현재 저장소 디렉터리별 책임

아래 표는 **현재 실제 디렉터리 구조**에 MVP 책임을 매핑한 것이다. 새 최상위
디렉터리를 만들지 않고 기존 예약 위치를 채운다.

| 위치 | MVP 책임 |
|---|---|
| `frontend_user/app.py` | 로그인과 애플리케이션 페이지 전환 진입점 |
| `frontend_user/app_pages/` | 홈, 게임 생성, 게임 진행, 불러오기, 결과 화면 추가 |
| `frontend_user/core/api_client.py` | 사용자용 Backend API 호출의 단일 경계 |
| `frontend_admin/app.py` | 관리자 메뉴와 권한 확인 진입점 |
| `frontend_admin/app_pages/` | KPI, 로그, 피드백 화면 추가 |
| `frontend_admin/core/api_client.py` | 관리자 전용 API 호출과 오류 변환 |
| `backend/app/routers/` | 게임·피드백·관리자 HTTP router 추가 |
| `backend/app/schemas/` | 게임 명령·상태·관리자 API 계약 추가 |
| `backend/app/services/` | 게임 생성/진행/저장, 조회, 관리자 유스케이스 |
| `backend/app/models/` | 게임 상태, 역할, 행동, 이벤트, 페르소나 도메인 |
| `backend/app/repositories/` | PostgreSQL 게임·피드백·로그 저장소 |
| `backend/app/agent/` | Agent Manager: 플레이어·공개 전용 AI GM 실행 조율 |
| `backend/app/llm/client.py` | OpenAI·Gemini 공급자 독립 구조화 호출과 timeout |
| `backend/app/mcp/` | 허용 MCP 서버·도구 등록, capability 정책, 감사 기록 |
| `backend/app/infrastructure/redis/` | 게임 lock, 실행 상태, event stream, idempotency |
| `backend/migrations/` | 게임 schema 순방향 SQL 추가 (`002_...` 이후 번호) |
| `mcp_server/mafia_game/` | **마피아 게임 컨텍스트 MCP 서버** (resource/tool) |
| `mcp_server/mcp_2/` | 후속 MCP 예약 (MVP에서 사용하지 않음) |

`backend/`가 DB·Redis application 코드를 소유하는 것과 실행 환경 담당자가 MCP
섹터인 것은 별개다. MCP 담당자는 Backend migration을 실행할 수 있지만 수정하지
않고, MCP 서버 runtime에는 DB·Redis 직접 접근 코드를 추가하지 않는다.

게임 컨텍스트 MCP 패키지는 예약 이름 `mcp_1`에서 `mafia_game`으로 변경했다
(2026-09-01, 사용자 승인). `mcp_2`는 용도 미정 예약 패키지로 유지하며 README의
Tour·Weather 설명은 과거 예약 명칭이다. 마피아 기능을 다른 예약 패키지와 섞지
않는다.

## 4. 사용자 화면과 전환

Streamlit 화면은 URL만으로 상태를 신뢰하지 않고 Backend가 반환한 현재 게임
상태를 기준으로 그린다. 새로 고침해도 `game_id`로 복구할 수 있어야 한다.

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

- 전체 인원 **6~9명** 선택, 기본값 6명
- 기본 규칙과 예상 역할 구성 표시
- AI 수는 자동으로 `전체 인원 - 1`
- 시작 시 Backend가 게임, 참가자·역할·시나리오와 개인 정보를 한 트랜잭션으로 생성

| 전체 인원 | 마피아 | 탐정 | 의사 | 시민 |
|---:|---:|---:|---:|---:|
| 6 | 1 | 1 | 1 | 3 |
| 7 | 1 | 1 | 1 | 4 |
| 8 | 2 | 1 | 1 | 4 |
| 9 | 2 | 1 | 1 | 5 |

역할은 인간에게도 완전 무작위 배정한다. Backend는 소유 사용자의 가장 최근
성공적으로 생성·commit된 게임과 같은 시나리오를 제외하고 나머지 중 하나를
seed로 선택한다. 생성 실패나 rollback은 직전 시나리오 기록을 바꾸지 않는다. 역할·
시나리오·개인 정보 배정에 쓴 seed와 불변 시나리오 snapshot은 서버에 기록하되
일반 응답에는 노출하지 않는다. 게임 생성자는 소유자 메타정보만 가지며 별도의
플레이어 권한은 없다.

### 4.3 게임 진행

- 상단: 라운드, 현재 단계, 생존자 수, 저장 상태, 행동·투표 남은 시간
- 중앙: AI GM 안내, 공개 시나리오와 공개 대화 타임라인
- 하단: 자신의 역할·알리바이·관찰 정보와 현재 허용 행동(버튼형 턴제)
- 사이드 패널: 생존 참가자, 공개된 사망자와 메모
- `저장하고 나가기`와 마지막 자동 저장 시각

낮 토론은 좌석순 기본 1순환이며 각 발언은 200자 이하이다. 전원이 `PASS`하면
Backend의 고정 GM 질문 뒤 추가 1순환만 허용한다. 실제 3~4분 자유 채팅 타이머는
두지 않는다. 밤 행동은 20초, 일반·재·최종 투표는 30초의 서버 권위 deadline을
사용한다. 인간이 탈락하면 PUBLIC 정보만 보는 관전 상태로 전환하며 `AI 진행 보기`와
`결과까지 빠르게 진행`을 제공한다.

### 4.4 불러오기와 결과

불러오기 화면에는 본인 소유의 `IN_PROGRESS` 또는 `PAUSED` 저장본만 표시한다.
생성일, 마지막 저장일, 라운드와 생존 인원을 보여 주며 Backend가 소유권과
snapshot version을 다시 확인한다.

결과 화면에는 승리 진영과 종료 사유, 시나리오, 전체 역할, 밤 공격·보호·조사,
일반·재·최종 투표의 검증된 주요 기록, 인간의 생존 여부와 투표 적중률을 표시한다.
AI의 내부 추론 전문은 저장하거나 공개하지 않고 공개 판단 근거 요약만 제공한다.
게임 종료 전에는 아직 공개되지 않은 역할과 개인 정보를 절대 반환하지 않는다.

## 5. 관리자 화면

관리자 앱은 일반 사용자용 내부 HMAC 서명을 관리자 권한으로 재사용하지 않는다.
OIDC 사용자와 DB의 명시적 관리자 role을 Backend가 함께 확인한 뒤 읽기 권한을
부여한다.

### 5.1 KPI 대시보드

- 오늘/7일/30일 신규 게임 수와 완주율
- 평균 게임 시간과 평균 라운드 수, 저장 후 재개율
- 인원수별 시민/마피아 승률, 인간 역할별 승률과 첫날 탈락률
- 시나리오별 선택·완주율, 평균 밤 수, 최종 지목 도달률과 진영별 승률
- 역할별 수동/timeout 자동 선택 횟수와 deadline 경합 실패율
- LLM 성공률, timeout률, fallback률, 평균 응답 시간
- 게임당 평균 token 사용량과 추정 비용
- 피드백 평균 점수와 미처리 건수

### 5.2 로그와 피드백

로그는 기간, trace id, game id, user id 해시, 심각도와 이벤트 유형으로
필터한다. 에이전트 오류, MCP 거부, 상태 전이 충돌과 저장 실패를 우선
조회한다. 전체 prompt, 비공개 역할 목록과 비밀정보는 노출하지 않고 민감
필드를 제거한 요약만 보관한다.

피드백은 별점, 분류, 내용, game id, 작성일과 처리 상태를 가진다. 분류는
`재미`, `AI 품질`, `규칙 오류`, `성능`, `기타`, 상태는 `NEW`, `REVIEWING`,
`RESOLVED`, `WONT_FIX`로 시작한다. MVP 관리자는 조회와 상태 변경만 할 수 있다.

## 6. 게임 규칙과 상태 머신

### 6.1 역할

| 역할 | 진영 | 밤 행동 | 승리 조건 |
|---|---|---|---|
| 마피아 | 마피아 | 자신을 제외한 생존자 1명 공격 선택 | 마피아 수가 비마피아 생존자 수 이상 |
| 탐정 | 시민 | 자신을 제외한 생존자 1명의 마피아 여부 조사 | 모든 마피아 제거 |
| 의사 | 시민 | 생존자 1명 보호 | 모든 마피아 제거 |
| 시민 | 시민 | 없음 | 모든 마피아 제거 |

- 탐정 조사 결과는 `마피아` 또는 `마피아가 아닙니다`로만 전달하고 정확한
  역할명은 알려주지 않는다.
- 의사는 자기 보호와 연속 동일 대상 보호를 허용한다. 자동 선택에서는 자신을
  제외하며 보호 성공 여부는 직접 알려주지 않는다.
- 마피아가 2명이면 서로의 정체를 모르며 서로 공격하거나 투표할 수 있다.
  팀원·진영 공유 이벤트는 만들지 않는다.
- 같은 밤 두 마피아가 같은 대상을 고르면 그 대상을 공격한다. 서로 다른 대상을
  고르면 두 후보 중 하나를 저장된 seed로 결정한다. 한 명만 제출하면 그 선택만
  쓰고, 생존 마피아 모두가 마감될 때까지 제출하지 않으면 유효 대상 하나를
  Backend가 결정적으로 자동 선택한다.
- 모든 밤 행동은 행동 수집 시작 시 생존했던 역할이 동시에 수행한 것으로 본다.
  같은 밤 공격받은 탐정의 조사와 의사의 보호도 유효하며, 판정 뒤 다음 단계부터
  사망 상태를 적용한다.
- 규칙은 `mystery-v1`, 시나리오 카탈로그는 `scenario-v1`에 묶어 저장본 복구 중
  바뀌지 않게 한다.

### 6.2 상태 전이

`CREATED`와 `PAUSED`는 게임 세션 lifecycle 상태이며 Phase enum이 아니다. 실제
진행 Phase는 아래 `ROLE_REVEAL`부터 `FINISHED`까지의 12개 값만 사용한다.

```text
CREATED
  → ROLE_REVEAL
  → DAY_ANNOUNCEMENT(round=0, 시나리오 공개)
  → DAY_DISCUSSION(round=0, 첫날 무투표)
  → NIGHT_ACTION(round=1..5)
  → NIGHT_RESOLUTION
  → DAY_ANNOUNCEMENT
       ├─ 표준 승패 확정 → FINISHED
       ├─ round=1..4 → DAY_DISCUSSION → DAY_VOTE → VOTE_RESOLUTION
       │                              ├─ 동률 → DAY_REVOTE → VOTE_RESOLUTION
       │                              ├─ 승패 확정 → FINISHED
       │                              └─ 승패 미확정 → 다음 NIGHT_ACTION
       └─ round=5, 승패 미확정
          → FINAL_DISCUSSION → FINAL_VOTE → FINAL_RESOLUTION → FINISHED
```

요청에는 `expected_version`과 idempotency key를 포함한다. Backend는 게임별
lock에서 소유권·상태·version·행동을 검증하고, event append와 snapshot 저장을
완료한 뒤에만 Redis cache와 event stream을 갱신한다. 이전 version 요청은
`409`로 응답한다. 밤 해소와 아침 공개 이벤트, 표준 승패 판정은 한 트랜잭션에서
확정해 사망 발표가 빠진 채 게임만 종료되지 않게 한다.

`round`는 첫 `NIGHT_ACTION` 진입 시 1이 되는 현재 밤 식별자다. 해당 밤의 완료
횟수는 `NIGHT_RESOLUTION` commit으로만 인정하고, 재시도·재개는 같은 round를
유지한다. 다음 `NIGHT_ACTION`에 진입할 때만 최대 5까지 증가시킨다.

### 6.3 진행 예산과 deadline

- 낮 토론은 좌석순 기본 1순환이다. 생존자는 200자 이하로 `SPEAK`하거나
  `PASS`한다. 전원이 `PASS`한 경우 Backend의 고정 질문을 공개한 뒤 추가
  1순환만 진행하고 종료한다. AI GM이 자의적으로 토론을 연장하거나 끝내지 않는다.
- 밤 행동 deadline은 20초이며 10초가 남으면 경고한다.
- 일반·재·최종 투표 deadline은 모두 30초이며 15초와 5초가 남으면 경고한다.
- `phase_deadline_at`은 Backend 시각의 절대 UTC 값이다. 마감과 사용자 제출이
  경합하면 게임 lock과 `state_version` 비교로 하나만 확정한다. 자동 선택 결과와
  `AUTO_TIMEOUT` 사유는 이벤트에 저장해 새로 고침·재접속으로 다시 뽑지 않는다.
- 명시적 `SAVE_AND_EXIT`는 안전 지점에서 남은 시간을 snapshot에 저장하고 deadline을
  비운다. 재개 시 남은 시간으로 새 deadline을 계산한다. 단순 네트워크 단절은 이미
  시작된 deadline을 되돌리지 않으며, 다음 timer sweep 또는 요청에서 만료를 해소한다.
- PostgreSQL의 `next_wakeup_at`과 짧은 worker lease가 timer·AI turn scheduler의
  원본이다. Redis deadline index는 재구성 가능한 가속 데이터다. 다중 Backend
  worker는 lease와 version CAS로 하나만 해소하고, 재시작 시 overdue deadline과
  연결 없는 AI turn도 다시 claim한다. `PAUSED` 상태에는 wakeup을 두지 않는다.

### 6.4 밤·아침 처리

밤에는 마피아 공격, 의사 보호, 탐정 조사를 수집한 뒤 공격과 보호가 같으면
사망을 취소한다. 탐정 결과는 해당 탐정의 PRIVATE 이벤트로만 저장한다. 의사는
선택 접수만 확인하고 보호 성공 여부는 받지 않는다. AI GM은 Backend가 확정한
사망자 또는 `NO_DEATH` 공개 이벤트만 전달받고 보호 대상·조사 결과·전체 역할표를
조회하지 않는다.

밤 사망자의 이름과 생존 상태는 공개하지만 역할은 공개하지 않는다. 밤 처리 뒤
생존 마피아가 0명이면 시민 승리, 생존 마피아 수가 생존 비마피아 수 이상이면
마피아 승리다.

### 6.5 투표와 최종 지목

- 첫날 낮에는 처형 투표를 하지 않는다.
- 투표 중 개별 선택은 비공개로 유지하고 해소 후 후보별 득표 집계만 공개한다.
- 살아 있는 다른 플레이어 중 한 명에게 투표하며 자기 자신에게는 투표할 수 없다.
- 최다 득표자가 처형되고 처형된 플레이어의 역할은 공개한다.
- **최다 득표 동률이면 동점자만 대상으로 재투표를 1회 진행하고, 재투표에서도
  동률이면 처형하지 않는다.**
- 처형된 플레이어는 이후 대화와 투표에 참여하지 않는다.
- 투표 무응답자는 자신을 제외한 유효 생존자 중 하나에 Backend가 결정적으로
  자동 투표한다. 재투표는 동점 후보만 유효 대상으로 한다.
- 5번째 밤 공개 뒤 표준 승패가 나지 않으면 `FINAL_ACCUSATION`을 시작한다.
  이는 새 Phase enum 값이 아니라 `FINAL_DISCUSSION → FINAL_VOTE →
  FINAL_RESOLUTION` 세 Phase를 묶어 부르는 게임 규칙 이름이다.
  최종 투표의 최고 득표 후보가 마피아이면 남은 마피아 수와 관계없이 시민이,
  비마피아이면 마피아가 승리한다. 최종 동률은 동점 후보 중 하나를 저장된 seed로
  선택한다. 이는 게임 길이를 제한하기 위한 `mystery-v1`의 명시적 급사 예외다.

### 6.6 `scenario-v1` 계약

- 정전된 방송국, 눈 내리는 산장, 폐관 직전의 박물관, 호텔 만찬의 마지막 손님,
  멈춰 선 야간열차 다섯 개를 검증된 정적 카탈로그로 등록한다.
- 공개 데이터는 id·version·제목·사건 배경·피해자·장소 목록·게임 목표뿐이다. 각 플레이어의
  알리바이와 관찰 정보는 해당 플레이어의 PRIVATE 데이터다.
- 각 시나리오는 9좌석까지 쓸 수 있는 짧은 알리바이·관찰 template을 가지며,
  Backend가 현재 참가자 ID를 바인딩한다. 관찰 대상은 자기 자신이 아니고 실제
  참가자여야 하며, 모든 문구는 역할을 직접 누설하거나 서로 모순되지 않아야 한다.
- 현재 시나리오 문서의 문장은 방향 예시이므로 Backend WU-B2에서 시나리오별
  알리바이 9개와 관찰 9개, 총 최소 90개 template record를 작성한다. 제품 담당자의
  역할 중립성·무모순 검수 전에는 `scenario-v1` 콘텐츠 완료로 보지 않는다.
- 알리바이는 검증된 사실이 아니라 각 플레이어가 일관되게 사용할 주장이다.
  관찰 정보는 여러 해석이 가능한 배경 사실이며 그것만으로 마피아가 확정되지 않는다.
- 2명의 마피아는 사건에 독립적으로 연루된 잠복 범죄자이지만 서로의 정체를 모른다.
  주범·공범 등급과 진영 공유 정보는 두지 않는다.
- 소유 사용자의 가장 최근 성공적으로 생성·commit된 게임 `scenario_id` 하나만
  후보에서 제외한다. 생성 실패나 rollback은 직전 기록을 바꾸지 않는다.
  전역 직전 게임을 사용하지 않으며, 같은 사용자 동시 생성은 PostgreSQL
  transaction-scoped 사용자별 advisory lock 안에서 직전 성공 게임 조회·선택·게임
  insert를 함께 commit해 직렬화한다. Redis TTL lock은 이 원자성에 사용하지 않는다.
  선택 결과와 scenario snapshot은 생성 시 확정한다.

## 7. 에이전트 설계

**플레이어 에이전트**는 자신의 승리 조건에 맞게 발언, 밤 행동과 투표를
선택한다. 각 에이전트의 모델 호출, 메시지 배열, 세션, 메모리 네임스페이스,
MCP 연결과 Tool 권한을 분리한다. 하나의 모델 호출에서 여러 에이전트를 동시에
연기하는 방식은 금지한다.

**AI GM**은 규칙 엔진이 만든 공개 결과와 `scenario-v1`의 공개 배경만 자연어로
전달하고 발언 순서를 안내한다. 전체 snapshot, 숨겨진 역할, 비공개 행동·조사
결과를 조회하거나 상태를 직접 변경하지 않는다. 사건 진실을 새로 만들거나
모순을 정답처럼 판정하는 추리극 해설은 후속 확장이다.

**Agent Manager**(`backend/app/agent/`)는 Backend 내부에서 에이전트 컨텍스트,
LLM/MCP 호출, timeout, 재시도, fallback과 사용량 기록을 조정한다.

### 7.1 시스템 프롬프트 2계층 분리

각 AI 에이전트의 시스템 프롬프트는 두 계층으로 분리한다.

**공통 제약 프롬프트(변경 불가):** 모든 에이전트에 동일하게 적용한다.

- 제공된 MCP Resource와 Tool만 사용한다.
- 게임 상태를 직접 변경할 수 없고 현재 노출된 Tool만 호출한다.
- 자신의 역할과 게임 정보는 MCP 서버가 제공한 값만 신뢰한다.
- 다른 에이전트의 프롬프트, 비공개 정보, 메모리를 요청하지 않는다.
- 게임 규칙과 Tool 권한은 개성 프롬프트보다 우선한다.
- 자신의 `agent_id`를 변경하거나 다른 에이전트를 가장하지 않는다.

**개성 프롬프트(운영자 수정 가능):** 말투, 어휘, 감정 표현, 공격성, 거짓말
방식, 증거 평가 방식, 발언 빈도, 투표 성향 등만 설정한다. 게임 룰, 역할별
권한, 페이즈, Tool 목록, 접근 권한, 승리 조건은 변경할 수 없다.

프롬프트 우선순위: 공통 제약 → 엔진 제공 게임 정보 → MCP 계약 → 개성
프롬프트 → 공개 대화. 충돌하면 게임 규칙이 항상 우선한다.

### 7.2 페르소나 파라미터

모든 수치 값은 0.0~1.0이며 API schema와 도메인 양쪽에서 검증한다.

| 파라미터 | 의미 |
|---|---|
| `sociability` | 발언 빈도와 대화 참여도 |
| `assertiveness` | 주장을 강하게 표현하는 정도 |
| `suspicion` | 작은 모순도 의심하는 정도 |
| `deception` | 마피아일 때 거짓 정보를 사용하는 정도 |
| `risk_tolerance` | 불확실한 대상에게 행동하는 정도 |
| `memory_recall` | 과거 발언과 투표를 활용하는 정도 |
| `reasoning_skill` | 증거를 연결하는 수준. `mystery-v1`에서는 모든 AI에 같은 값 고정 |
| `emotionality` | 압박에 반응하는 표현 강도 |
| `cooperativeness` | 타인의 의견을 수용하는 정도 |
| `verbosity` | 한 번에 말하는 길이 |

문자열은 `display_name`, `speech_style`, `backstory`로 제한하고 길이와 허용
문자를 검증한다. MVP는 서버 등록 프리셋을 무작위 배정하되 정보 접근 범위와
`reasoning_skill`은 동일하게 고정한다. 말투, 감정 표현, 발언 빈도와 마피아의
기만 표현만 달리해 규칙 밸런스와 모델 성능 차이를 섞지 않는다.

### 7.3 입력 컨텍스트와 구조화 출력

각 에이전트에는 다음만 전달한다.

```text
공통 정보: mystery-v1 규칙, scenario-v1 공개 배경, 현재 라운드·단계,
          생존자 목록, 공개 발언·투표 집계·사망 결과
개인 정보: 자신의 role·알리바이·관찰 정보·생존 상태, persona,
          자기 private event·메모리, 현재 허용 action과 deadline
```

다른 참가자의 role, 다른 탐정의 조사 결과, 보호 대상, random seed, 전체 게임
상태 객체, 엔진 내부 로그는 전달하지 않는다. 공개 채팅의 명령문은 시스템
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

### 7.4 실패 fallback

| 실패 | MVP fallback |
|---|---|
| AI 발언 timeout | 해당 발언 건너뛰기 |
| AI 투표·밤 행동 실패 | 역할별 timeout 규칙에 따른 결정적 유효 후보 선택 |
| AI GM 문장 실패 | 규칙 엔진의 고정 한국어 템플릿 |
| MCP 조회 실패 | 검증된 snapshot을 같은 audience allowlist로 재투영한 최소 컨텍스트만 사용 |
| Redis 장애 | 새 agent turn 중단, PostgreSQL 원본 보존 |
| LLM 공급자 전체 장애 | 발언은 `PASS`, 밤·투표는 결정적 자동 선택으로 deadline 안에 계속 진행 |

fallback도 raw snapshot이나 전체 상태 객체를 Agent·AI GM에 전달하지 않는다.
checksum·event sequence를 검증한 snapshot을 Backend가 `PUBLIC` 또는 현재 actor의
`PRIVATE` audience로 다시 투영하며, AI GM에는 `PUBLIC`만 허용한다. 이 경로도
카나리·비간섭성 테스트를 통과해야 한다. 내부 오류나 자격정보는 사용자에게
표시하지 않고 관리자 로그에만 기록한다.

## 8. 게임 컨텍스트 MCP 서버 (`mcp_server/mafia_game`)

MCP는 규칙 엔진을 대신하지 않고 에이전트가 허용된 컨텍스트를 읽고 제한된
행동을 **제안**하는 표준 경계다. MCP 서버는 게임 상태의 최종 판정자가 아니며
최종 유효성은 항상 Backend 게임 엔진 코드가 판정한다.

### 8.1 식별자와 세션 규칙

- Backend가 `game_id`, `agent_id`, phase, `state_version`, 만료 시각 기준으로
  짧은 수명 capability를 발급하고 허용 목록 밖의 호출을 거부한다. phase 또는
  version이 바뀌면 기존 capability를 폐기하고 새 agent turn용으로 다시 발급한다.
- Agent Manager는 매 agent turn의 MCP 세션 bootstrap을 별도 HMAC으로 인증한다.
  개발 환경은 loopback HTTP만 허용하고 운영 환경은 인증서가 검증되는 TLS를
  강제한다. Front용·Engine API용 secret을 bootstrap에 재사용하지 않는다.
- `MAFIA_MCP_URL`은 `/mcp`를 포함한 전체 endpoint이며 Backend client가 경로를
  추가로 붙이지 않는다.
- `agent_id`는 인증된 MCP 연결 생성 시 서버가 고정한다. 에이전트가 Tool 입력으로
  `actor_id`, `agent_id`, `session_id`를 보내지 않는다.
- 다른 `agent_id`를 지정할 수 있는 API를 제공하지 않는다. `me`는 연결된
  세션 기준으로 해석한다.
- phase·version 변경, actor 사망, 저장 게임 재개와 프로세스 재시작 시 새로운
  `session_id`와 capability를 발급하거나 해당 actor 세션을 폐기하고 이전 값을 거부한다.
- 메모리 네임스페이스는 `{game_id}/{agent_id}`로 강제한다.

### 8.2 Resources

| URI | 내용 |
|---|---|
| `mafia://rules/mystery-v1` | 현재 규칙, 역할, 페이즈·deadline과 승리 조건 |
| `mafia://scenarios/scenario-v1/{scenario_id}` | 현재 게임에 확정된 시나리오의 공개 필드 |
| `mafia://games/{game_id}/public-state` | 공개 시나리오, 페이즈, 라운드, deadline, 생존자·사망자 |
| `mafia://games/{game_id}/public-timeline` | 공개 사건과 발언 기록 |
| `mafia://games/{game_id}/agents/me` | 자기 정보(역할, 생존, 표시명) |
| `mafia://games/{game_id}/agents/me/private-state` | 자기 알리바이·관찰·private event·메모리 |
| `mafia://games/{game_id}/agents/me/allowed-actions` | 현재 허용 행동과 유효 대상 |
| `mafia://personas/{persona_id}` | 검증된 페르소나 설정 |

### 8.3 Tools

| Tool | 용도 | 주요 검증 |
|---|---|---|
| `game.speak` | 공개 발언 제안 | 생존, 발언 페이즈·차례, 길이, 안전 정책 |
| `game.vote` | 낮 투표 제안 | 투표 페이즈, 생존자, 유효 대상, 자기 투표 금지 |
| `game.kill` | 마피아 공격 대상 제안 | 마피아 역할, 밤 페이즈, 생존 대상, 중복 |
| `game.investigate` | 탐정 조사 제안 | 탐정 역할, 밤 페이즈, 자기 제외 유효 대상, 중복 |
| `game.protect` | 의사 보호 제안 | 의사 역할, 밤 페이즈, 유효 대상 |
| `game.pass` | 현재 발언 차례의 명시적 `PASS` 제안 | 토론 페이즈·현재 턴 소유 여부 |

- Tool은 상태를 직접 변경하지 않고 Game Service가 검증할 **행동 제안**을
  반환한다. 실제 event append와 상태 전이는 Backend 트랜잭션에서만 수행한다.
- `game.kill`이 호출되어도 실제 공격 대상과 사망 여부는 엔진이 blind-mafia
  집계·보호 규칙을 계산해 결정한다. 조사 결과는 호출 탐정에게만 비공개로 반환한다.
- 역할·페이즈별로 필요한 Tool만 노출하되, **노출 제한만으로 권한 검사를
  끝내지 않고** 호출 시마다 엔진이 game/session/agent/생존/역할/페이즈/대상/
  중복을 다시 검증한다(이중 검증).

### 8.4 감사 로그

모든 Resource 조회와 Tool 호출은 고정 `audit_id`, producer `instance_id`,
`request_id`, `game_id`, `actor_player_id_hash`, `session_id_hash`, 작업 유형·이름,
허용 여부, 결과 event id, 시각으로 기록한다. 결과 event id와 audit id는 구분한다.
Backend가 처리한 `/context`·`/actions`는 같은 트랜잭션의 감사/outbox 기록으로
남긴다. MCP가 Engine 호출 전에 거부한 입력은 전용 내부 audit sink로 민감정보를
제거한 요약만 전달한다. audit sink 일시 실패는 이미 확정된 게임 행동을 되돌리지
않고 bounded retry 대상으로 남기며, 재시도 실패는 로컬 보안 로그와 운영 경고로
격상한다. MCP runtime은 이 목적으로 DB·Redis에 직접 접근하지 않는다. 감사 로그와
retry 상태는 AI 에이전트가 조회할 수 없다.

## 9. 데이터 모델

PostgreSQL을 영구 원본으로 사용한다. 검색·무결성 필드는 열로, 규칙별 확장
데이터는 검증된 JSONB로 둔다. schema는 `backend/migrations/`에 다음 번호의
순방향 SQL로 Backend 섹터가 추가한다. PostgreSQL 인스턴스와 DB 구축, 해당
migration의 실제 실행·재실행 검증은 MCP 섹터가 담당한다.

| 테이블 | 주요 필드 | 목적 |
|---|---|---|
| `game_sessions` | id, owner_user_id, creation_order, status, phase, round, winner, finish_reason, player_count, ruleset/scenario version·snapshot, random_seed, phase_deadline_at, paused_remaining_ms, next_wakeup_at, worker lease, state_version, timestamps | 게임 헤더·생성 순서·고정 시나리오·deadline scheduler 원본 |
| `game_players` | id, game_id, user_id nullable, kind, seat, display_name, role, private_profile, alive, eliminated_by/round, persona_id, timestamps | 참가자와 비공개 역할·구조화 알리바이/관찰 |
| `game_events` | id, game_id, sequence, type, visibility, audience_player_id, payload, created_at | append-only 게임 기록 |
| `game_snapshots` | game_id, version, state, checksum, last_event_sequence, created_at | 빠른 저장·검증 복구 |
| `game_command_receipts` | game/requester/operation/idempotency key, request_hash, 최초 status·response, committed_event_id, created_at | Redis·재시작과 무관한 영구 멱등 원본 |
| `agent_personas` | id, version, name, parameters, active | 버전 고정 페르소나 |
| `agent_runs` | id, game_id, player_id, phase, status, latency_ms, token_usage, model_code, error_code | 품질·비용 지표 |
| `user_feedback` | id, user_id, game_id nullable, rating, category, content, status, timestamps | 사용자 의견 |
| `user_roles` | user_id, role, granted_at | 명시적 관리자 권한 |
| `audit_logs` | id, trace_id, source_instance_id/audit_id/payload_hash, actor_type/id_hash, action, target, allowed, metadata, created_at | 관리자·보안·MCP 감사와 receipt 멱등 원본 |
| `audit_outbox` | id, audit_id, source, source_instance_id, sanitized_payload, status, attempts, next_attempt_at, created_at, delivered_at | `(source, source_instance_id, audit_id)` 멱등 감사와 유한 재시도 |

이벤트 공개 범위(visibility)는 세 가지로 분리한다.

- `PUBLIC`: 모든 참가자 (공개 발언, 투표 집계, 사망 발표, 페이즈 전환, 종료)
- `PRIVATE`: 지정 플레이어 (역할·알리바이·관찰 배정, 조사 결과, 행동 접수 결과)
- `SYSTEM`: 엔진 전용 (전체 역할표, 야간 행동 원본, seed, deadline 판정,
  감사 재시도와 내부 오류)

진영은 `role`에서 엔진 내부적으로 파생하며 플레이어별 `faction`을 별도 저장하거나
응답·event 필드로 직렬화하지 않는다. `winner` 같은 종료 진영 값은 SYSTEM 판정 뒤
게임 종료 결과에서만 공개한다.

중요 사용자 행동과 phase 종료 직후 자동 저장한다. `저장하고 나가기`는 agent
run이 끝난 안전 지점에서 `PAUSED`로 전환한다. checksum·schema·ruleset/scenario
version 중 하나라도 일치하지 않는 snapshot은 복구 입력으로 사용하지 않는다.
이전의 검증된 snapshot부터 재생하고, 그것도 없으면 genesis event부터 전체
재생한다. 재생 결과와 마지막 event sequence를
검증한 뒤에만 새 snapshot으로 채택한다. 검증 후 채택된 발언과 행동만 원본으로
저장한다.

## 10. Redis 사용

| Key/채널 | 용도 | TTL |
|---|---|---:|
| `team4:game:{game_id}:lock` | 중복 턴 방지 | 30초, 갱신 가능 |
| `team4:game:{game_id}:runtime` | snapshot 읽기 cache | 30분 |
| `team4:game:{game_id}:events` | Frontend 갱신 Stream | 소비 후 정리 |
| `team4:idempotency:{user_id}:{key}` | 명령 재전송 방지 | 24시간 |
| `team4:agent:{run_id}:status` | LLM/MCP 진행 상태 | 15분 |
| `team4:capability:{token_hash}` | phase·version 범위와 폐기 상태 | capability 만료 이내 |
| `team4:rate:{user_id}` | 생성·LLM 호출 제한 | 정책별 |

lock token 소유자만 lock을 해제한다. LLM·MCP 외부 호출 동안 게임 lock을 잡고
있지 않는다. 짧은 lock 안에서 입력 snapshot·version과 agent-turn reservation을
확정하고 해제한 뒤 외부 호출을 수행하며, 다시 lock을 얻어 version·deadline·
capability를 검증하고 CAS commit한다. stale 결과는 폐기하거나 규칙 fallback으로
대체한다. DB commit 전에 cache를 성공으로 갱신하지 않으며 Redis는 영구 게임
원본으로 사용하지 않는다. 기존 identity API의 `request_id`도 짧은 TTL의 재전송
차단 키로 확장한다. Redis client·key·TTL·lock 의미는 Backend 코드 계약이고,
Redis 인스턴스 구축·기동·health 확인은 MCP 섹터 운영 책임이다.
게임 명령·resume·Engine proposal의 최종 멱등 원본은 PostgreSQL
`game_command_receipts`다. Redis idempotency key는 24시간 조회 가속일 뿐이며,
만료·flush·프로세스 재시작 뒤에도 같은 key와 request hash에는 최초 결과만 반환한다.

## 11. Backend API

게임 API는 OIDC에서 연결된 내부 사용자를 검증하고 요청 body의 `user_id`는
권한 근거로 신뢰하지 않는다. 기존 공통 오류와 trace id 계약
(`code`, `message`, `details`, `trace_id`)을 유지한다.

### 사용자 API

| Method | Endpoint | 용도 |
|---|---|---|
| `POST` | `/api/v1/games` | 인원수와 ruleset으로 새 게임 생성 |
| `GET` | `/api/v1/games?status=saved` | 본인의 저장 게임 목록 |
| `POST` | `/api/v1/games/{game_id}/resume` | 저장본 검증·deadline 재발급 뒤 재개 |
| `GET` | `/api/v1/games/{game_id}` | 권한에 맞게 필터한 현재 상태 |
| `POST` | `/api/v1/games/{game_id}/commands` | 행동, 투표, 저장, 빠른 진행 |
| `GET` | `/api/v1/games/{game_id}/events` | SSE 진행 이벤트 구독 |
| `GET` | `/api/v1/games/{game_id}/result` | 종료 게임 결과 |
| `POST` | `/api/v1/feedback` | 별점과 정규화한 내용 저장 |

명령 요청 예시:

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
`ADMIN_ACCESS_DENIED`로 시작한다. 없거나 소유하지 않은 게임은 같은 응답으로
처리한다.

## 12. 보안·운영 경계

- 기존 HMAC은 서버 간 무결성 수단이지 사용자·관리자 권한 증명이 아니다.
- MVP 게임 API는 신뢰된 Streamlit 서버의 HMAC과 서명 body/header의 내부
  `acting_user_id`를 함께 검증하고 모든 조회에서 활성 사용자·소유권을 재검사한다.
  브라우저가 Backend를 직접 호출하는 단계에서는 짧은 수명 access token으로 교체한다.
- 관리자 권한은 DB의 명시적 role과 공급자 identity를 함께 확인한다.
- 사용자 발언, 피드백, LLM/MCP 결과는 검증하고 HTML 렌더링 전에 escape한다.
- MCP 서버·tool·resource는 allowlist와 game/agent capability를 확인한다.
- prompt injection 문자열은 명령이 아닌 데이터로 전달한다.
- 비밀정보, 전체 prompt, chain-of-thought와 다른 참가자 private 정보를
  로그에 남기지 않는다.
- 모델·prompt·persona·ruleset 버전을 기록해 장애를 재현한다.
- 비용·속도 제한을 사용자, 게임, agent run 단위로 적용한다.
- 자유 채팅의 사용자 입력과 AI 출력에 최소 안전 필터를 적용한다.
- 명시적 `SAVE_AND_EXIT`는 게임을 `PAUSED`로 저장하고 재접속 시 기존 역할·좌석과
  남은 deadline으로 이어간다. 단순 연결 손실은 토론 단계에서는 상태를 보존하지만,
  이미 시작된 밤·투표 deadline은 되돌리지 않는다. MVP에서 인간 좌석을 AI로
  자동 교체하지 않는다.

### 12.1 컨텍스트 격리 검증

- 모델 호출 전 컨텍스트에 현재 `agent_id`의 개인 정보만 포함되었는지,
  다른 에이전트의 역할·메모리·다른 게임 이벤트가 없는지 검사한다.
- 비간섭성 테스트: 다른 에이전트의 비공개 상태만 바뀌었을 때 현재
  에이전트의 Resource와 모델 입력이 동일해야 한다.
- 테스트 환경에서는 에이전트별 고유 카나리 값을 비공개 컨텍스트에 넣고,
  다른 에이전트의 입력·출력·Resource·메모리에서 발견되면 유출로 판정한다.

## 13. Agent Manager 실행 흐름

```text
사용자 명령 또는 phase 시작
  → 게임별 Redis lock 획득
  → PostgreSQL 최신 version 확인
  → 규칙 엔진이 허용 행동·대상·deadline 계산
  → 최소 컨텍스트·agent-turn reservation 확정
  → phase/version/deadline 범위 capability 발급
  → 입력 snapshot version 기록 후 lock 해제
  → MCP/LLM 구조화 결정 요청 (게임 lock 밖)
  → schema·규칙·안전 정책 검증
  → 실패 시 교정 1회 또는 fallback
  → 게임별 lock 재획득
  → version·deadline·capability 재검증
  → CAS game event append + snapshot commit
  → Redis cache/event stream 갱신
  → 사용한 capability 폐기 + lock 해제
  → Frontend에 새 version 전달
```

독립적인 밤 행동은 동시에 요청할 수 있지만 DB 반영은 게임별 lock 안에서 한
번에 처리한다. 낮 대화는 이전 발언이 다음 에이전트 컨텍스트에 포함되므로
좌석 순서대로 진행한다. AI GM은 공개 event가 확정된 뒤 호출한다. 기본 LLM
timeout 15초는 호출별 상한일 뿐 전체 deadline 보장이 아니다. Agent Manager는
Backend 절대 deadline에서 네트워크·검증·CAS commit용 최소 3초를 먼저 예약하고,
각 MCP·LLM timeout을 설정 상한·남은 전체 외부 예산·deadline 중 가장 짧은 값으로
줄인다. LLM 직전에는 commit reserve뿐 아니라 뒤이어 필요한 MCP action 호출
상한도 먼저 뺀다.
reserve 이하이면 외부 호출과 교정을 생략하고 즉시 결정적 fallback을 commit한다.
구조화 응답 교정 1회도 이 예산 안에서 끝낼 수 있을 때만 허용하며, 늦게 도착한
결과는 version·deadline CAS에서 폐기한다.

## 14. 구현 단계

### 0단계: 계약 고정 (완료 사항 반영)

- `mystery-v1`: 6~9명 역할표, 탐정, blind mafia, 첫날 무처형 낮,
  의사 자기·연속 보호, 재투표 1회 후 무처형, 최대 5밤과 최종 지목 확정
- `scenario-v1`: 경량 시나리오 5종, 결정적 개인 정보 배정, 사용자별 직전
  생성 시나리오 제외 확정
- 텍스트 토론은 좌석순 1순환(+전원 PASS 시 추가 1순환), 밤 20초·투표 30초
  서버 deadline의 하이브리드 진행 확정
- LLM 공급자 OpenAI·Gemini 이중 지원, `LLM_PROVIDER`로 선택
- 게임 MCP는 `mcp_server/mafia_game`에 배치
- 사용자 게임 API는 Streamlit 서버 HMAC + `acting_user_id` 재검증 방식으로 확정
- 남은 결정: 게임당 비용 상한과 저장본 보존 기간

### 1단계: LLM 없는 규칙 엔진

- `backend/app/models/`에 게임 도메인과 상태 머신
- 결정적 역할 배정, 첫날 낮, blind-mafia 공격 집계, 밤 동시 처리
- 일반·재·최종 투표, 표준 승패와 `FINAL_ACCUSATION` 경계 테스트
- fake agent로 6~9명 전 구성 자동 완주 테스트

### 2단계: 시나리오 엔진

- `scenario-v1` 정적 카탈로그 5종과 schema 검증
- 6~9명별 알리바이·관찰 정보 결정적 배정과 관찰 대상 무결성 검사
- 사용자별 직전 생성 시나리오 제외의 동시 생성 테스트
- 역할·다른 플레이어의 비공개 정보를 유추시키지 않는 카나리 테스트

### 3단계: DB·Redis 저장과 deadline

- Backend: `backend/migrations/`의 순방향 SQL, `repositories/` 저장소,
  event append, optimistic version, 검증 snapshot 저장·genesis 복구 구현
- Backend: `infrastructure/redis/`의 client, lock, idempotency와 실행 상태 구현
- Backend: fake clock 기반 deadline, 자동 행동, 일시정지·재개와 재시작 복구
- MCP: PostgreSQL·`Team4_Proj` DB에 DDL 전용 migrator role과 DML 최소 권한
  runtime role을 분리하고 Redis 인스턴스를 구축·기동
- MCP: Backend migration 수신 뒤 migrator URL로 실행·재실행하고 runtime role의
  불필요한 DDL 권한 부재와 Backend 연결·Redis health 확인
- 공동: deadline 경합, Redis 장애, 동시 명령 충돌과 PostgreSQL 원본 보존 검증

### 4단계: 사용자 화면과 API

- `routers/`·`schemas/`·`services/`에 게임 API
- `frontend_user/app_pages/`에 홈, 생성, 진행, 저장 목록, 결과 페이지
- SSE 또는 짧은 polling으로 agent 상태·서버 시각·deadline 표시와 경고
- 오류별 재시도·복구 안내

### 5단계: 플레이어/AI GM과 MCP

- persona preset과 분리된 private memory
- `llm/client.py`에 OpenAI·Gemini 구조화 client, 제한 시간, 비용 기록
- `mcp_server/mafia_game`에 게임 MCP resource/tool, `backend/app/mcp/`에
  turn별 session bootstrap과 phase/version capability 정책
- audit sink·재시도, JSON 오류, timeout, 정보 누설(카나리), prompt injection 테스트

### 6단계: 관리자와 관측성

- 관리자 인증/권한과 관리자 API
- `frontend_admin/app_pages/`에 KPI, 로그, 피드백 화면
- trace id로 요청부터 agent run까지 연결
- 비용·오류율 알림 기준

### 7단계: 알파 검증

- 6~9명별 heuristic bot 100회 이상, 가능하면 1,000회 규칙 시뮬레이션
- 진영·역할별 승률과 게임 길이 분석
- 재미, AI 자연스러움, 억울한 탈락 피드백 수집
- 실제 LLM은 비용 승인된 소수 표본으로만 검증하고 규칙 회귀에는 호출하지 않음
- 6·7명 시민 우세, 8명 마피아 증가, 무제한 보호와 최종 지목 영향을 각각
  하나씩만 조정하며 비교

## 15. 테스트와 완료 기준

필수 자동 테스트: 6~9명 역할 배정, 시나리오·개인 정보 결정성과 무결성,
blind-mafia 정보 비간섭성, 첫날 무처형, 의사·탐정·마피아 동시 밤 처리,
일반·재·최종 투표와 승패 경계, deadline 제출/timeout 경합, 저장·재개 시 남은
시간, 손상 snapshot 배제와 genesis replay, optimistic lock, idempotency,
Redis lock, capability 갱신·폐기, MCP session bootstrap, 감사 재시도, 게임
소유권, 관리자 권한, 에이전트 정보 누설(카나리·비간섭성), LLM/MCP 실패
fallback, 입력 escape와 민감 로그 제거.

통합 테스트는 생성 → 역할·시나리오 확인 → 첫날 낮 → 밤 → 일반·재투표 →
저장·재개 → 다섯째 밤 최종 지목 → 결과 흐름과 관리자 KPI 집계를 synthetic
데이터, fake clock과 fake LLM/MCP로 검증한다. 유료 LLM을 기본 회귀나 대량
밸런스 테스트에서 호출하지 않는다.

MVP 완료 조건:

- 로그인한 사용자 한 명이 6~9명 게임을 생성·완주한다.
- `scenario-v1` 다섯 시나리오와 개인 정보가 재현 가능하게 배정된다.
- AI마다 서로 다른 표현 persona가 적용되되 추론 능력·정보 권한은 같다.
- 네 역할의 행동, 투표와 승패는 규칙 엔진으로 동작한다.
- 프로세스 재시작 후 저장 게임을 이어 할 수 있다.
- 인간 탈락 후 관전 또는 빠른 진행으로 결과를 확인한다.
- LLM/MCP 실패가 게임 상태를 훼손하지 않는다.
- 관리자만 KPI, 정제된 로그와 피드백을 조회한다.
- 소유권, 비공개 역할과 관리자 권한 거부 경로가 테스트된다.
- MCP 섹터가 분리된 migrator/runtime DB 권한, PostgreSQL migration 재실행과
  Redis health를 확인하고 Backend가 동일 환경에서 persistence·lock smoke를 통과한다.
- 6~9명별 heuristic bot 시뮬레이션 결과와 허용 편차를 기록하고 한 진영이 60%를
  넘으면 규칙 하나만 조정한 뒤 다시 검증한다.
- 전체 테스트, compileall과 lint가 통과하고 README가 구현과 일치한다.

## 16. 남은 결정 항목

1. 게임당 token·비용 상한
2. 저장본 보존 기간과 사용자 삭제 기능 제공 시점

진행 방식은 **발언 버튼형 턴제 + 밤·투표 deadline의 하이브리드**, 목표 플레이
시간은 10~15분으로 확정한다. 초기 저장본 보존 권장값은 30일이다.
