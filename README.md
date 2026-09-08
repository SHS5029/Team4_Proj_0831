# AI 마피아

**AI 마피아**는 함께할 사람을 기다리지 않아도 1명의 인간 플레이어와 개성 있는
여러 AI 플레이어가 바로 한 판을 완주할 수 있도록 만드는 소셜 디덕션 게임입니다.
`mystery-v1`은 6~9명 규모의 마피아 게임에 다섯 개의 경량 사건 배경을 결합합니다.
AI별 말투·공격성·기만 표현은 달리하되 MVP 밸런스 검증 중 추론 모델과 정보 접근
권한은 동일하게 유지합니다. 규칙과 승패는 Backend 게임 엔진이 결정하고 LLM은
허용된 정보 안에서 대화와 선택만 담당합니다.

제품 목표와 MVP 범위는
[AI 마피아 MVP 공통 마스터플랜](docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md)을
기준으로 합니다. 개발하거나 기여하기 전에 반드시 [AGENTS.MD](AGENTS.MD)의
브랜치, 커밋, 파일·디렉터리 구조, 테스트, 주석 및 문서화 규칙을 확인하세요.

날짜별 변경·검증 기록은 [docs/fix/](docs/fix/)에 모아 두었습니다.

## 주요 기능

### 게임 규칙 (mystery-v1 · scenario-v1)

- 전체 6~9명, 탐정·의사·시민과 서로 정체를 모르는 마피아
- 첫날 낮은 1분 45초 자유 채팅 후 무투표로 밤에 진입
- 첫날(Day 1)은 인간·AI 모두 발언 PASS 금지. AI 생성·MCP 조회 실패 시에는 사실을
  단정하지 않는 짧은 질문을 사용합니다. 확인한 공개 이력의 질문은 중복을 피하고,
  준비된 질문을 모두 사용하면 가장 오래된 질문부터 재사용하며, 이력이 없으면
  게임·AI·발언 창별로 결정적으로 선택합니다. 이력 조회 자체가 실패하면
  중복 방지를 보장할 수 없습니다. 둘째 날 이후 PASS 규칙은 유지합니다
- 정상 생성한 대사는 MCP 제출 실패만으로 기본 대사로 바꾸지 않습니다. 최초 상태
  버전·발언 창으로 같은 대사를 재제출하며, 이미 처리됐거나 차례가 바뀌면 기존 검증이 거부합니다
- 게임·관리자 API의 동기 DB 작업은 별도 스레드에서 실행합니다. 브라우저 조회나
  관리자 집계가 오래 걸려도 공용 이벤트 루프와 MCP 응답 처리를 막지 않습니다
- 발언은 200자 이하, 플레이어별 최근 1분에 최대 7회. 밤 행동은 20초·투표는 30초의
Backend 권위 deadline
- 다섯 개 시나리오와 플레이어별 알리바이·관찰 정보를 검증된 seed 기반
카탈로그로 배정하고 사용자별 직전 시나리오 제외
- 최대 다섯째 밤 뒤 표준 승패가 없으면 최종 지목으로 종료
- 투표·재투표·최종 지목은 모든 미제출 AI가 병렬로 판단하고 완료된 표부터 저장
- 투표는 후보별 집계만 공개하고 밤 사망 역할은 숨기며 처형 역할만 공개
- AI GM은 공개 확정 이벤트만 받고 전체 비공개 상태는 Backend만 보유
- 저장한 게임은 이어서 재개할 수 있고, 사용자는 진행·저장 게임을 수동으로 삭제할 수 있습니다
- `IN_PROGRESS` 게임은 마지막 사용자 command 뒤 15분간 새 사용자 command가 없으면
중앙 worker가 자동 삭제합니다(SAVED·COMPLETED·FAILED는 자동 삭제하지 않음)

### AI 플레이어

- 역할(시민·탐정·의사·마피아)별 전략과 승리 계획은 MCP의 프롬프트가 제공하고,
  기본 LLM 모델과 정보 접근 권한은 모든 AI에 동일합니다
- 성격(preset)별 `speech_style`·`backstory`·`parameters`는 team DB의
  `agent_personas`에 배정된 값을 모델에 그대로 전달합니다
- AI는 상대 답변에 대한 인정·반박·정정과 조건부 협력을 섞고, 의심 대상과 설득할
  상대를 구분하도록 안내합니다. 모든 성격에 도발을 강제하지 않으며 말투·감정 표현은
  배정된 페르소나와 상황에 맞춥니다
