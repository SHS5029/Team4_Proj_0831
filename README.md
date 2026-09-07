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

현재 실행 경로는 브라우저 UUID와 `X-User-Id`를 사용하는 사용자 앱·공개 API입니다.
`mystery-v1` 규칙 엔진과 관리자·Agent 관련 코드도 있지만 공개 게임의 PostgreSQL
영속화, 실제 Agent/MCP 연결과 Front 사용자 흐름의 마무리는 남아 있습니다.
Google OIDC·Front HMAC 소스와 일부 테스트는 legacy로 남아 있으며 identity route는
기본 앱에 등록하지 않습니다. 코드 존재와 실제 통합 완료는 구분합니다.

게임을 실제로 테스트할 때 남은 기능·연결·규칙 차이는
[게임 테스트 관점 미구현·미완료 목록](docs/AI_MAFIA_GAME_TEST_GAP_REPORT.md)에
테스트 장면, 우선순위, 코드 근거와 관련 WU별 표로 정리했습니다. 2026-09-07 현재
미커밋 작업을 포함한 코드 조사이며 실제 게임 실행·외부 서비스 통합 성공 기록은 아닙니다.

개발하거나 기여하기 전에 반드시 [AGENTS.MD](AGENTS.MD)의 브랜치, 커밋,
파일·디렉터리 구조, 테스트, 주석 및 문서화 규칙을 확인하세요.

## 현재 구현 범위

- UUID-only 사용자 Frontend의 홈·게임 진행·관전·서버 확정 결과·게임별 피드백 화면과 Backend 공개 API client
- UUID v4 요청 검증과 게임 소유권 확인, 생성·command·sync·feedback 공개 API
- 6~9명 `mystery-v1` 규칙 엔진과 synthetic 시뮬레이션 테스트
- PostgreSQL repository·command 서비스, Redis lock/cache/outbox 코드
- read-only 관리자 API·allowlist 검사와 사용자 앱에서 분리된 관리자 화면
- Agent reservation·lease·fallback과 내부 Engine API 코드(운영 연결은 미완료)
- Backend 소유 PostgreSQL migration 실행 코드(MCP 섹터가 실제 실행)
- 독립 관리자 Streamlit 앱과 후속 MCP 서버 예약 구조(`mcp_server/mcp_2`)
- `WU-M2` Mafia Game MCP의 stateful `/mcp` initialize, 일회성 MCP 세션 개설
  토큰(bootstrap token) 검증, 30초 idle/DELETE session 정리
- `WU-M3` consume 5-field issuance binding, subject별 Resource allowlist와 다섯
  `application/json` Resource, canonical HMAC Engine context GET, 폐쇄형 응답 검증과
  Resource 성공 응답 commit·terminal 전이의 session별 선형화
- `WU-M5` 선행 범위: 기존 MCP 경로의 허용 metadata 검증과 주입 가능한 로그 전달
  경계. 운영 sink·보존 정책은 미결정이며 기본 실행에서는 기록을 폐기합니다.

개발 섹터 역할은 코드 소유권과 실행 환경 책임을 분리합니다. Backend 섹터는
DB schema·migration SQL·repository와 Redis client·lock 코드를 작성하고, MCP
섹터는 PostgreSQL·Redis 인스턴스 구축·기동·중지, DDL migrator와 DML runtime
계정·권한 준비,
migration 실행과 health 확인을 담당합니다. 실제 Backend 프로세스는 DB·Redis에
직접 연결하며 MCP 서버를 데이터 프록시로 사용하지 않습니다.
Backend의 영속 `event_outbox`와 Redis fan-out은 Backend 소유이며, MCP의
`WU-M5`는 별도 영속 outbox 없이 구조화 감사 로그와 redaction만 검증합니다.

