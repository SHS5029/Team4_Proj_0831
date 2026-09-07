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
환경을 전제로 합니다. 실제 `mystery-v1` 게임 엔진과 AI 플레이어 기능은 후속 WU
범위이며 계획 문서만으로 구현 완료로 간주하지 않습니다.

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
- FastMCP 등록부에서 Backend synthetic context·prompt·action endpoint로 전달하는 HTTP adapter

개발 섹터 역할은 코드 소유권과 실행 환경 책임을 분리합니다. Backend 섹터는
DB schema·migration SQL·repository와 Redis client·lock 코드를 작성하고, MCP
섹터는 PostgreSQL·Redis 인스턴스 구축·기동·중지, DDL migrator와 DML runtime
계정·권한 준비,
migration 실행과 health 확인을 담당합니다. 실제 Backend 프로세스는 DB·Redis에
직접 연결하며 MCP 서버를 데이터 프록시로 사용하지 않습니다.
기존 `event_outbox`와 agent 관련 테이블·암호화 컬럼은 DB/migration 호환을 위해
보존합니다. 신규 MVP 실행 경로의 게임 추적은 `game_events`와 `receipts`를
사용하고, MCP는 FastMCP 표준 protocol session만 사용합니다.

LLM Agent loop, 관리자 업무 기능과 canonical game의 Redis 연결은 아직 구현하지
않았습니다. FastMCP는 실제 Backend 게임 snapshot과 command를 호출하는 최소
Resource·Prompt·Tool 등록부를 제공합니다. 실제 Agent turn orchestration은 후속 정의합니다. 기존 LLM Provider adapter는 연결돼
있지만 앱 수준의 LLM timeout 설정, token 상한·사용량, 비용·예산과 관련 KPI는 새 MVP
범위에서 제외합니다.

게임 흐름용 `DeterministicGameAgent`는 DB reservation이나 lease 없이 Backend가
제공한 context를 deterministic Fake Provider에 전달하고, 검증된 action만 Backend
경계로 반환합니다.

PostgreSQL에서는 `PostgresAgentDiscussionService`가 deterministic AI PASS를 인간과
동일한 GameEngine 검증·transaction으로 기록합니다. AI 원장의 source 값은 기존
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
재투표·승패 규칙과 종료 snapshot의 PostgreSQL smoke도 확인했습니다. Local LLM을
사용한 전체 런 검증 중 인간 생존 DAY_VOTE에서 AI 투표가 대기되지 않던 결함을
수정했으며, 전체 런 재검증은 다음 통합 테스트 단계입니다.
사망한 인간의 `FAST_FORWARD` command도 PostgreSQL action service에 연결했습니다.
`SAVE_AND_EXIT`와 `RESUME`의 실제 PostgreSQL 왕복도 smoke로 확인했습니다.
Backend는 서버 시작 시 중앙 `AiProgressWorker`를 실행해 열린 AI speech·night·vote
window를 비동기로 회복합니다. phase 전환은 마지막 필수 actor 제출을 처리하는
동기 PostgreSQL transaction에서만 수행합니다. 테스트 앱에서는 수동 command와의
경쟁을 막기 위해 `enable_background_worker=False`를 사용할 수 있습니다. worker 장애는
민감한 payload·식별자·긴 예외 원문을 제외하고 조회·Agent 실행·fallback 단계, 오류
종류·발생 위치(`파일:줄:함수`)와 최대 240자의 원인 문구만 Backend 로그에 남깁니다.
최종 토론 snapshot도 현재 speech 제출 원장과 함께 복원됩니다.
PostgreSQL sync의 공개 event와 action window payload도 Frontend 정본 구조로 변환됩니다.
worker는 한 게임의 진행 오류가 다른 게임의 AI 진행을 막지 않도록 격리합니다.
순수 규칙 엔진은 기존 `GameEngine` facade를 유지하면서 플레이어 검증·사망 처리·
표준 승패·토론 입력·밤 역할 판정·투표 집계·replay 분기를
`backend/app/game_engine/` 모듈로 이동했습니다. 실제 `GameEngine`, deterministic
fallback, phase 전이 구현은 해당 package가 소유하고, 기존
`backend/app/agent/game_engine.py`, `fallback.py`, `state_machine.py`는 import
기존 `agent/game_engine.py`, `fallback.py`, `state_machine.py`, `agent/rules/`는
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
adapter를 사용하며, 순수 게임 흐름은 PostgreSQL 정본 경로로 전환하는 중입니다.
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
Frontend SSE bridge는 실제 변경이 있는 `envelope`만 Streamlit component state로
등록해 화면을 rerun합니다. 현재 cursor를 그대로 돌려주는 no-op 응답은 폐기하며,
응답 stream이 종료되어도 마지막 `last_sequence`부터 자동 재연결해 phase 전환을
반영합니다. Backend `/events`는 연결을 유지하면서 변경 batch만 push하고 15초
간격 heartbeat만 보내므로, 변경 없는 stream 데이터가 페이지를 반복 rerun하지 않습니다.
Backend 중앙 AI worker는 만료된 밤 window도 조회해 인간 역할의 무응답을 정본의
결정적 자동 선택으로 해소하고 다음 낮 단계까지 진행합니다.
게임 command Front guard는 입력 형식만 정규화하고, 현재 phase·turn·window·대상
허용 여부는 Backend가 최신 transaction에서 최종 확인합니다.