- 마피아는 사실과 필요한 왜곡을 섞어 신뢰·표를 확보하고, 시민 진영은 오처형 위험을
  고려해 미끼 주장을 사용합니다. 탐정은 조사 공개 시점, 의사는 보호 계획의 노출,
  마피아는 공격과 낮 처형의 이득을 비교합니다. 실제 기록·타인의 주장·자신의 블러핑을
  구분하며 역할·허용 행동·정보 권한과 첫날 SPEAK 의무는 유지합니다. 프롬프트 지침이므로
  실제 대화 품질이나 승률 개선을 보장하지는 않습니다
- 문구는 `mcp_server/mafia_game/api/prompts/instructions.py`에서 관리합니다.
  실행 중인 MCP는 재시작해야 바뀐 지침을 다음 AI 판단부터 전달합니다
- Backend 중앙 AI worker가 열린 AI 차례(발언·밤·투표)를 비동기로 회복하며,
  LLM·MCP 호출 실패 시에만 같은 규칙의 결정적 fallback을 사용합니다
- AI 판단 단계(정보 확인 → 판단 → 선택 → 적용)와 제한된 공개 판단 근거 요약을
  게임 화면에서 확인할 수 있습니다
- Agent 예약은 최대 40초이며 실제 게임 창 마감을 넘지 않습니다. MCP 조회·최초
  모델 요청·교정 요청이 같은 잔여 시간을 사용하고 완료·제출용으로 3초를 남깁니다.
  요청 취소를 삼킨 늦은 응답도 거부하며, 시작할 시간이 없으면 추가 요청 없이 폐기합니다
- `FALLBACK`은 예약 완료가 승인된 대체 선택이며 실제 반영은 `APPLIED`와 DB event로
  확인합니다. 만료·fencing 거부로 버린 시도는 `FALLBACK PASS` 선택으로 기록하지 않습니다.
  `AGENT_GENERATION_FAILED` 내부 진단은 비공개 actor·원문 없이 고정 실패 코드만 남깁니다

### 화면

- **사용자 앱**: UUID 자동 생성, 홈(게임 목록·이어하기), 새 게임 생성·역할 공개,
  게임 진행·관전, 결과·게임 기록, 일반·게임별 피드백
- 토론 입력은 Enter로 순서대로 예약하며 실시간 대화·상태 갱신 중에도 유지합니다.
  밤·투표는 선택 입력과 시계 갱신을 분리하고, 홈 이동 시 저장·이탈 확인을 제공합니다.
  탐정의 조사 결과는 본인 화면에서만 별도로 표시합니다
- **관리자 앱**(read-only): 게임 KPI·진영별 승률·페르소나별 AI 승률, 사용자 피드백,
  관리자 감사 로그와 공개 AI 발언 분석을 네 탭으로 표시하고 30초마다 갱신합니다.
  발언 분석은 `speech_analysis` 임베딩으로 유사 주제를 묶고 원문 키워드·stance·
  대표 근거를 함께 보여 줍니다. 운영 에이전트 계획 탭은 제거됐으며 질문 API는
  Backend 독립 계약으로 유지합니다
- 공개 발언의 실시간 임베딩·주장 분석과 투표 보조 정보 표시(선택 기능,
  기본 비활성)

## 아키텍처 개요

- **Backend**(FastAPI, `backend/`): 게임 엔진(`backend/app/game_engine/`),
  PostgreSQL 게임 원장·snapshot·event, 공개/내부 HTTP API, 중앙 AI worker,
  발언 분석 worker
- **MCP server**(FastMCP, `mcp_server/mafia_game/`): AI에게 게임 context를 제공하는
  Resource·Prompt·행동 위임 Tool. DB·Redis에 직접 접근하지 않고 Backend 내부
  API만 호출합니다
- **Frontend**(Streamlit): `frontend_user/`(사용자), `frontend_admin/`(관리자,
  read-only). 둘 다 Backend만 HTTP로 호출하고 DB·Redis·MCP에 직접 접근하지 않습니다
- **PostgreSQL**: 게임 원본(migration 001~009로 구성)
- **Redis**: 전체 공개 대화 cache와 보조 계층

Backend는 actor별 허용된 정보만 scope별로 투영하고, 밤 행동과 개별 투표는 게임
종료 전에 공개하지 않습니다.

## 개발 문서

