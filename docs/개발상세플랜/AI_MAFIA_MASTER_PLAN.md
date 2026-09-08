# AI 마피아 MVP 공통 마스터플랜

> **MVP 단순화 프로파일(2026-09-05):** DB·스키마·migration 이력은 보존한다.
> OAuth/OIDC·Front HMAC, custom MCP bootstrap/capability/nonce/session registry,
> Agent lease/fencing/job 상태 머신, LLM 비용·usage·자동 failover, Redis outbox
> publisher와 복잡한 reconnect/backoff는 신규 실행 경로의 요구사항에서 제외한다.
> 관련 migration 구조는 legacy 호환용으로만 남긴다.

**문서 상태:** 구현 목표 계약

**규칙 세트:** `mystery-v1`

**시나리오 팩:** `scenario-v1`

**최종 갱신:** 2026-09-03

이 문서는 AI 마피아 MVP의 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터
소유권과 작업 순서를 정의하는 공통 정본이다. 세부 계약은 다음 문서만 사용한다.

| 구분 | 정본 |
|---|---|
| 제품 범위·규칙·시나리오·작업 계획 | 이 문서 |
| PostgreSQL·Redis·transaction·migration | [AI_MAFIA_DB_DESIGN.md](AI_MAFIA_DB_DESIGN.md) |
| Front·Backend·MCP HTTP 계약 | [AI_MAFIA_API_SPEC.md](AI_MAFIA_API_SPEC.md) |
| 사용자·관리자 화면과 상태 전이 | [AI_MAFIA_SCREEN_FLOW.md](AI_MAFIA_SCREEN_FLOW.md) |
| 섹터 간 최소 연결 형식·독립 개발 규칙 | [AI_MAFIA_INDEPENDENT_CONTRACT.md](AI_MAFIA_INDEPENDENT_CONTRACT.md) |

MCP runtime의 구현 구조와 MCP·Data WU 실행 순서는
[AI_MAFIA_MCP_SERVER_DESIGN.md](AI_MAFIA_MCP_SERVER_DESIGN.md)가 구체화한다. 이
설계서는 구현 가이드이며 MCP Resource `data` field·enum·nullable 계약은 이 설계서가
아니라 API 명세 8.2절과 그 절이 명시적으로 참조하는 API 공통 모델만 정본으로
사용한다.

이 문서들은 아직 구현되지 않은 목표 상태를 포함한다. 현재 코드의 완료 범위는 루트
[README.md](../../README.md)를 기준으로 판정하며, 계획에 적혔다는 이유로 구현 완료로
간주하지 않는다. 계약을 변경할 때는 영향받는 정본 문서를 같은 변경에서 갱신한다.

### 현재 MVP FastMCP 프로파일

현재 전환 작업의 기준은 참고 프로젝트 수준의 얇은 FastMCP adapter다. MCP는 Agent가
사용하는 Resource·Prompt·Tool 컨텍스트를 제공하고, Tool 호출은 Backend로 전달한다.
행동 판정·게임 상태 변경·인증·권한·DB·Redis·LLM은 Backend가 소유한다. MCP 내부의
HMAC·bootstrap token·capability state machine·session registry·idle timeout·DELETE
cleanup은 현재 FastMCP 전환 범위에서 제외하며, 기존 상세 M2~M8 운영 프로파일은
후속 별도 WU로 취급한다. 현재 디렉터리 구조는 `mcp_server/mafia_game` 아래에서
유지한다.

## 2026-09-07 공개 기록 UI 개선 범위

사용자가 승인한 이번 단일 작업 단위는 WU-F6 공개 기록·결과 표현 개선이다.
기존 게임·관전 공통 타임라인을 채팅으로 표현하고 AI 처리 영역을 접을 수 있게 하며,
종료 결과의 마피아 선택 분산에 따른 RNG 사유를 표시한다. 기존 Front 파일만 사용하며
Backend 규칙·API·비공개 정보 공개 시점은 유지한다.

## 1. 확정 결정

### 1.1 사용자 식별

- Google OIDC, 이메일, 프로필, 로그인·로그아웃과 Front→Backend HMAC은 MVP에서
  제거한다.
- 브라우저가 첫 실행에 UUID v4 `user_id`를 생성해 same-origin local storage에
  보관한다. Front는 모든 사용자 API에 `X-User-Id`로 전달한다.
- UUID 형식만으로 사용자를 구분하며 이름, 이메일, OAuth subject와 비밀번호를
  수집하지 않는다.
- 사용자는 설정 화면에서 기존 UUID를 입력해 같은 브라우저의 식별자를 복구할 수
  있다. UUID는 비밀 자격증명이 아니므로 복구 기능을 계정 인증으로 표현하지 않는다.
- Backend는 UUID를 신뢰 가능한 인증 claim으로 취급하지 않는다. 최초 쓰기 요청에서
  최소 `users` 행을 멱등 생성하고, 모든 게임 소유권 검사는 전달된 UUID와 저장된
  `owner_user_id`의 일치만 확인한다.
- 이 방식은 사용자 가장을 막지 못한다. MVP 배포 범위는 개인 개발 환경 또는 접근이
  통제된 사설망으로 제한한다. 공개 인터넷 배포 전에 별도 인증 계약을 승인해야 한다.

### 1.2 관리자 경계

- 관리자 앱은 일반 사용자 앱과 별도 프로세스로 유지한다.
- `ADMIN_USER_IDS`에 등록된 UUID만 read-only 관리자 API를 호출할 수 있다.
- UUID allowlist도 강한 인증이 아니므로 관리자 기능은 loopback 또는 사설망에서만
  활성화한다. MVP 관리자 API에는 강제 종료, 데이터 수정·삭제 기능을 두지 않는다.

### 1.3 LLM 범위

- MVP는 한 번에 하나의 Provider만 선택한다. 자동 Provider failover는 구현하지 않는다.
- 앱 수준의 LLM timeout 설정, token 상한, token 사용량 저장·집계, 비용 저장·추정,
  예산 경보와 관련 KPI는 구현하지 않는다.
- Provider 오류, 잘못된 구조화 응답, Agent worker lease 만료 또는 게임 `deadline`까지
  결과가 확정되지 않은 경우 Backend 규칙 기반 fallback을 사용한다. 고정된 짧은
  worker lease는 중단된 작업의 소유권 회수 장치이며 사용자·운영자가 조정하는 LLM
  timeout 설정이나 측정 KPI가 아니다.
- API key, prompt 원문, 비공개 컨텍스트, raw model response와 내부 chain-of-thought는
  저장하거나 로그에 남기지 않는다.

### 1.3.1 AI 진행 표시와 운영 로그 (2026-09-07)