## 개발상세플랜 정본 (2026-09-03)

중복·충돌하던 AI 마피아 계획과 계약을 `docs/개발상세플랜/`의 정본 문서로 통합했습니다.
섹터별 담당자는 작업 전에 [AGENTS.MD](AGENTS.MD)와 해당 정본을 읽고, coding AI
agent 한 세션을 마스터플랜의 WU 한 개 이하로 제한합니다.

| 문서 | 기록된 내용 |
|---|---|
| [AI_MAFIA_MASTER_PLAN.md](docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md) | 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터 소유권, WU와 CP |
| [AI_MAFIA_DB_DESIGN.md](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md) | PostgreSQL·Redis schema, transaction, lock, migration과 보존 계약 |
| [AI_MAFIA_API_SPEC.md](docs/개발상세플랜/AI_MAFIA_API_SPEC.md) | 일반·관리자·내부 Engine HTTP API와 MCP Resource·Tool 계약 |
| [AI_MAFIA_MCP_SERVER_DESIGN.md](docs/개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md) | MCP runtime 구조, 보안 경계와 WU-M1A~WU-M8 실행·검증 계획 |
| [AI_MAFIA_SCREEN_FLOW.md](docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md) | UUID 초기화, 사용자 게임·관전·피드백과 관리자 화면 흐름 |
| [AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md](docs/개발상세플랜/AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md) | Streamlit Front 전용 WU-F1~F8 기술 설계, 상태·동기화·협업 계약·보안·테스트·완료 기준 |
| [AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md](docs/개발상세플랜/AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md) | Frontend–Backend 공개 API, SSE·CORS, 오류·private 경계와 공동 완료 조건 요약 |
| [AI_MAFIA_INDEPENDENT_CONTRACT.md](docs/개발상세플랜/AI_MAFIA_INDEPENDENT_CONTRACT.md) | 세 섹터가 독립 구현할 때 공통으로 고정할 최소 연결 형식과 경계 |
| [AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md](docs/개발상세플랜/AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md) | 게임 엔진·Agent Manager 모듈화 전략 임시 초안 |
| [AI_MAFIA_CURRENT_CODE_STATUS.md](docs/AI_MAFIA_CURRENT_CODE_STATUS.md) | 현재 실제 코드 구조, 게임 흐름, 공개 API, 설정, 검증 결과와 제약 |

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

이 규칙은 아직 구현되지 않았습니다. Backend 규칙·시나리오·deadline WU와
Front·MCP 계약을 차례로 완료한 뒤 사용할 수 있습니다. 규칙 수준의 밸런스는
유료 LLM 없이 6~9명별 heuristic bot 시뮬레이션으로 검증합니다. 실제 Provider smoke는
명시적으로 opt-in한 소수 표본만 사용하며 token·비용 KPI를 만들지 않습니다.
마스터플랜의 개인 정보 문장 예시를 바탕으로 `004_seed_mystery_v1_catalog.sql`에
최대 9좌석용 최소 90개 template record를 작성했습니다. 실제 환경에 적용하기 전에
문장별 역할 중립성·무모순을 제품 검수해야 `scenario-v1` 콘텐츠가 완료됩니다.