| 문서 | 기록된 내용 |
| --- | --- |
| [AI_MAFIA_MASTER_PLAN.md](docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md) | 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터 소유권, WU/CP 정본 |
| [AI_MAFIA_DB_DESIGN.md](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md) | PostgreSQL·Redis schema, transaction, lock, migration과 보존 계약 |
| [AI_MAFIA_API_SPEC.md](docs/개발상세플랜/AI_MAFIA_API_SPEC.md) | 일반·관리자·내부 Engine HTTP API와 MCP Resource·Tool 계약 |
| [AI_MAFIA_MCP_SERVER_DESIGN.md](docs/개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md) | MCP runtime 구조, 보안 경계와 WU-M1A~WU-M8 실행·검증 계획 |
| [AI_MAFIA_SCREEN_FLOW.md](docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md) | UUID 초기화, 사용자 게임·관전·피드백과 관리자 화면 흐름 |
| [AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md](docs/개발상세플랜/AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md) | Streamlit Front 전용 WU-F1~F10 기술 설계 |
| [AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md](docs/개발상세플랜/AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md) | Frontend–Backend 공개 API, SSE·CORS, 오류·private 경계 요약 |
| [AI_MAFIA_INDEPENDENT_CONTRACT.md](docs/개발상세플랜/AI_MAFIA_INDEPENDENT_CONTRACT.md) | 세 섹터 독립 구현 시 공통 최소 연결 형식·경계 |
| [AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md](docs/개발상세플랜/AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md) | 게임 엔진·Agent Manager 모듈화 전략 임시 초안 |
| [AI_MAFIA_CURRENT_CODE_STATUS.md](docs/AI_MAFIA_CURRENT_CODE_STATUS.md) | 현재 실제 코드 구조, 게임 흐름, 공개 API, 설정, 검증 결과와 제약 |
| [AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md](docs/AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md) | StateGraph 도입안: 분기·기억·도구·공유 상태·종료 조건 |

다섯 MCP Resource의 상세 `data` schema는 API 명세 8.2절만 정본입니다.
날짜별 변경·검증 내역은 [docs/fix/](docs/fix/)를 참조하세요.

## 프로젝트 구조

```text
.
├── AGENTS.MD                         # 개발·기여 작업 규칙
├── README.md                         # 전체 설정·실행·검증 안내
├── .env.example                      # Backend 환경 변수 예시
├── run_openai.sh                     # macOS/Linux용 OpenAI Backend·MCP·Front 동시 실행
├── run_openai.bat                    # Windows용 PowerShell 실행 진입점
├── run_openai.ps1                    # Windows용 OpenAI Backend·MCP·Front 실행 로직
├── pyproject.toml                    # ai-mafia 통합 런타임·개발 의존성 및 도구 설정
├── backend/
│   ├── app/main.py                   # FastAPI 생성과 router·오류 처리 등록
│   ├── app/routers/                  # health·공개 게임·내부 Engine endpoint
│   ├── app/schemas/                  # 요청·응답 validation 계약
│   ├── app/services/                 # UUID 사용자·게임 유스케이스
│   │   └── game/                     # 게임 업무 Service·공용 계약
│   ├── app/models/identity.py        # UUID 내부 사용자 모델
│   ├── app/repositories/             # PostgreSQL CRUD·row 변환 저장소
│   ├── app/infrastructure/           # migration·PostgreSQL·내부 HMAC 구현
│   ├── app/agent/                    # Agent 정책·projection·orchestration
│   ├── app/game_engine/              # 순수 게임 규칙·phase·결정적 RNG 정본 package
│   ├── app/llm_provider/             # 현재 LLM Provider adapter
│   ├── app/mcp/                      # Backend Agent용 MCP context client·registry
│   ├── migrations/                   # Backend 작성 SQL migration(MCP 실행, 001~009)
│   ├── logs/                         # 실행 시 생성되는 순환 진행 로그 (Git 제외)
│   ├── tests/
│   └── README.md
├── frontend_user/
│   ├── app.py                        # UUID bootstrap·화면 dispatcher
│   ├── app_pages/                    # 홈·생성·역할 공개·게임·결과·피드백·설정 화면
│   ├── components/                   # identity bridge·테마·투표 보조 등 공통 UI
│   ├── core/                         # identity·session·api_client·sync
│   ├── .streamlit/secrets.toml.example
│   └── tests/
├── frontend_admin/                   # read-only 관리자 운영 분석·발언 분석·피드백·로그
├── mcp_server/
│   ├── pyproject.toml, uv.lock       # Python 3.12·MCP SDK 1.29.1 독립 실행 환경
│   ├── mafia_game/                   # 최소 FastMCP 등록부·Backend HTTP adapter
│   ├── tests/
│   └── mcp_2/                        # 후속 MCP 독립 예약 패키지
├── docs/
│   ├── fix/                          # 날짜별 변경·검증 기록 모음
│   ├── AI_MAFIA_GAME_TEST_GAP_REPORT.md # 게임 테스트 관점 미구현·미연결·규칙 차이 점검표
│   ├── AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md # 자동 투표 원인·병렬 처리 수정·실행 확인
│   ├── AI_MAFIA_UI_UX_PLAYTEST_REPORT.md # UI·UX 관찰·정본 대조·개선 우선순위
│   └── 개발상세플랜/                  # 위 개발 문서 표의 정본
└── scripts/                          # 운영·개발 보조 스크립트
```