이번 사용자 요청의 단일 작업 단위는 **WU-B6 발언·투표 장애 수정과 판단 표시 연결**이다.
Backend의 Provider·proposal 검증·fallback과 기존 Front game shell의 해당 상태 표시,
관련 테스트·정본·README만 포함한다. 새 파일·DB migration·MCP runtime 변경은 없다.
기존 섹터 소유권은 유지하며 이번 요청에 명시된 Backend/Front 연결 범위를 함께 수정한다.
발언은 역할·공개 대화·본인에게 허용된 정보로 질문 또는 주장을 만들도록 요청하고,
대상 행동은 첫 후보로 조용히 보정하지 않는다. 잘못된 행동·대상은 한 번 교정한 뒤
실패로 구분하며, fallback은 게임·window·actor별 결정적 선택으로 좌석 편향을 없앤다.
OpenAI 추론 모델은 높은(high) reasoning effort와 최종 JSON을 위한 여유를 사용하고
미완성·인증·요청 제한·모델 접근 오류를 비밀정보 없는 코드로 구분한다.
공개 판단 근거는 자유 문자열 대신 API 2.4.1절의 제한된 근거 코드만 표시한다.

후속 요청의 단일 WU-B6 보완은 기존 orchestrator의 역할·페르소나 프롬프트와
사용자가 함께 요청한 기존 결과 화면의 대비 수정에 한정한다. 새로운 파일,
Resource schema, DB migration과 역할 판정 규칙은 추가하지 않는다.

대화 이력에 따른 후속 WU-B6 조정은 기존 persona seed의 수치와 이를 해석하는
프롬프트에 한정한다. 승패·투표 실행 경로는 읽기 전용으로 검토한다. `reasoning_skill`
0.5와 정보 권한은 유지하고 과거 발언 활용·주장·위험 감수·협력 성향을 보강한다.
재실행 가능한 기존 seed의 persona 구간과 해당 게임 DB의 등록 preset 5건을 함께
갱신하며, 원본 parameters 비교 후 같은 transaction에서 content_hash도 갱신한다.

사용자가 추가 요청한 토큰·Redis 보완도 WU-B6의 context 전달 범위에 포함한다.
기존 `infrastructure/redis/cache.py`에 전체 공개 대화 캐시를 두고 Backend 읽기·Agent
context에 연결한다. PostgreSQL은 영구 원본이며 비공개 context는 Redis에 쓰지 않는다.
`LLM_MAX_OUTPUT_TOKENS`를 실제 Agent 요청에 연결하고 기본값을 8192로 상향한다.
고정 15초 lease와 대사 200자 제한은 유지한다. 새 파일·DB migration은 추가하지 않는다.

후속 병렬 투표 요청은 WU-B6의 투표 scheduler·proposal 적용 경계를 보완한다.
사용자 제출과 무관하게 투표 window가 열리면 모든 미제출 AI의 판단을 병렬로 시작하고,
완료된 표부터 각각 저장한다. 한 AI의 실패·지연은 다른 AI의 유효 표를 폐기하지 않는다.
투표 polling은 발언·밤 LLM 호출과 분리하고 window 변경 시 즉시 깨운다. 미해소 AI 표는
공개 버전·event를 바꾸지 않는다. 인간의 같은 window 첫 투표로만 증가한 한 버전은
원장으로 증명한 경우에만 진행 중 AI 판단에 허용한다. 저장·재개·다른 window·마감은
이 예외에 포함하지 않으며 공개 사용자 command의 strict version 검증도 유지한다.
사용자가 요청한 조사·해결 기록은 `docs/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md`에
별도 문서로 남긴다. 실행 코드의 파일·디렉터리 구조와 DB schema는 추가하지 않는다.

- Front는 각 AI의 공개 발언 처리 단계와 확정 행동을 짧게 표시한다. 판단 요약은
  검증된 처리 상태와 행동에서 만든 고정 안내이며 모델의 내부 사고 원문이 아니다.
- 밤에는 actor별 진행·역할·대상·응답 수를 공개하지 않고 공통 비공개 단계 안내만
  표시한다. 투표 대상과 개별 표는 종료 전 표시하지 않는다.
- Backend 터미널과 순환 파일 로그는 같은 순서 번호, 실행 식별자, UTC 시각,
  game_id, phase, state_version과 허용된 처리 상태를 사용한다. 성공 적용 로그는
  transaction 성공 반환 뒤 기록하며 실패·대체·중복을 구분한다.
- 비공개 밤 actor와 대상, prompt, 자유 형식 rationale, 응답 원문, 예외 원문은 로그에
  넣지 않는다. 임의 외부 문자열 대신 검증된 enum과 고정 한국어 설명을 사용한다.
- UI용 상태는 게임별 크기가 제한된 프로세스 메모리다. 재시작 후 이전 실행의
  상태는 복원하지 않으며 확정 공개 이력은 기존 PostgreSQL event에서 복원한다.
- WU-B6는 `backend/app/agent/activity.py`, `backend/tests/test_agent_activity.py`,
  기존 core logging·Agent orchestrator·runtime 연결을 소유한다. 로그 출력 경로
  `backend/logs/game-progress.log`와 순환 파일은 실행 산출물이며 Git에서 제외한다.
  WU-F3는 기존 game shell에 API 2.4.1절의 상태 표시만 추가한다.

### 1.4 계약 단순화

- 게임 시작은 생성과 분리한 명시적 `BEGIN_GAME` command다.
- 모든 게임 변경은 하나의 discriminated-union command endpoint를 사용한다.
- Front가 호출하는 모든 공개 변경 `POST`는 UUID `Idempotency-Key`를 사용하고, 현재
  게임을 바꾸는 command는 추가로 `expected_state_version`을 사용한다. 내부 Agent
  proposal은 body의 `proposal_id`, MCP 세션 개설 토큰(bootstrap token)은 일회성 nonce
  원장을 사용한다.
- 동기화는 `operations` envelope 하나를 polling과 SSE가 함께 사용한다.
- 사용자 개인 메모, 수동 작성 note, 공개 채팅 자유 입력은 MVP에 포함하지 않는다.
- OpenAPI 별도 수기 파일을 관리하지 않는다. FastAPI가 생성하는 `/openapi.json`을
  구현 계약 검증에 사용한다.

### 1.5 섹터별 독립 개발과 자체 목데이터

- 세 섹터는 정본 문서의 예시와 필드·enum·오류코드를 기준으로 각자 필요한
  목데이터와 테스트 픽스처를 작성할 수 있다. 공통 fixture 파일이나 mock server를
  모든 섹터가 먼저 공동 작성해야만 개발을 시작할 수 있는 것은 아니다.
- Front는 Backend가 아직 구현되지 않은 동안 snapshot, sync operation, 오류 응답과
  SSE frame을 자체 fixture로 만들어 화면·상태 reducer를 검증한다. Backend의 DB·Redis,
  MCP와 직접 연결하는 mock을 Front 저장소에 두지 않는다.
- Backend는 Front와 MCP가 없어도 규칙 엔진, repository, 공개 API와 내부 API를
  synthetic 요청으로 검증한다. 외부 Provider와 MCP는 fake transport 또는 고정 응답으로
  대체하며 실제 비밀값·유료 API를 테스트에 사용하지 않는다.