## 프로젝트 구조

```text
.
├── AGENTS.MD                         # 개발·기여 작업 규칙
├── README.md                         # 전체 설정·실행·검증 안내
├── .env.example                      # Backend 환경 변수 예시
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
│   ├── app/game_engine/               # 순수 게임 규칙·phase·결정적 RNG 정본 package (현재 phase가 행동 실행 포함)
│   ├── app/llm_provider/             # 현재 LLM Provider adapter
│   ├── app/mcp/                      # Backend Agent용 MCP context client·registry
│   ├── migrations/                   # Backend 작성 SQL migration(MCP 실행)
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
├── frontend_admin/                   # 관리자 독립 앱의 최소 실행 골격
├── mcp_server/
│   ├── pyproject.toml, uv.lock        # Python 3.12·MCP SDK 1.29.1 독립 실행 환경
│   ├── mafia_game/                   # 최소 FastMCP 등록부·Backend HTTP adapter
│   ├── tests/                        # 등록·adapter·ASGI 왕복 테스트
│   └── mcp_2/                        # 후속 MCP 독립 예약 패키지
├── docs/
│   └── 개발상세플랜/
│       ├── AI_MAFIA_MASTER_PLAN.md    # 제품 규칙·시나리오·아키텍처·WU/CP 정본
│       ├── AI_MAFIA_DB_DESIGN.md      # PostgreSQL·Redis 정본
│       ├── AI_MAFIA_API_SPEC.md       # 공개·내부·MCP API 정본
│       ├── AI_MAFIA_MCP_SERVER_DESIGN.md # MCP runtime·Data WU 구현 설계
│       ├── AI_MAFIA_SCREEN_FLOW.md    # 사용자·관리자 화면 정본
│       ├── AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md # Front WU-F1~F8 파생 기술 설계안
│       ├── AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md # Frontend–Backend 연동 인계 요약
│       └── AI_MAFIA_INDEPENDENT_CONTRACT.md # 섹터 간 최소 연결 형식·독립 개발 규칙
├── tests/{integration,e2e}/          # 서버 간·브라우저 검증 확장 위치
└── scripts/                          # 운영·개발 보조 스크립트
```

### Frontend 컴포넌트별 가상환경

Windows에서는 컴포넌트별 환경을 분리합니다. 기존 `.venv`가 있으면 삭제하지
않고 재사용하며, 반드시 환경 내부 Python으로 설치합니다.

```powershell
& ".\backend\.venv\Scripts\python.exe" -m pip install -r ".\backend\requirements.txt"
& ".\frontend_user\.venv\Scripts\python.exe" -m pip install -r ".\frontend_user\requirements-dev.txt"
& ".\frontend_admin\.venv\Scripts\python.exe" -m pip install -r ".\frontend_admin\requirements.txt"
```

`.vscode\settings.json`과 `.vscode\project-venv.ps1`은 현재 폴더에 맞는
PowerShell 가상환경 자동 전환을 제공합니다. PowerShell 7에서 발생할 수 있는
`Split-Path -LiteralPath ... -Parent` 매개변수 집합 오류를 피하기 위해 스크립트는
상위 폴더를 .NET API로 계산합니다. 원본 Python 설치가 바뀐 경우에는
각 컴포넌트의 `.venv`를 재생성하기 전에 먼저 Python 3.12 설치 경로를 확인합니다.

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

관리자 화면을 확인하려면 관리자 Frontend의 local storage에 생성된 UUID를
`ADMIN_USER_IDS`에 등록한 뒤 Backend를 재시작합니다. UUID는 관리자 화면의 브라우저
개발자 도구에서 `ai_mafia_admin_user_id_v1` 값을 확인할 수 있습니다.

```powershell
$env:ADMIN_USER_IDS = "브라우저에서_확인한_UUID"
```

`frontend_user`와 `frontend_admin`은 Backend만 HTTP로 호출합니다. Frontend가 DB,
Redis, MCP 서버에 직접 연결하거나 MCP 서버끼리 서로의 내부 모듈을 import하지
않습니다. MCP 섹터가 DB·Redis 실행 환경을 운영해도 `mcp_server/mafia_game`
runtime은 DB·Redis에 직접 접근하지 않습니다.

