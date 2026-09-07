# AI 마피아

**AI 마피아**는 함께할 사람을 기다리지 않아도 1명의 인간 플레이어와 개성 있는
여러 AI 플레이어가 바로 한 판을 완주할 수 있도록 만드는 소셜 디덕션 게임입니다.
계획된 `mystery-v1`은 6~9명 규모의 마피아 게임에 다섯 개의 경량 사건 배경을
결합합니다. AI별 말투·공격성·기만 표현은 달리하되 MVP 밸런스 검증 중 추론
능력과 정보 접근 권한은 동일하게 유지합니다. 규칙과 승패는 Backend 게임 엔진이
결정하고 LLM은 허용된 정보 안에서 대화와 선택만 담당합니다.
제품 목표와 MVP 범위는
[AI 마피아 MVP 공통 마스터플랜](docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md)을
기준으로 합니다.

현재 저장소는 로그인 없이 브라우저가 생성·보관한 UUID `user_id`와
`X-User-Id`로 사용자를 구분합니다. UUID는 인증 수단이 아니므로 신뢰된 로컬·사설망
환경을 전제로 합니다. `mystery-v1` 규칙 엔진, PostgreSQL runtime과 AI 진행 worker는
연결되어 있습니다. actor별 정보 격리, 마피아 전원 행동·재투표·최종 집계, 저장 후 재개와
두 번째 새 게임 생성 흐름을 보완했습니다. 화면에는 AI별 처리 단계와 행동 요약을
작게 표시하며 Backend 터미널과 순환 파일에서 같은 순서의 진행 기록을 확인합니다.
버튼·입력 영역의 배경과 글자색도 함께 지정했습니다. 수정 내역과 검증 범위는
[게임 테스트 보고서 8절](docs/AI_MAFIA_GAME_TEST_GAP_REPORT.md#8-수정권고-반영과-ai-진행-표시)을 참고하세요.

개발하거나 기여하기 전에 반드시 [AGENTS.MD](AGENTS.MD)의 브랜치, 커밋,
파일·디렉터리 구조, 테스트, 주석 및 문서화 규칙을 확인하세요.

## 현재 구현 범위

- UUID-only 사용자 Frontend의 홈·게임 진행·관전·서버 확정 결과·게임별 피드백 화면과 Backend 공개 API client
- `POST /api/v1/feedback`의 PostgreSQL 영속 저장, 멱등 재생, 일반·게임별 피드백 검증
- 브라우저 UUID v4 생성·보관과 `X-User-Id` 기반 사용자 구분
- FastAPI 공개 게임 API와 UUID별 게임 소유권 확인
- Frontend API client의 `/health`·`/ready` 상태 확인과 공개 API header·오류 계약 테스트
- Backend 소유 PostgreSQL migration 실행 코드(MCP 섹터가 실제 실행)
- 독립 관리자 Streamlit 앱과 후속 MCP 서버 예약 구조(`mcp_server/mcp_2`)
- FastMCP 기반 `/mcp`와 최소 Resource·Prompt·Tool 등록부
- FastMCP 등록부에서 Backend 게임 context·prompt·action endpoint로 전달하는 HTTP adapter

개발 섹터 역할은 코드 소유권과 실행 환경 책임을 분리합니다. Backend 섹터는
DB schema·migration SQL·repository와 Redis client·lock 코드를 작성하고, MCP
섹터는 PostgreSQL·Redis 인스턴스 구축·기동·중지, DDL migrator와 DML runtime
계정·권한 준비,
migration 실행과 health 확인을 담당합니다. 실제 Backend 프로세스는 DB·Redis에
직접 연결하며 MCP 서버를 데이터 프록시로 사용하지 않습니다.
기존 `event_outbox`와 agent 관련 테이블·암호화 컬럼은 DB/migration 호환을 위해
보존합니다. 신규 MVP 실행 경로의 게임 추적은 `game_events`와 `receipts`를
사용하고, MCP는 FastMCP 표준 protocol session만 사용합니다.

AI 진행 worker는 actor별 Resource → Provider → 검증된 Tool 제출 경로를 사용하고,
read-only 관리자 API와 연결됩니다. 공개/본인/차례/persona 경계를 따로 검증하며
GM 안내는 기본 이벤트 수준입니다. canonical game의 Redis publisher 자동 기동,
LLM 비용·예산 집계와 별도 GM LLM 연출은 현재 범위에 포함하지 않습니다.

게임 흐름용 `DeterministicGameAgent`는 DB reservation이나 lease 없이 Backend가
제공한 context를 deterministic Fake Provider에 전달하고, 검증된 action만 Backend
경계로 반환합니다.

PostgreSQL에서는 검증된 AI SPEAK/PASS를 인간과 동일한 GameEngine 검증·transaction으로
기록합니다. AI 원장의 source 값은 기존
스키마 계약에 맞춘 `AGENT`입니다.

Frontend sync는 Backend `game_events`의 operation `type`을 적용하며, DB·Redis를
직접 호출하지 않습니다.

인간 SPEAK/PASS와 행동 command는 자신의 제출만 PostgreSQL에 기록하고 즉시
반환합니다. 중앙 `AiProgressWorker`가 열린 AI window를 비동기로 회복하며,
LLM·MCP 실패 시에만 같은 command 경계의 deterministic fallback을 사용합니다.

PostgreSQL snapshot은 생성 직후뿐 아니라 `DAY_DISCUSSION` 진행 상태도 복원합니다.
새로고침 시 현재 `action_windows`와 토론 제출 원장을 다시 읽어 실제 window ID와
인간 legal action을 반환하므로, 같은 게임을 이어서 테스트할 수 있습니다.
밤 행동과 투표 command도 PostgreSQL action service를 통해 GameEngine과
`action_submissions`·`game_events`에 연결되어 있습니다. 투표는 인간 표를 먼저
원장에 기록하고 생존 AI 표를 이어서 수집한 뒤, 모든 생존자 표가 모였을 때만
해소합니다. 현재 열린 투표 원장은 snapshot·worker 재시작 시에도 복원합니다.
인간 시민의 밤은 별도 입력 없이 Backend가 자동 해소해 다음 낮으로 전환합니다.
실제 PostgreSQL smoke에서 밤 행동과 다음날 투표 command 왕복을 확인했으며,
재투표·승패 규칙과 종료 snapshot의 PostgreSQL smoke도 확인했습니다.
2026-09-07에는 격리 DB와 dummy Provider의 실제 8인 게임을 최종 지목까지 완주했습니다.
사망한 인간의 `FAST_FORWARD` command도 PostgreSQL action service에 연결했습니다.
`SAVE_AND_EXIT`와 `RESUME`의 실제 PostgreSQL 왕복도 smoke로 확인했습니다.
Backend는 서버 시작 시 중앙 `AiProgressWorker`를 실행해 열린 AI speech·night·vote
window를 비동기로 회복합니다. phase 전환은 마지막 필수 actor 제출을 처리하는
동기 PostgreSQL transaction에서만 수행합니다. 테스트 앱에서는 수동 command와의
경쟁을 막기 위해 `enable_background_worker=False`를 사용할 수 있습니다. worker 장애는
외부 예외 원문 없이 고정된 실패 단계로 기록합니다. 게임 진행과 AI 정보 확인·판단·
행동 선택·적용은 Backend 터미널과 `backend/logs/game-progress.log`에 JSON 한 줄씩
기록합니다. `run_id`는 서버 실행을, `sequence`는 그 실행 안의 발생 순서를 나타냅니다.
로그 시각은 UTC이며 파일은 5 MiB마다 회전하고 이전 파일 3개를 보관합니다.
실제 적용 성공은 DB transaction 성공 반환 뒤 기록하며 비공개 역할·밤 actor·대상,
프롬프트·모델 내부 추론 원문을 기록하지 않습니다.
게임 화면의 **AI 판단과 실행**에서 정보 확인 → 판단 → 선택 → 적용 순서와 공개
판단 근거(공개 단서·진술 비교·확인 질문·근거 부족·추가 의견 없음)를 확인할 수 있습니다.
근거는 모델이 선택한 제한된 유형의 요약이며 실제 사고 원문이나 사실 검증 결과가 아닙니다.
모델의 자발적 PASS, 더미 고정 행동, 장애로 인한 규칙 대체를 구분하고, 적용 완료 후에도
미완성 응답·인증·요청 제한·모델 접근·MCP 조회/제출 오류를 그대로 표시합니다.
밤과 투표에는 기존처럼 개별 actor·역할·대상·응답 여부를 공개하지 않습니다.

AI 프롬프트는 매 행동 전에 본인 역할을 확인하고, 역할 공개·은폐와 밤 능력을
상황에 맞게 활용하도록 안내합니다. 탐정은 실제 조사 결과가 있으면 탐정임을 밝히고
대상·조사 라운드·마피아 여부를 공개할 수 있습니다. 조사 결과가 `false`인 경우에는
‘마피아가 아님’만 알 수 있으므로 시민·의사 등 특정 직업으로 단정하지 않습니다.
의사는 보호 선택과 공개 위험을 고려하고, 시민은 진술 비교로 협력하며, 마피아는
정체 은폐와 역할 위장을 활용합니다. 이는 모델의 발언 지침이며 역할 판정 규칙을 바꾸지 않습니다.
페르소나의 말투·배경과 성향 수치를 질문 방식, 주장 강도, 감정, 협력, 발언 길이의
구체적인 지침으로 연결해 캐릭터별 표현 차이를 강화합니다. 200자 제한은 유지합니다.
종료 후 **▣ 게임 기록 보기**의 밤·투표 기록에는 밝은 회청색 카드와 짙은 글자색을
함께 지정했습니다. 결과 요약 숫자와 보조 설명도 다크 테마에 영향을 받지 않도록
색상을 지정해 밝은 카드에서 읽을 수 있게 했습니다.
처형 투표·재투표·최종 지목의 행동 패널도 제목, 안내, 잔여 시간, 공개 요약과
후보 이름·생존 표기를 검은색으로 지정해 흰 배경에서 읽을 수 있게 했습니다.
이 색상 수정은 자동 테스트 없이 합성 투표 화면을 Chromium 다크 테마로 열어
제목·안내·후보의 검은 글자와 선택 후 제출 버튼의 대비를 확인했습니다.

2026-09-07 12:08~~12:19 산장 9인 게임 복기 후, `agent_personas.parameters`의
기억 활용을 0.90~~0.98, 주장 강도를 0.65~0.90으로 높이고 캐릭터별 위험 감수·협력·
참여도를 조정했습니다. 정확한 preset별 값은 마스터플랜 5.3절과 기존
`004_seed_scenarios_and_personas.sql`에 있습니다. 의심·기만·감정·발언 길이와
검증 계약의 `reasoning_skill=0.5`는 유지합니다. 이는 모델 추론 effort 설정이 아닙니다.
프롬프트에는 발언자·원문 대조, 이미 답한 질문 반복 방지, 처형으로 뒷받침된 탐정
보고의 신뢰도 갱신, 비공개 투표 이력 추측 금지, 마지막 판정에서의 결론 제시를
반영했습니다. 의사는 다섯 번째 밤에도 신뢰할 탐정의 조사 전달 가치를 고려합니다.
해당 게임이 저장된 로컬 Backend `18000`의 preset 5건과 content_hash를 한 transaction으로
갱신하고 읽어 확인했습니다. 공유 DB에는 적용하지 않았습니다. persona는 매 context 조회에서
읽으므로 다음 AI 판단부터 적용되며, 이전 완료 게임의 대사·투표·역할은 변경하지 않습니다.

Agent의 구조화 응답 한도는 `LLM_MAX_OUTPUT_TOKENS=8192`이며 발언·밤 행동·투표와
교정 요청에 같은 설정을 적용합니다. 추론 모델은 내부 추론도 이 예산을 사용합니다.
대사 200자와 호출·job의 기존 시간 제한은 유지하므로 토큰 상향이 투표 마감 문제를
해결하지는 않습니다. 설정 변경 뒤에는 Backend를 재시작해야 합니다.

전체 공개 사건·발언은 `.env`의 `REDIS_URL`로 연결한 Redis에 게임별로 저장하며,
Frontend snapshot과 AI public context가 같은 전체 이력을 읽습니다. 최근 일부 발언으로
잘라 저장하지 않습니다. key는 `mafia:v1:conversation:{db_scope}:{game_id}`이며 DB 접속
대상을 구분하는 namespace, 상태 버전·cursor·checksum과 7일 TTL을 사용합니다.
소유권·현재 DB 버전을 확인한 후 공개 필드를 재검증하고, 캐시 누락·손상·장애 시
PostgreSQL 전체 원장에서 복구합니다. PostgreSQL은 영구 원본이며 개인 정보 scope와
비공개 역할 원장·모델 내부 추론은 이 캐시에 넣지 않습니다.

같은 게임의 승패·투표 원장 검토 결과는 다음과 같습니다. 투표 실행 문제는 아래 후속
병렬 투표 수정에 반영했고, 승패·최종 처형 상태 문제는 검토만 했습니다.

- 마피아는 3·5번이었고, 다섯 번째 밤 이후 최종 지목에서 시민 7번이 선택되어
`MAFIA / FINAL_NON_MAFIA_SELECTED`로 종료됐습니다. 현재 최대 5밤 규칙과 일치합니다.
- **AI 투표 45표 중 28표가 AUTO**였습니다. 1라운드 일반·재투표는 AI 생성 작업 없이
자동 선택됐고, 3라운드 일반·재투표는 일부 모델 응답이 마감 전에 완성돼도 batch에
반영되지 않았습니다. 인간 표가 있어야 AI를 시작하는 조회 조건과 순차 생성 후 전체
batch 저장 구조가 원인이었습니다. 파라미터 상향과 별도로 실행 구조를 수정했습니다.
- 최종 지목은 7번의 `PLAYER_EXECUTED` 이벤트를 발행하지만 엔진이 생존 상태를 바꾸지
않아 DB의 `alive=true`와 처형 표시가 불일치합니다. 승리 진영 계산에는 영향이 없으나
결과 화면의 상태·생존자 수 정합성을 정리해야 하는 미수정 사항입니다.
- 9번의 ‘2라운드에 6번 투표’ 발언은 실제 3번 투표와 달랐습니다. 자기 과거 투표가
context에 없는데 발언으로 만들어 낸 사례여서, 공개 득표만으로 개인 표를 추정하지
않도록 지침을 보완했습니다. 5번은 실제 마피아이므로 의도적인 혼란 유도와 시민의
기억 오류를 같은 성향 수치로 평가하지 않습니다.

이번 조정은 자동 테스트·추가 유료 게임 없이 소스·완료 게임 원장·설정 저장값을
확인했습니다. 새 값의 실제 대사·승률 개선은 아직 측정하지 않았습니다.

일반 투표·재투표·최종 지목은 window 시작부터 모든 미제출 AI가 병렬로 판단하고,
완료된 표부터 개별 저장합니다. 사용자 투표를 기다리지 않으며 다른 AI의 실패로
이미 저장된 표를 취소하지 않습니다. 투표 scheduler는 발언·밤 호출과 분리했고,
command commit이 새 투표 조회를 깨웁니다. 미해소 AI 표는 공개 버전·event를 올리지
않으며 인간이 같은 window에 첫 표를 제출한 경우의 한 버전 증가만 원장으로 검증해
허용합니다. 마지막 제출·마감에서만 결과를 해소하고, deadline에는 미제출자만 자동
선택합니다. 적용에는 Backend 재시작이 필요하며 새 환경 변수·migration은 없습니다.
재현 조건·원인·해결 과정·실행 확인은
[AI 병렬 투표 버그 리포트](docs/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md)에 기록합니다.
실제 로컬 9인 게임의 두 일반 투표에서 AI 7명·6명이 각각 0.141초·0.105초 간격 안에
판단을 시작했습니다. 인간이 AI 전원 제출 뒤 투표한 경우와 AI 판단 도중 제출한 경우 모두
AI 합계 13표가 AGENT로 저장됐고 AUTO는 0표였습니다. Frontend 화면도 확인한 뒤
게임을 저장했습니다. 자동 테스트·lint·전체 회귀와 별도 장애 주입은 생략했습니다.

최종 토론 snapshot도 현재 speech 제출 원장과 함께 복원됩니다.
PostgreSQL sync의 공개 event와 action window payload도 Frontend 정본 구조로 변환됩니다.
worker는 한 게임의 진행 오류가 다른 게임의 AI 진행을 막지 않도록 격리합니다.
순수 규칙 엔진은 기존 `GameEngine` facade를 유지하면서 플레이어 검증·사망 처리·
표준 승패·토론 입력·밤 역할 판정·투표 집계·replay 분기를
`backend/app/game_engine/` 모듈로 이동했습니다. 실제 `GameEngine`, deterministic
fallback, phase 전이 구현은 해당 package가 소유합니다. 기존 `agent/game_engine.py`, `fallback.py`, `state_machine.py`, `agent/rules/`는
모든 호출부를 새 정본으로 전환한 뒤 제거했습니다.
게임 API runtime은 router 전역 변수가 아니라 앱별 `app.state.game_runtime`에
주입되며, 테스트 앱과 운영 앱의 상태가 서로 공유되지 않습니다. PostgreSQL 실행
계층의 phase별 다음 행동 순서는
`backend/app/services/game/turn_order_service.py`가, 행동 제한 시간과 deadline은
`backend/app/services/game/action_timer_service.py`가 각각 담당하도록 분리하는
구조를 사용합니다. `window_service.py`는 두 결과를 기존 `ActionWindowInsert`로
조합하는 얇은 adapter로만 유지합니다. DB/API의 기존 `action_windows` 명칭은 저장
계약 호환을 위해 유지합니다. 현재 실제 구현 상태와 실행 경로는
[AI_MAFIA_CURRENT_CODE_STATUS.md](docs/AI_MAFIA_CURRENT_CODE_STATUS.md)에 기록합니다.
AI worker의 시작·종료는 FastAPI lifespan에서 앱별 runtime과 함께 관리합니다.
중앙 worker는 runtime facade의 AI 차례 조회·실행 메서드만 호출하며 PostgreSQL
transaction이나 Repository를 직접 소유하지 않습니다.
게임 실행 command의 공개 조합 경계는 `command_service.py`와
`lifecycle_service.py`, 실제 transaction은
`action_command.py`, `discussion_command.py`, `agent_discussion.py`, runtime 조합은
`postgres_runtime.py`가 담당합니다. 생성 transaction은
`services/game/creation_service.py`, 게임 목록·snapshot 조회와 순수 공개 projection은
`services/game/game_read_service.py`, DB row 변환은
`services/game/game_read_service.py`가 함께 담당합니다. event 조회·sync envelope와
event row의 Front operation 변환은 `services/game/event_sync_service.py`에 둡니다.
기존 `snapshot_service.py`와 `sync_service.py`는 전환 기간에만 호환 re-export로
유지할 수 있습니다. 별도 projection 파일은 만들지 않습니다.
`event_outbox`는 PostgreSQL event의 전달 원본으로 transaction에서 enqueue하며,
`services/outbox_service.py`의 publisher가 Redis fan-out을 담당합니다. 현재
publisher worker 자동 기동은 연결하지 않고, Redis 장애 시 DB 원본과 재처리 경계를
유지합니다.
MCP registry와 관리자 API 계약 테스트는 게임 실행 runtime과 분리된 synthetic
adapter를 사용하며, 실제 게임 흐름은 PostgreSQL 정본 경로를 사용합니다.
완료 게임 결과 projection은 `services/game/result_service.py`가 담당합니다. sync 조회와
snapshot 변환은 새 모듈로 이동했으며, 생성 seed·시나리오·persona·단서 조합은
`creation_service.py`, BEGIN_GAME·SAVE_AND_EXIT·RESUME transaction orchestration은
`lifecycle_service.py`가 담당합니다. 기존 API 호환을 위한 facade 클래스는
`game_service.py`에 유지합니다.
`FINAL_DISCUSSION` snapshot에서 발언용 `legal_actions`와 `SPEECH` window가 누락되어
마지막 토론이 멈추던 문제도 수정했으며, 서버를 종료한 상태의 PostgreSQL 전체 흐름
smoke 4개가 통과했습니다.
또한 밤 공격 후 메모리 상태만 변경되고 `game_players.alive`에 저장되지 않던 문제를
수정해, 마피아 공격 결과가 다음 snapshot에도 유지되도록 했습니다.
Frontend SSE bridge는 실제 변경이 있는 `envelope`와 제한된 진행 확인 tick을
Streamlit component state로 전달합니다. 현재 cursor를 그대로 돌려주는 no-op 응답은 폐기하며,
응답 stream이 종료되어도 마지막 `last_sequence`부터 자동 재연결해 phase 전환을
반영합니다. Backend `/events`는 연결을 유지하면서 변경 batch만 push하고 15초
간격 heartbeat만 보내므로, 변경 없는 stream 데이터가 페이지를 반복 rerun하지 않습니다.
Backend 중앙 AI worker는 만료된 밤·일반/재/최종 투표 window도 조회합니다.
이미 제출된 선택은 보존하고 무응답만 결정적 자동 선택으로 채워 해소합니다.
게임 command Front guard는 입력 형식만 정규화하고, 현재 phase·turn·window·대상
허용 여부는 Backend가 최신 transaction에서 최종 확인합니다.

## 개발상세플랜 정본 (2026-09-03)

중복·충돌하던 AI 마피아 계획과 계약을 `docs/개발상세플랜/`의 정본 문서로 통합했습니다.
섹터별 담당자는 작업 전에 [AGENTS.MD](AGENTS.MD)와 해당 정본을 읽고, coding AI
agent 한 세션을 마스터플랜의 WU 한 개 이하로 제한합니다.


| 문서                                                                                           | 기록된 내용                                                        |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| [AI_MAFIA_MASTER_PLAN.md](docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md)                               | 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터 소유권, WU와 CP                      |
| [AI_MAFIA_DB_DESIGN.md](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md)                                   | PostgreSQL·Redis schema, transaction, lock, migration과 보존 계약  |
| [AI_MAFIA_API_SPEC.md](docs/개발상세플랜/AI_MAFIA_API_SPEC.md)                                     | 일반·관리자·내부 Engine HTTP API와 MCP Resource·Tool 계약               |
| [AI_MAFIA_MCP_SERVER_DESIGN.md](docs/개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)                   | MCP runtime 구조, 보안 경계와 WU-M1A~WU-M8 실행·검증 계획                  |
| [AI_MAFIA_SCREEN_FLOW.md](docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md)                               | UUID 초기화, 사용자 게임·관전·피드백과 관리자 화면 흐름                            |
| [AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md](docs/개발상세플랜/AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md)   | Streamlit Front 전용 WU-F1~F8 기술 설계, 상태·동기화·협업 계약·보안·테스트·완료 기준  |
| [AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md](docs/개발상세플랜/AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md)     | Frontend–Backend 공개 API, SSE·CORS, 오류·private 경계와 공동 완료 조건 요약 |
| [AI_MAFIA_INDEPENDENT_CONTRACT.md](docs/개발상세플랜/AI_MAFIA_INDEPENDENT_CONTRACT.md)             | 세 섹터가 독립 구현할 때 공통으로 고정할 최소 연결 형식과 경계                          |
| [AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md](docs/개발상세플랜/AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md) | 게임 엔진·Agent Manager 모듈화 전략 임시 초안                              |
| [AI_MAFIA_CURRENT_CODE_STATUS.md](docs/AI_MAFIA_CURRENT_CODE_STATUS.md)                      | 현재 실제 코드 구조, 게임 흐름, 공개 API, 설정, 검증 결과와 제약                     |


다섯 MCP Resource의 상세 `data` schema는 API 명세 8.2절과 그 절이 명시적으로
참조하는 API 공통 모델만 정본이며 MCP 서버 설계서에는 URI·Engine scope 매핑과
비규범 예시만 둡니다.

문서 통합은 구현 완료 범위를 바꾸지 않습니다. 계약 변경은 영향받는 정본을 먼저
갱신하고 세 섹터가 합의한 뒤 구현합니다.

### 섹터별 독립 개발 기준

Front, Backend, MCP·Data 담당자는 정본 문서의 예시와 필드·enum·오류코드를 기준으로
각자 필요한 목데이터와 테스트 픽스처를 작성해 다른 섹터의 실행 프로세스 없이
단위·계약 관련 테스트를 수행할 수 있습니다. 공통 fixture 파일이나 mock server를
먼저 공동 작성하는 것은 필수 조건이 아닙니다.

- Front는 snapshot·sync operation·오류·SSE fixture로 화면과 상태 처리를 검증합니다.
- Backend는 synthetic 요청과 fake LLM/MCP transport로 엔진·공개 API·내부 API를
검증합니다.
- MCP는 정본의 세션 개설 토큰·session·Resource·Tool 계약과 fake Engine transport로
runtime을 검증합니다.
- 자체 fixture는 정본에 없는 필드·enum·상태 전이를 임의로 추가하지 않습니다.
- 통합 기준은 각 섹터의 fixture가 아니라 Backend `/openapi.json`과 정본 문서입니다.
- 공개 API, 내부 Engine API, MCP wire, DB schema 또는 화면 상태 소유권을 바꾸면
구현 전에 영향받는 정본을 갱신하고 세 섹터의 합의를 거칩니다.

따라서 독립 개발을 위해 별도 mock·fixture 체계를 먼저 완성할 필요는 없지만, 각
섹터는 자체 fixture의 계약 근거와 검증 명령을 완료 보고에 남겨야 합니다.

### 게임 규칙 계약 개정 (2026-09-02)

기획안 전체와 공통·섹터별 상세 플랜을 대조해 다음 후속 구현 계약을
`mystery-v1`·`scenario-v1`로 확정했습니다.

- 전체 6~9명, 탐정·의사·시민과 서로 정체를 모르는 마피아
- 첫날 낮은 좌석순 기본 1회 발언 후 무투표로 밤에 진입
- 텍스트 토론은 200자 이하의 턴 방식, 밤 행동은 20초·투표는 30초의
Backend 권위 deadline
- 다섯 개 시나리오와 플레이어별 알리바이·관찰 정보를 검증된 seed 기반
카탈로그로 배정하고 사용자별 직전 시나리오 제외
- 최대 다섯째 밤 뒤 표준 승패가 없으면 최종 지목으로 종료
- 투표는 후보별 집계만 공개하고 밤 사망 역할은 숨기며 처형 역할만 공개
- AI GM은 공개 확정 이벤트만 받고 전체 비공개 상태는 Backend만 보유

이 규칙의 Backend 엔진·시나리오·deadline 코드와 테스트는 작성됐지만 실제 영속 API와
Front·MCP 연결까지 완료됐다는 뜻은 아닙니다. 규칙 수준의 밸런스는
유료 LLM 없이 6~9명별 heuristic bot 시뮬레이션으로 검증합니다. 실제 Provider smoke는
명시적으로 opt-in한 소수 표본만 사용하며 token·비용 KPI를 만들지 않습니다.
마스터플랜의 개인 정보 문장 예시를 바탕으로 `004_seed_scenarios_and_personas.sql`에
최대 9좌석용 최소 90개 template record를 작성했습니다. 실제 환경에 적용하기 전에
문장별 역할 중립성·무모순을 제품 검수해야 `scenario-v1` 콘텐츠가 완료됩니다.

## 프로젝트 구조

```text
.
├── AGENTS.MD                         # 개발·기여 작업 규칙
├── README.md                         # 전체 설정·실행·검증 안내
├── .env.example                      # Backend 환경 변수 예시
├── run_openai.sh                     # OpenAI Backend·MCP·Front 동시 실행
├── pyproject.toml                    # ai-mafia 통합 런타임·개발 의존성 및 도구 설정
├── backend/
│   ├── app/main.py                   # FastAPI 생성과 router·오류 처리 등록
│   ├── app/routers/                  # health·공개 게임·내부 Engine endpoint
│   ├── app/schemas/                  # 요청·응답 validation 계약
│   ├── app/services/                 # UUID 사용자·게임 유스케이스
│   │   └── game/                     # 게임 업무 Service·Repository 조합·공용 계약
│   │       ├── postgres_helpers.py   # PostgreSQL 상태 복원·replay 공통 helper
│   │       ├── service_errors.py     # 엔진 오류·API 오류 변환
│   │       ├── runtime_factory.py    # 게임 runtime·Agent adapter composition root
│   │       ├── postgres_runtime.py   # router·worker가 호출하는 PostgreSQL facade
│   │       ├── turn_order_service.py # 다음 행동 주체·순서·cycle 계산
│   │       ├── action_timer_service.py # 행동 deadline·잔여 시간 계산
│   │       ├── window_service.py     # phase별 action window 조합·검증
│   │       ├── actor_context.py      # HUMAN·AGENT 공통 행동 주체 계약
│   │       ├── game_read_service.py  # 게임 목록·snapshot 조회와 row 변환
│   │       ├── event_sync_service.py # event 변환·sync envelope 조합
│   ├── app/models/identity.py        # UUID 내부 사용자 모델
│   ├── app/repositories/             # PostgreSQL CRUD·row 변환 저장소
│   ├── app/infrastructure/           # migration·PostgreSQL·내부 HMAC 구현
│   ├── app/agent/                    # Agent 정책·projection·orchestration (DB·Engine 런타임 import 없음)
│   │   └── activity.py               # 공개 AI 진행 메모리와 비밀정보 없는 순차 로그
│   ├── app/game_engine/               # 순수 게임 규칙·phase·결정적 RNG 정본 package (현재 phase가 행동 실행 포함)
│   ├── app/llm_provider/             # 현재 LLM Provider adapter
│   ├── app/mcp/                      # Backend Agent용 MCP context client·registry
│   ├── migrations/                   # Backend 작성 SQL migration(MCP 실행)
│   ├── logs/                         # 실행 시 생성되는 순환 진행 로그 (Git 제외)
│   ├── tests/
│   └── README.md
├── frontend_user/
│   ├── app.py                        # UUID bootstrap·화면 dispatcher
│   ├── app_pages/home_page.py         # 게임 목록·이어하기 홈
│   ├── app_pages/game_create_page.py  # 새 게임·인원 선택·생성 UI
│   ├── app_pages/settings_page.py    # UUID 확인·복구·교체 화면
│   ├── components/identity_bridge.py # 브라우저 local storage UUID bridge
│   ├── components/theme.py           # 사용자 화면 공통 시각 토큰·접근성 스타일
│   ├── components/browser_components/identity/ # 정적 UUID bridge
│   ├── core/identity.py              # UUID v4 검증·생성
│   ├── core/session.py               # identity scope·session mirror
│   ├── core/api_client.py            # UUID 공개 Backend API client
│   ├── .streamlit/secrets.toml.example
│   └── tests/
├── frontend_admin/                   # read-only 관리자 대시보드·게임 목록·상세
├── mcp_server/
│   ├── pyproject.toml, uv.lock        # Python 3.12·MCP SDK 1.29.1 독립 실행 환경
│   ├── mafia_game/                   # 최소 FastMCP 등록부·Backend HTTP adapter
│   ├── tests/                        # 등록·adapter·ASGI 왕복 테스트
│   └── mcp_2/                        # 후속 MCP 독립 예약 패키지
├── docs/
│   ├── AI_MAFIA_GAME_TEST_GAP_REPORT.md # 게임 테스트 관점 미구현·미연결·규칙 차이 점검표
│   ├── AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md # 자동 투표 원인·병렬 처리 수정·실행 확인
│   ├── AI_MAFIA_UI_UX_PLAYTEST_REPORT.md # 실제 6인 게임 UI·UX 관찰·정본 대조·개선 우선순위
│   └── 개발상세플랜/
│       ├── AI_MAFIA_MASTER_PLAN.md    # 제품 규칙·시나리오·아키텍처·WU/CP 정본
│       ├── AI_MAFIA_DB_DESIGN.md      # PostgreSQL·Redis 정본
│       ├── AI_MAFIA_API_SPEC.md       # 공개·내부·MCP API 정본
│       ├── AI_MAFIA_MCP_SERVER_DESIGN.md # MCP runtime·Data WU 구현 설계
│       ├── AI_MAFIA_SCREEN_FLOW.md    # 사용자·관리자 화면 정본
│       ├── AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md # Front WU-F1~F8 파생 기술 설계안
│       ├── AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md # Frontend–Backend 연동 인계 요약
│       └── AI_MAFIA_INDEPENDENT_CONTRACT.md # 섹터 간 최소 연결 형식·독립 개발 규칙
└── scripts/                          # 운영·개발 보조 스크립트
```

### 로컬 가상환경과 의존성 준비

2026-09-07 macOS에서 Python 3.12.11로 다음 환경을 준비했습니다. 기존 루트·MCP
환경은 재사용하고 나머지 환경은 컴포넌트의 의존성 파일에 맞춰 생성했습니다.


| 위치                     | 용도·설치 기준                                                    |
| ---------------------- | ----------------------------------------------------------- |
| `.venv`                | 기존 통합 환경, 루트 `pyproject.toml`·`uv.lock`의 dev 포함             |
| `backend/.venv`        | `backend/requirements.txt`, pytest·pytest-asyncio·httpx2 포함 |
| `frontend_user/.venv`  | `frontend_user/requirements-dev.txt`                        |
| `frontend_admin/.venv` | `frontend_admin/requirements.txt`와 테스트용 `pytest>=8,<9`      |
| `mcp_server/.venv`     | 독립 `pyproject.toml`·`uv.lock`의 dev 포함, MCP SDK 1.29.1       |


기존 환경을 삭제하거나 덮어쓰지 않고, 없는 컴포넌트 환경만 `uv venv --python 3.12 <컴포넌트>/.venv`로 만듭니다. 설치·갱신은 저장소 루트에서 다음과 같이 수행합니다.

```bash
uv sync --locked --dev
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
uv pip install --python frontend_user/.venv/bin/python -r frontend_user/requirements-dev.txt
uv pip install --python frontend_admin/.venv/bin/python -r frontend_admin/requirements.txt 'pytest>=8,<9'
uv sync --project mcp_server --locked --dev
```

루트 dev에 `httpx2`를 추가하고 merge 이후 불일치하던 lock을 갱신했습니다.
컴포넌트 requirements는 범위 설치이므로 루트 lock 환경과 패치 버전이 다를 수 있습니다.
각 환경의 `uv pip check --python <환경>/bin/python`은 모두 통과했습니다.

로컬 `.vscode/settings.json`, `.zshenv`, `.zshrc`, `project-venv.zsh`는 macOS의 새
VS Code 터미널에서 사용자 shell 초기화 뒤 가장 가까운 `.venv`를 선택합니다.
루트는 통합 환경, `cd backend`·`frontend_user`·`frontend_admin`·`mcp_server`는 각
환경으로 전환하고 저장소 밖에서는 관리하던 환경을 해제합니다. 새 터미널과 폴더
이동으로 `VIRTUAL_ENV`·`sys.executable`을 확인했습니다. `.vscode/`와 가상환경은
Git 제외 대상인 로컬 설정입니다. 기존 터미널은 새로 열어야 하며 외부 터미널에서는
`source backend/.venv/bin/activate`처럼 직접 활성화합니다.

### Windows 컴포넌트별 설치

Windows에서는 컴포넌트별 환경을 분리합니다. 기존 `.venv`가 있으면 삭제하지
않고 재사용하며, 반드시 환경 내부 Python으로 설치합니다.

```powershell
& ".\backend\.venv\Scripts\python.exe" -m pip install -r ".\backend\requirements.txt"
& ".\frontend_user\.venv\Scripts\python.exe" -m pip install -r ".\frontend_user\requirements-dev.txt"
& ".\frontend_admin\.venv\Scripts\python.exe" -m pip install -r ".\frontend_admin\requirements.txt"
```

이번 환경 준비는 macOS에서 수행했습니다. Windows 환경 및 PowerShell 자동
전환 스크립트는 이번에 준비·검증하지 않았습니다.

현재 일반 사용자 Frontend는 WU-F1 UUID-only bootstrap과 공통 화면 테마를 사용합니다. 브라우저
저장 key는 `ai_mafia_user_id_v1`이며, Backend에는 UUID를 `X-User-Id` header로만
전달합니다. 홈·게임·피드백 화면은 화면 정본의 상태 표현과 반응형·접근성 스타일을
공유하며, 게임 상태와 결과의 원본은 계속 Backend snapshot입니다.

Backend의 현재 게임 API는 canonical `mystery-v1` 계약을 사용하고, Backend에 남아 있는
기존 migration 이력의 `scaffold_*` schema는 보존하지만 runtime에서는 사용하지 않습니다.
Frontend의 Scaffold 전용 실행 경로와 client는 제거되었으며, Backend의 게임 API는
PostgreSQL 정본 runtime만 사용합니다. 따라서 화면 확인과 API 테스트 전에 PostgreSQL
migration과 연결 환경을 준비해야 합니다.
관리자 통계 화면은 종료된 게임만 분석하며, 종료 게임이 없을 때는 빈 통계를 오류로
표시하지 않고 안내 문구를 보여줍니다.

관리자 화면에서는 Backend `ADMIN_USER_IDS`에 이미 등록된 UUID를 직접 입력하고
확인한 뒤 적용합니다. 브라우저 저장 응답과 Backend 권한 확인이 끝나야 데이터가
표시되며, 거부되면 UUID 교체나 재시도를 할 수 있습니다. 목록의 상태·단계 필터는
실제 API query에 전달하고 `game_id` 주소로 상세를 다시 열 수 있습니다.
UUID를 입력하는 것만으로 관리자 권한이 등록되지는 않습니다.

`frontend_user`와 `frontend_admin`은 Backend만 HTTP로 호출합니다. Frontend가 DB,
Redis, MCP 서버에 직접 연결하거나 MCP 서버끼리 서로의 내부 모듈을 import하지
않습니다. MCP 섹터가 DB·Redis 실행 환경을 운영해도 `mcp_server/mafia_game`
runtime은 DB·Redis에 직접 접근하지 않습니다.

MCP 구현부터 `mcp_server/`를 독립 프로젝트 루트, `mafia_game`을 공식 Python import
package로 사용합니다. composition root는 `mafia_game/main.py`, module 진입점은
`mafia_game/__main__.py`, package test 위치는 `mcp_server/tests/`로 고정했습니다.
독립 `pyproject.toml`과 `uv.lock`은 Python 3.12와 MCP SDK 1.29.1을 정확히 고정합니다.
현재 runtime은 FastMCP 표준 session을 사용하며 별도 bootstrap·HMAC·capability
registry를 구현하지 않습니다. Resource template은
`mafia://context/current/{game_id}/{user_id}`와
`mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}`이며 두 Resource는
`application/json`을 반환합니다. Prompt는 `agent_instruction`, Tool은 `submit_action`입니다.
AI는 자기 actor의 public/me/turn/persona를 차례로 조회하고 명시적인 Tool 승인과
window/version 일치를 확인합니다. 시각은 UTC RFC 3339의 `Z`와 `+00:00`을 허용합니다.

## 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한(MCP 섹터 운영 책임)
- Redis 실행 환경(MCP 섹터 운영 책임, 게임 기능 구현 단계부터 필요)
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

```bash
uv sync --dev
```

기존 LLM adapter는 선택한 Provider key를 사용합니다. 실제 값은 `.env.example`의
placeholder만 참고하고 Git에 넣지 않습니다.

## Backend·Data Infrastructure 환경 설정

기존 `.env`에는 다른 로컬 설정이나 비밀값이 있을 수 있으므로 덮어쓰지 마세요.
아래 복사는 현재 로컬 개발용 placeholder 시작점일 뿐입니다. 운영에서는
`.env.example` 전체를 한 프로세스에 로드하지 않고 아래 allowlist대로 필요한
키만 비밀 저장소나 프로세스 환경으로 주입합니다.

```bash
cp .env.example .env
chmod 600 .env
```

필수·기본 설정은 다음과 같습니다.

```dotenv
DATABASE_URL=postgresql://app_user:change-me@localhost:5432/Team4_Proj
DATABASE_MIGRATION_URL=postgresql://migration_user:change-me@localhost:5432/Team4_Proj
DATABASE_NAME=Team4_Proj
```

- `TEAM_DATABASE_URL`에는 실제 원격 PostgreSQL의 DML 최소 권한 계정을 설정합니다.
`TEAM_DATABASE_URL`이 없을 때만 `DATABASE_URL`을 로컬 테스트 fallback으로 사용합니다.
- `TEAM_DATABASE_URL`이 설정되면 URL의 database path를 보존하며, 원격 검증 대상은
`DATABASE_NAME`으로 덮어쓰지 않습니다.
- `DATABASE_MIGRATION_URL`은 migration runner에 필수인 전용 DDL 연결입니다.
runtime DSN으로 대체하지 않으며 Backend runtime 프로세스에는 전달하지 않습니다.
- `DATABASE_URL` fallback일 때만 URL의 DB 경로를 `DATABASE_NAME`으로 바꿉니다.
`DATABASE_NAME` 기본값은 `Team4_Proj`입니다.
- 최소 FastMCP process는 `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT`만
읽습니다. 기본 Backend 주소는 `http://127.0.0.1:8000`, MCP 주소는
`http://127.0.0.1:8100/mcp`입니다. 현재 연결은 loopback 개발용이며 인증·TLS·운영
보안은 이 최소 전환 범위에 포함하지 않습니다.
- Backend 중앙 AI worker는 `MCP_SERVER_URL`로 FastMCP 서버 주소를 주입받아
context 조회와 Agent action 전달에 사용합니다. MCP가 중지되거나 LLM 호출이
실패하면 현재 AI speech window는 기존 규칙 기반 PASS fallback으로 종료됩니다.
- LLM Provider 설정은 `config.py`에서 선택값과 모델·필수 키를 검증합니다.
`LLM_PROVIDER=dummy`는 발언에 고정 PASS를 반환하는 테스트 전용 제공자입니다.
실제 추론은 선택한 Local/OpenAI/Gemini adapter를 사용합니다. 이번 수정의 외부 호출은
fake로 검증했으며 실제 모델의 발언 품질은 별도 실행 확인이 필요합니다.
앱 수준의 token 사용량 집계·비용·게임별 예산 설정은 MVP에서 사용하지
않습니다. 중단된 Agent worker는 조정 불가능한 고정 lease와 fencing token으로
회수하며, 만료·실패한 동일 AI job은 다음 예약 시 lease를 재사용해 재시도할 수
있습니다. LLM·MCP 호출 동안 PostgreSQL transaction이나 Redis
game lock을 보유하지 않습니다.
- Local Provider는 OpenAI 호환 `/chat/completions` 형식과 JSON 응답을 사용합니다.
게임 proposal 요청에서는 `think=false`를 사용해 불필요한 reasoning 출력을 끕니다.
모든 제공자에 역할·발언 목적·현재 job의 JSON schema를 전달합니다. 밤 행동·투표에서
잘못된 PASS나 허용되지 않은 대상을 반환하면 한 번 교정하고, 실패 시 `FALLBACK`으로
구분합니다. 대체 대상은 승인된 후보 UUID를 정렬한 뒤 게임·window·actor·행동 종류로
결정적으로 선택해 후보 순서와 첫 좌석으로의 편향을 없앱니다. 합법 대상이 없으면
선택을 만들지 않습니다. 정상 모델 선택은 그대로 유지합니다.
- OpenAI 추론 모델(`gpt-5*`, `gpt-6*`, `o1*`, `o3*`, `o4*`)에는 낮은 reasoning effort와
기본 8192토큰(`LLM_MAX_OUTPUT_TOKENS`)의 출력 여유를 적용하며 설정값이 작아도
최소 4096토큰을 확보합니다. 기존 400토큰은 추론 중 소진되어
최종 JSON이 나오지 않을 수 있습니다. `incomplete`는 별도 오류로 구분하며 자동
Provider 전환은 하지 않습니다. SDK 자동 재시도를 끄고 `store=False`로 요청합니다.
근거: [OpenAI 추론·출력 한도 문서](https://developers.openai.com/api/docs/guides/reasoning#allocating-space-for-reasoning).
출력 토큰 설정과 프롬프트 수정 반영에는 Backend 재시작이 필요합니다.
실제 Local endpoint가 실행되지 않은 환경에서는 유료 API 없이 fake transport로
성공·timeout·잘못된 응답 처리를 검증합니다. Ollama 호환 서버에는
`response_format=json_object`를 요청하고 Backend가 최종 proposal schema를 검증합니다.
- FastMCP 전환은 `mcp_server/mafia_game/main.py`의 독립 composition 경계에서 실행되며,
최소 Resource·Prompt·AI 행동 요청 Tool 등록과 initialize·호출·Backend 오류 왕복을
`mcp_server/tests/test_fastmcp_roundtrip.py`에서 ASGI fixture로 검증합니다.
- 기존 custom bootstrap·HMAC·nonce·session registry runtime은 제거되었으며, MCP protocol
session은 FastMCP SDK 경계에서만 관리합니다.
- FastMCP 계획은 Resource·Prompt·Tool 컨텍스트 제공에 집중하며, Tool의 행동 판정과
상태 변경은 Backend가 담당합니다. MCP 내부 HMAC·bootstrap·session 상태 머신은
FastMCP 전환 범위에서 제외합니다.
- 기존 FastMCP 전환안은 보관용입니다. 현재 Resource data와 scope 계약은
`docs/개발상세플랜/AI_MAFIA_API_SPEC.md` 8.2절을 따릅니다.
- MCP 테스트는 등록부·adapter·ASGI 왕복을 대상으로 하며 Backend 회귀 테스트와 함께
실행합니다.
- 현재 MVP 동기화는 PostgreSQL `game_events` polling을 정본으로 사용하며, 기존
`event_outbox`는 migration·호환 구조로 보존합니다. `LLM_MAX_OUTPUT_TOKENS`는
실제 Agent 요청에 적용하고 legacy timeout·비용 단가는 사용하지 않습니다.
- 기존 DB 게임 흐름 smoke test는 `py -m pytest backend/tests/test_postgres_game_flow.py -q`로
실행합니다. 테스트는 고유 UUID와 실행 ID를 사용하고 종료 시 생성한 사용자·게임·Redis
키만 정리합니다.
- 최소 FastMCP는 `BACKEND_API_URL`을 Backend base URL로 사용하고 `/internal/mcp/*`
경로를 호출합니다. MCP endpoint는 `MCP_LISTEN_HOST`와 `MCP_LISTEN_PORT`로 정합니다.
- Backend는 `CORS_ALLOWED_ORIGINS`에 등록된 Front origin에만 SSE fetch preflight와
동기화 header를 허용합니다. 활성 밤·투표 window의 `remaining_ms`는 저장된
`deadline_at`을 기준으로 매 snapshot마다 계산하며, sync cursor 불일치 시 전체
snapshot으로 복구합니다.


| 환경 소비자            | 허용하는 AI 마피아 관련 키                                                                                                                                                          | 주입 금지                                       |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Front 서버          | Backend URL                                                                                                                                                               | DB·Redis·LLM·MCP/Engine secret              |
| Backend runtime   | `TEAM_DATABASE_URL`, `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, game state keyring, LLM Provider·model·key, `ADMIN_USER_IDS`, `MCP_SERVER_URL`, `CORS_ALLOWED_ORIGINS` | `DATABASE_MIGRATION_URL`, MCP runtime 전용 설정 |
| migration 실행 프로세스 | `DATABASE_MIGRATION_URL`, 비교용 `TEAM_DATABASE_URL`/`DATABASE_URL`·`DATABASE_NAME`                                                                                          | LLM·MCP secret                              |
| MCP runtime       | `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT`                                                                                                                   | DB·Redis·LLM·인증 secret                      |


로컬에서도 실 자격증명을 채운 공용 루트 `.env`를 Backend와 MCP가 함께 읽게 하지
않습니다. migration 자격증명은 migration 명령 프로세스에만 일시 주입하고, MCP
서버는 자체 allowlist 밖 환경변수를 읽지 않도록 fail-closed합니다.

섹터 작업에서는 MCP 담당자가 PostgreSQL·Redis를 구축하고 실제 접속 값을 비밀
채널로 Backend 담당자에게 제공합니다. Backend 담당자는 제공받은 URL을 소비하며
DB·Redis 프로세스를 직접 설치·기동하지 않습니다. 실제 URL·비밀번호는 문서,
로그, 완료 보고에 기록하지 않습니다.

`Team4_Proj` 데이터베이스는 앱이 만들지 않습니다. MCP 담당자가 migration 전에
관리 도구로 데이터베이스, DDL migrator 계정과 DML runtime 계정을 분리해
준비합니다. schema 생성·변경 권한은 migrator에만, 애플리케이션에 필요한
테이블 DML 권한은 runtime에만 부여합니다.

## 데이터베이스 마이그레이션

Backend가 작성·소유하는 `backend/migrations/`의 SQL을 MCP 담당자가 이름순으로
실행합니다. 아래 명령은 Backend 실행기를 사용하지만 실행 책임은 MCP 섹터에
있습니다.

일반 `Settings.from_env()`와 `get_settings()`는 DDL 환경키를 조회하거나 보관하지
않습니다. CLI만 `Settings.from_migration_env()`로 별도 설정을 만들며 runtime 캐시를
재사용하지 않습니다. runner는 전용 `DATABASE_MIGRATION_URL`만 DDL 연결에 사용합니다. runtime effective DSN과
percent-decoding한 DB 경로를 대소문자까지 비교하며 불일치하면 연결 전에 거부합니다.
URL의 계정·경로를 query로 덮어쓰는 옵션은 거부하고 `sslmode` 같은 일반 옵션은
보존합니다. host·port의 물리적 동일성은 보장하지 않으므로 실행 담당자가 대상 서버와
DDL 권한을 확인해야 합니다. 전용 DSN과 비교용 runtime DSN은 migration 프로세스에만
필요 범위로 주입하고 실제 값은 shell history·로그·문서에 남기지 않습니다.
CLI는 성공 시 SQL 파일명과 개수, 실패 시 고정 메시지와 실패 종료 코드만 출력합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

현재 seed 정본은 `004_seed_scenarios_and_personas.sql` 하나이며, 중복된 `004` 번호의
seed 파일을 함께 두지 않습니다. `001`·`002` migration은 legacy `users`·`oauth_identities`와 `scaffold_*` 게임
테이블을 생성합니다. `003_create_mystery_v1_schema.sql`은 기존 객체와 데이터를
삭제하지 않고 `users.last_seen_at`을 보강한 뒤
[DB 설계 정본](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md)의 canonical `mystery-v1`
테이블, 복합 FK, 상태 제약과 조회 index를 순방향으로 추가합니다.
`004_seed_scenarios_and_personas.sql`은 정본 시나리오 5개, 시나리오별 알리바이 9개와
관찰 9개로 구성된 최소 90개 문장, 최소 활성 persona 한 개를 고정 key 기반으로
멱등 등록하고 콘텐츠 SHA-256 hash와 승인 시각을 기록합니다. legacy cleanup은 아직
포함하지 않으며, 적용된 migration 파일은 수정하지 않고 이후 번호의 순방향
migration으로 확장합니다.

## Frontend 설정

Frontend는 Google 로그인 없이 브라우저 localStorage에 UUID v4를 저장하고,
Backend 요청의 `X-User-Id` header로 사용자 scope를 전달합니다. UUID는 인증 수단이
아니므로 신뢰된 로컬·사설망 환경에서만 사용합니다. Backend 주소만 설정합니다.

```bash
cp frontend_user/.streamlit/secrets.toml.example \
  frontend_user/.streamlit/secrets.toml
chmod 600 frontend_user/.streamlit/secrets.toml
```

실제 `.env`와 `secrets.toml`은 Git 무시 대상이며 이동·커밋하지 않습니다.

## 실행

### 브라우저 게임 1회 검증과 후속 수정 (2026-09-07)

후속 수정은 [보고서 8절](docs/AI_MAFIA_GAME_TEST_GAP_REPORT.md#8-수정권고-반영과-ai-진행-표시)에
기록합니다. UUID 초기 응답 전 API 요청을 막고 localStorage 복구 확인 뒤 사용자 scope를
교체하며, 홈 목록 cache와 UUID 표시를 함께 초기화합니다. 새 게임은 성공 직후 실제
참가자 이름이 있는 완료 화면으로 이동하고 이전 생성 결과를 재사용하지 않습니다.
홈은 최신 20개에서 상태별 최대 3개를 표시하고 수동 새로고침·홈 이탈·30초 경과 뒤
다음 진입에서 목록을 갱신합니다. TTL이 만료돼도 기존 카드와 홈·설정 입력을 먼저
처리하고 홈에 남아 있을 때만 목록을 조회하므로 첫 클릭이 사라지지 않습니다.
일반 피드백도 홈 버튼에서 열 수 있습니다.

진행 로그는 저장소 루트에서 다음 명령으로 순서대로 확인할 수 있습니다.

```bash
tail -f backend/logs/game-progress.log
```

`STARTED → CONTEXT_READY → DECIDING → DECIDED → APPLIED`가 정상 AI 처리 흐름이며,
기본 행동·오류·중복은 `FALLBACK`·`FAILED`·`SKIPPED`로 구분합니다. dummy Provider는
고정 행동임을 설명에 표시합니다. 공개 발언 진행 표시는 게임당 최근 50건, 최대
128게임의 메모리에 한정하고 서버 재시작 시 비워집니다. 영구 게임 이력은 DB의
공개 이벤트와 확정 행동 원장에서 복원합니다.

Agent가 선택을 마쳤어도 실제 행동 저장에 실패하면 같은 게임·window·version의
미제출 작업만 lease 반환 또는 만료 후 재시도합니다. 저장된 선택은 Provider를 다시
호출하지 않고 검증해 사용하며, 이미 제출된 행동이나 지난 window에는 적용하지 않습니다.

이번 수정 검증은 기존 데이터와 분리한 임시 PostgreSQL에서 진행했습니다. 검증용
사용자 화면은 [http://127.0.0.1:18501](http://127.0.0.1:18501), 관리자 화면은 [http://127.0.0.1:18502](http://127.0.0.1:18502)이며,
Backend/MCP는 각각 18000/18100 포트입니다. 모두 loopback에서 실행하고 dummy Provider를
사용합니다. 임시 DB는 `team4-game-qa-20260907` 컨테이너이며 종료 시 데이터가 사라집니다.
실제 `.env`·secrets·운영 계정·keyring은 변경하지 않았습니다. 기존 설정을 사용하는
8000/8100 Backend·MCP도 수정 코드와 dummy Provider로 재시작했으며, 일반 사용자
접속 포트는 8501입니다. 대량 테스트와 migration은 격리 QA DB에서만 실행했습니다.

처음 실행한 6인 게임의 발견 사항은 보고서 7절에 보존했습니다. 수정 후에는 별도의
**8인·인간 시민 게임**에서 생성·발언·저장·재개·투표·사망 후 관전·최종 지목·피드백을
진행했습니다. 낮 6일차/라운드 5의 최종 지목 실패로 마피아 승리가 확정됐고, 밤 기록
5개·투표 기록 5개·공개 이벤트 83개가 결과에 남았습니다. 결과에서 새 6인 게임을
만들어 탐정 조사 표시·저장 재개·사망 후 빠른 진행 선택과 종료도 확인했습니다.
탐정 결과는 본인 정보 영역에서 이름·밤 번호·마피아 여부로 표시합니다. 결과의
마지막 투표 표시는 해당 투표의 round/phase를 사용하며 실제 종료 원인과 구분합니다. 실제 LLM 품질이나 모든
역할의 사람 입력을 이 한 판에서 검증한 것은 아닙니다.

2026-09-07에는 같은 격리 환경의 Orca 내장 브라우저에서 **6인·인간 탐정 게임**을
추가로 완주해 UI·UX를 점검했습니다. 생성·발언·저장·재개·자동 밤 행동·투표·결과
기록은 정상 동작했지만, 누적 타임라인 아래에 인간 행동 패널이 묻혀 탐정 조사와
낮 투표를 놓치고 자동 선택으로 처리되는 문제를 확인했습니다. 실게임 근거, 화면
정본 대비 차이와 WU별 개선 순서는
[UI·UX 플레이테스트 보고서](docs/AI_MAFIA_UI_UX_PLAYTEST_REPORT.md)에 기록했습니다.

홈을 제외한 새 게임 설정·생성 완료·역할 공개·게임 진행·결과·일반 및 게임별 피드백
화면에는 공통 `뒤로가기`와 `홈` 버튼이 표시됩니다. 뒤로가기는 검증된 앱 내부 방문
기록을 따르고 기록이 없으면 홈으로 이동합니다. 홈 이동은 진행 게임·작성 중 입력과
결과 불명 요청을 보존하고 홈 목록 cache만 무효화해 최신 게임 상태를 다시 조회합니다.
두 버튼은 모바일에서도 유지됩니다.

### 직접 실행

MCP 담당자가 전용 테스트 PostgreSQL·Redis의 대상과 migration·seed 상태를 확인한
뒤 Backend를 실행합니다. Backend worker는 DB에 열린 AI 차례를 처리하므로 공유
게임 데이터와 분리된 환경을 사용합니다. 첫 게임 검증은 dummy Provider로 진행합니다.

```bash
LLM_PROVIDER=dummy .venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
```

OpenAI Provider로 실행할 때는 루트 `.env`에 `OPENAI_API_KEY`와 `OPENAI_MODEL`을
설정하고, migration·seed가 준비된 격리 저장소를 `AI_MAFIA_DATABASE_URL`과
`AI_MAFIA_REDIS_URL`에 지정한 뒤 전용 스크립트를 사용합니다. 팀 공유
`TEAM_DATABASE_URL`과 같은 DB는 여러 Backend worker가 한 게임을 선점할 수 있으므로
스크립트가 시작을 거부합니다. 스크립트는 키와 접속 URL을 하드코딩하거나 출력하지 않고
루트 `.env`를 `python-dotenv`로 읽으며, Backend에만 `LLM_PROVIDER=openai`를 적용합니다.
Backend·MCP·일반 사용자 Front를 함께 실행하고, `Ctrl+C` 또는 한 프로세스의 종료 시
나머지 프로세스도 정리합니다. Front와 MCP에는 OpenAI·DB 비밀 환경 변수를 전달하지
않습니다.

```bash
./run_openai.sh --check  # 유료 API 호출 없이 세 런타임 설정·import 검증
./run_openai.sh          # Backend·MCP·Front 동시 실행
```

동시 실행 주소는 Backend `http://127.0.0.1:18000`, MCP
`http://127.0.0.1:18100/mcp`, Front `http://127.0.0.1:18501`입니다.
다른 프로젝트와 포트가 겹치면 세 주소를 함께 맞추도록 실행 포트를 바꿀 수 있습니다.

```bash
AI_MAFIA_BACKEND_PORT=28000 AI_MAFIA_MCP_PORT=28100 \
AI_MAFIA_FRONTEND_PORT=28501 ./run_openai.sh
```

수동 Backend의 health 주소는 `http://127.0.0.1:8000/health`, 동시 실행 스크립트의
health 주소는 `http://127.0.0.1:18000/health`이며 정상 응답은 `{"status":"ok"}`입니다.

Mafia Game MCP는 Backend를 먼저 실행한 뒤 최소 FastMCP process로 실행합니다. 아래
명령은 저장소 루트에서 실행하며, 개발 환경에서는 loopback 연결만 사용합니다.

```bash
uv sync --project mcp_server --locked --dev
(cd mcp_server && .venv/bin/python -m mafia_game)
```

기본 endpoint는 `http://127.0.0.1:8100/mcp`입니다. `/health`나 다른 공개 endpoint는
추가하지 않습니다. FastMCP composition에는 실제 게임 context를 읽고 Backend
command를 호출하는 Resource·Prompt·AI 행동 요청 Tool이 등록됩니다. 게임 판정과
상태 변경은 Backend/GameEngine이 수행합니다.

일반 사용자 앱은 별도 터미널에서 실행합니다.

```bash
uv run streamlit run frontend_user/app.py --server.port 8501
```

Windows에서 `uv`를 사용하지 않는 경우 프로젝트 가상환경의 Python으로 실행할 수
있습니다.

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m streamlit run ".\frontend_user\app.py" --server.port 8501
```

브라우저에서 [http://localhost:8501](http://localhost:8501)을 엽니다. Backend
설정이 없거나 연결되지 않으면 고정된 연결 오류 안내를 표시합니다.

`test_process_backend_roundtrip.py`는 Backend·FastMCP subprocess와 실제 DB를 사용하는
통합 테스트입니다. 독립 MCP 가상환경에는 Backend 의존성이 없으므로 아래 테스트
절의 실행 조건을 먼저 확인하세요.

관리자 앱은 read-only 통계·게임 목록·상세 화면을 제공합니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 entrypoint는 실행 위치와 무관하게 저장소 루트를 import 경로에 등록해
`frontend_admin` 패키지를 불러옵니다.

## 테스트와 정적 검사

DB·Redis·유료 Provider 없이 실행할 범위는 다음과 같습니다. 실제 DB 테스트 세
파일은 자동 skip되지 않으므로 아래 제외 목록과 MCP 파일 목록을 유지합니다.

2026-09-07 WU-B6 발언·투표 수정은 사용자의 후속 요청에 따라 전체 회귀를 생략하고
**Chrome에서 실제 OpenAI `gpt-5.6-luna`로 6인 게임 한 판을 완료**했습니다.
기존 로컬 DB 환경의 `18000` Backend, `18100` MCP, `18501` 사용자 Front를 사용했고
다른 원격 실행과 분리했습니다. `CORS_ALLOWED_ORIGINS`에는 실제 Front origin을
명시해야 합니다. 이번 실행에는 `http://127.0.0.1:18501,http://localhost:18501`을 사용했습니다.

- 첫날 AI 5명, 둘째 날 4명, 셋째 날 2명: **모델 발언 11회·적용 11회, PASS 0회**.
- 첫 투표의 AI 선택은 좌석 순서로 **1번·6번·6번·4번**이었고 마지막 두 AI는
공개된 탐정 조사 결과에 따라 1번을 선택했습니다. 실행 로그에서 AI 투표 6건 모두
정상 선택·적용을 확인했으며 fallback은 없었습니다.
- 셋째 날 마피아가 처형되어 **시민 진영 승리**로 종료됐습니다. 밤은 입력 마감에
따른 자동 선택으로 해소됐으며 수동 밤 제출 성공은 이번 플레이에서 확인하지 않았습니다.
- UI의 공개 판단 근거·모델/대체 구분과 종료 후 전체 투표 기록을 실제 브라우저에서
확인했습니다. 저장·재개도 같은 게임에서 확인했습니다.
- 최초 공유 DB 실행에서는 이 Backend가 완료하기 전에 다른 실행 경로가 AI PASS를
기록하는 간섭이 관찰돼 해당 게임을 저장했습니다. 같은 DB를 쓰는 다른 Backend도
동일 버전으로 갱신하거나 실행 대상을 분리해야 합니다. 이 작업은 원격 작업자를 중지하지 않습니다.

후속 요청 전 focused 검증은 Backend 68개·Front 148개가 통과했습니다. 이후 추가한
검증 코드와 전체 회귀는 사용자 요청에 따라 실행하지 않았습니다. 위 한 판의 결과는
여러 게임의 추론 품질·승률을 보장하는 자료가 아닙니다.

이어진 역할·페르소나 프롬프트와 결과 화면 대비 수정에서는 사용자 요청에 따라
자동 테스트·lint·전체 회귀를 실행하지 않았습니다. 기존 완료 게임을 로컬 Front에서
다시 열고 별도 Chromium의 다크 테마에서 밤·조사·투표 기록, 요약 숫자와 보조 설명의
실제 색상·화면을 확인했습니다. 로컬 Backend를 재시작해 프롬프트도 반영했습니다.
앞의 게임 한 판은 이번 프롬프트 보강 이전 기록이며, 새 지침의 역할 공개·페르소나
발언 품질은 추가 실게임으로 평가하지 않았습니다.

토큰·Redis 보완에서는 로컬 `.env`에 Redis 설정이 없어 실행 중인 loopback Redis의
0번 DB를 지정하고 출력 한도를 8192로 설정한 뒤 로컬 Backend `18000`을 재시작했습니다.
실제 게임 snapshot API가 200을 반환했고, PostgreSQL·응답·Redis의 공개 이력 63건
(발언 45건)이 순서와 내용까지 일치했습니다. 해당 게임의 파생 캐시만 지운 뒤 다시
조회해 전체 이력이 복구되는 것도 확인했습니다. 자동 테스트·lint·전체 회귀와
추가 LLM 게임은 사용자 요청에 따라 생략했으며, 상향 후의 발언 품질은 미평가입니다.
실제 Redis에서 이전 상태 버전의 저장이 거부되고 최신 이력이 유지되는 것도 확인했습니다.

```bash
TEAM_DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests' \
DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests' \
GAME_STATE_KEYRING_FILE='' GAME_STATE_ACTIVE_KEY_ID='' \
LLM_PROVIDER=dummy OPENAI_API_KEY='' GEMINI_API_KEY='' \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin backend/tests \
  --ignore=backend/tests/test_b5_game_api.py \
  --ignore=backend/tests/test_postgres_game_flow.py -q

BACKEND_API_URL=http://127.0.0.1:8000 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  frontend_user/.venv/bin/python -m pytest -c pyproject.toml frontend_user/tests -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 frontend_admin/.venv/bin/python -m pytest \
  -c pyproject.toml frontend_admin/tests -q

(cd mcp_server && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin \
  tests/test_backend_context_client.py tests/test_fastmcp_composition.py \
  tests/test_fastmcp_registration.py tests/test_fastmcp_roundtrip.py -q)
```

2026-09-07 후속 수정의 최종 회귀는 **Backend 510개, MCP 44개, 관리자 Front 18개**가
통과했습니다. 사용자 Front **331개**를 더해 **총 903개 통과, 실패 0**입니다.
실브라우저 근거는
[보고서 8절](docs/AI_MAFIA_GAME_TEST_GAP_REPORT.md#8-수정권고-반영과-ai-진행-표시)에 기록합니다.
최초 Backend 회귀의 2개 실패는 강화된 window 계약을 반영하지 않은 테스트 대역을
수정한 뒤 해소됐습니다. Front의 낡은 sync fixture·소스 문자열 검사 2개도 현재 계약과
Node 동작 검증으로 보완한 뒤 통과했습니다. 기존 config의 긴 줄 Ruff 경고 1개는 범위 밖으로 남겼습니다.

실제 SQL을 사용하는 `test_b5_game_api.py`, `test_postgres_game_flow.py`,
`test_b6_agent_manager.py`의 opt-in 8개와 MCP process 테스트도 **격리된 로컬 QA DB**에서
검증했습니다. 공유 DB를 대상으로 실행하지 않습니다. MCP process 테스트는 이제
Tool `accepted=true`, receipt와 window/version 변경을 확인하며 오류 응답을 통과시키지 않습니다.

아래는 이번에 사용한 **합성 자격증명의 임시 DB 전용** 검증 예입니다. 해당 DB에
기존 migration 4개를 적용하고 로컬 Redis 15번 DB를 준비한 뒤 실행합니다. 두 DB
변수를 함께 덮어써 원격 `.env` 값이 선택되지 않게 합니다. B6 opt-in은 아래 loopback
QA 주소만 허용합니다. 테스트는 자신이 만든 UUID·게임·Redis key만 정리합니다.

```bash
export TEAM_DATABASE_URL='postgresql://qa:synthetic-only@127.0.0.1:55432/mafia_qa'
export DATABASE_URL="$TEAM_DATABASE_URL"
export DATABASE_MIGRATION_URL="$TEAM_DATABASE_URL"
export TEST_DATABASE_URL="$TEAM_DATABASE_URL"
export DATABASE_NAME=mafia_qa REDIS_URL=redis://127.0.0.1:6379/15
export GAME_STATE_KEYRING_FILE='' GAME_STATE_ACTIVE_KEY_ID=''
export LLM_PROVIDER=dummy OPENAI_API_KEY='' GEMINI_API_KEY=''
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
B6_LOCAL_QA=1 backend/.venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin backend/tests -q
PYTHONPATH=.:mcp_server .venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin mcp_server/tests -q
```

실제 유료/Local LLM의 추론 품질·운영 DDL 권한·기존 데이터 암호화 전환·운영 TLS는
검증하지 않았습니다. 6~9명 각각 100판의 heuristic 시뮬레이션 400판은 전부 종료됐으나,
마피아 승률 62/54/68/69%는 실제 LLM의 시나리오별 균형을 보장하지 않습니다.

## 보안 원칙과 알려진 제약

- `.env`, 실제 `secrets.toml`, token과 모든 실제 자격증명을 커밋하지 않습니다.
- 목표 공개 API의 `X-User-Id`는 인증이 아니라 UUID scope 선택값입니다. UUID를 아는
사용자의 가장을 막지 못하므로 MVP는 개인 개발 환경 또는 사설망으로 제한합니다.
- 현재 최소 FastMCP는 custom bootstrap·HMAC·capability 인증을 제공하지 않습니다.
요청 schema·게임 소유권·행동 유효성은 Backend가 검증하며, 운영 보안을 완료한
공개 배포 구성으로 취급하지 않습니다.
- Backend는 각 AI actor의 허용된 자기 정보만 scope별로 투영합니다. 밤 행동과
개별 투표는 종료 전에 공개하지 않으며 확정 공개 결과와 본인의 조사 결과를
구분합니다. GM 안내는 기본 게임 이벤트 수준이며 별도 GM LLM 연출은 후속 범위입니다.
- MCP runtime은 DB·Redis에 직접 접근하거나 영속 outbox를 소유하지 않습니다.
구 custom MCP 감사 로그 프로파일을 현재 FastMCP의 검증된 보장으로 사용하지 않습니다.
- seed와 engine snapshot keyring은 저장소 밖에 두고 과거 record가 참조하는 key를
보존합니다. 현재 runtime은 keyring 미설정 시 legacy plaintext 경로를 사용하므로
실제 게임 환경에서 암호화 설정 여부를 확인해야 합니다.
- LLM prompt, raw response, private context, token과 비용을 로그에 넣지 않습니다.
- `ADMIN_USER_IDS`는 강한 인증이 아니므로 관리자 앱도 loopback·사설망에서만 사용합니다.
- 관리자 앱은 UUID 입력·저장 확인, read-only 통계·상태/단계별 목록·주소로 여는 상세를
제공합니다. 관리자 권한은 Backend allowlist로 확인하며 자동 등록하지 않습니다.
- 현재 Mafia Game MCP에는 `/mcp` 서버, 최소 Resource·Prompt·Tool 등록부와 Backend
HTTP adapter, fake·ASGI 테스트가 있습니다. 실제 프로세스 테스트는 DB를 사용하므로
독립 테스트와 구분합니다.

비밀값 노출이 의심되면 값을 다시 출력하지 말고 즉시 폐기·재발급한 뒤 Git 이력과
외부 로그를 별도로 점검하세요.

## 확장 지점

- UUID 사용자 식별: `frontend_user/core/identity.py`, `frontend_user/core/session.py`,
`frontend_user/components/identity_bridge.py`, `backend/app/services/identity_service.py`
- Backend API client: `frontend_user/core/api_client.py`
- 사용자 저장소: `backend/app/repositories/user_repository.py`
- schema 변경: Backend가 `backend/migrations/`에 다음 번호의 순방향 SQL을
추가하고 MCP 담당자가 실제 환경에서 실행·재실행 검증
- Agent·LLM·MCP client: `backend/app/agent/`, `backend/app/llm_provider/`,
`backend/app/mcp/`
- 독립 MCP 기능: `mcp_server/mafia_game/`(현재 FastMCP Resource·Prompt·Tool) 또는
`mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만 커밋이나
push를 자동 승인하지 않습니다.  
  
  
  ---
  
+ 추가 기능) 타 직업의 툴을 호출할 수 있는 agent 생성 기능 (환경설정 페이지) + agent parameters 부분 변경 가능(0.1초과, 1.0 미만 금지)
+ 위 변경사항 의미 있으려면 게임 시작 전 커스텀 메뉴에서 플레이어 직업 선택 가능하도록 변경 있어야함

게임·관전 공개 타임라인은 노란색 발언 말풍선과 행동 알림을 구분합니다. `AI 판단과 실행`은 기본적으로 접혀 있으며 펼쳐서 확인합니다. 종료 결과에는 마피아 선택과 최종 공격 대상을 구분하고, 두 선택이 갈린 경우 RNG로 결정되었다고 안내합니다. 비공개 선택은 게임 종료 후에만 표시합니다.

AI 발언 지침은 구어체 자기 보호 계획을 이미 제공된 답으로 인정하고, 아직 발언 기회가 없는 무응답과 모호한 목격을 마피아 증거로 삼지 않도록 보완했습니다. 시민 오처형 뒤에는 기존 의심 근거를 재검토하며, 밤 사망만으로 역할 자칭을 확정하지 않습니다. 프롬프트 지침이므로 모든 모델 응답의 준수를 보장하지는 않습니다.

운영 FastMCP는 AI 입력에서 시나리오 제목만 유지하고 배경·피해자·장소·개인 알리바이·목격담을 제외합니다. 대신 public.data.rules로 밤 행동·투표·승패·정보 공개 규칙을 제공합니다. 공개 발언과 본인 조사 결과는 보존하며 Front의 시나리오 화면은 그대로입니다.
Backend MCP 클라이언트는 기존·축약 응답을 모두 허용합니다. 실행 중인 MCP 프로세스는 코드 변경 후 재기동해야 적용됩니다. 검증: MCP 테스트 45개, Backend MCP 클라이언트 테스트 47개 통과. 실제 유료 모델 호출은 실행하지 않았습니다.

OpenAI 실행의 루트 `.env` 모델은 `OPENAI_MODEL=gpt-5.6-luna`로 설정하며, OpenAI 추론 모델 요청의 `reasoning.effort`는 `high`을 사용합니다.
