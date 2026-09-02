# AI 마피아 문서 병합 충돌 및 의사결정 목록

**상태:** 결정 대기
**기준일:** 2026-09-02
**범위:** `docs/AI_MAFIA_*.md`, `docs/LLM_PROVIDER_IMPLEMENTATION_PLAN.md`,
`docs/개발상세플랜/*.md` 및 이 문서들이 정본으로 참조하는 최종 규칙·플랜

이 문서는 일치하는 내용이나 구현 절차를 반복하지 않는다. 문서끼리 같은 계약을
다르게 정의한 부분, 최신 계약 안에서도 구현 전에 선택해야 하는 부분, 선택 없이
바로 교정할 수 있는 명백한 문서 오류만 기록한다. 여기의 권고안은 결정 기록이
아니며, 선택 결과를 정본 계약과 기계 판독 schema에 반영해야 확정된 것으로 본다.

| 우선순위 | 의미 |
|---|---|
| `P0` | 해당 계약을 소비하는 WU 착수 전에 결정하지 않으면 독립 구현이 서로 호환되지 않음 |
| `P1` | migration 또는 contract test 고정 전에 결정해야 함 |
| `P2` | MVP 운영 전까지 결정하면 되지만 기본값을 임의로 구현하면 안 됨 |
| `교정` | 새 설계 결정 없이 현재 승인 내용에 맞춰 문구만 고치면 됨 |

---

## 1. 문서 정본과 버전

### DOC-01. 루트 `minimum-v1/basic-v1` 계약 문서의 처리 (`P0`)

- **충돌:** [Backend API 계약](../AI_MAFIA_BACKEND_API_CONTRACT.md) 1~16행,
  [게임 규칙](../AI_MAFIA_GAME_RULES.md) 1~3행,
  [DB·Redis 설계](../AI_MAFIA_DATA_REDIS_DESIGN.md) 1~3행과
  [MCP 계약](../AI_MAFIA_MCP_API_CONTRACT.md) 1~6행은 각각 자신을 확정 계약 또는
  유일한 기준으로 선언한다. 반면 [통합·수정 내역](../플랜/AI_MAFIA_PLAN_INTEGRATION_NOTES.md)
  20~23행과 165~184행은 `basic-v1`, 5~9명, `FACTION`, `mcp_1`을 현재 구현 기준이
  아니라고 명시하고 `mystery-v1/scenario-v1` 및 현재 상세 플랜을 우선한다.
- **현재 승인 방향:** 제품 규칙은 `mystery-v1/scenario-v1`, 구현 계약은
  [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)와 섹터 계획이다. 제품 버전을
  다시 고르는 문제가 아니라, 오래된 계약 문서가 계속 정본처럼 보이는 문제가 남아 있다.
- **결정:** 루트 6개 문서와 OpenAPI를 `현재 계약으로 전면 개정`, `대체됨 배너를
  붙여 보존`, `별도 legacy 디렉터리로 이동` 중 어떤 방식으로 처리할지 정한다.
- **권고:** 우선 모든 구문서에 `대체됨` 배너와 현재 정본 링크를 넣고, 아래 P0 결정을
  마친 뒤 파일명은 유지한 채 현재 계약으로 전면 개정한다. 같은 `/api/v1`에서 두
  계약 세대를 동시에 지원하는 선택은 하지 않는다.
- **영향:** Front `WU-F1`, Backend `WU-B1/B3/B5/B7`, MCP `WU-M2` 전체.

DOC-01로 한 번에 해소해야 할 계약 세대 차이는 다음과 같다.

| 영역 | 루트 계약 | 현재 승인 상세 플랜 |
|---|---|---|
| 규칙 | `basic-v1`, 5~9명, 7명부터 마피아 2명 | `mystery-v1/scenario-v1`, 6~9명, 8명부터 마피아 2명 |
| 진행 | 역할 공개 뒤 밤, 해소·최종 phase 없음 | 첫날 낮 무투표, 명시적 해소 phase, 5번째 밤 뒤 `FINAL_*` |
| 실패 기본값 | 밤 무행동·투표 기권·일부 장애 시 pause | 밤·투표 결정적 자동 선택, 토론 `PASS`, Provider 장애만으로 pause 금지 |
| 공개 범위 | 타인 역할 종료 전 비공개, 세부 예외 불완전 | 낮 처형 역할만 즉시 공개, 밤 사망 역할·진행 중 개별 투표 비공개 |
| 사용자 인증 | `X-User-Id` UUID 형식만 검사 | Streamlit HMAC + body/header의 `acting_user_id` 재검증 |
| 생성·명령 | 생성 key 필수, `BEGIN_GAME/KILL/PAUSE/RESUME`, 발언 280자 | 생성 key 누락, `NIGHT_*/PASS/SAVE_AND_EXIT`, 별도 resume, 발언 200자 |
| 처리 결과 | command `202` + operation polling | command `200` + 현재 `GameStateView`, SSE/상태 polling |
| 목록·상태 | cursor 목록, `your_player`, flat timing, `valid_targets` | `status=saved`, `you`, scenario/private profile, 중첩 timing |
| SSE | 이벤트 4종, `Last-Event-ID`, heartbeat | 단일 `game_update`, `since_sequence` polling이나 세부 wire 미정 |
| 부가 기능 | 사용자 notes, 게임별 1회 rating, 관리자 읽기 전용 | notes 없음, 일반 feedback, ADMIN role과 feedback 상태 PATCH |
| DB | operation·범용 idempotency·notes, `seed_ciphertext`, `faction` | command receipt·audit outbox, `random_seed`, blind-mafia로 `faction` 금지 |
| Redis | operation status 중심 5개 key | runtime·deadline·agent reservation/status를 포함한 확장 key |
| MCP | `mcp_1`, HMAC header, Resource 5종, underscore Tool | `mafia_game`, Bearer transport + Engine HMAC, Resource 8종, dot Tool |