실제 게임의 LLM Agent loop 연결, MCP Tool과 canonical 게임 API의 PostgreSQL·Redis
연결은 아직 완료하지 않았습니다. WU-M3 서버는 세션 개설 토큰 검증과 5-field consume 성공 뒤
session binding이 허용한 Resource만 열며 Tool은 WU-M4에서 추가합니다. 기존 LLM Provider adapter는 연결돼
있지만 앱 수준의 LLM timeout 설정, token 상한·사용량, 비용·예산과 관련 KPI는 새 MVP
범위에서 제외합니다.

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
- 첫날 낮은 좌석순 기본 1회 발언 후 무투표로 밤에 진입하되, 전원이 `PASS`하면
  고정 질문과 추가 발언 순환을 정확히 한 번 진행
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
├── pyproject.toml                    # ai-mafia 통합 런타임·개발 의존성 및 도구 설정
├── backend/
│   ├── app/main.py                   # FastAPI 생성과 router·오류 처리 등록
│   ├── app/routers/                  # health·정본/legacy 게임·관리자·내부 Engine endpoint
│   ├── app/schemas/                  # 요청·응답 validation 계약
│   ├── app/services/                 # 사용자·게임·관리자·내부 Engine 유스케이스
│   ├── app/models/identity.py        # 외부 identity·내부 사용자 도메인 모델
│   ├── app/repositories/             # PostgreSQL 사용자·게임·Agent·관리자 저장소
│   ├── app/infrastructure/           # migration·PostgreSQL·HMAC 구현
│   ├── app/agent/                    # 규칙 엔진·Agent 정책·orchestrator(실제 실행 연결 미완료)
│   ├── app/llm_provider/             # 현재 LLM Provider adapter
│   ├── app/mcp/                      # 현재 scaffold MCP client·registry
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
│   ├── app_pages/login_page.py       # legacy OIDC 코드(실행 경로 제외)
│   ├── auth/                         # OIDC 설정·claim·접근·저장 결과 정책
│   ├── components/ui.py              # 안전한 HTML·CSS 표현
│   ├── .streamlit/secrets.toml.example
│   └── tests/
├── frontend_admin/                   # read-only 관리자 대시보드·게임 목록·상세
├── mcp_server/
│   ├── pyproject.toml, uv.lock        # Python 3.12·MCP SDK 1.29.1 독립 실행 환경
│   ├── mafia_game/                   # WU-M2 session + WU-M3 Resource MCP runtime
│   │   ├── api/streamable_session_pool.py # 세션별 Server·stateful manager 공개 lifecycle pool
│   │   ├── api/resources/            # SDK list/read handler와 session binding 연결
│   │   ├── domain/, schemas/         # URI registry·consume/context 폐쇄형 계약
│   │   ├── core/audit.py, ports/audit.py # 허용 metadata 검증·운영 sink와 독립된 로그 전달
│   │   ├── ports/, integrations/     # Engine consume/context port와 HMAC HTTP adapter
│   │   └── services/                 # bootstrap·Resource 요청 orchestration
│   ├── tests/                        # fake Engine·SDK-level WU-M2/M3 계약 테스트
│   │   └── test_audit_logging.py, test_audit_runtime.py # 로그 경계·runtime 민감정보 비노출
│   └── mcp_2/                        # 후속 MCP 독립 예약 패키지
├── docs/
│   ├── AI_MAFIA_GAME_TEST_GAP_REPORT.md # 게임 테스트 관점 미구현·미연결·규칙 차이 점검표
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
└── scripts/configure_google_oidc.py  # Google client JSON → Streamlit secrets 생성
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

Backend의 현재 게임 API는 canonical `mystery-v1` 계약을 사용하고, 기존 `scaffold-v1`
요청은 호환 경로로 처리합니다. in-memory mock repository를 주입한 실행에서는
`GET /api/v1/games`가 같은 Backend 프로세스에서 생성한 게임만 UUID 소유자별 목록으로 반환하며,
게임이 없으면 오류가 아닌 `200`과 빈 `items`를 반환합니다.
mock 게임의 좌석은 화면 표시용으로 민수·철수·영희·태경·지효·성주·환석·유빈·태웅·지혜·지토
preset 이름을 사용하지만,
API 식별자와 소유권 검사는 계속 UUID를 사용합니다.

현재 canonical 공개 게임 API의 기본 저장소도 메모리이며 사용자 upsert는 PostgreSQL을
사용합니다. 따라서 별도 테스트 의존성 주입 없이 DB가 필요 없는 실행 모드로 간주하면
안 됩니다. 과거의 `BACKEND_DATA_MODE=mock` 실행 분기는 현재 코드에 없습니다.
게임·피드백은 프로세스 재시작 시 보존되지 않으며 관리자 API의 기본 PostgreSQL
저장소와도 분리돼 있습니다. 테스트는 명시적으로 fake 저장소를 주입합니다.

