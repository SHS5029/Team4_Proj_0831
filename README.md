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

현재 저장소는 이 MVP를 구현하기 위한 기반 단계입니다. 기존 Google OIDC, Front
HMAC identity API와 scaffold game은 아직 코드에 남아 있지만 새 정본에서는 폐기
대상입니다. `WU-F1`·`WU-B1`에서 로그인 흐름을 제거하고 브라우저가 생성·보관한 UUID
`user_id`와 `X-User-Id`만 사용하도록 전환합니다. 실제 `mystery-v1` 게임 엔진과 AI
플레이어 기능도 후속 WU 범위이며 계획 문서만으로 구현 완료로 간주하지 않습니다.

개발하거나 기여하기 전에 반드시 [AGENTS.MD](AGENTS.MD)의 브랜치, 커밋,
파일·디렉터리 구조, 테스트, 주석 및 문서화 규칙을 확인하세요.

## 현재 구현 범위

- Streamlit `st.login("google")`, `st.user`, `st.logout()` 기반 Google OIDC 로그인
- OIDC 설정 누락, placeholder, 취약한 cookie secret, 안전하지 않은 URL 사전 검사
- Google `sub` 기반 provider-neutral 사용자 식별과 외부 프로필 정규화
- Frontend가 timestamp, UUID request id, raw body를 HMAC-SHA256으로 서명하는 내부 API
- FastAPI `GET /health`, `POST /api/v1/identity/provision`
- 첫 로그인 시 `users`와 `oauth_identities` 레코드의 원자적 생성
- 재로그인 프로필·최근 로그인 시각 갱신과 비활성 사용자 fail-closed 차단
- 외부 프로필 HTML escape와 HTTPS 아바타 URL 제한
- Backend 소유 PostgreSQL migration 실행 코드(MCP 섹터가 실제 실행)
- 독립 관리자 Streamlit 앱과 MCP 서버 예약 구조(`mcp_server/mafia_game`, `mcp_2`)

개발 섹터 역할은 코드 소유권과 실행 환경 책임을 분리합니다. Backend 섹터는
DB schema·migration SQL·repository와 Redis client·lock 코드를 작성하고, MCP
섹터는 PostgreSQL·Redis 인스턴스 구축·기동·중지, DDL migrator와 DML runtime
계정·권한 준비,
migration 실행과 health 확인을 담당합니다. 실제 Backend 프로세스는 DB·Redis에
직접 연결하며 MCP 서버를 데이터 프록시로 사용하지 않습니다.

LLM Agent loop, MCP Tool·Resource, 관리자 업무 기능과 canonical game의 Redis 연결은
아직 구현하지 않았습니다. 기존 LLM Provider adapter는 연결돼 있지만 앱 수준의 LLM
timeout 설정, token 상한·사용량, 비용·예산과 관련 KPI는 새 MVP 범위에서 제외합니다.

## 개발상세플랜 정본 (2026-09-03)

중복·충돌하던 AI 마피아 계획과 계약을 `docs/개발상세플랜/`의 정본 문서로 통합했습니다.
섹터별 담당자는 작업 전에 [AGENTS.MD](AGENTS.MD)와 해당 정본을 읽고, coding AI
agent 한 세션을 마스터플랜의 WU 한 개 이하로 제한합니다.

| 문서 | 기록된 내용 |
|---|---|
| [AI_MAFIA_MASTER_PLAN.md](docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md) | 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터 소유권, WU와 CP |
| [AI_MAFIA_DB_DESIGN.md](docs/개발상세플랜/AI_MAFIA_DB_DESIGN.md) | PostgreSQL·Redis schema, transaction, lock, migration과 보존 계약 |
| [AI_MAFIA_API_SPEC.md](docs/개발상세플랜/AI_MAFIA_API_SPEC.md) | 일반·관리자·내부 Engine HTTP API와 MCP Resource·Tool 계약 |
| [AI_MAFIA_SCREEN_FLOW.md](docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md) | UUID 초기화, 사용자 게임·관전·피드백과 관리자 화면 흐름 |
| [AI_MAFIA_INDEPENDENT_CONTRACT.md](docs/개발상세플랜/AI_MAFIA_INDEPENDENT_CONTRACT.md) | 세 섹터가 독립 구현할 때 공통으로 고정할 최소 연결 형식과 경계 |

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
- MCP는 정본의 bootstrap·session·Resource·Tool 계약과 fake Engine transport로
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