### DOC-02. 계약 충돌 우선순위 (`P0`)

- **충돌:** [계약 인덱스](../AI_MAFIA_API_CONTRACT.md) 15행은
  `Backend API schema > 게임 규칙 > DB projection > 화면 표현`을 선언한다.
  [최종 통합 플랜](../플랜/AI_MAFIA_MVP_FINAL_PLAN.md) 14~18행은 제품 규칙과 구현
  계약이 충돌하면 어느 한쪽을 임의로 우선하지 않고 함께 고치도록 한다.
- **결정:** 고정 우선순위를 유지할지, 제품 의미와 기술 계약을 함께 변경하는
  contract-change gate를 사용할지 정한다.
- **권고:** 현재 최종 플랜의 공동 변경 원칙을 채택한다. OpenAPI는 제품 규칙을
  덮어쓰는 상위 정본이 아니라, 합의된 공개 API를 기계 판독 형태로 표현한 산출물로 둔다.

### DOC-03. LLM Provider 패키지와 승인 파일 범위 (`P0`)

- **충돌:** [LLM Provider 계획](../LLM_PROVIDER_IMPLEMENTATION_PLAN.md) 23~39행과
  231~254행은 `backend/app/llm_provider/`의 다중 파일 구조를 현재·목표 경로로
  사용한다. 실제 코드도 이 경로에 있다. 반면 [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
  954~969행과 [Backend 지침서](SECTOR_PLAN_BACKEND.md) 54~102행은 신규 승인 파일을
  `backend/app/llm/providers.py` 하나로 제한한다. README도 일부 위치에서 구 경로
  `backend/app/llm/`을 안내한다.
- **결정:** `llm_provider/`를 정식 구현 경로로 채택할지, 단일 `llm/providers.py`로
  다시 합칠지 정한다.
- **권고:** 현재 구현을 보존해 `llm_provider/`를 정식 경로로 채택하고 Backend
  `WU-B8`의 승인 파일 및 테스트 목록을 갱신한다. 호환 facade는 실제 소비자가
  확인되지 않으면 추가하지 않는다.
- **영향:** Backend `WU-B8`, README 구조, Provider 테스트 및 import 계약.

---

## 2. Frontend와 공개 Backend API

### API-01. 게임 생성 직후 상태와 `ROLE_REVEAL` 종료 조건 (`P0`)

- **공백:** 현재 Command enum에는 `BEGIN_GAME`이 없지만
  [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md) 275~289행은
  `CREATED → ROLE_REVEAL → DAY_ANNOUNCEMENT`를 요구한다. 생성 응답 설명
  349~391행은 최초 `status`, `phase`, `round`, `state_version`과 다음 전이 trigger를
  고정하지 않았고 DB 기본 version은 0이다.
- **결정:** 역할 확인을 명시적 command/ack로 끝낼지, 별도 start endpoint를 둘지,
  서버가 자동 전이할지 선택한다. 최초 상태 4-tuple과 최초 event sequence도 함께 정한다.
- **권고:** 생성은 `IN_PROGRESS/ROLE_REVEAL/round=0/version=1`까지 원자적으로 확정하고,
  idempotent한 역할 확인 command가 들어온 뒤 `DAY_ANNOUNCEMENT`로 전이한다.
- **영향:** Backend `WU-B1/B5`, Front `WU-F1/F5`.

### API-02. 변경 endpoint별 version·idempotency 표 (`P0`)

- **충돌:** 루트 Backend 계약 27~29행은 모든 상태 변경에 `idempotency_key`를
  요구하고 Front 지침서 164~185행도 변경 명령의 version·key 전달을 요구한다.
  그러나 상세 계약의 생성 요청 349~359행과 feedback 요청 630~640행에는 key가 없고,
  `expected_version`과 key를 함께 쓰는 endpoint는 command와 resume뿐이다. 같은 key의
  다른 body도 구 계약은 `IDEMPOTENCY_CONFLICT`, 현재 receipt 절은
  `GAME_STATE_CONFLICT`를 사용한다.
- **결정:** 생성, 역할 확인, command, resume, feedback, 관리자 PATCH 각각에 대해
  `expected_version`, `idempotency_key`, key scope, 보존 기간, 재전송 응답을 표로 고정한다.
- **권고:** 생성·feedback에도 key를 필수화하고, 게임이 아직 없는 생성은
  `(owner_user_id, operation, key)` 범위의 receipt를 사용한다. 다른 request hash는
  version 충돌과 구별되는 `IDEMPOTENCY_CONFLICT`로 반환한다. View는 현재 audience로
  다시 투영한다.
- **영향:** Front `WU-F1`, Backend `WU-B3/B5`, DB migration.

### API-03. 저장 목록과 resume version (`P0`)

- **충돌:** 저장 목록 item에는 `state_version`이 없지만 상세 계약 416~433행의 resume는
  `expected_version`을 필수로 한다. Front 지침서 253~255행은 목록에서 바로 resume를
  호출한다.
- **결정:** 목록 item에 `state_version`을 추가할지, resume 전에 상태 GET을 강제할지,
  resume에서 version을 없앨지 선택한다.
- **권고:** 목록에 `state_version`을 추가하고 resume 시 Backend가 다시 CAS 검증한다.

### API-04. `allowed_commands`와 target schema (`P0`)

- **공백:** `GameStateView` 예시는 `SPEAK.max_length`만 보여 준다. 투표·밤 행동의
  유효 target을 어디에 담는지 정의하지 않았는데 Front는 응답에 없는 target을
  계산할 수 없다. 구 계약의 top-level `valid_targets`와도 구조가 다르다.
- **결정:** top-level `valid_targets`를 복원할지, `allowed_commands`를 command별
  discriminated union으로 만들지 정한다.
- **권고:** 각 command object에 `valid_target_player_ids`, 입력 제약과 required 여부를
  포함한 union을 사용한다. target이 없는 command에는 해당 필드를 금지한다.
- **영향:** Backend `WU-B5`, Front `WU-F1/F2/F5`의 strict parser와 화면.

### API-05. SSE와 증분 polling wire (`P0`)

- **충돌·공백:** 구 계약은 SSE 이벤트 4종, sequence id, `Last-Event-ID`, 30초 heartbeat와
  45초 재연결을 정한다. 현재 상세 계약 555~571행은 단일 `game_update` 예시만 두며
  event id, private event 전달, heartbeat, 재연결 규칙이 없다. Front 지침서 286~309행은
  중복·역순·sequence 공백 복구를 요구하지만 `?since_sequence` 응답 schema도 없다.
- **결정:** 이벤트 이름, 공통 envelope, SSE `id`, 공개·본인 private payload,
  heartbeat/retry, polling 주기, 증분 응답의 `next_sequence/has_more`를 고정한다.
- **권고:** DB event sequence를 SSE `id`와 증분 cursor의 단일 기준으로 사용하고,
  SSE와 polling이 동일한 audience-filtered event envelope을 반환하게 한다.
- **영향:** Backend `WU-B5/B6`, Front `WU-F1/F6`.

### API-06. 공개 오류 code와 HTTP status (`P0`)

- **충돌·공백:** 루트 Backend 계약 43~53행과 상세 계획 193~223행의 오류 집합이
  다르다. 현재 계획 안에서도 `GAME_STATE_CONFLICT`가 version 불일치와 idempotency
  hash 불일치에 함께 쓰이며, invalid/self target의 422 code가
  `ACTION_NOT_ALLOWED`인지 `INVALID_GAME_REQUEST`인지 정해지지 않았다.
- **결정:** endpoint·검증 단계별 HTTP/code/details 표를 고정하고 Engine 내부 code,
  MCP JSON-RPC code, audit record 거부 code를 별도 namespace로 분리할지 정한다.
- **권고:** 공개 API, Engine API, MCP, audit rejection의 enum을 분리한다. Front가
  재조회할 충돌과 사용자가 입력을 고쳐야 할 오류를 같은 code로 합치지 않는다.

### API-07. notes·게임 평가·일반 feedback의 범위 (`P1`)

- **충돌:** 루트 계약은 개인 notes API와 FINISHED 게임당 1회 rating을 요구한다.
  현재 최종 플랜과 상세 계약은 notes 저장소 없이 `game_id` nullable인 일반 feedback,
  category/content/status와 관리자 처리 흐름을 사용한다. 상세 feedback에는 필드
  필수성, 사용자·게임별 건수, 중복·조회 규칙이 없다.
- **결정:** 사용자 notes를 MVP에서 제외할지 복원할지, 게임 평가와 일반 문의를
  하나의 `user_feedback`으로 합칠지 분리할지, cardinality와 재제출 정책을 정한다.
- **권고:** notes는 이번 MVP에서 제외한다고 명시한다. feedback은 여러 건 가능한
  일반 의견과 게임당 1회 평가를 분리하거나, 단일 테이블을 쓰더라도 type과 부분
  UNIQUE를 둔다. 결과 API에는 현재 사용자의 평가 상태를 제공한다.
- **영향:** Backend `WU-B3/B5/B9`, Front `WU-F5/F7`.

### API-08. 관리자 API의 완전한 schema (`P1`)

- **충돌·공백:** 구 계약은 인증 없는 내부 테스트용 read-only API, 날짜 범위와 cursor를
  사용한다. 현재 계약은 `user_roles.ADMIN`, `period`, page/size와 feedback PATCH를
  사용하지만 각 응답 envelope, item 필드, nullability, 정렬, page metadata, 최대 size를
  정의하지 않았다. 모든 non-GET body에 `acting_user_id`가 필요하다는 공통 규칙과
  PATCH 예시 `{"status":"REVIEWING"}`도 충돌한다.
- **결정:** 관리자 네 endpoint의 전체 요청·응답 schema, pagination 방식, PATCH의
  actor 전달·idempotency·동시 수정 정책을 고정한다.
- **권고:** 현재 ADMIN fail-closed 방향을 유지하고 OpenAPI 수준 fixture를 Front·Backend가
  함께 사용한다.

---

## 3. 게임 엔진·DB·Redis

### ENG-01. 병렬 AI 제출과 전역 `state_version` (`P0`)

- **충돌:** 상세 계획 1063~1074행은 같은 phase의 AI reservation과 호출을 병렬 처리하고
  actor별 결과를 반영한다. 1190~1196행은 capability를 정확한 전역
  `state_version`에 묶고 version 변경 즉시 폐기한다. 첫 AI 제출이 version을 올리면
  같은 action window에서 발급한 나머지 capability가 모두 stale이 된다.
- **결정:** 공개 상태 version과 행동 창 식별자를 분리할지, actor별 submission version을
  둘지, 비공개 접수 중에는 전역 version을 올리지 않을지 정한다. 한 transaction의
  event 수와 version 증가 단위도 함께 고정한다.
- **권고:** immutable `action_window_id/phase_epoch`와 actor별 receipt를 두고 capability를
  그 창에 귀속한다. 모든 제출을 해소한 공개 상태 전이에서 전역 version을 증가시킨다.
- **영향:** Backend `WU-B1/B3/B6/B7/B8`, MCP `WU-M2~M5`.

### ENG-02. `/internal/v1/engine/actions`의 commit 경계 (`P0`)

- **충돌:** 내부 API 1141~1146행과 1257~1264행은 `/actions`가 최종 검증·event commit 후
  `event_id`를 반환한다고 한다. 반면 Backend 지침서 399~408행은 MCP `/actions` 호출이
  끝난 뒤 Agent Manager가 다시 lock을 얻어 CAS 반영한다고 읽힌다.
- **결정:** `/actions` handler가 유일한 게임 행동 commit 경계인지, proposal receipt만
  만들고 Agent Manager가 나중에 commit하는지 정한다.
- **권고:** `/actions` handler를 유일한 commit 경계로 둔다. 호출 후 Agent Manager의
  후속 작업은 `agent_runs`와 reservation 종료 기록만 갱신하고 행동을 다시 적용하지 않는다.

### ENG-03. deadline 경계와 request-worker 선형화 (`P0`)

- **공백:** 문서는 “deadline 이후”만 거부하며 `now == deadline_at`, API 수신 시각과
  row lock 획득 시각 중 판정 기준, 사용자 요청과 timeout worker가 동시에 도착했을 때의
  승자 규칙을 정의하지 않았다.
- **결정:** 유효 조건을 `<` 또는 `<=`로 고정하고, 권위 clock과 transaction
  linearization point를 정한다.
- **권고:** game row lock 안에서 DB 권위 시각 `now < deadline_at`을 재검증하고,
  같은 lock/CAS를 먼저 성공한 transaction 하나만 행동 또는 자동 해소를 commit한다.

### ENG-04. `FAST_FORWARD` 실행 정책 (`P1`)

- **공백:** 인간 사망 후 결과까지 자동 진행한다는 의미만 있고, 20/30초 deadline을
  기다리는지, LLM을 호출하는지, 비용 상한과 취소·중복 요청을 어떻게 처리하는지 없다.
- **결정:** `정상 시간+정상 LLM`, `deadline 생략+정상 LLM`, `즉시 결정적 fallback` 중
  하나를 정하고 game 단위 최대 시간·token·비용을 정한다.
- **권고:** 사용자 요청의 “빠른 진행” 의미를 지키기 위해 deadline과 LLM을 생략하고
  같은 seed 기반 fallback으로 즉시 완주하되, 결과에는 자동 진행 사실을 표시한다.

### ENG-05. 영구 reservation과 pause 안전 지점 (`P0`)

- **충돌·공백:** `SAVE_AND_EXIT`은 외부 LLM/MCP run이 없는 안전 지점에서만 허용한다.
  Redis reservation은 손실 가능한 가속 데이터인데 현재 `agent_runs`에는
  `reservation_id`, `RUNNING/CANCELLED/COMMITTED`, lease와 완료 marker가 없다.
  active run 중 저장 요청의 오류·대기·취소 정책도 없다.
- **결정:** 별도 reservation 테이블, 확장한 `agent_runs`, 완결된 SYSTEM event reducer,
  또는 phase 경계에서만 저장하는 방식 중 하나를 고른다. active run 요청 처리와
  늦은 결과 폐기도 함께 정한다.
- **권고:** PostgreSQL에 reservation 상태와 lease를 영속화하고 `PAUSING` 또는 동등한
  신규 claim 차단 상태를 둔다. 기존 run을 취소/종료한 뒤 deadline을 비우고
  `paused_remaining_ms`만 저장한다. Redis index 등록 실패는 resume DB commit을
  되돌리지 않는다.

### DATA-01. `finished_at`과 random seed 보호 (`P0`)

- **충돌:** 루트 DB 설계는 `seed_ciphertext`와 `finished_at`을 사용한다. 현재 상세 DB는
  `random_seed text` 평문이고 `finished_at`이 없지만, 종료 기간 KPI와 보존 기산이 필요하다.
  `SEED_RECORDED` event와 full snapshot의 seed 표현도 정의하지 않았다.
- **결정:** `finished_at` 저장 여부, seed 암호화·키 버전·파생 방식, event에는 raw seed가
  아닌 commitment/reference만 둘지, snapshot에 무엇을 저장할지 정한다.
- **권고:** `finished_at`을 추가하고 seed는 인증 암호화한 ciphertext와 key version으로
  보관한다. event·receipt에는 raw seed를 넣지 않고 안정적인 참조나 hash만 둔다.
- **영향:** Backend `WU-B3`, 운영 key 관리, KPI·purge.

### DATA-02. snapshot schema version과 생성·정리 주기 (`P1`)

- **공백:** checksum, last event sequence와 복구 순서는 정했지만 검증 대상인 snapshot
  schema version의 저장 위치, snapshot 생성 trigger, 오래된 snapshot 정리 정책이 없다.
- **결정:** 별도 `snapshot_schema_version` 열 또는 state 내부 필수 필드, 생성 시점
  `(초기/phase 해소/pause/finish/N events)`, 보존 개수를 정한다.
- **권고:** version 열을 두고 초기·각 resolution·pause·finish에 생성하며 최근 검증본
  여러 개를 남겨 손상 시 이전 본으로 복구할 수 있게 한다.

### DATA-03. Agent 판단 요약과 비용의 영속 모델 (`P1`)

- **충돌·공백:** 결과 API는 `agent_decision_summaries`를 반환하고 관리자 KPI는 token·비용을
  요구하지만 현재 `agent_runs`에는 round, reservation/action event 연결, 정제된 summary,
  계산 비용과 가격 version이 없다. retry/failover 시 한 run이 turn인지 provider attempt인지도
  정하지 않았다.
- **결정:** attempt별 row 또는 turn별 aggregate를 선택하고, 공개 summary의 저장 위치,
  provider/model/token/cost/currency/pricing version과 재시도 합산 방식을 정한다.
- **권고:** provider attempt마다 row를 남기고 공통 turn/reservation ID로 묶는다. 공개 가능한
  짧은 summary는 별도 필드에 저장하며 prompt, raw response, chain-of-thought는 저장하지 않는다.

### DATA-04. audit 저장 schema와 관리자 로그 query (`P0`)

- **충돌:** 관리자 logs는 `game_id`, `severity`, `event_type` 필터를 요구한다. 현재
  `audit_logs` 표에는 해당 열이 없고 `action`, `target_type/id`, `allowed`, `metadata`만 있다.
  MCP `audit-v1` 입력 필드가 DB 열에 어떻게 매핑되는지도 정하지 않았다.
- **결정:** 감사와 운영 오류를 한 테이블/조회로 합칠지 분리할지, 필터 열·인덱스와
  `request_id/event_id/reason_code` 저장 위치를 정한다.
- **권고:** 보안 감사와 애플리케이션 오류를 논리적으로 분리하고 관리자 API에서 명시적
  union projection을 제공한다. 검색 필드는 JSONB가 아니라 정규 열로 둔다.

### DATA-05. persona의 안정적 ID와 중복 정책 (`P1`)

- **충돌·공백:** DB는 UUID `id`와 `(name, version)`을 쓰지만 MCP Resource는
  `persona_id`를 계약 ID로 사용한다. seed persona는 5종인데 9인 게임에는 AI가 최대
  8명이며, 한 게임 안의 persona/display name 중복 허용 여부가 없다.
- **결정:** stable slug 또는 deterministic UUID, version row 불변성, 최소 preset 수,
  게임 내 중복·표시명 정책과 `parameters` JSON schema를 정한다.
- **권고:** stable slug + immutable version을 계약 ID로 쓰고, 표현 preset 중복은 허용하되
  표시명은 좌석과 함께 고유하게 보이도록 한다.

### DATA-06. append-only와 해소 exactly-once의 DB 강제 (`P1`)

- **공백:** event UPDATE/DELETE 금지는 repository 규율뿐이고, `(game_id, round,
  NIGHT_RESOLVED)` exactly-once를 강제할 열·unique key가 없다.
- **결정:** runtime role 권한 제거, immutable trigger, `round/dedupe_key`와 partial UNIQUE 중
  어느 수준까지 DB에서 강제할지 정한다.
- **권고:** runtime role에서 UPDATE/DELETE를 제거하고 resolution dedupe key에 UNIQUE를 둔다.

### DATA-07. 보존·purge·사용자 삭제 (`P1`)

- **충돌:** 루트 설계의 PAUSED 30일, FINISHED 90일, audit 180일은 현재 비정본이며,
  [최종 통합 플랜](../플랜/AI_MAFIA_MVP_FINAL_PLAN.md) 824~830행은 보존 기간과 사용자
  삭제를 미결정으로 남긴다. 현재 상세 schema의 CASCADE/RESTRICT/익명화 순서도 완결되지 않았다.
- **결정:** 상태·events·snapshots·receipts·runs·feedback·audit·outbox별 기간, 기산 시각,
  purge 실행 주체와 주기, 사용자 삭제 시 익명화·삭제 순서를 정한다.
- **권고:** 법적·운영 요구가 없다는 전제에서 자동 purge는 별도 WU로 미루되, MVP에는
  “자동 삭제 없음”과 수동 운영 절차를 명시해 오래된 30/90/180일 수치가 적용되지 않게 한다.

### REDIS-01. key 값·TTL과 장애 degradation matrix (`P0`)

- **충돌·공백:** 현재 상세 계약은 일부 key 이름과 lock 30초, runtime 30분,
  idempotency 24시간, agent status 15분만 정한다. event stream trim, deadline zset cleanup,
  reservation·rate TTL과 값 schema가 없다. PostgreSQL에서 복구 가능하다는 원칙과
  Redis 실패를 모두 `GAME_PERSISTENCE_UNAVAILABLE`로 묶은 오류 설명도 충돌한다.
  DB receipt scope와 Redis `team4:idempotency:{user_id}:{key}` scope도 다르다.
- **결정:** key별 value allowlist, TTL/trim, 생성·삭제 시점, DB 재구성 방식과
  Redis 장애 시 `DB fallback/성공+경고/fail-closed 503` 중 동작을 표로 고정한다.
- **권고:** lock은 DB row lock, event는 DB polling, idempotency는 DB receipt,
  deadline은 DB sweep으로 degrade한다. rate limit과 필수 감사 경계만 fail-closed한다.
  idempotency cache key는 DB unique tuple과 같은 scope를 쓰고 receipt ID만 cache한다.
- **영향:** Backend `WU-B4/B5/B6`, MCP 인프라 인수 기준.

---

## 4. MCP·Engine 내부 계약

### MCP-01. transport session 생성과 capability 설치 wire (`P0`)

- **충돌·공백:** Backend가 발급하는 Bearer token은 아직 알 수 없는 `session` claim을
  포함하지만 MCP 지침서 286~297행은 `session_id`를 MCP가 발급한다고 한다. Tool 입력에는
  capability를 넣지 않으며 turn마다 교체해야 하지만, capability를 session에 설치·회전·폐기하는
  인증된 control endpoint/header/message와 ack schema가 없다.
- **결정:** session ID 발급 주체와 initialize 순서, transport Authorization·session header,
  capability control wire, reconnect·rotation·revoke 절차를 정한다.
- **권고:** Backend가 UUID session ID를 먼저 만들고 짧은 Bearer token에 묶어 MCP가 채택하게
  한다. 별도 인증 control method로 opaque capability를 설치·교체하고 Agent Tool 인자와
  LLM context에는 노출하지 않는다.
- **영향:** Backend `WU-B7/B8`, MCP `WU-M3/M5/M7`.

### MCP-02. capability claim 범위 (`P0`)

- **충돌:** 상위 계획과 Backend 지침서는 capability를
  game/subject/phase/version/reservation/expiry에 묶지만 MCP 지침서는 ruleset/scenario
  version까지 claim에 요구한다.
- **결정:** 정확한 claim 목록, timed/untimed phase TTL, 서명 형식·알고리즘과 revocation
  저장 방식을 고정한다. `deadline_at`과 `server_deadline_at`의 명칭 차이는 상위 내부 API의
  `deadline_at`으로 교정할 항목이며 별도 제품 결정이 아니다.
- **권고:** ruleset/scenario version을 claim에 포함하고 실제 게임 상태와의 일치 여부는
  Backend가 매 요청 다시 조회한다.

### MCP-03. HMAC replay 방지와 안전 재시도 (`P0`)

- **충돌:** Engine 요청은 request ID replay를 거부해야 하지만 MCP 지침서 391~396행은
  안전한 재시도에 동일 `request_id`를 재사용하도록 한다. action commit 뒤 capability는
  폐기되지만 동일 `proposal_id` 재전송은 기존 결과를 반환해야 한다.
- **결정:** HTTP nonce와 업무 idempotency ID의 수명·재사용 규칙, 검증 순서와 nonce TTL을 정한다.
- **권고:** HTTP 재시도마다 새 `request_id`를 사용하고 logical `proposal_id/audit_id`는 유지한다.
  `/actions`는 인증된 원래 subject와 exact request hash를 확인한 뒤 기존 receipt를 먼저
  반환하고, 신규 proposal에만 현재 capability 유효성을 요구한다.

### MCP-04. Resource envelope·batch·timeline cursor (`P1`)

- **공백:** Resource별 allowlist는 있으나 공통 versioned envelope이 없다. `/context`는 resource
  하나만 받는데 Agent의 전체 context 예산은 3초이며, `public-timeline` 응답은
  `from_sequence/next_sequence`를 말하면서 요청 cursor·limit을 받을 필드가 없다.
- **결정:** `{meta,data}` 또는 flat 공통 필드, batch 허용 여부와 최대 개수/byte,
  static resource cache, timeline cursor·limit·정렬·has_more를 정한다.
- **권고:** `{schema_version, meta, data}` envelope과 제한된 batch를 사용한다. rules/scenario/persona는
  version별 cache를 허용하고 동적 state/actions는 매 turn 조회한다.

### MCP-05. Engine HTTP 오류와 MCP JSON-RPC 오류 매핑 (`P1`)

- **충돌·공백:** `/actions` 거부가 HTTP 200 `accepted:false`, HTTP 4xx 공통 오류,
  MCP JSON-RPC error 중 어느 형태인지 구분되지 않는다. `INVALID_AUDIT_RECORD`와 transport
  거부 code도 공통 13종에 없다.
- **결정:** endpoint별 HTTP status/envelope과 MCP-facing safe code 매핑을 고정한다.
- **권고:** 인증·schema·계약 실패는 HTTP 오류, 유효한 actor의 도메인 행동 거부는
  `accepted:false`로 구분하고, MCP는 허용된 code만 JSON-RPC `error.data`에 노출한다.

### MCP-06. `audit-v1` lifecycle event와 health endpoint (`P2`)

- **공백:** MCP 지침서는 capability 발급·교체·폐기를 모두 감사하도록 하지만 audit operation
  enum에는 대응 값이 없다. GM은 player ID가 없는데 actor hash 필드는
  `actor_player_id_hash`뿐이다. 구 MCP 계약의 `GET /health`도 현재 계약에서 사라졌다.
- **결정:** capability/session lifecycle operation, `subject_kind/subject_id_hash`, transport·audit
  reason/rejection enum과 MCP liveness/readiness endpoint를 고정한다.
- **권고:** contract 변경 전이면 `audit-v1`을 보완하고, 이미 외부 구현이 시작됐다면
  `audit-v2`로 올린다. `/health`는 민감정보 없는 liveness와 인증된 readiness로 분리한다.

---

## 5. LLM Provider 계약

### LLM-01. 모델 출력 action schema와 명칭 매핑 (`P0`)

- **충돌:** Provider 계획 69~72행은 모든 proposal의 최소 필드를
  `action/target_player_id/source_state_version`으로 보지만 `SPEAK`에는 message가 필요하고
  `PASS`에는 target이 없다. Backend는 `CAST_VOTE/NIGHT_KILL/...`, MCP는
  `game.vote/game.kill/...`, 현재 scaffold Provider는 `PING`을 사용한다.
- **결정:** Provider 출력 vocabulary와 command별 discriminated union, Backend Command와
  MCP Tool의 단일 mapping, GM summary 전용 schema를 고정한다.
- **권고:** Provider는 Backend domain command union을 반환하고 orchestration이 MCP Tool로
  명시적으로 매핑한다. `proposal_id`는 모델이 만들지 않으며 transport/orchestration이 발급한다.
- **영향:** Backend `WU-B8`, MCP `WU-M5`, Provider contract test.

### LLM-02. 단일 Provider 선택과 이중 Provider failover (`P0`)

- **충돌:** Provider 계획은 단일 `LLM_PROVIDER`를 선택하고 adapter 간 자동 전환을 금지한다.
  상세 계획 1041~1042행과 1090~1100행은 두 번째 Provider failover와 “양 Provider 장애”를
  전제로 한다. Provider 장애 시 pause 가능 문구와 최신 게임 계약의 결정적 fallback도 다르다.
- **결정:** 단일 Provider 실패 즉시 fallback인지, primary→secondary→결정적 fallback인지,
  게임 도중 Provider 고정인지 정한다. failover 대상 오류와 retry·교정·failover 순서도 정한다.
- **권고:** MVP는 단일 선택 Provider + 결정적 fallback으로 단순화한다. 이중 Provider가 필수면
  adapter가 아니라 Agent orchestration에 primary/secondary 설정과 남은 절대 예산 검사를 둔다.

### LLM-03. timeout·token·비용 설정의 이름과 범위 (`P1`)

- **충돌:** Provider 계획은 `LLM_MAX_OUTPUT_TOKENS`, game 전체
  `GAME_MAX_TOTAL_TOKENS`, 공통 input/output 단가를 사용한다. 상세 계획은
  `GAME_MAX_TOKENS_PER_RUN`, LLM 15초와 외부 예산 16초를 사용한다. 현재 설정 코드는
  LLM 30초와 `GAME_MAX_TOTAL_TOKENS`를 사용한다. provider/model별 가격, retry 비용,
  게임 비용 cap은 없다.
- **결정:** attempt/output/run/game별 token 한도, timeout이 attempt 또는 retry 포함 stage 중
  어디에 적용되는지, hard max, provider/model별 단가·통화·가격 version, 비용 초과 동작을 정한다.
- **권고:** 현재 구현 이름을 보존하되 output/run/game 한도를 서로 다른 명시적 설정으로 둔다.
  모든 retry·교정·failover는 하나의 phase 절대 예산 안에 포함하고 비용 cap 초과는 LLM 호출 없이
  결정적 fallback한다.

---

## 6. 선택 없이 바로 교정할 충돌

| ID | 문서 충돌 | 교정 내용 |
|---|---|---|
| `FIX-01` | [MCP 지침서](SECTOR_PLAN_MCP.md) 243~246행은 `CP-B2` 산출물 뒤 `CP-M1B`를 시작한다고 하지만 `CP-B2` 자체가 `CP-M1B`를 기다린다. | `CP-M1A → Backend WU-B3 migration 산출물 → CP-M1B → CP-B2`로 문구를 통일한다. |
| `FIX-02` | MCP 지침서는 `server_deadline_at`, 상위 내부 API와 사용자 API는 `deadline_at`을 사용한다. | alias를 구현하지 말고 MCP 문서와 fixture를 `deadline_at`으로 통일한다. |
| `FIX-03` | [계약 인덱스](../AI_MAFIA_API_CONTRACT.md) 16~17행은 인증이 범위 밖이고 MCP 경로가 `mcp_1`이라고 한다. | 현재 OIDC/HMAC 경계와 `mcp_server/mafia_game`으로 교정하거나 DOC-01의 대체 배너를 붙인다. |
| `FIX-04` | Provider 계획 257~261행은 실제 action 목록이 미확정이라고 하지만 상세 계획에는 이미 Command와 Tool 목록이 있다. | LLM-01 결정 결과를 반영하고 scaffold `PING`은 임시 계약으로 명시한다. |
| `FIX-05` | Provider 계획은 `llm_provider` 구현 완료를 기록하면서 앞부분은 rename을 미래 단계로 서술한다. | 완료된 rename과 남은 게임 action 확장을 분리해 시제를 교정한다. |
| `FIX-06` | README와 `pyproject.toml` 일부 주석은 `backend/app/llm`, `mcp_1`, 예약 Provider 상태를 안내한다. | DOC-03 및 MCP 계약 결정 뒤 현재 디렉터리·설정·구현 상태로 갱신한다. |
| `FIX-07` | 루트 Backend 계약이 기계 정본으로 연결한 `AI_MAFIA_BACKEND_OPENAPI.yaml`은 `basic-v1`, `X-User-Id`, operation·notes 계약이다. | DOC-01과 API-01~08 결정 전까지 현재 API 정본으로 사용하지 않는다고 표시하고, 결정 후 재생성한다. |
| `FIX-08` | 루트 DB 설계의 identity 길이(`display_name` 80, provider 32, subject 255)가 Backend identity API와 migration의 120/64/512 계약과 다르다. | 이미 구현된 identity API와 `001_create_oauth_schema.sql`을 유지하고, 게임 schema 개정 시 기존 identity 표를 중복 재정의하지 않는다. |

---

## 7. 결정 순서

| 순서 | 결정 ID | 합의 주체 | 다음 착수 가능 범위 |
|---:|---|---|---|
| 1 | `DOC-01~03` | 3개 섹터 + 제품 책임자 | 어떤 문서와 파일 경로를 구현할지 확정 |
| 2 | `API-01`, `ENG-01~03`, `MCP-01~03` | Backend + Front/MCP 영향자 | 규칙 엔진, 공개 API, capability 골격 |
| 3 | `ENG-05`, `DATA-01`, `DATA-04`, `REDIS-01` | Backend + MCP 인프라 | migration 002와 Redis client |
| 4 | `API-02~06`, `MCP-04~05`, `LLM-01~02` | Front + Backend + MCP | 독립 fake와 contract test |
| 5 | `API-07~08`, `ENG-04`, `DATA-02~07`, `LLM-03`, `MCP-06` | 기능별 소유자 + 제품 책임자 | 관리자·운영·알파 완료 조건 |

각 결정은 선택한 옵션, 영향 schema·문서, 적용 version, 합의자와 날짜를
[상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md) 9장 변경 이력에 기록한다.
결정 전에는 coding AI agent에게 관련 WU 구현을 지시하지 않는다.