관리자 접근은 Backend의 `ADMIN_USER_IDS` allowlist로 제한합니다. 관리자 UUID 저장 key는
`ai_mafia_admin_user_id_v1`이며 이 allowlist는 강한 사용자 인증을 대신하지 않습니다.

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
각 headerless initialize는 fresh low-level `Server`와 그 child application 전용 stateful
`StreamableHTTPSessionManager`를 하나씩 만듭니다. top-level lifecycle pool은 SDK 공개
constructor·`run()`·`handle_request()`만 사용하며 manager마다 `run()` context를 정확히
한 번 소유합니다. SDK 자체 idle reaper는 공개 설정 `None`으로 비활성화하고,
registry/middleware reaper만 30초 idle 종료를 소유합니다. terminal 승자는 route를 먼저
분리하고 공개 DELETE를 최대 한 번 시도한 뒤 성공·오류·취소 모두에서 해당 manager
`run()`을 끝내므로 SDK transport·owner tombstone도 함께 폐기합니다. 테스트용
`application.state.session_manager`는 이제 단일 SDK manager가 아니라 이 pool이며,
민감 ID 없이 candidate·active·running count와 run-exit count만 관측합니다. initialize
응답은 route와 registry를 모두 준비하고 commit 소유권을 얻은 뒤 외부 start/body를
송신하므로 그 사이 DELETE·reaper가 manager를 먼저 닫지 못합니다.
fresh credential 조정은 `WU-M7` 범위입니다. 초기 요청의 capability header는 정확히
한 번만 허용하고 후속 요청은 동일 bearer로만 session owner를 증명합니다. consume은
`status`, `allowed_resource_scopes`, `phase`, `state_version`, `window_id` 정확한 다섯
field를 요구하고 bootstrap claim은 기존 field 그대로 유지합니다. Resource list는
binding만 사용해 Engine을 호출하지 않으며, 허용 read는 `GET
/internal/v1/agent-context?scope=...`를 한 번 호출하고 응답을 캐시하지 않습니다.
Resource read의 Engine 호출은 서로 병렬로 진행할 수 있습니다. session gate 안에서는
검증된 성공 응답의 commit 소유권 또는 route·registry terminal 소유권만 짧게 확정하고
실제 ASGI 송신과 SDK DELETE·manager stop은 gate와 registry lock 밖에서 수행합니다.
terminal 전이가 먼저 소유권을 얻으면 이미 버퍼된 성공 context를 보내지 않고, 성공
commit이 먼저면 gate 밖 body 송신이 끝났다는 event 뒤에 terminal cleanup이 진행됩니다.
reaper는 session별 teardown을 독립 dispatch하므로 A 종료가 지연돼도 같은 sweep의 B와
이후 만료 C의 route 제거·teardown 시작을 막지 않습니다. registry cleanup의 실제
승자만 SDK transport를 한 번 닫으며 동시 DELETE 패자는 `404 SESSION_NOT_FOUND`로
끝납니다.
session ID 재사용 회귀는 A 요청 scope의 expected owner·binding과 같은 ID의 B registry
binding을 애플리케이션 경계에서 직접 구성해, SDK 내부 생성 구현을 monkeypatch하지 않고
A가 B capability로 Engine GET을 호출하지 않는지와 고정 내부 오류 redaction을 검증합니다.
후속 요청에서 raw URI·validation 같은 고정 오류 응답의 송신이 실패해도 기대 binding을
gate-aware하게 한 번 닫고 원래 transport 예외를 전파합니다. 과도하게 깊거나 5,000자리
정수를 포함한 client·Engine JSON과 비표준 `NaN`·`Infinity`·`-Infinity`는 decoder
예외나 비유한 값으로 통과하지 않고 각각 고정 `-32602`, `-32004`로 정규화됩니다. 오류
원문과 `data`는 노출하지 않으며 이 입력·Engine validation 오류 자체만으로 정상
session을 닫지는 않습니다.

## 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한(MCP 섹터 운영 책임)
- Redis 실행 환경(MCP 섹터 운영 책임, 게임 기능 구현 단계부터 필요)
- Google Cloud OAuth client는 보존된 legacy 코드 참고용이며 현재 UUID-only 앱에는 불필요
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

```bash
uv sync --dev
```