## 시작하기

### 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한(MCP 섹터 운영 책임)
- Redis 실행 환경(MCP 섹터 운영 책임)
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

### 로컬 가상환경과 의존성 준비

| 위치 | 용도·설치 기준 |
| --- | --- |
| `.venv` | 통합 환경, 루트 `pyproject.toml`·`uv.lock`의 dev 포함 |
| `backend/.venv` | `backend/requirements.txt`, pytest·pytest-asyncio·httpx2 포함 |
| `frontend_user/.venv` | `frontend_user/requirements-dev.txt` |
| `frontend_admin/.venv` | `frontend_admin/requirements.txt`와 테스트용 `pytest>=8,<9` |
| `mcp_server/.venv` | 독립 `pyproject.toml`·`uv.lock`의 dev 포함, MCP SDK 1.29.1 |

기존 환경을 삭제하거나 덮어쓰지 않고, 없는 컴포넌트 환경만
`uv venv --python 3.12 <컴포넌트>/.venv`로 만듭니다. 설치·갱신:

```bash
uv sync --locked --dev
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
uv pip install --python frontend_user/.venv/bin/python -r frontend_user/requirements-dev.txt
uv pip install --python frontend_admin/.venv/bin/python -r frontend_admin/requirements.txt 'pytest>=8,<9'
uv sync --project mcp_server --locked --dev
```

Windows에서는 컴포넌트별 환경을 분리하고 반드시 환경 내부 Python으로 설치합니다:

```powershell
& ".\backend\.venv\Scripts\python.exe" -m pip install -r ".\backend\requirements.txt"
& ".\frontend_user\.venv\Scripts\python.exe" -m pip install -r ".\frontend_user\requirements-dev.txt"
& ".\frontend_admin\.venv\Scripts\python.exe" -m pip install -r ".\frontend_admin\requirements.txt"
```

### 사용자 식별

로그인 없이 브라우저가 생성·보관한 UUID v4 `user_id`와 `X-User-Id` header로
사용자를 구분합니다(저장 key: `ai_mafia_user_id_v1`). UUID는 인증 수단이 아니므로
신뢰된 로컬·사설망 환경에서만 사용합니다.

```bash
cp frontend_user/.streamlit/secrets.toml.example \
  frontend_user/.streamlit/secrets.toml
chmod 600 frontend_user/.streamlit/secrets.toml
```

실제 `.env`와 `secrets.toml`은 Git 무시 대상이며 이동·커밋하지 않습니다.

## 환경 설정

### Backend·Data Infrastructure

기존 `.env`에는 다른 로컬 설정이나 비밀값이 있을 수 있으므로 덮어쓰지 마세요.
아래 복사는 로컬 개발용 placeholder 시작점입니다. 운영에서는 프로세스별
allowlist만 주입합니다(아래 표).

```bash
cp .env.example .env
chmod 600 .env
```

필수·기본 설정 예시:

```dotenv
TEAM_DATABASE_URL=postgresql://runtime_user:change-me@remote-host:4000/Team4_Proj
DATABASE_MIGRATION_URL=postgresql://migration_user:change-me@remote-host:4000/Team4_Proj
DATABASE_NAME=Team4_Proj
AI_MAFIA_STORAGE_MODE=team
```