- MCP는 Backend가 없어도 정본의 세션 개설 토큰, session, Resource, Tool과 Engine API
  request/response 예시를 사용해 자체 fake Engine transport로 검증한다. MCP runtime은
  DB·Redis용 목 연결을 추가하더라도 실제 runtime 경계를 우회하지 않는다.
- 자체 fixture의 작성 위치와 구현 방법은 섹터 담당자가 정하되, 정본에 없는 필드·enum·
  오류코드·상태 전이를 임의로 계약에 추가하지 않는다. 예시만으로 결정할 수 없는
  항목은 구현 전에 영향받는 정본과 WU를 갱신한다.
- 섹터 간 통합 시에는 각자의 fixture가 아니라 Backend가 제공하는 `/openapi.json`,
  API 정본, DB·Redis 정본과 MCP 계약을 최종 기준으로 삼는다. 통합 중 불일치가
  발견되면 코드를 먼저 맞추지 않고 영향받는 정본과 계약 테스트를 함께 갱신한다.
- 독립 개발은 계약을 임의로 분기하는 권한이 아니다. 공개 API, 내부 Engine API,
  MCP wire, DB schema 또는 화면 상태 소유권을 바꾸는 경우에는 영향받는 정본을 먼저
  갱신하고 세 섹터가 합의한 뒤 구현한다.

## 2. MVP 목표와 범위

AI GM이 진행하는 대화형 마피아 추리게임이다. 인간 사용자는 항상 한 명이며 나머지
좌석은 AI 에이전트가 담당한다. 복잡한 사건 해결보다 대화, 의심, 역할 행동과 투표에
집중한다.

### 2.1 포함 범위

- 6~9명 게임과 역할 무작위 배정
- 인간 1명과 AI 플레이어 5~8명
- 정적 시나리오 5종과 좌석별 알리바이·관찰 정보
- 턴 기반 낮 대화, 밤 행동, 처형 투표, 재투표와 최종 지목
- 저장·재개, 새로고침 복구, 사용자 사망 후 관전과 빠른 진행
- 공개 이벤트와 사용자 본인에게 허용된 비공개 정보
- AI 플레이어 페르소나, AI GM, MCP Resource·Tool 경계
- 일반 피드백과 게임별 피드백
- 사설망 전용 read-only 관리자 모니터링

### 2.2 제외 범위

- OAuth/OIDC, 비밀번호, 이메일 계정, 프로필과 사용자 역할 테이블
- 멀티 인간 플레이, 매치메이킹, 초대, 실시간 사람 간 채팅
- 마피아 전용 대화, 마피아 상호 인지와 공동 공격 채널
- 과금, 아이템, 랭킹, 소셜 기능, 모바일 네이티브 앱
- 사용자가 작성하는 게임 note
- 런타임 LLM 시나리오 생성과 LLM의 규칙 판정
- Provider 자동 failover와 LLM timeout·token·비용 운영 기능
- 공개 인터넷에서의 안전한 관리자 기능

## 3. 게임 규칙

### 3.1 인원과 역할

| 전체 인원 | 마피아 | 탐정 | 의사 | 시민 |
|---:|---:|---:|---:|---:|
| 6명 | 1명 | 1명 | 1명 | 3명 |
| 7명 | 1명 | 1명 | 1명 | 4명 |
| 8명 | 2명 | 1명 | 1명 | 4명 |
| 9명 | 2명 | 1명 | 1명 | 5명 |

- 역할 ID는 `MAFIA`, `DETECTIVE`, `DOCTOR`, `CITIZEN`이다.
- 역할은 Backend가 암호학적으로 안전하게 생성한 게임 seed와 결정적 RNG로 배정한다.
- 인간 사용자의 역할도 다른 좌석과 같은 방식으로 무작위 배정한다.
- 방 생성자는 소유자일 뿐 게임 안에서 별도 권한을 갖지 않는다.
- 마피아가 두 명이어도 서로의 정체, 선택과 응답 여부를 알 수 없다.
- 탐정과 의사는 시민 진영이다.

### 3.2 공개 정보와 비공개 정보

| 공개 정보 | 본인에게만 공개하는 정보 |
|---|---|
| 시나리오 제목·배경·피해자·장소 | 자신의 역할 |
| 현장 플레이어와 시작 마피아 수 | 한 문장 알리바이와 한 문장 관찰 정보 |
| 현재 단계·round·생존자 | 자신의 조사 결과 또는 보호 선택 |
| 공개 발언·사망자·처형 공개 역할 | 자신에게 허용된 private event |
| 해소된 투표의 후보별 득표수 | 게임 종료 전 개별 투표·밤 행동 |

밤 사망자의 역할은 게임 종료 전 공개하지 않는다. 처형된 플레이어의 역할은 즉시
공개한다. 게임 종료 후 전체 역할, 공격·보호·조사·개별 투표와 주요 대화 로그를
공개할 수 있지만 내부 chain-of-thought는 공개하지 않는다.

### 3.3 상태와 round

```text
ROLE_REVEAL
  -> DAY_DISCUSSION(day=1, round=0)
  -> NIGHT_ACTION(round=1)
  -> NIGHT_RESOLUTION
  -> DAY_DISCUSSION(day=2, round=1)
  -> DAY_VOTE -> REVOTE(필요한 경우)
  -> NIGHT_ACTION(round=2)
  -> ...
  -> NIGHT_ACTION(round=5)
  -> FINAL_DISCUSSION -> FINAL_ACCUSATION(표준 승패가 없을 때)
  -> ENDED
```

- 게임 생성 직후 `status=IN_PROGRESS`, `phase=ROLE_REVEAL`, `round=0`,
  `state_version=1`이다.
- `BEGIN_GAME`이 첫날 낮 토론을 연다.
- `round`는 밤 번호다. 첫 `NIGHT_ACTION` 진입 때 1이 되고 최대 5다.
- `NIGHT_RESOLUTION`은 Backend transaction 안의 내부 전이이며 Front는 확정된
  공개 이벤트를 통해 아침 결과를 표시한다.
- 승패는 밤·처형 결과를 commit한 직후 판정한다. 화면 표시가 승패를 다시 판정하지
  않는다.

### 3.4 첫날 낮

- AI GM이 고정 공개 사건 정보를 설명한다.
- 생존자 전원이 좌석순으로 `SPEAK` 또는 `PASS`를 정확히 한 번 제출한다.
- `SPEAK` 본문은 공백 정규화 후 1~200자다.
- 첫 순환이 끝나면 발언 내용과 관계없이 첫날 밤으로 이동한다.

> 현재 가장 의심되는 플레이어와 그 이유를 한 문장으로 말해 주세요.

- 첫 순환 종료 후 응답 수와 관계없이 첫날 밤으로 이동한다.
- 첫날에는 처형 투표나 의심도 투표를 하지 않는다.

게임 시작 안내에는 다음 문장을 사용한다.

> 사건이 발생한 뒤, 현장에 있던 사람들은 범인을 찾기 위해 서로를 추궁하기 시작했습니다. 그러나 범인은 자신의 정체가 드러나는 것을 막기 위해 밤마다 다른 플레이어를 제거하려 합니다.