현재 사용자 앱에는 Google 설정과 Front HMAC secret이 필요하지 않습니다. LLM adapter는
선택한 Provider 설정을 사용합니다. 실제 값은 `.env.example`의 placeholder만 참고하고
Git에 넣지 않습니다.

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
INTERNAL_API_SECRET=REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS
INTERNAL_API_MAX_AGE_SECONDS=300
```

- `DATABASE_URL`에는 Backend runtime이 사용할 DML 최소 권한 계정을 설정합니다.
- `DATABASE_MIGRATION_URL`은 목표 migration runner가 사용할 DDL 계정입니다. 현재
  runner는 아직 이 이름을 읽지 않으므로 아래 migration 절의 격리 주입 절차를
  따릅니다. Backend runtime 프로세스에는 전달하지 않습니다.
- 앱은 URL의 원래 DB 경로 대신 `DATABASE_NAME`을 사용하며 기본값은 `Team4_Proj`입니다.
- `INTERNAL_API_SECRET`은 현재 legacy identity API에만 필요한 32자 이상의 값이며
  `WU-F1`·`WU-B1` 완료 뒤 제거합니다.
- 같은 `INTERNAL_API_SECRET`을 `frontend_user/.streamlit/secrets.toml`의
  `backend.internal_api_secret`에도 설정합니다. 브라우저나 소스 코드에는 넣지 않습니다.
- Backend의 기본 서명 허용 시간 오차는 300초이며 최대 3600초로 제한됩니다.
- 현재 scaffold는 `.env.example`의 `REDIS_URL`, `LLM_PROVIDER`, 선택 Provider 설정과
  `MAFIA_MCP_URL`을 이미 읽습니다. game state keyring, `MCP_SERVER_AUTH_SECRET`,
  `ENGINE_INTERNAL_API_SECRET`, `ADMIN_USER_IDS`와 `ENGINE_API_URL`은 Backend canonical
  WU에서 연결할 목표 설정입니다. WU-M3 MCP runtime은 뒤의 세 MCP 관련 값 중
  `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`만 process
  환경에서 직접 읽습니다. 실제 키 값은 승인된 비밀 저장소나 로컬의 권한 제한
  파일에만 보관합니다.
- 현재 Backend MCP client의 코드 기본값은 아직 `8010/mcp`이고 `game_ping`,
  `game_get_context`, `game_submit_proposal` placeholder Tool을 호출합니다. 목표값
  `8100/mcp`, 다섯 Resource·네 Tool과 세션 개설 토큰·capability 연결은 `WU-B6`·`WU-B7`·
  `WU-M6` 범위이며 현재 구현 완료로 간주하지 않습니다.
  `GAME_STATE_KEYRING_FILE`은 저장소 밖의 권한 제한 JSON을 가리키고
  `GAME_STATE_ACTIVE_KEY_ID`는 신규 seed·snapshot 암호화 key를 선택합니다.
  `MCP_SERVER_AUTH_SECRET`은 Backend→MCP 세션 개설 토큰 서명,
  `ENGINE_INTERNAL_API_SECRET`은 MCP→Backend 내부 경계용입니다. 두 값과
  `INTERNAL_API_SECRET`은 모두 서로 다른 값을 사용해야 합니다. 운영 MCP 연결은
  검증된 TLS를 사용합니다.
- 앱 수준의 LLM timeout, token 상한·사용량, 비용·예산 설정은 MVP에서 사용하지
  않습니다. 중단된 Agent worker는 조정 불가능한 고정 lease와 fencing token으로
  회수하며 LLM·MCP 호출 동안 PostgreSQL transaction이나 Redis game lock을 보유하지
  않습니다.
- 현재 `config.py`와 scaffold proposal에는 legacy timeout, token 상한과 비용 단가
  기본값이 남아 있습니다. 이 동작은 target MVP 기능이 아니며 `WU-B6`에서 설정 field와
  함께 제거합니다.
- `MAFIA_MCP_URL`은 `/mcp`를 포함한 전체 endpoint이며 Backend client가 경로를
  다시 붙이지 않습니다.
- `MCP_REQUIRE_TLS=false`는 loopback 개발 기본값뿐입니다. 운영은 `true`와 검증된
  CA 경로를 강제합니다.

| 환경 소비자 | 허용하는 AI 마피아 관련 키 | 주입 금지 |
|---|---|---|
| Front 서버 | Backend URL, 브라우저 UUID 저장 key | DB·Redis·LLM·MCP/Engine secret |
| Backend runtime | `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, game state keyring, LLM Provider·model·key, `MAFIA_MCP_URL`, `MCP_REQUIRE_TLS`, `MCP_TLS_CA_FILE`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ADMIN_USER_IDS`, 전환 전 `INTERNAL_API_SECRET` | `DATABASE_MIGRATION_URL` |
| migration 실행 프로세스 | `DATABASE_MIGRATION_URL`, `DATABASE_NAME` | runtime·LLM·MCP secret |
| MCP runtime | `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`와 비밀이 아닌 listen/TLS 설정 | DB·Redis·LLM 자격증명 |

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
`004_seed_scenarios_and_personas.sql`은 정본 시나리오 5개, 시나리오별 알리바이 9개와
관찰 9개로 구성된 최소 90개 문장, 최소 활성 persona 한 개를 고정 key 기반으로
멱등 등록하고 콘텐츠 SHA-256 hash와 승인 시각을 기록합니다. legacy cleanup은 아직
포함하지 않으며, 적용된 migration 파일은 수정하지 않고 이후 번호의 순방향
migration으로 확장합니다.

## Legacy Google OAuth와 Streamlit secrets

이 절은 저장소에 남아 있는 legacy 설정·스크립트의 참고용입니다. 현재 UUID 기반
MVP 실행에는 필요하지 않으며, 잔여 파일 정리는 해당 섹터에서 별도로 진행합니다.

Google Cloud Console에서 OAuth 동의 화면과 웹 애플리케이션 client를 만들고 로컬
승인된 redirect URI를 다음 값과 정확히 일치시킵니다.

```text
http://localhost:8501/oauth2callback
```

운영 환경은 실제 HTTPS 도메인의 `/oauth2callback`을 Google 설정과 Streamlit
secrets 양쪽에 동일하게 등록합니다.

Google client JSON은 저장소 밖의 안전한 경로에 두고 다음 스크립트로 OIDC 항목을
생성합니다. 이 스크립트는 client secret을 출력하지 않으며 기존 파일을 기본적으로
덮어쓰지 않습니다.

```bash
uv run python scripts/configure_google_oidc.py \
  --client-json /secure/path/google-oauth-client.json