MCP 구현부터 `mcp_server/`를 독립 프로젝트 루트, `mafia_game`을 공식 Python import
package로 사용합니다. composition root는 `mafia_game/main.py`, module 진입점은
`mafia_game/__main__.py`, package test 위치는 `mcp_server/tests/`로 고정했습니다.
독립 `pyproject.toml`과 `uv.lock`은 Python 3.12와 MCP SDK 1.29.1을 정확히 고정합니다.
stateful MCP session은 initialize 전에 canonical 세션 개설 토큰을 검증하고 Backend
Engine consume이 성공한 뒤에만 활성화되며, 명시적 DELETE와 30초 idle에 메모리를
멱등 폐기합니다. 세션 개설 토큰 만료가 idle보다 이르면 만료 시각을 우선하며 consume
결과가 비확정이면 신규 HTTP code 없이 `403 BOOTSTRAP_DENIED`로 fail-closed합니다.
fresh credential 조정은 `WU-M7` 범위입니다. 초기 요청의 capability header는 정확히
한 번만 허용하고 후속 요청은 동일 bearer로만 session owner를 증명합니다.

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
- `DATABASE_MIGRATION_URL`은 목표 migration runner가 사용할 DDL 계정입니다. 현재
  runner는 아직 이 이름을 읽지 않으므로 아래 migration 절의 격리 주입 절차를
  따릅니다. Backend runtime 프로세스에는 전달하지 않습니다.
- 앱은 URL의 원래 DB 경로 대신 `DATABASE_NAME`을 사용하며 기본값은 `Team4_Proj`입니다.
- 최소 FastMCP process는 `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT`만
  읽습니다. 기본 Backend 주소는 `http://127.0.0.1:8000`, MCP 주소는
  `http://127.0.0.1:8100/mcp`입니다. 현재 연결은 loopback 개발용이며 인증·TLS·운영
  보안은 이 최소 전환 범위에 포함하지 않습니다.
- Backend 중앙 AI worker는 `MCP_SERVER_URL`로 FastMCP 서버 주소를 주입받아
  context 조회와 Agent action 전달에 사용합니다. MCP가 중지되거나 LLM 호출이
  실패하면 현재 AI speech window는 기존 규칙 기반 PASS fallback으로 종료됩니다.
- LLM Provider 설정은 `config.py`에서 선택값, Local 모델 주소·이름, timeout과 출력
  token 상한을 검증합니다. 현재 3번 연결 작업은 Dummy Provider와 Local Provider의
  최소 호출 계약을 대상으로 하며, OpenAI·Gemini 실제 호출은 선택 Provider 작업으로
  남겨 둡니다. Agent Runtime은 Fake Context와 Dummy Provider로 proposal 완료 흐름을
  검증할 수 있습니다. 앱 수준의 token 사용량·비용·예산 설정은 MVP에서 사용하지
  않습니다. 중단된 Agent worker는 조정 불가능한 고정 lease와 fencing token으로
  회수하며, 만료·실패한 동일 AI job은 다음 예약 시 lease를 재사용해 재시도할 수
  있습니다. LLM·MCP 호출 동안 PostgreSQL transaction이나 Redis
  game lock을 보유하지 않습니다.
- Local Provider는 OpenAI 호환 `/chat/completions` 형식과 JSON 응답을 사용합니다.
  게임 proposal 요청에서는 `think=false`를 사용해 불필요한 reasoning 출력을 끕니다.
  밤 행동·투표에서 Provider가 잘못 `PASS`를 반환하면 MCP turn context의 첫 합법
  대상으로 보정하며, 합법 대상이 없을 때만 안전하게 실패 처리합니다.
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
- 기존 FastMCP 전환안은 보관용이며, 현재 FastMCP WU는
  `AI_MAFIA_MCP_FASTMCP_MINIMAL_CONNECTION_PLAN.md`의 최소
  연결 기준을 우선합니다.
- MCP 테스트는 등록부·adapter·ASGI 왕복을 대상으로 하며 Backend 회귀 테스트와 함께
  실행합니다.
- 현재 MVP 동기화는 PostgreSQL `game_events` polling을 정본으로 사용하며, 기존
  `event_outbox`는 migration·호환 구조로 보존합니다. legacy timeout, token 상한과
  비용 단가는 신규 실행 경로에서 사용하지 않는 방향으로 정리 중입니다.