### 3.5 밤 행동

- 서버 기준 입력 시간은 20초이며 Backend의 `deadline_at`만 판정 권한을 갖는다.
- 마피아는 자신을 제외한 생존자 한 명을 공격 대상으로 선택한다.
- 탐정은 자신을 제외한 생존자 한 명을 조사한다.
- 의사는 자신을 포함한 생존자 한 명을 보호한다. 횟수와 연속 보호 제한은 없다.
- 밤 시작 시점의 생존 상태로 행동 자격을 고정하고 첫 유효 제출 후 변경하지 않는다.
- 탐정·의사 무응답은 자신을 제외한 유효 후보 중 결정적으로 자동 선택한다.
- 마피아 한 명만 응답하면 그 선택만 사용한다. 전원이 무응답이면 마피아를 제외한
  생존자 중 한 명을 진영 단위로 한 번 자동 선택한다.
- 마피아 둘이 같은 대상을 선택하면 그 대상을 공격한다. 다른 대상을 선택하면 두
  제출 대상 중 한 명을 결정적 RNG로 선택한다.
- 보호, 공격, 조사는 하나의 transaction에서 동시에 확정한다. 같은 밤 공격받아
  사망할 탐정의 조사와 의사의 보호도 유효하다.
- 보호 대상과 공격 대상이 같으면 사망자가 없다. 의사에게 보호 성공 여부를 별도로
  알려주지 않는다.
- 조사 결과는 `마피아` 또는 `마피아가 아닙니다`만 탐정 본인에게 공개한다.
- 자동 선택과 RNG 결과를 저장하여 재시도·재접속으로 다시 추첨하지 않는다.

### 3.6 아침과 이후 낮

- AI GM은 Backend가 확정한 공개 이벤트만 자연어로 설명한다.
- 사망자가 있으면 이름만 공개하고 역할은 숨긴다.
- 사망자는 이후 발언, 투표와 역할 행동을 제출할 수 없다.
- 둘째 날부터 낮 토론은 첫날과 같은 기본 한 순환, 전원 `PASS` 시 추가 한 순환이다.
- 별도의 3~4분 자유 토론이나 AI GM 재량의 연장·종료 단계는 없다.
- 토론 뒤 30초 처형 투표를 연다.

### 3.7 투표

- 모든 생존자는 자신을 제외한 유효 생존자 한 명을 선택한다.
- 기권과 복수 선택은 허용하지 않으며 첫 유효 제출 후 변경하지 않는다.
- 일반 투표, 재투표와 최종 지목은 각각 서버 기준 30초다.
- AI는 window 시작부터 동시에 판단하고 완료된 표를 즉시 개별 제출한다. 인간의
  첫 표를 기다리지 않으며, 생존자 전원 제출 또는 마감에서만 결과를 해소한다.
- 마감까지 미제출한 플레이어의 표는 유효 후보 중 결정적으로 자동 선택한다.
- 진행 중 개별 선택과 현재 득표수는 공개하지 않는다.
- 해소 후 후보별 최종 득표수와 탈락 결과만 공개한다. 누가 누구에게 투표했는지와
  자동 선택 여부는 게임 종료 전 숨긴다.
- 최다 득표자가 여러 명이면 그 후보만 대상으로 재투표한다.
- 재투표도 동률이면 그날은 아무도 탈락하지 않는다.
- 처형된 플레이어의 역할은 즉시 공개하고 Backend가 승패를 판정한다.

### 3.8 승리와 최대 다섯 번째 밤

- 생존 마피아가 0명이면 시민 진영 승리다.
- 생존 마피아 수가 생존 비마피아 수 이상이면 마피아 진영 승리다.
- 다섯 번째 밤까지 표준 승패가 없으면 마지막 아침 결과 뒤 최종 발언 한 순환과
  `FINAL_ACCUSATION`을 진행한다.
- 최종 지목 전에 다음 문장을 공개한다.

> 이번 투표는 마지막 판정 투표입니다. 마피아를 찾으면 시민이 승리하고, 시민을 선택하면 마피아가 승리합니다.

- 최종 지목 최다 득표 대상이 마피아이면 시민 승리, 비마피아이면 마피아 승리다.
- 최종 지목 동률은 재투표하지 않고 동률 후보 중 한 명을 결정적 RNG로 선택한다.
- 최종 판정 직후 대상 역할과 전체 역할을 공개한다.

### 3.9 저장·재개·관전

- `SAVE_AND_EXIT`은 window 해소 transaction이 실행 중이지 않은 안정 상태에서만
  성공한다. timed action window는 남은 시간을 snapshot에 저장하고, 발언처럼
  deadline이 없는 상태는 남은 시간 없이 저장한다. 열린 `deadline_at`을 비운 뒤
  `status=SAVED`로 바꾼다.
- `RESUME`은 timed window에 저장된 남은 시간이 있을 때만 새 서버 `deadline_at`을
  계산한다. untimed 발언 window는 deadline 없이 복원하고 `ROLE_REVEAL`처럼 window가
  없던 상태는 `action_window=null`을 유지한다. 역할, 좌석, 시나리오, 이미 확정한
  결과와 RNG 결과를 다시 선택하지 않는다.
- 단순 새로고침·네트워크 단절은 서버 deadline을 멈추지 않는다.
- 인간이 사망하면 관전 모드로 전환한다. 공개 상태와 이미 허용됐던 본인의 역할·개인
  정보만 읽을 수 있다. 발언, 투표와 밤 행동 command는 Backend가 거부한다.
- 인간 사망 뒤에도 AI 게임은 계속된다. `FAST_FORWARD`와 `SAVE_AND_EXIT`은 관전자가
  계속 사용할 수 있다. 빠른 진행 상태는 game에 저장하며 남은 AI 행동을 규칙
  기반으로 진행하되 이미 확정된 deadline·결과를 변경하지 않는다.

## 4. 시나리오 계약

### 4.1 공통 원칙

- `scenario-v1`은 사전에 작성하고 제품 검수한 정적 카탈로그다.
- 피해자는 게임 시작 전에 사망했으며 모든 플레이어가 현장에 있었다.
- 정적 시나리오에는 특정 좌석으로 고정된 범인이 없다. 역할 배정 뒤 마피아가 사건의
  독립 연루자가 된다.
- 마피아가 둘이어도 사전 공모를 전제하지 않는다.
- 목표는 범행 방법·동기를 맞히는 것이 아니라 마피아를 찾는 것이다.
- 각 좌석에는 한 문장 알리바이와 한 문장 관찰 정보를 정확히 하나씩 배정한다.
- 같은 version, scenario ID, seed, 인원과 좌석에는 항상 같은 배치가 나온다.
- LLM은 카탈로그 사실과 개인 정보를 추가하거나 변경할 수 없다.

### 4.2 시나리오 카탈로그