- `TEAM_DATABASE_URL`의 팀 DB가 기본 테스트 DB입니다. DB 조사·실제 게임·DB 연동
검증을 여기서 진행하며, 실제 `.env`에는 로컬 DB URL을 두지 않습니다. DML 최소 권한
계정을 설정하고 다른 테스트의 게임·자료는 임의로 변경하지 않습니다.
- 기존 `DATABASE_URL` fallback은 별도 로컬 작업을 명시적으로 선택할 때만 사용합니다.
- `DATABASE_MIGRATION_URL`은 migration runner 전용 DDL 연결입니다. runtime DSN으로
대체하지 않으며 Backend runtime 프로세스에는 전달하지 않습니다.
- `run_openai.sh`의 `AI_MAFIA_STORAGE_MODE` 기본값은 `team`(공유
`TEAM_DATABASE_URL` 사용)입니다. `isolated`는 별도 로컬 작업을 명시적으로 요청한
경우에만 선택합니다.
- LLM Provider는 `LLM_PROVIDER`로 `dummy`(테스트 전용 고정 PASS)·`local`·`openai`·
`gemini` 중 하나를 선택하고, `config.py`가 모델·필수 키를 검증합니다.
- `LLM_TIMEOUT_SECONDS`(기본 30초)는 모든 중앙 Agent의 요청별 상한입니다. 실제
요청은 창·예약 마감에서 완료·제출 여유 3초를 뺀 잔여 시간보다 길게 실행하지 않습니다.
3초는 여유이며 DB·네트워크 지연에도 제출 완료를 보장하는 값은 아닙니다. 늦은 제출은
기존 마감·상태 검증으로 거부합니다. OpenAI의 `high` 추론 노력과 출력 한도는 유지합니다.
- Backend 중앙 AI worker는 `MCP_SERVER_URL`로 FastMCP 서버를 호출합니다.
- Backend는 `CORS_ALLOWED_ORIGINS`에 등록된 Front origin에만 SSE fetch preflight와
동기화 header를 허용합니다.
- 공개 발언 분석은 `SPEECH_ANALYSIS_ENABLED=false`가 기본이며, 활성화하려면
migration 006·008 적용과 [.env.example](.env.example)의 `SPEECH_ANALYSIS_*` 설정이
필요합니다.

| 환경 소비자 | 허용하는 AI 마피아 관련 키 | 주입 금지 |
| --- | --- | --- |
| Front 서버 | Backend URL | DB·Redis·LLM·MCP/Engine secret |
| Backend runtime | `TEAM_DATABASE_URL`, `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, game state keyring, LLM Provider·model·key, `ADMIN_USER_IDS`, `MCP_SERVER_URL`, `CORS_ALLOWED_ORIGINS` | `DATABASE_MIGRATION_URL`, MCP runtime 전용 설정 |
| migration 실행 프로세스 | `DATABASE_MIGRATION_URL`, 비교용 `TEAM_DATABASE_URL`/`DATABASE_URL`·`DATABASE_NAME` | LLM·MCP secret |
| MCP runtime | `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT` | DB·Redis·LLM·인증 secret |

## 데이터베이스 마이그레이션

Backend가 작성·소유하는 `backend/migrations/`의 SQL을 MCP 담당자가 이름순으로
실행합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

- `001` legacy `users`·`oauth_identities`, `002` scaffold `scaffold_*` 게임 테이블(보존, 미사용)
- `003_create_mystery_v1_schema.sql`은 canonical `mystery-v1` 테이블을 순방향 추가
- `004_seed_scenarios_and_personas.sql`은 정본 시나리오 5개·알리바이·관찰 문장·persona를 멱등 등록
- `005_create_admin_knowledge_schema.sql` 관리자 운영 에이전트 색인(pgvector 필요)
- `006_create_speech_analysis.sql` 발언 분석 파생 저장소(pgvector 비의존)
- `007_add_stale_game_cleanup.sql` `games.last_user_action_at` 추가와 15분 무동작 정리 index
- `008_allow_public_human_speech_analysis.sql` 공개 사용자 발언 분석 허용
- `009_update_persona_reasoning_skill.sql` persona 추론 수치·내용 hash 갱신

자세한 기본값·권한 분리는 [.env.example](.env.example)과
[DB 설계 정본](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md)을 참고하세요.

## 실행

### 한 번에 실행 (OpenAI)

```bash
./run_openai.sh --check  # 유료 API 호출 없이 세 런타임 설정·import 검증
./run_openai.sh          # Backend·MCP·Front 동시 실행
```

Windows PowerShell 또는 명령 프롬프트에서는 다음처럼 실행합니다.

```bat
run_openai.bat --check
run_openai.bat
```

동시 실행 주소: Backend `http://127.0.0.1:18000`, MCP
`http://127.0.0.1:18100/mcp`, Front `http://127.0.0.1:18501`.
다른 프로젝트와 포트가 겹치면 `AI_MAFIA_BACKEND_PORT`·`AI_MAFIA_MCP_PORT`·
`AI_MAFIA_FRONTEND_PORT`로 바꿀 수 있습니다.

Backend는 `backend/app` 안의 코드 변경만 `--reload`로 반영합니다. Front·테스트 편집은
Backend를 재시작하지 않습니다. MCP 프롬프트·adapter는 자동 재적재하지 않습니다.
MCP 변경 후에는 실행 터미널에서 `Ctrl+C`로 종료하고 `./run_openai.sh`로 전체 재시작합니다.