- 기존 DB 게임 흐름 smoke test는 `py -m pytest backend/tests/test_postgres_game_flow.py -q`로
  실행합니다. 테스트는 고유 UUID와 실행 ID를 사용하고 종료 시 생성한 사용자·게임·Redis
  키만 정리합니다.
- 최소 FastMCP는 `BACKEND_API_URL`을 Backend base URL로 사용하고 `/internal/mcp/*`
  경로를 호출합니다. MCP endpoint는 `MCP_LISTEN_HOST`와 `MCP_LISTEN_PORT`로 정합니다.
- Backend는 `CORS_ALLOWED_ORIGINS`에 등록된 Front origin에만 SSE fetch preflight와
  동기화 header를 허용합니다. 활성 밤·투표 window의 `remaining_ms`는 저장된
  `deadline_at`을 기준으로 매 snapshot마다 계산하며, sync cursor 불일치 시 전체
  snapshot으로 복구합니다.

| 환경 소비자 | 허용하는 AI 마피아 관련 키 | 주입 금지 |
|---|---|---|
| Front 서버 | Backend URL | DB·Redis·LLM·MCP/Engine secret |
| Backend runtime | `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, game state keyring, LLM Provider·model·key, `ADMIN_USER_IDS`, `MCP_SERVER_URL`, `CORS_ALLOWED_ORIGINS` | `DATABASE_MIGRATION_URL`, MCP runtime 전용 설정 |
| migration 실행 프로세스 | `DATABASE_MIGRATION_URL`, `DATABASE_NAME` | runtime·LLM·MCP secret |
| MCP runtime | `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT` | DB·Redis·LLM·인증 secret |

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

현재 runner는 `DATABASE_MIGRATION_URL`을 직접 읽지 않고 `DATABASE_URL`을 읽습니다.
`WU-B2` 전까지 MCP 담당자는 격리된 migration 프로세스에 DDL DSN을 일시적으로
`DATABASE_URL` 이름으로만 주입해 아래 명령을 실행하고, 평소 Backend runtime의
`DATABASE_URL`이나 공용 `.env`에 DDL 권한을 부여하지 않습니다. 실제 DSN을 shell
history나 완료 로그에 쓰지 않습니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

현재 seed 정본은 `004_seed_scenarios_and_personas.sql` 하나이며, 중복된 `004` 번호의
seed 파일을 함께 두지 않습니다. `001`·`002` migration은 legacy `users`·`oauth_identities`와 `scaffold_*` 게임
테이블을 생성합니다. `003_create_mystery_v1_schema.sql`은 기존 객체와 데이터를
삭제하지 않고 `users.last_seen_at`을 보강한 뒤
[DB 설계 정본](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md)의 canonical `mystery-v1`
테이블, 복합 FK, 상태 제약과 조회 index를 순방향으로 추가합니다.
`004_seed_mystery_v1_catalog.sql`은 정본 시나리오 5개, 시나리오별 알리바이 9개와
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

MCP 담당자가 PostgreSQL을 먼저 기동하고 연결·migration 상태를 확인한 뒤
Backend를 실행합니다. 게임용 Redis가 구현된 이후에는 Redis health도 먼저
확인합니다.

```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

`http://127.0.0.1:8000/health`의 정상 응답은 `{"status":"ok"}`입니다.

Mafia Game MCP는 Backend를 먼저 실행한 뒤 최소 FastMCP process로 실행합니다. 아래
명령은 저장소 루트에서 실행하며, 개발 환경에서는 loopback 연결만 사용합니다.