| ID | 제목 | 사건 배경 | 피해자 | 장소 | 문장 방향 예시 |
|---|---|---|---|---|---|
| `BLACKOUT_STUDIO` | 정전된 방송국 | 생방송 준비 중 정전된 방송국에서 PD가 사망했다. | 생방송 PD | 스튜디오, 조정실, 분장실, 대기실, 장비실 | 조정실에서 장비를 확인했다. 정전 직전 장비실 쪽으로 이동하는 사람을 봤다. |
| `SNOWBOUND_LODGE` | 눈 내리는 산장 | 폭설로 고립된 산장에서 관리인이 약병 사건으로 사망했다. | 산장 관리인 | 거실, 주방, 복도, 관리인 방, 창고 | 거실에서 사람들과 이야기했다. 관리인 방에서 나오는 사람을 봤다. |
| `CLOSING_MUSEUM` | 폐관 직전의 박물관 | 폐관 직전 박물관에서 전시 담당자가 사망했다. | 전시 담당자 | 중앙 전시장, 보안실, 안내 데스크, 복원실, 직원 휴게실 | 안내 방송 때 안내 데스크에 있었다. 보안실 근처의 다툼을 들었다. |
| `LAST_BANQUET_GUEST` | 호텔 만찬의 마지막 손님 | 비공개 호텔 만찬 도중 주최자가 사망했다. | 만찬 주최자 | 연회장, 주방, 로비, 복도, VIP룸 | 연회장에서 식사했다. 누군가 주최자와 대화한 뒤 급히 나갔다. |
| `STOPPED_NIGHT_TRAIN` | 멈춰 선 야간열차 | 열차가 터널에 멈춘 사이 승무원이 사망했다. | 열차 승무원 | 승무원실, 객차, 식당칸, 연결 통로, 화물칸 | 정차 당시 좌석에 있었다. 연결 통로에서 승무원실로 이동하는 사람을 봤다. |

표의 문장은 콘텐츠 방향 예시이며 배포용 전체 레코드가 아니다. `WU-B2`에서
시나리오별 알리바이 9개와 관찰 9개, 전체 최소 90개 template record를 작성한다.
관찰 대상은 명시적 좌석 placeholder 또는 익명 표식으로 저장한다.

### 4.3 정적 검수 게이트

- 6~9명 모든 구성에서 좌석별 알리바이·관찰 정보가 하나씩 배정된다.
- 같은 입력은 같은 결과를 내며 다른 게임의 비공개 정보가 섞이지 않는다.
- 문장만으로 역할이나 범인을 확정할 수 없다.
- 마피아 상호 인지나 공모를 암시하지 않는다.
- 공개 배경, 장소와 개인 문장 사이에 논리적 모순이 없다.
- 정확한 분 단위 시각과 복잡한 이동 경로를 사용하지 않는다.
- 역할 중립성·무모순·배치 결과를 제품 담당자가 승인해야 `scenario-v1` 완료다.

### 4.4 선택 규칙

- 사용자가 직전에 성공적으로 생성한 게임의 시나리오는 다음 새 게임 후보에서 뺀다.
- 첫 게임에는 제외 대상이 없다.
- 후보 중 하나를 게임 seed로 결정적으로 선택한다.
- 사용자 단위 PostgreSQL advisory transaction lock으로 동시 생성을 직렬화한다.
- 저장 게임·재접속은 저장된 scenario와 배치 snapshot을 재사용한다.
- MVP는 직전 scenario 하나만 조회하며 추천 알고리즘이나 별도 전체 사용 이력을 두지
  않는다.

## 5. AI 플레이어와 GM

### 5.1 권한

- Backend 규칙 엔진만 전체 상태와 최종 판정 권한을 가진다.
- AI player는 MCP로 허용된 자기 컨텍스트를 읽고 행동 proposal만 제출한다.
- MCP 서버는 DB·Redis에 직접 접근하지 않고 Backend 내부 Engine API만 호출한다.
- AI GM은 MCP의 `public`, `gm-guide` Resource로 `PUBLIC` audience 확정 이벤트와 고정
  안내만 읽는다. 행동 Tool은 없으며 생성한 narration은 LLM adapter가 Backend Agent
  Manager에 직접 반환한다.
- 공개 대화 속 명령문은 신뢰할 수 없는 데이터로 취급한다.

### 5.2 프롬프트와 출력

프롬프트 우선순위는 공통 제약, 엔진 제공 정보, MCP 계약, 페르소나, 공개 대화
순서다. 공통 제약은 에이전트가 자신의 `agent_id`를 바꾸거나 다른 참여자의 정보와
도구를 요청하지 못하게 한다.

AI player 구조화 출력은 `SPEAK`, `PASS`, `NIGHT_ACTION`, `VOTE` proposal 중 현재
단계에서 허용된 한 종류만 받는다. Backend는 대상, 생존 상태, 역할, 단계, 글자 수와
`state_version`을 다시 검증한다. AI GM의 `GM_NARRATION`은 MCP Tool이나 proposal
endpoint를 거치지 않고 Agent Manager가 guide reference, 공개 정보 범위, 길이와
fencing 조건을 검증한 뒤에만 `PUBLIC` event로 반영한다. 잘못된 구조화 결과는 한 번
교정할 수 있고 계속 잘못되면 규칙 기반 fallback을 사용한다.

역할 활용 프롬프트는 `me.data.role`을 본인의 실제 역할로 고정한다. 탐정은
`INVESTIGATION_RESULT`가 있을 때 필요에 따라 탐정임을 밝히고 해당 라운드·대상의
마피아 여부를 발언할 수 있다. `is_mafia=false`는 의사·탐정·시민 중 특정 직업을
확정하지 않는다. 의사는 보호 선택을 활용하되 제공되지 않은 보호 성공을 단정하지
않는다. 시민은 역할 공개와 공개 진술 비교로 협력하며 조사 능력을 주장하지 않는다.
마피아는 정체를 숨기거나 시민 진영 역할로 위장할 수 있지만 없는 시스템 확정
조사 결과나 동료 마피아 정보를 인용하지 않는다. 공개 발언의 역할 주장은
서버 확정 role 변경이나 다른 player의 private 정보 자동 공개를 의미하지 않는다.

### 5.3 페르소나

매 발언에는 배정된 `speech_style`의 어미·문장 리듬과 `backstory`의 대화 태도를
반영한다. 숫자 parameters는 참여도·단정 강도·의심·기만 성향·위험 감수·기억 활용·
감정·협력·길이의 구체적인 표현 지침으로 바꾼다. 신중한 분석가는 유보적 근거 제시,
토론가는 직접적 질문·반론, 기록자는 앞선 발언 비교, 반응가는 감정적 반응,
조정자는 의견 연결로 구별한다. 직전 AI의 질문·문장 구조를 반복하지 않으며
페르소나 소개문을 매번 말하지 않는다. 200자 상한과 같은 추론 능력은 유지한다.

2026-09-07 산장 게임 이력에 따른 조정값은 아래와 같다. 기존 말투·기만·의심·감정·
발언 길이는 유지하며, 조정하지 않은 수치는 기존 seed 값을 사용한다.