```

기본 출력은 `frontend_user/.streamlit/secrets.toml`, redirect URI는
`http://localhost:8501/oauth2callback`, 파일 권한은 `0600`입니다. 생성 후 예시의
`[backend]` 항목을 참고해 Backend 주소와 `.env`와 동일한 내부 서명 secret을
추가해야 합니다.

```toml
[backend]
api_url = "http://127.0.0.1:8000"
internal_api_secret = "REPLACE_WITH_THE_SAME_RANDOM_VALUE_AS_BACKEND"
```

수동 설정은 예시를 복사한 뒤 OIDC와 Backend 값을 모두 채웁니다.

```bash
cp frontend_user/.streamlit/secrets.toml.example \
  frontend_user/.streamlit/secrets.toml
chmod 600 frontend_user/.streamlit/secrets.toml
```

실제 `.env`, `secrets.toml`, Google OAuth JSON은 Git 무시 대상이며 이동·커밋하지
않습니다.

## 실행

MCP 담당자가 PostgreSQL을 먼저 기동하고 연결·migration 상태를 확인한 뒤
Backend를 실행합니다. 게임용 Redis가 구현된 이후에는 Redis health도 먼저
확인합니다.

```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

`http://127.0.0.1:8000/health`의 정상 응답은 `{"status":"ok"}`입니다.

Mafia Game MCP는 별도 프로젝트 환경을 동기화하고 MCP 전용 process 환경에 서로 다른
32자 이상 secret과 Engine base URL을 주입한 뒤 실행합니다. 공용 루트 `.env`를 자동
로딩하지 않으며 현재 평문 listen은 loopback만 허용합니다. 아래 명령은 저장소
루트에서 실행합니다.

```bash
uv sync --project mcp_server --locked --dev
uv run --project mcp_server --directory mcp_server --locked python -m mafia_game.main
```