이 규칙은 아직 구현되지 않았습니다. Backend 규칙·시나리오·deadline WU와
Front·MCP 계약을 차례로 완료한 뒤 사용할 수 있습니다. 규칙 수준의 밸런스는
유료 LLM 없이 6~9명별 heuristic bot 시뮬레이션으로 검증합니다. 실제 Provider smoke는
명시적으로 opt-in한 소수 표본만 사용하며 token·비용 KPI를 만들지 않습니다.
마스터플랜의 개인 정보 문장은 현재 방향 예시이며, WU-B2에서 최대 9좌석용 최소
90개 template record를 작성·제품 검수해야 `scenario-v1` 콘텐츠가 완료됩니다.

## 프로젝트 구조

```text
.
├── AGENTS.MD                         # 개발·기여 작업 규칙
├── README.md                         # 전체 설정·실행·검증 안내
├── .env.example                      # Backend 환경 변수 예시
├── pyproject.toml                    # 통합 런타임·개발 의존성 및 도구 설정
├── backend/
│   ├── app/main.py                   # FastAPI 생성과 router·오류 처리 등록
│   ├── app/routers/                  # health·legacy identity·scaffold endpoint
│   ├── app/schemas/                  # 요청·응답 validation 계약
│   ├── app/services/                 # identity 연결 유스케이스
│   ├── app/models/identity.py        # 외부 identity·내부 사용자 도메인 모델
│   ├── app/repositories/             # PostgreSQL 사용자 저장소
│   ├── app/infrastructure/           # migration·PostgreSQL·HMAC 구현
│   ├── app/agent/                    # 아직 loop가 없는 Agent 정책·orchestrator 골격
│   ├── app/llm_provider/             # 현재 LLM Provider adapter
│   ├── app/mcp/                      # 현재 scaffold MCP client·registry
│   ├── migrations/                   # Backend 작성 SQL migration(MCP 실행)
│   ├── tests/
│   └── README.md
├── frontend_user/
│   ├── app.py                        # 얇은 Streamlit 실행 진입점
│   ├── app_pages/login_page.py       # OIDC 로그인·프로필 화면 흐름
│   ├── auth/                         # OIDC 설정·claim·접근·저장 결과 정책
│   ├── components/ui.py              # 안전한 HTML·CSS 표현
│   ├── core/api_client.py            # HMAC Backend API client
│   ├── .streamlit/secrets.toml.example
│   └── tests/
├── frontend_admin/                   # 관리자 독립 앱의 최소 실행 골격
├── mcp_server/
│   ├── mafia_game/                   # 게임 컨텍스트 MCP 예약 패키지(MVP 대상)
│   └── mcp_2/                        # 후속 MCP 독립 예약 패키지
├── docs/
│   └── 개발상세플랜/
│       ├── AI_MAFIA_MASTER_PLAN.md    # 제품 규칙·시나리오·아키텍처·WU/CP 정본
│       ├── AI_MAFIA_DB_DESIGN.md      # PostgreSQL·Redis 정본
│       ├── AI_MAFIA_API_SPEC.md       # 공개·내부·MCP API 정본
│       ├── AI_MAFIA_SCREEN_FLOW.md    # 사용자·관리자 화면 정본
│       └── AI_MAFIA_INDEPENDENT_CONTRACT.md # 섹터 간 최소 연결 형식·독립 개발 규칙
├── tests/{integration,e2e}/          # 서버 간·브라우저 검증 확장 위치
└── scripts/configure_google_oidc.py  # Google client JSON → Streamlit secrets 생성
```

`frontend_user`와 `frontend_admin`은 Backend만 HTTP로 호출합니다. Frontend가 DB,
Redis, MCP 서버에 직접 연결하거나 MCP 서버끼리 서로의 내부 모듈을 import하지
않습니다. MCP 섹터가 DB·Redis 실행 환경을 운영해도 `mcp_server/mafia_game`
runtime은 DB·Redis에 직접 접근하지 않습니다.

## 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한(MCP 섹터 운영 책임)
- Redis 실행 환경(MCP 섹터 운영 책임, 게임 기능 구현 단계부터 필요)
- 현재 legacy 로그인 실행에만 필요한 Google Cloud OAuth client. UUID-only 전환 뒤 제거
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

```bash
uv sync --dev
```