| preset | sociability | assertiveness | memory_recall | risk_tolerance | cooperativeness |
|---|---:|---:|---:|---:|---:|
| CAUTIOUS_ANALYST | 0.60 | 0.65 | 0.95 | 0.55 | 0.75 |
| ACTIVE_DEBATER | 0.90 | 0.90 | 0.90 | 0.70 | 0.65 |
| OBSERVANT_NOTEKEEPER | 0.65 | 0.70 | 0.98 | 0.55 | 0.75 |
| EMOTIONAL_REACTOR | 0.70 | 0.75 | 0.90 | 0.65 | 0.70 |
| COOPERATIVE_MEDIATOR | 0.80 | 0.70 | 0.95 | 0.60 | 0.95 |

이미 모른다고 답한 시각·방향을 반복 요구하지 않으며 정보 부족과 진술 모순을
구별한다. 조사 주장은 확정 역할이 아니지만, 처형으로 앞선 조사가 맞았음이 확인되면
신뢰도를 높이고 해당 탐정의 비마피아 보고와 모순되는 의심에는 새 근거를 요구한다.
개별 투표는 공개 득표 합계로 복원할 수 없으며 본인의 과거 표도 context에 없으면
만들어 말하지 않는다. 최종 지목은 추가 질문의 기회가 아니라 마지막 선택임을 반영한다.

| 필드 | 범위와 의미 |
|---|---|
| `sociability` | 0.0~1.0, 발언 참여도 |
| `assertiveness` | 0.0~1.0, 주장 표현 강도 |
| `suspicion` | 0.0~1.0, 공개 모순을 의심하는 정도 |
| `deception` | 0.0~1.0, 마피아의 거짓 표현 경향 |
| `risk_tolerance` | 0.0~1.0, 불확실한 선택 경향 |
| `memory_recall` | 0.0~1.0, 공개 과거 정보를 활용하는 정도 |
| `reasoning_skill` | 모든 MVP preset에서 같은 중간 값 |
| `emotionality` | 0.0~1.0, 감정 표현 강도 |
| `cooperativeness` | 0.0~1.0, 타인의 주장 수용 경향 |
| `verbosity` | 0.0~1.0, 200자 범위 안의 발언 길이 경향 |

`display_name`, `speech_style`, `backstory`는 서버 등록 preset만 사용한다. 페르소나는
말투·감정·발언 성향을 바꿀 수 있지만 규칙, 정보 권한과 추론 능력을 바꿀 수 없다.

### 5.4 실패 처리

| 실패 | 결정적 처리 |
|---|---|
| AI 발언 생성 실패 | `PASS` |
| AI 밤 행동·투표 미확정 | 역할·투표의 자동 선택 규칙 |
| AI GM 생성 실패 | Backend 고정 한국어 안내 템플릿 |
| MCP 조회 실패 | 검증된 snapshot을 같은 audience allowlist로 재투영 |
| Redis 장애 | 새 Agent turn을 열지 않고 PostgreSQL 원본으로 복구 가능 상태 유지 |
| Provider 장애 | 자동 Provider 전환 없이 위 fallback으로 진행 |

Agent job은 reservation부터 최대 15초인 고정 lease와 fencing token을 가진다. timed
window의 남은 시간이 더 짧으면 그 deadline을 사용한다. lease가 끝난 job의 늦은
결과는 반영하지 않고 scheduler가 원자적으로 fallback 소유권을 획득한다. 사용자에게
보이는 발언 시간 제한을 추가하지 않으며 lease 값은 환경 설정이나 관리자 UI로
노출하지 않는다.

각 agent job은 새 capability, 일회성 세션 개설 토큰과 새 MCP session을 사용한다.
성공·fallback·stale·실패·lease 만료 뒤 세션 메모리와 capability를 폐기한다. 연결이
끊겨도 소비한 세션 개설 토큰, 기존 capability와 `Mcp-Session-Id`를 재사용하지 않으며,
살아 있는 같은 job을 재개할 수 있을 때만 새 세 값으로 연결한다. 이전 결과를 새
phase·window·`state_version`에 자동 재적용하지 않는다.

## 6. 시스템 아키텍처

```text
Browser
  -> frontend_user:8501 / frontend_admin:8502
  -> Backend FastAPI:8000
       -> PostgreSQL: 영구 원본과 transaction
       -> Redis: lock, cache, event fan-out
       -> Agent Manager
            -> 선택된 LLM Provider 한 개
            -> mafia_game MCP:8100/mcp
                 -> Backend internal Engine API
```

### 6.1 경계 원칙

- Frontend는 Backend 공개 API만 호출하고 DB·Redis·LLM·MCP에 접근하지 않는다.
- Backend는 DB schema, migration, repository, Redis key와 게임 판정을 소유한다.
- MCP 섹터는 PostgreSQL·Redis 실행 환경, 계정·권한, migration 실행과 health 확인을
  담당한다.
- MCP runtime은 Backend 내부 API만 호출하며 DB·Redis 자격증명을 받지 않는다.
- PostgreSQL `event_outbox`와 Redis fan-out publisher는 Backend가 소유한다. MCP
  runtime은 이 outbox를 읽거나 쓰지 않고 자체 영속 audit outbox도 만들지
  않는다.
- Backend→MCP 세션 개설 토큰 서명 secret과 MCP→Backend Engine HMAC secret은 서로
  다르다.
- Agent capability는 Backend가 발급·hash 저장하는 opaque random token이다. MCP는
  signing key 없이 전달만 하고 Backend가 현재 DB 상태와 함께 최종 검증한다.
- 외부 호출 중 PostgreSQL transaction이나 Redis game lock을 잡지 않는다.

## 7. 섹터 소유권

| 섹터 | 소유 | 소유하지 않음 |
|---|---|---|
| Front | `frontend_user`, `frontend_admin`, 화면 상태, API client, UUID local storage | 규칙 판정, DB·Redis, LLM·MCP 직접 호출 |
| Backend | `backend`, 공개·내부 API, engine, Agent Manager, schema·migration·repository, Redis application code | DB·Redis 프로세스 운영, 화면 렌더링 |
| MCP·Data | `mcp_server/mafia_game`, PostgreSQL·Redis 실행 환경, 계정·권한, migration·health runbook | schema 의미 변경, 게임 판정, DB 직접 읽는 MCP Tool |

공통 계약 변경은 구현보다 먼저 영향받는 정본 문서를 갱신하고 세 섹터가 API 예시,
오류 코드, schema version과 테스트 fixture를 함께 승인한다.

## 8. 작업 단위

`AGENTS.MD`에 따라 coding AI agent 한 세션은 아래 WU 한 개 이하만 수행한다. 한 WU의
신규 파일이나 책임이 바뀌면 먼저 이 절을 갱신한다.