기본 endpoint는 `http://127.0.0.1:8100/mcp`입니다. `/health`나 다른 공개 endpoint는
현재 WU에 없고 Tool·Resource template·legacy alias도 등록하지 않습니다. Resource는
`mafia://session/public`, `me`, `turn`, `persona`, `gm-guide` 다섯 canonical URI 중
consume binding이 허용한 nonempty 부분집합만 나열·조회합니다. 현재 merge된 Backend의
consume 구현은 아직 `{"status":"CONSUMED"}`만 반환해 승인된 5-field 계약과
불일치하므로 실제 initialize는 의도대로 `403 BOOTSTRAP_DENIED`로 실패합니다. Backend가
`WU-B7`의 5-field 응답을 맞춘 뒤 실제 왕복은 `WU-M6`에서 검증하며, 그 전에는 아래
package 테스트의 fake Engine으로 WU-M3 독립 계약만 검증합니다.

Resource read는 Engine 결과를 메모리에 버퍼링한 뒤 실제 응답 송신 직전에 같은
bearer와 기대 session binding을 다시 검증합니다. 이 사이에 만료·종료되었거나
Engine이 capability를 403·404로 거부하면 binding과 SDK transport를 한 번만
정리하고 같은 session의 후속 list/read를 허용하지 않습니다.

일반 사용자 앱은 별도 터미널에서 실행합니다.

```bash
uv run streamlit run frontend_user/app.py --server.port 8501
```