두 실행 스크립트의 기본 저장소 모드는 `team`입니다. 명시적 `isolated`는
`AI_MAFIA_DATABASE_URL`·`AI_MAFIA_REDIS_URL`을 사용하며 같은 팀 DB를 격리 DB로
지정하면 거부합니다. Windows `--check`는 필수 환경값 읽기와 import만 검사하고,
설정 객체·DB·Redis·migration·seed·API 연결은 검사하지 않습니다. macOS/Linux
`--check`는 선택한 DB·Redis와 seed 준비 상태까지 읽기 전용으로 검사합니다.

### 개별 실행

```bash
# Backend (dummy Provider로 첫 검증)
LLM_PROVIDER=dummy .venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000

# MCP server
(cd mcp_server && .venv/bin/python -m mafia_game)

# 사용자 Front
uv run streamlit run frontend_user/app.py --server.port 8501

# 관리자 Front (실제 API 모드 예시)
BACKEND_API_URL=http://127.0.0.1:18000 ADMIN_DEMO_MODE=false \
  frontend_admin/.venv/bin/python -m streamlit run frontend_admin/app.py \
  --server.address 127.0.0.1 --server.port 8502 --server.headless true
```

health 주소: 수동 Backend `http://127.0.0.1:8000/health`, 동시 실행
`http://127.0.0.1:18000/health` → `{"status":"ok"}`.

진행 로그 확인:

```bash
tail -f backend/logs/game-progress.log
```

관리자 앱의 실제 조회는 Backend `ADMIN_USER_IDS`에 등록된 UUID가 필요합니다.
Backend·UUID 없이 화면만 확인하려면 `ADMIN_DEMO_MODE=true`로 실행하면 합성
데이터가 표시됩니다(실제 권한 검증을 대신하지 않습니다).

### Backend와 관리자 Front만 실행

기존 `run_openai.sh` 실행은 해당 터미널의 `Ctrl+C`로 Backend·MCP·사용자 Front를
함께 종료하고, 별도로 실행한 관리자 Front도 종료합니다. 아래 명령은 저장소 루트의
서로 다른 터미널에서 실행합니다. Backend는 `.env`의 팀 DB와 관리자 allowlist를
사용하며, 관리자 조회에 필요 없는 게임·발언 분석 백그라운드 worker는 시작하지 않습니다.

```bash
# Backend: 관리자 조회용으로 백그라운드 게임 진행을 중지한 상태로 실행합니다.
CORS_ALLOWED_ORIGINS=http://127.0.0.1:18502,http://localhost:18502 \
  .venv/bin/python -c 'import uvicorn; from backend.app.main import create_app; uvicorn.run(create_app(enable_background_worker=False), host="127.0.0.1", port=18000)'

# 관리자 Front: 기존 Backend의 실제 관리자 API에 연결합니다.
BACKEND_API_URL=http://127.0.0.1:18000 ADMIN_DEMO_MODE=false \
  .venv/bin/python -m streamlit run frontend_admin/app.py \
  --server.address 127.0.0.1 --server.port 18502 --server.headless true
```

접속 주소는 Backend `http://127.0.0.1:18000`, 관리자 Front
`http://127.0.0.1:18502`입니다. 기동 확인은 각각 `/health`, `/_stcore/health`로
수행합니다. 이 구성에서는 MCP·사용자 Front를 실행하지 않으며 실제 게임 진행에는
전체 실행 구성이 필요합니다.
Backend만 리로드할 때는 Backend 터미널에서 `Ctrl+C` 후 위 Backend 명령을 다시
실행합니다. 관리자 Front는 그대로 유지하고 `/health`의 정상 응답을 확인합니다.

## 테스트와 정적 검사

DB·Redis·유료 Provider 없이 실행할 범위:

반복 발언 장애 복구의 집중 검증은 `backend/tests/test_b6_agent_manager.py`와
`backend/tests/test_agent_activity.py`를 사용합니다. API 대기로 MCP 응답이 막히는지
확인하는 합성 동시성 사례는 기존 `test_mcp_registry_api.py`와 `test_b8_admin_api.py`에
포함합니다. 2026-09-08 최종 Backend 회귀는 1,011건 통과·17건 선택 생략·기존 실패
6건이었습니다. 외부 유료 API 자동 테스트와 DB 정리형 통합 테스트는 실행하지 않았습니다.
기존 실패는 Agent/Redis/SQL 계층 경계 검사 3건과 MCP public context fixture의
`cache_public_history` 누락 3건이며 이번 발언 복구 변경에서는 수정하지 않았습니다.