2026-09-07 수정의 WU-F1 회귀 경계는 `frontend_user/tests/test_identity_f1.py`에
추가한다. WU-B4는 기존 `backend/app/models/game_state.py`의 순수 상태 필드
`revote_candidates`(UUID 집합, 기본 빈 집합)를 소유하며 재투표 진입·해소 때만
관리한다. DB 복원은 WU-B5에서 직전 확정 투표 원장을 기준으로 재구성한다.

### 8.1 Front

| WU | 범위 | 완료 기준 |
|---|---|---|
| `WU-F1` | OIDC·로그인·Front HMAC 제거, UUID 저장·복구 shell | 새 UUID와 복구 UUID가 `X-User-Id`로 전송됨 |
| `WU-F2` | 홈, 새 게임 설정, 저장 게임 목록 | loading·empty·error와 6~9명 검증 완료 |
| `WU-F3` | 역할 공개와 게임 공통 shell | refresh 후 snapshot으로 같은 private view 복구 |
| `WU-F4` | 낮 발언, 밤 행동, 투표 command UI | legal action과 deadline에 따른 제어·오류 처리 |
| `WU-F5` | polling/SSE 동기화와 reconnect | 같은 operations envelope를 중복 없이 적용 |
| `WU-F6` | 관전, 빠른 진행, 결과 공개 | 사망자 command 차단과 종료 공개 범위 검증 |
| `WU-F7` | 일반·게임별 피드백 | 종류별 validation과 게임당 한 건 처리 |
| `WU-F8` | read-only 관리자 앱 | UUID allowlist 거부·목록·상세·metrics 확인 |

### 8.2 Backend

| WU | 범위 | 완료 기준 |
|---|---|---|
| `WU-B1` | identity/OIDC API 제거와 UUID user context | identity route 미등록, UUID validation·소유권 테스트 |
| `WU-B2` | migration, seed data, scenario 90문장 | 재실행 가능한 migration과 정적 콘텐츠 승인 |
| `WU-B3` | repository, transaction, Redis lock/cache | concurrent create·command와 Redis 장애 테스트 |
| `WU-B4` | 순수 규칙 엔진과 결정적 RNG | 6~9명 규칙·동률·다섯째 밤 단위 테스트 |
| `WU-B5` | 공개 game·sync·feedback API | API 정본 success·reject·idempotency 테스트 |
| `WU-B6` | Agent Manager와 기존 LLM adapter 연결 | player proposal·GM 직접 반환 검증과 fallback, 유료 호출 없는 테스트 |
| `WU-B7` | 내부 Engine API, game event outbox와 SSE | capability/HMAC, revoke·현재 상태·projection provenance·cross-scope 의미 불변식, audience 격리·event ordering 테스트 |
| `WU-B8` | read-only 관리자 API와 audit, 관리자 센터 확장 및 기존 Front API 연결 | allowlist fail-closed, 비공개 응답 redaction, 직업별 AI 집계·피드백/감사 커서 조회·화면 연결 테스트 |
| `WU-B9` | 시뮬레이션·회귀·운영 보강 | 6~9명 heuristic bot 회귀와 장애 복구 검증 |
| `WU-B10` | 승인 운영 자료 검색과 근거 중심 관리자 도우미 | pgvector 혼합 검색, 답변·근거·신뢰도 응답, 질문 감사 기록, 자동 변경 차단 |

### 8.3 MCP Server·Data Infrastructure

| WU | 범위 | 완료 기준 |
|---|---|---|
| `WU-M1A` | PostgreSQL·Redis 실행 환경과 계정 준비 | DDL·DML 계정 분리와 health 확인 |
| `WU-M1B` | Backend migration 실행·재실행 | schema version과 최소 권한 검증 |
| `WU-M2` | MCP Streamable HTTP server와 세션 개설 인증 | job별 새 `/mcp` initialize·consume 성공과 재사용 거부 테스트 |
| `WU-M3` | session·capability와 Resource | 5개 schema, subject allowlist와 private context 비간섭성 검증 |
| `WU-M4` | Tool proposal와 Engine adapter | phase·target·동일 proposal replay 거부·재현 테스트 |
| `WU-M5` | MCP 구조화 감사 로그와 redaction | 영속 outbox 없이 허용 metadata만 기록하고 민감한 payload를 기록하지 않음을 검증 |
| `WU-M6` | Backend·MCP 통합 | DB 직접 접근 없이 실제 session 왕복 |
| `WU-M7` | 장애·재접속 검증 | stale capability, Engine 장애, fresh credential reconnect 처리 |
| `WU-M8` | 운영 runbook과 release evidence | 기동·중지·migration·health 절차 재현 |

WU-M5의 MCP 내부 로그 경계는 `mcp_server/mafia_game/ports/audit.py`,
검증·전달 정책은 `core/audit.py`, 독립 검증은
`mcp_server/tests/test_audit_logging.py`와 `test_audit_runtime.py`에 둔다.
기존 initialize·consume·Resource·Engine·teardown 경로에만 먼저 연결하고,
Tool 경로는 WU-M4 계약 정리 뒤 연결한다. 운영 sink와 보존 정책을 결정하지 않은
상태에서는 주입된 sink에만 허용 metadata를 전달하며 기본값은 기록 폐기다.
이 선행 구현은 OPEN-04 해소나 WU-M5 전체 완료를 뜻하지 않는다.

## 9. 체크포인트

| CP | 선행 조건 | 통과 증거 |
|---|---|---|
| `CP-0` 계약 고정 | 정본 문서 승인 | 링크·용어·schema 예시 일치, 섹터별 자체 fixture 작성 기준 합의 |
| `CP-1` 기반 정리 | F1, B1, M1A | UUID-only 요청과 인프라 health |
| `CP-2` 데이터 | B2, B3, M1B | migration 재실행, transaction·lock 테스트 |
| `CP-3` 게임 엔진 | B4 | 규칙·결정성·불변식 회귀 |
| `CP-4` Agent·MCP | B6, B7, M2~M6 | audience 비간섭성과 fallback E2E |
| `CP-5` 사용자 흐름 | F2~F7, B5 | 생성부터 저장·재개·종료·피드백 E2E |
| `CP-6` 운영 | F8, B8, B9, B10, M7~M8 | 관리자 거부 경로, 장애 복구, 근거 검색 경계, runbook |

`WU-M1A -> WU-B2 migration 산출물 -> WU-M1B -> CP-2` 순서를 지킨다. MCP 담당자는
Backend 소유 migration SQL을 수정하지 않는다.

## 10. 검증 전략

- 규칙 엔진은 seed 고정 property test와 6~9명 table-driven test를 작성한다.
- 모든 command는 성공, 잘못된 phase·actor·role·target, deadline 경계, duplicate,
  stale version과 concurrent 제출을 검증한다.
- private projection은 다른 `agent_id`의 역할·알리바이·조사·행동이 응답, SSE와 로그에
  나타나지 않는 비간섭성 테스트를 수행한다.
- polling과 SSE는 client-visible transaction에 연속으로 배정된 `front_sequence`와
  batch 안의 `operation_index`를 사용해 같은 operation을 중복·누락 없이 재구성해야
  한다. 내부·다른 Agent private event의 sequence는 Front에 노출하지 않는다.