현재 legacy 앱은 Google OIDC 자격증명을 사용하고 기존 LLM adapter는 선택한
Provider key를 사용합니다. UUID-only 전환 뒤 Google 설정과 Front HMAC secret을
제거합니다. 실제 값은 `.env.example`의 placeholder만 참고하고 Git에 넣지 않습니다.

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
  `ENGINE_INTERNAL_API_SECRET`, `ADMIN_USER_IDS`와 `ENGINE_API_URL`은 canonical WU에서
  연결할 목표 설정입니다. 실제 키 값은 승인된 비밀 저장소나 로컬의 권한 제한
  파일에만 보관합니다.
  `GAME_STATE_KEYRING_FILE`은 저장소 밖의 권한 제한 JSON을 가리키고
  `GAME_STATE_ACTIVE_KEY_ID`는 신규 seed·snapshot 암호화 key를 선택합니다.
  `MCP_SERVER_AUTH_SECRET`은 Backend→MCP session bootstrap,
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
| Front 서버 | 현재 legacy OIDC·`INTERNAL_API_SECRET`, 목표 상태의 Backend URL | DB·Redis·LLM·MCP/Engine secret |
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

현재 migration은 legacy `users`·`oauth_identities`와 `scaffold_*` 게임 테이블을
생성합니다. canonical UUID-only·`mystery-v1` schema는 아직 후속 WU 범위입니다.
적용된 migration 파일은 수정하지 않고 새 번호의 순방향 migration으로 전환합니다.

## Legacy Google OAuth와 Streamlit secrets

이 절은 아직 남아 있는 현재 identity 코드 실행용입니다. 새 MVP 목표에는 포함되지
않으며 `WU-F1`·`WU-B1` 완료 뒤 설정·스크립트·route와 함께 제거합니다.

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

일반 사용자 앱은 별도 터미널에서 실행합니다.

```bash
uv run streamlit run frontend_user/app.py --server.port 8501
```

브라우저에서 [http://localhost:8501](http://localhost:8501)을 엽니다. OIDC 또는
Backend 설정이 없거나 안전성 검사를 통과하지 못하면 접근을 허용하지 않고 고정된
구성·재시도 안내만 표시합니다.

관리자 앱은 업무 기능 없이 독립 실행 경계만 확인할 수 있습니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

## 현재 legacy 구현: Google 로그인

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

## 테스트와 정적 검사

변경 동작별 focused test 예시는 다음과 같습니다.

```bash
uv run pytest backend/tests/test_identity_api.py
uv run pytest backend/tests/test_users_repository.py
uv run pytest frontend_user/tests
```

완료 전 전체 회귀·컴파일·lint는 다음 명령으로 확인합니다.

```bash
uv run pytest
uv run python -m compileall -q backend frontend_user frontend_admin mcp_server
uv run ruff check .
```

자동 테스트는 synthetic identity, 가짜 DB 연결, mock HTTP transport를 사용해 Google,
운영 DB, 유료 API를 호출하지 않습니다. 실제 Google OAuth 왕복과 실제 PostgreSQL
마이그레이션은 자격 증명과 로컬 인프라가 필요하므로 MCP 담당자가 실행 환경을
준비·검증하고 Backend 담당자와 결과를 공동 판정합니다.

## 보안 원칙과 알려진 제약

- `.env`, 실제 `secrets.toml`, OAuth JSON, token과 모든 실제 자격증명을 커밋하지 않습니다.
- 현재 legacy OIDC cookie secret과 Front HMAC secret은 전환 전까지 재사용하지 않고
  응답·로그에 넣지 않습니다.
- 목표 공개 API의 `X-User-Id`는 인증이 아니라 UUID scope 선택값입니다. UUID를 아는
  사용자의 가장을 막지 못하므로 MVP는 개인 개발 환경 또는 사설망으로 제한합니다.
- 내부 Engine HMAC과 MCP bootstrap secret은 Front에 전달하지 않고 서로 다른 값으로
  유지합니다. 서명을 통과한 payload도 schema와 도메인 규칙으로 다시 검증합니다.
- Backend만 전체 역할·야간 행동·seed를 보유하고, AI GM과 각 플레이어 Agent에는
  공개 상태 및 자기에게 허용된 개인 정보만 전달합니다.
- MCP capability는 game·agent·phase·state version·deadline에 묶어 agent turn마다
  갱신하며, 이전 session과 capability는 재사용하지 않습니다.
- seed와 engine snapshot keyring은 저장소 밖에 두고 과거 record가 참조하는 key를
  보존합니다.
- LLM prompt, raw response, private context, token과 비용을 로그에 넣지 않습니다.
- `ADMIN_USER_IDS`는 강한 인증이 아니므로 관리자 앱도 loopback·사설망에서만 사용합니다.
- 현재 관리자 앱에는 인증·권한과 업무 기능이 없으며 준비 화면만 표시합니다.
- 현재 MCP 디렉터리에는 실행 서버와 Tool이 없고 외부 API를 호출하지 않습니다.

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
- 독립 MCP 기능: `mcp_server/mafia_game/`(게임 컨텍스트 MCP 예정) 또는
  `mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만 커밋이나
push를 자동 승인하지 않습니다.