```bash
TEAM_DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests' \
DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests' \
GAME_STATE_KEYRING_FILE='' GAME_STATE_ACTIVE_KEY_ID='' \
SPEECH_ANALYSIS_ENABLED=false \
LLM_PROVIDER=dummy OPENAI_API_KEY='' GEMINI_API_KEY='' \
PYTHONPATH=mcp_server PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
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

Backend 전체 회귀는 Streamlit 관리자 연동과 FastMCP context 테스트도 포함하므로
위 명령은 통합 `.venv`와 `PYTHONPATH=mcp_server`를 사용합니다. 컴포넌트 환경에
해당 의존성이 없을 때 발생하는 import 실패를 제품 회귀로 판정하지 않습니다.

실제 DB 검증은 **팀 테스트 DB를 우선** 사용합니다. B6 예약 검증은
`TEAM_DATABASE_URL`을 환경에 주입한 뒤 `B6_LOCAL_QA=1`로 선택합니다. 이름은 기존
실행 플래그와 호환하기 위한 것이며 실제 접속은 팀 DB만 사용합니다. 세션 임시 테이블에서
검증하고 rollback하므로 기존 public 게임은 변경하지 않습니다.
`test_b5_game_api.py`, `test_postgres_game_flow.py`, MCP process 왕복 테스트는 public
게임을 생성하므로 다른 PC worker도 처리할 수 있습니다. 이번 자동 회귀에서는 세 파일을
제외하고 별도 실제 게임 한 판으로 진행·제출을 확인했습니다. 로컬 DB는 새로 만들지 않습니다.

실제 유료/Local LLM의 추론 품질·운영 DDL 권한·기존 데이터 암호화 전환·운영 TLS는
이 명령으로 검증하지 않습니다.

관리자 발언 분석 API는 `GET /api/v1/admin/speech-analytics`이며 기존 관리자 UUID
allowlist와 감사 기록을 그대로 사용합니다. 화면의 분석 조건에서 기간·에이전트·라운드·
게임 UUID를 좁혀 조회할 수 있고, 최대 500건의 결정적 표본을 Backend에서
저장 벡터의 앞 96차원 투영으로 cosine 유사도(0.78)를 계산해 묶고, 미완료 분석과
표본 제한을 coverage에 표시합니다. API는
공개 AI 발언만 반환하며 벡터·역할·진영·개별 행동·투표·private context는 노출하지
않습니다. 운영 화면에서 임베딩 행이 없으면 주제 대신 분석 대기 상태를 표시합니다.

## 보안 원칙과 알려진 제약

- `.env`, 실제 `secrets.toml`, token과 모든 실제 자격증명을 커밋하지 않습니다.
- 공개 API의 `X-User-Id`는 인증이 아니라 UUID scope 선택값입니다. UUID를 아는
사용자의 가장을 막지 못하므로 MVP는 개인 개발 환경 또는 사설망으로 제한합니다.
- 현재 최소 FastMCP는 custom bootstrap·HMAC·capability 인증을 제공하지 않습니다.
요청 schema·게임 소유권·행동 유효성은 Backend가 검증합니다.
- Backend는 각 AI actor의 허용된 자기 정보만 scope별로 투영합니다. 밤 행동과
개별 투표는 종료 전에 공개하지 않으며 확정 공개 결과와 본인의 조사 결과를 구분합니다.
- MCP runtime은 DB·Redis에 직접 접근하거나 영속 outbox를 소유하지 않습니다.
- seed와 engine snapshot keyring은 저장소 밖에 두고 과거 record가 참조하는 key를
보존합니다.
- LLM prompt, raw response, private context, token과 비용을 로그에 넣지 않습니다.
- 루트 `*_runtime*.log`는 사용자·게임 식별자가 포함될 수 있어 Git 추적에서 제외합니다.
  2026-09-08 병합으로 들어온 6개 로그도 로컬 파일을 보존하면서 추적 해제했습니다.
  기존 병합 이력에는 남으므로 외부 공유 범위를 점검해야 합니다. 비밀키가 추가로
  확인되면 해당 키를 폐기·재발급해야 하며, 이번 작업은 Git 이력을 재작성하지 않습니다.
- `ADMIN_USER_IDS`는 강한 인증이 아니므로 관리자 앱도 loopback·사설망에서만 사용합니다.
- 현재 홈에는 UUID 복구 설정 진입점이 없으며, 완료 화면의 새 게임 시작은 홈을
  거쳐야 합니다. 관련 기존 회귀 실패는 이번 병합 수정 범위에서 유지합니다.
- 팀 DB를 공유하는 Backend worker는 같은 버전으로 실행해야 합니다. 이번 실게임에서는
  로컬 적용 로그가 없는 첫날 AI PASS와 마감이 없는 HUMAN 창이 관찰됐고, DB job·receipt와
  lease 시간 비교는 다른 버전의 worker 개입을 강하게 시사했습니다. 저장된 정보만으로
  호스트는 특정할 수 없으며 다른 개발자의 프로세스나 게임은 변경하지 않았습니다.
  반복 발언 재현에서도 같은 게임의 MCP_UNAVAILABLE 기본 발언과 첫날 PASS가
  다른 실행에서 적용됐고, 로컬 작업자가 정상 생성한 발언은 서로 달랐습니다.
  로컬 재시작·코드 수정만으로 다른 worker의 대체 발언을 막을 수는 없습니다.
  게임을 점검할 때는 Backend·MCP를 함께 최신 코드로 재시작하고 DB job 결과를
  로컬 `game-progress.log`의 실행 식별자·상태 버전과 대조해야 합니다.

비밀값 노출이 의심되면 값을 다시 출력하지 말고 즉시 폐기·재발급한 뒤 Git 이력과
외부 로그를 별도로 점검하세요.

## 변경 이력

날짜별 변경·검증 기록은 [docs/fix/](docs/fix/)에 모아 두었습니다.

2026-09-08 `chd_test`·`jyu` 병합 검증에서는 실시간 갱신·발언 예약·저장/이탈·
조사 결과 표시와 관리자 접근 거부 후 복귀를 복구했습니다. 외부 Chrome의 6인 박물관
게임은 시민 승리(2라운드), 8인 산장 게임은 저장·재개 후 마피아 승리(3라운드)로
모두 `COMPLETED`/`ENDED`를 확인했습니다. 마지막 Front·관리자 회귀는 605 통과·
기존 실패 5건, Backend는 전체 실행과 실패 재검증 합산 978 통과·기존 실패 14건·
선택 검증 17건 생략, 독립 MCP 대상 검증은 101 통과였습니다. Windows 실기동은
환경이 없어 생략했으며 PowerShell 스크립트는 합성 dotenv·대상 비교와 정적 검증만
수행했습니다. 후속 프롬프트 작업부터 전체 회귀는 사용자 요청으로 보류합니다.

역할별 공격적 토론·블러핑 프롬프트 보완 후에는 최소 MCP 검증 48건이 통과했고,
재시작한 MCP의 실제 Prompt 응답이 최종 소스와 일치함을 확인했습니다. 외부 Chrome의
추가 6인 야간열차 게임은 직접 발언·투표, 관전 빠른 진행을 거쳐 3일차 2라운드에
시민 승리로 종료됐습니다(16:19:34 KST). 실제 대화에서 직접 추궁·표 몰이·앞선 말과
다른 해명을 관찰했습니다. 공유 worker 개입 가능성이 남아 있어 한 판만으로 역할별
기만 빈도나 의도적 날조의 효과를 확정하지 않습니다.

| 문서 | 기록 범위 |
| --- | --- |
| [persona-and-prompts](docs/fix/2026-09-08-persona-and-prompts.md) | 역할별 프롬프트, persona 추론 수치(009), dialogue_focus, 실게임 검증 |
| [speech-analysis](docs/fix/2026-09-08-speech-analysis.md) | 공개 발언 분석 구현·006/008 적용·Team DB 적용·실게임 점검 |
| [game-lifecycle](docs/fix/2026-09-08-game-lifecycle.md) | 저장·재개·삭제·뒤로가기, 병렬 투표, stale 게임 자동 정리(007) |
| [frontend-ui](docs/fix/2026-09-07-08-frontend-ui.md) | WU-F5 발언 대기열, 홈·UUID 복구, 타임라인·채팅 UI |
| [infra-merge-admin](docs/fix/2026-09-07-infra-merge-admin.md) | 섹터 병합, 관리자 앱 연결, Redis 캐시, 로깅, 회귀 기록 |

## 확장 지점

- UUID 사용자 식별: `frontend_user/core/identity.py`, `frontend_user/core/session.py`,
`frontend_user/components/identity_bridge.py`, `backend/app/services/identity_service.py`
- Backend API client: `frontend_user/core/api_client.py`
- 사용자 저장소: `backend/app/repositories/user_repository.py`
- schema 변경: Backend가 `backend/migrations/`에 다음 번호의 순방향 SQL을
추가하고 MCP 담당자가 실제 환경에서 실행·재실행 검증
- Agent·LLM·MCP client: `backend/app/agent/`, `backend/app/llm_provider/`,
`backend/app/mcp/`
- 관리자 발언 분석: `backend/app/repositories/admin_repository.py`,
  `backend/app/services/admin_service.py`, `frontend_admin/app_pages/dashboard_page.py`
- 독립 MCP 기능: `mcp_server/mafia_game/` 또는 `mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만
커밋이나 push를 자동 승인하지 않습니다.