- Redis 중단 뒤 PostgreSQL snapshot으로 복구하고 결과를 다시 추첨하지 않는지 확인한다.
- LLM·MCP 자동 테스트는 fake transport와 synthetic context만 사용한다.
- MCP 구조화 로그는 승인된 metadata allowlist만 남기고 Resource·Tool payload,
  capability, token, signature, prompt와 raw model response를 남기지 않는지 캡처 테스트한다.
- 섹터별 단위 테스트는 타 섹터의 실행 프로세스 없이 자체 목데이터·fixture로 수행할
  수 있어야 한다. 이 fixture는 정본 계약을 복제하는 보조 자료이며 별도 공통 산출물로
  강제하지 않는다.
- 밸런스는 인원별 최소 100회, 가능하면 1,000회 heuristic bot simulation으로 먼저
  확인한다. 시민·마피아 목표 승률은 각각 45~55%, 40~60%는 관찰 범위, 60% 초과는
  조정 대상으로 본다.
- 밸런스 변경은 AI 표현 성향 또는 규칙 하나만 한 번에 바꾸고 version을 올린다.

관찰 지표는 진영·인원별 승률, 평균 밤 횟수와 게임 시간, 보호 성공, 탐정 생존과
조사 영향, 마피아 상호 공격·투표, 인간 첫날 밤 사망, deadline 자동 선택 횟수다.
LLM token·비용과 LLM timeout 지표는 MVP 수집 대상이 아니다.

## 11. 환경과 운영

| 프로세스 | 허용 설정 |
|---|---|
| Front | Backend URL, 브라우저 UUID 저장 key 이름 |
| Backend | `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, `GAME_STATE_KEYRING_FILE`, `GAME_STATE_ACTIVE_KEY_ID`, 선택 Provider·model·API key, `MAFIA_MCP_URL`, `MCP_REQUIRE_TLS`, `MCP_TLS_CA_FILE`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ADMIN_USER_IDS` |
| migration | `DATABASE_MIGRATION_URL`, `DATABASE_NAME`, DB path 비교용 `TEAM_DATABASE_URL`/`DATABASE_URL` |
| MCP runtime | `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`, listen·TLS 설정 |

- 실제 비밀값은 문서, 로그와 Git에 넣지 않는다.
- `GAME_STATE_KEYRING_FILE`은 저장소 밖의 권한 제한 파일을 가리킨다. active key와
  저장된 `key_id`의 과거 key를 함께 제공해 재시작 뒤 seed·snapshot을 복호화한다.
- migration 계정은 DDL, Backend 계정은 필요한 DML 최소 권한만 가진다.
- MCP runtime에는 DB·Redis·LLM 자격증명을 주입하지 않는다.
- Front에는 내부 Engine·MCP·DB·Redis·LLM secret을 주입하지 않는다.
- `MCP_REQUIRE_TLS=false`는 loopback 개발에서만 허용한다.
- migration runner가 `DATABASE_MIGRATION_URL`을 직접 읽고 runtime DSN과 분리하는 것은
  `WU-B2` 완료 조건이다. 전환 전 runner의 실제 제한은 README를 따른다.

## 12. 완료 정의

- 정본 문서와 FastAPI `/openapi.json`이 같은 용어·enum·필드를 사용한다.
- 이전 identity/OIDC route와 Front 로그인 코드가 실행 경로에서 제거된다.
- 6~9명 게임이 생성, 시작, 진행, 저장, 재개와 종료까지 결정적으로 동작한다.
- 새로고침·중복 요청·동시 제출로 상태와 RNG 결과가 중복되지 않는다.
- 다른 플레이어의 비공개 정보가 Front·Agent·GM·MCP·로그에 노출되지 않는다.
- PostgreSQL·Redis·Provider·MCP 장애의 정의된 fallback 또는 fail-closed 경로가
  테스트된다.
- README, 환경 예시와 package README가 실제 구현 상태와 정본 문서를 가리킨다.

### WU-B6 대화 의미·증거 평가 보완 (2026-09-07)

사용자가 제공한 대화 사례에 따라 기존 orchestrator 프롬프트만 보완한다. 자기 보호 등 구어체 답변 인정, 발언 기회 없는 무응답의 중립 처리, 실제 모순과 정보 부족의 구분, 시민 오처형 뒤 근거 재검토, 사망한 역할 자칭자의 신뢰와 확정 사실 구분을 포함한다. 모델·Provider·API·DB·게임 규칙은 변경하지 않는다.

이번 단일 WU-M3 보완은 사용자가 요청한 운영 FastMCP 모델 입력 축약·게임 규칙 안내 추가다. 기존 Resource 등록 파일에서만 변환하며 상세 계약은 API 명세의 FastMCP 모델 입력 축약 절을 따른다. Backend MCP 소비 클라이언트는 기존·축약 응답을 함께 허용하는 최소 호환 변경을 포함한다. DB·게임 판정은 변경하지 않는다.

이번 WU-B6 프롬프트 보완은 사용자 요청에 따라 진영 승리 우선·인간/AI 동일 증거 평가와 마피아 deception 성향의 런타임 2배 해석(상한 1.0)을 포함한다. 거짓 역할 주장과 의심·투표 유도 강도에 적용하며 DB seed·실제 역할·공개 사실·승패 규칙은 변경하지 않는다. 실제 발언 발생 비율은 모델 선택에 달려 있다.

## 2026-09-07 자유 토론 변경 (사용자 승인 WU-B4)

이번 단일 WU-B4는 1분 45초 자유 토론과 연결되는 Front·MCP 표현의 변경이다. 이 절이 기존 좌석당 한 번 발언·전원 PASS 추가 순환 규칙보다 우선한다. 새 일반·최종 토론은 Backend deadline 105초까지 열리며 인간은 AI 처리 순서와 무관하게 발언한다. 플레이어별 최근 60초 SPEAK는 최대 7회이며 서버 게임 행 잠금 안에서 원장으로 검증한다. PASS는 조기 마감하지 않는다. AI 작업은 기존 단일 예약 창을 재사용해 공정하게 배분하고, 발언마다 새 window를 열되 토론 deadline은 보존한다. turn_player_id는 AI 스케줄링 힌트이며 인간의 발언 권한 제한이 아니다. SPEECH에도 deadline·remaining_ms가 제공된다. 저장 시 잔여 시간을 보존한다. 마감 뒤 첫날은 밤, 이후 낮은 투표, 최종 토론은 최종 지목으로 진행한다. 과거 deadline 없는 발언 창은 기존 방식으로 처리한다. DB 구조와 idempotency·게임 상태 버전 검증은 보존한다.

WU-B6 말투 보완: 사용자 요청에 따라 AI 발언은 반말을 허용한 자연스러운 게임 채팅 구어체로 작성한다. 페르소나의 격식보다 구어체를 우선하고, 과도한 논리 보고·검증 용어·상황 요약을 줄인다. 실제 근거 판단과 진영 승리 우선순위는 유지한다.