Windows에서 `uv`를 사용하지 않는 경우 프로젝트 가상환경의 Python으로 실행할 수
있습니다.

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m streamlit run ".\frontend_user\app.py" --server.port 8501
```

브라우저에서 [http://localhost:8501](http://localhost:8501)을 엽니다. OIDC 또는
Backend 설정이 없거나 안전성 검사를 통과하지 못하면 접근을 허용하지 않고 고정된
구성·재시도 안내만 표시합니다.

관리자 앱은 업무 기능 없이 독립 실행 경계만 확인할 수 있습니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 entrypoint는 실행 위치와 무관하게 저장소 루트를 import 경로에 등록해
`frontend_admin` 패키지를 불러옵니다.

## 실행 경로에서 제외된 legacy 구현: Google 로그인

Google OIDC 인증부터 내부 사용자 계정 연결, 로그인 프로필 표시와 로그아웃까지
현재 코드에 구현돼 있습니다. 이 흐름은 새 UUID-only 계약과 동시에 사용하는 기능이
아니며 `WU-F1`·`WU-B1`에서 제거합니다. 전환 전 제공되는 화면은 연결된 계정의
프로필과 로그아웃 UI이고 AI 마피아 홈·게임 화면은 후속 구현 범위입니다.

1. 앱 시작 시 `auth.redirect_uri`, 32자 이상의 cookie secret, Google client
   ID·secret과 HTTPS metadata URL을 검사합니다. 설정이 누락되거나 안전하지 않으면
   로그인 버튼을 비활성화하고, 남아 있는 OIDC cookie도 인증 상태로 사용하지 않습니다.
2. 사용자가 `Google로 계속하기`를 누르면 `st.login("google")`이 Google OIDC
   리디렉션을 시작하고 Streamlit이 `/oauth2callback`과 cookie session을 처리합니다.
3. 콜백 후 `st.user`의 `sub`, email, 표시명, email 검증 여부와 프로필 이미지를
   공급자 중립 신원 모델로 변환합니다. 문자열은 제어 문자와 길이를 제한하고,
   아바타는 HTTPS 절대 URL만 허용합니다.
4. Frontend는 정규화한 신원을 JSON body로 만들고
   `timestamp.request_id.raw_body`를 HMAC-SHA256으로 서명해
   `POST /api/v1/identity/provision`만 호출합니다. DB에는 직접 접근하지 않습니다.
5. Backend는 UUID request id, 기본 300초 시간 오차, HMAC과 요청 schema를 다시
   검증한 뒤 `IdentityService`와 PostgreSQL 저장소를 호출합니다.
6. 첫 로그인은 `users`와 `oauth_identities`를 한 트랜잭션에서 생성하고,
   재로그인은 프로필과 최근 로그인 시각을 갱신합니다. 동시 첫 로그인은
   `(provider, provider_subject)` 기준 advisory transaction lock으로 직렬화합니다.
7. 저장된 활성 사용자 응답을 받은 실행에서만 애플리케이션 접근을 허용합니다.
   설정 오류, 서명 실패, Backend·DB 장애와 비활성 계정은 모두 접근 거부로 끝납니다.
8. 로그아웃은 세션에 캐시한 계정 연결 결과를 제거한 뒤 `st.logout()`을 호출해
   다른 Google 계정으로 다시 로그인할 때 이전 사용자 상태가 재사용되지 않게 합니다.

이메일은 변경 가능한 프로필일 뿐 계정 연결 키가 아니며, `(provider,
provider_subject)`만 외부 계정 연결에 사용합니다. `request_id`는 현재 추적
상관관계에 사용하고, Redis가 추가되는 후속 단계에서 짧은 TTL의 재전송 차단 키로
확장합니다.

## 독립 MCP 작업·검증 결과 (2026-09-05)

이번 변경은 타 섹터 협의를 제외한 기존 M3 보완, M5 로그 선행 구현과 확정된 로컬
실행 절차에 한정했습니다. Backend·Front 소스, 공개·내부 API 계약과 DB SQL은 변경하지
않았습니다. 기존 사용자 변경을 유지했으며 commit·push는 하지 않았습니다.

- M3: 단독 Unicode surrogate가 UTF-8 직렬화 단계에서 실패하기 전에 계약 오류로
  거부하고, RFC3339 소수초를 미세초로 절삭하지 않고 비교합니다.
- M5 선행: 여섯 필드의 안전한 record만 주입한 sink로 전달합니다. 기본값은 폐기이고
  SDK·HTTP·Uvicorn의 원문 진단 로그는 formatter 전에 차단합니다. 요청별 상관관계,
  오류·취소·teardown·수집기 실패를 검증했습니다. Tool 계측과 OPEN-04는 남아 있습니다.
- 운영 준비: [MCP README](mcp_server/mafia_game/README.md)에 확정된 환경 분리와
  로컬 실행·종료 절차를 반영했습니다. M6~M8 전체 완료로 표시하지 않습니다.

| 검증 | 결과 | 범위·제외 사항 |
|---|---|---|
| MCP 전체 | 255 passed | fake Engine·SDK/ASGI, 실제 외부 서비스 없음 |
| MCP Ruff·lock | 통과 | `ruff check mafia_game tests`, `uv lock --check --offline` |
| Backend | 101 passed, 2 deselected | 실제 `.env`를 직접 읽는 설정 테스트 두 개 제외 |
| Front 사용자 | 46 passed, 기존 실패 1개·수집 오류 파일 2개 | 구 OIDC 테스트의 import·화면 기대치 불일치 |
| Front 관리자 | 3 passed | synthetic API 응답 검증 |

Backend·Front의 첫 전체 수집은 `frontend_user/tests/test_api_client.py`와
`test_persistence.py`가 삭제된 `IdentityApiClient`를 참조해 중단됐습니다. 이 두 파일을
제외한 부분 검증 합계는 150 passed, 1 failed, 2 deselected입니다. 남은
`test_app_smoke.py`는 실제 Backend 호출 시도가 있어 연결 차단기로 막았고, 프로세스에만
synthetic 빈 게임 목록을 주입한 재현에서도 현재 UUID 화면에 과거 Google 로그인 버튼을
기대해 실패했습니다. 이 기존 문제는 이번 MCP 변경과 독립적이므로 수정하지 않았습니다.

타 섹터 검증은 `env -i`, `PYTHON_DOTENV_DISABLED=1`, synthetic 설정·빈 Streamlit
secrets와 프로세스 한정 socket/psycopg 차단 wrapper에서 수행했습니다. 실제 설정 파일을
직접 읽는 `test_project_env_database_url_keeps_connection_and_targets_team4_proj`와
`test_settings_can_load_the_configured_database_name_from_env`는 deselect했습니다.
일반 pytest 명령만으로 같은 격리가 보장되는 것은 아닙니다.

보류 항목은 M4 Tool 허용표 조회·proposal 세부 schema/오류 정책, 운영 sink·TLS·health·
fresh reconnect 조정, 인프라 대상 환경 확인과 실제 Backend 연결입니다. migration `004`의
시나리오 검증은 비정상 행을 세면서 `5-count(*)`를 계산해 정상 seed도 실패시킬 구조가
정적으로 확인됐습니다. 실제 DB에서 재현하지 않았으며 Backend 수정 산출물 전에는
M1B 성공을 선언하지 않습니다. 자세한 WU별 경계는
[MCP 설계서](docs/개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)의 15.4절을
따릅니다.

## 테스트와 정적 검사

변경 동작별 focused test 예시는 다음과 같습니다.

```bash
uv run pytest backend/tests/test_identity_api.py
uv run pytest backend/tests/test_users_repository.py
uv run pytest frontend_user/tests
cd mcp_server
uv run --locked pytest tests
uv run --locked ruff check mafia_game tests
uv lock --check
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