```bash
uv sync --project mcp_server --locked --dev
uv run --project mcp_server --directory mcp_server --locked python -m mafia_game.main
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

최소 MCP 왕복 검증은 Backend와 FastMCP를 각각 subprocess로 실행해 수행합니다.

```powershell
$env:PYTHONPATH = "mcp_server"
uv run --project mcp_server --locked pytest -q mcp_server/tests/test_process_backend_roundtrip.py
```

관리자 앱은 업무 기능 없이 독립 실행 경계만 확인할 수 있습니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 entrypoint는 실행 위치와 무관하게 저장소 루트를 import 경로에 등록해
`frontend_admin` 패키지를 불러옵니다.

## 테스트와 정적 검사

변경 동작별 focused test 예시는 다음과 같습니다.

```bash
uv run pytest backend/tests/test_identity_api.py
uv run pytest backend/tests/test_users_repository.py
uv run pytest frontend_user/tests
uv run --project mcp_server pytest mcp_server/tests
uv run --project mcp_server ruff check --config mcp_server/pyproject.toml mcp_server
```

사용자 게임 목록은 API 명세서의 `status`, opaque `cursor`, `limit(1~100)` query를
지원하며, 역할 공개 화면은 명세서의 `BEGIN_GAME` command를 성공한 뒤 진행 화면으로
이동합니다. 관리자 게임 목록도 `status`, `phase`, `cursor`, `limit(1~100)` query
계약을 사용합니다.

완료 전 전체 회귀·컴파일·lint는 다음 명령으로 확인합니다.

```bash
uv run pytest
uv run python -m compileall -q backend frontend_user frontend_admin mcp_server
uv run ruff check .
```

자동 테스트는 synthetic identity, 가짜 DB 연결, mock HTTP transport를 사용해 운영 DB와
유료 API를 호출하지 않습니다. 실제 PostgreSQL
마이그레이션은 자격 증명과 로컬 인프라가 필요하므로 MCP 담당자가 실행 환경을
준비·검증하고 Backend 담당자와 결과를 공동 판정합니다.

## 보안 원칙과 알려진 제약

- `.env`, 실제 `secrets.toml`, token과 모든 실제 자격증명을 커밋하지 않습니다.
- 목표 공개 API의 `X-User-Id`는 인증이 아니라 UUID scope 선택값입니다. UUID를 아는
  사용자의 가장을 막지 못하므로 MVP는 개인 개발 환경 또는 사설망으로 제한합니다.
- 내부 Engine HMAC과 MCP 세션 개설 토큰 서명 secret은 Front에 전달하지 않고 서로
  다른 값으로
  유지합니다. 서명을 통과한 payload도 schema와 도메인 규칙으로 다시 검증합니다.
- Backend만 전체 역할·야간 행동·seed를 보유하고, AI GM과 각 플레이어 Agent에는
  공개 상태 및 자기에게 허용된 개인 정보만 전달합니다.
- MCP capability는 game·agent job·phase·state version·deadline에 묶습니다. 각
  `agent_jobs` reservation은 새 capability·세션 개설 토큰·MCP session을 사용하고
  terminal 처리와 reconnect에서 기존 값을 재사용하지 않습니다.
- AI GM은 MCP의 `public`, `gm-guide`만 읽고 Tool을 사용하지 않습니다. narration은
  LLM adapter가 Backend Agent Manager에 직접 반환하며 Backend가 검증·fallback·
  `PUBLIC` event 저장을 담당합니다.
- MCP runtime은 Backend `event_outbox`를 사용하거나 영속 audit outbox를 소유하지
  않습니다. MCP 로그는 request·correlation ID, operation, status, duration과
  비밀이 없는 분류 오류만 남기고 payload·capability·token·signature·prompt는
  남기지 않습니다.
- seed와 engine snapshot keyring은 저장소 밖에 두고 과거 record가 참조하는 key를
  보존합니다.
- LLM prompt, raw response, private context, token과 비용을 로그에 넣지 않습니다.
- `ADMIN_USER_IDS`는 강한 인증이 아니므로 관리자 앱도 loopback·사설망에서만 사용합니다.
- 현재 관리자 앱에는 인증·권한과 업무 기능이 없으며 준비 화면만 표시합니다.
- 현재 Mafia Game MCP에는 `/mcp` 실행 서버와 세션 개설 토큰 consume용 Engine HTTP
  adapter가 있으며 FastMCP 독립 composition 경계에 최소 Resource·Prompt·AI 행동 요청
  Tool 등록부와
  ASGI 왕복 fixture가 있습니다. MCP runtime은 여전히 DB·Redis에 직접 접근하지 않습니다.

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
- 독립 MCP 기능: `mcp_server/mafia_game/`(게임 컨텍스트 MCP 예정) 또는
  `mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만 커밋이나
push를 자동 승인하지 않습니다.