자동 테스트는 synthetic identity, 가짜 DB 연결, mock HTTP transport를 우선 사용합니다.
다만 위 결과에 기록한 기존 설정·smoke 테스트는 실제 파일·서비스를 참조하므로 격리나
명시적 제외가 필요합니다. 실제 Google OAuth 왕복과 실제 PostgreSQL
마이그레이션은 자격 증명과 로컬 인프라가 필요하므로 MCP 담당자가 실행 환경을
준비·검증하고 Backend 담당자와 결과를 공동 판정합니다.

## 보안 원칙과 알려진 제약

- `.env`, 실제 `secrets.toml`, OAuth JSON, token과 모든 실제 자격증명을 커밋하지 않습니다.
- 현재 legacy OIDC cookie secret과 Front HMAC secret은 전환 전까지 재사용하지 않고
  응답·로그에 넣지 않습니다.
- 목표 공개 API의 `X-User-Id`는 인증이 아니라 UUID scope 선택값입니다. UUID를 아는
  사용자의 가장을 막지 못하므로 MVP는 개인 개발 환경 또는 사설망으로 제한합니다.
- 내부 Engine HMAC과 MCP 세션 개설 토큰 서명 secret은 Front에 전달하지 않고 서로
  다른 값으로
  유지합니다. 서명을 통과한 payload도 schema와 도메인 규칙으로 다시 검증합니다.
- Backend만 전체 역할·야간 행동·seed를 보유하고, AI GM과 각 플레이어 Agent에는
  공개 상태 및 자기에게 허용된 개인 정보만 전달합니다.
- MCP capability는 game·agent job·phase·state version·window에 묶습니다. 각
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
- 관리자 앱에는 read-only 화면과 Backend allowlist 응답 기반 거부 경로가 있습니다.
  강한 인증과 전체 사용자 게임 흐름의 운영 통합은 완료되지 않았습니다.
- 현재 Mafia Game MCP에는 `/mcp`, 5-field consume binding, 다섯 Resource와 Engine
  context HTTP adapter가 있으며 Tool과 DB·Redis 접근은 없습니다. Context JSON은
  API 8.2의 폐쇄형 schema, binding, AI subject·투표 target·집계의 단일 응답
  불변식을 통과한 요청에서만 반환하고 요청 종료 뒤
  cache·model·text reference를 보관하거나 stale fallback으로 재사용하지 않습니다.
- 현재 Backend `consume_bootstrap`은 status-only 응답이므로 실제 MCP initialize와
  통합할 수 없습니다. MCP validator를 완화하지 않으며 Backend `WU-B7` 정합화와
  `WU-M6` 실제 통합을 남은 제약으로 둡니다.

비밀값 노출이 의심되면 값을 다시 출력하지 말고 즉시 폐기·재발급한 뒤 Git 이력과
외부 로그를 별도로 점검하세요.

## 확장 지점

- 제거 대상 legacy identity: `frontend_user/auth/`, `frontend_user/app_pages/login_page.py`,
  `backend/app/routers/identity_router.py`, `backend/app/services/identity_service.py`
- Backend API client: `frontend_user/core/api_client.py`
- 사용자 저장소: `backend/app/repositories/user_repository.py`
- schema 변경: Backend가 `backend/migrations/`에 다음 번호의 순방향 SQL을
  추가하고 MCP 담당자가 실제 환경에서 실행·재실행 검증
- Agent·LLM·MCP client: `backend/app/agent/`, `backend/app/llm_provider/`,
  `backend/app/mcp/`
- 독립 MCP 기능: `mcp_server/mafia_game/`(현재 session·Resource, 후속 Tool) 또는
  `mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만 커밋이나
push를 자동 승인하지 않습니다.
