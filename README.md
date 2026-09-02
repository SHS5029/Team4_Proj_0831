# Team4 서비스 아키텍처와 Google OIDC 로그인

일반 사용자용 Streamlit OIDC 로그인, 서명된 내부 요청을 받는 FastAPI Backend,
PostgreSQL 사용자 저장을 독립 실행 단위로 분리한 프로젝트입니다. Google로 처음
로그인하면 내부 계정이 생성되고, 이후 로그인에서는 프로필과 최근 로그인 시각이
갱신됩니다.

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
- Backend 소유 PostgreSQL migration 실행기
- 독립 관리자 Streamlit 앱과 MCP 서버 예약 구조(`mcp_server/mcp_1`, `mcp_2`)

LLM Agent loop, 실제 마피아 규칙, 관리자 업무 기능은 아직 구현하지 않았습니다.
연결 뼈대 단계에서는 dummy 게임 REST API, operation·SSE smoke, 게임 MCP의 최소
JSON-RPC(`initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`)
왕복만 구현했습니다. 다음 최소 인프라 연결은 PostgreSQL 원본 저장, Redis 보조
연결, Backend dummy LLM·MCP 왕복, SSE replay·polling fallback 순서로 진행하며,
기본 LLM provider는 외부 키가 필요 없는 `dummy`이며, 설정을 `local`로 바꾸면
OpenAI 호환 로컬 `/chat/completions` endpoint를 호출합니다. 상세 경계와 다음 구현 순서는
[연결 뼈대 계획](docs/scaffold/AI_MAFIA_SCAFFOLD_PLAN.md)을 참고하세요.

현재 구조를 이용해 1명의 인간 플레이어와 AI 에이전트가 기본 마피아 게임을
진행하는 후속 MVP의 확정 설계는
[AI 마피아 MVP 최종 통합 플랜](docs/AI_MAFIA_MVP_FINAL_PLAN.md)에 정리되어
있습니다. 이 문서는 세 기획 초안(`docs/mafia_game_plan.md`,
`docs/AI_MAFIA_MVP_PLAN.md`, `docs/ai_mafia_game_engine분리규칙.md`)을 제품 범위와
책임 경계 기준으로 검증·통합한 구현 기준 문서이며, 통합 시 변경·결정된
항목은 [통합·수정 내역](docs/AI_MAFIA_PLAN_INTEGRATION_NOTES.md)에 기록되어
있습니다. 최종 플랜은 구현 계획이며 아래의 현재 구현 범위를 확장했다고
간주하지 않습니다.

게임 MVP는 기존 OIDC 로그인·인증 경계를 사용하지 않는다. 화면에서 입력한
UUID `user_id`를 `X-User-Id` 헤더로 전달해 게임 소유자와 메모 작성자를 구분하며,
이 식별 방식은 로컬·내부 테스트 범위로 제한한다.

구현 계약은 [연결 뼈대 우선 구현 계획](docs/scaffold/AI_MAFIA_SCAFFOLD_PLAN.md),
[게임 규칙·로직](docs/AI_MAFIA_GAME_RULES.md),
[Backend REST·SSE API 계약](docs/AI_MAFIA_BACKEND_API_CONTRACT.md),
[게임 MCP API 계약](docs/AI_MAFIA_MCP_API_CONTRACT.md),
[DB·Redis 설계](docs/AI_MAFIA_DATA_REDIS_DESIGN.md),
[Frontend 화면 설계](docs/AI_MAFIA_FRONTEND_SPEC.md)로 분리했습니다.
세부 문서는 `minimum-v1`의 확정 규칙·요청·응답, 저장·캐시, 화면 상태 계약입니다.
최종 플랜의 현재 디렉터리 안내는 구현 계약이 아니며, 실제 파일 배치는 기존
import 경계에 맞춰 정합니다. AI 페르소나의 수치 변환과 적용 순서는 최종 플랜
7.3이 단일 기준이고, API 문서는 해당 값의 wire schema만 소유합니다.
단일 Backend worker의 복구 실행기, PostgreSQL operation·idempotency 원본,
SSE와 operation polling, HMAC 기반 MCP 내부 context 조회를 최소 구현 방식으로
고정했습니다. 현재 코드가 이 계약을 구현했다는 의미는 아닙니다.

운영 기본값은 게임당 총 60,000 token, agent 호출당 최대 출력 400 token,
원격 모델 예상 비용 1 USD 경고선, `PAUSED` 게임 30일과 `FINISHED` 게임 90일
보존입니다. 사용자 즉시 삭제 API와 다중 Backend worker는 MVP 범위에서 제외합니다.

## 프로젝트 구조

```text
.
├── AGENTS.MD                         # 개발·기여 작업 규칙
├── README.md                         # 전체 설정·실행·검증 안내
├── .env.example                      # Backend 환경 변수 예시
├── pyproject.toml                    # 통합 런타임·개발 의존성 및 도구 설정
├── backend/
│   ├── app/main.py                   # FastAPI 생성과 router·오류 처리 등록
│   ├── app/routers/                  # health·identity HTTP endpoint
│   ├── app/schemas/                  # 요청·응답 validation 계약
│   ├── app/services/                 # identity 연결 유스케이스
│   ├── app/models/identity.py        # 외부 identity·내부 사용자 도메인 모델
│   ├── app/repositories/             # PostgreSQL 사용자 저장소
│   ├── app/infrastructure/           # migration·PostgreSQL·HMAC 구현
│   ├── app/{agent,llm_provider,mcp}/ # Agent·LLM Provider·MCP 연결 위치
│   ├── migrations/                   # Backend 소유 SQL migration
│   ├── tests/
│   └── README.md
├── frontend_user/
│   ├── app.py                        # 얇은 Streamlit 실행 진입점
│   ├── game_scaffold_app.py          # 로그인 없는 연결 뼈대 smoke 진입점
│   ├── app_pages/login_page.py       # OIDC 로그인·프로필 화면 흐름
│   ├── auth/                         # OIDC 설정·claim·접근·저장 결과 정책
│   ├── components/ui.py              # 안전한 HTML·CSS 표현
│   ├── core/api_client.py            # HMAC Backend API client
│   ├── .streamlit/secrets.toml.example
│   └── tests/
├── frontend_admin/                   # 관리자 독립 앱의 최소 실행 골격
├── mcp_server/
│   ├── mcp_1/                        # 게임 컨텍스트 MCP 예약 패키지(MVP 대상)
│   └── mcp_2/                        # 후속 MCP 독립 예약 패키지
├── docs/
│   ├── AI_MAFIA_MVP_FINAL_PLAN.md    # 제품 범위·책임 경계·구현 단계
│   ├── scaffold/                     # 연결 뼈대 구현 계획 모음
│   │   ├── AI_MAFIA_SCAFFOLD_PLAN.md      # 연결 뼈대 우선 구현 계획
│   │   ├── AI_MAFIA_SCAFFOLD_FILE_PLAN.md # 뼈대 파일별 책임과 구현 순서
│   │   ├── AI_MAFIA_SCAFFOLD_SCHEMA.md    # 뼈대 JSON 입출력 계약
│   │   ├── AI_MAFIA_SCAFFOLD_RUNBOOK.md   # 뼈대 실행·smoke 절차
│   │   ├── AI_MAFIA_SCAFFOLD_TEST_PLAN.md # 뼈대 테스트 계획
│   │   └── AI_MAFIA_MIN_CONNECTION_PLAN.md # DB·Redis·LLM·SSE 최소 연결 계획
│   ├── AI_MAFIA_GAME_RULES.md        # basic-v1 규칙·상태 전이·해소 로직
│   ├── AI_MAFIA_API_CONTRACT.md     # 계약 문서 인덱스
│   ├── AI_MAFIA_BACKEND_API_CONTRACT.md # Frontend·Backend REST/SSE 계약
│   ├── AI_MAFIA_BACKEND_OPENAPI.yaml # Swagger UI 생성용 OpenAPI 3.1 원본
│   ├── AI_MAFIA_MCP_API_CONTRACT.md # Backend·게임 MCP 계약
│   ├── AI_MAFIA_DATA_REDIS_DESIGN.md # PostgreSQL·Redis 저장·복구 계약
│   ├── AI_MAFIA_FRONTEND_SPEC.md    # 사용자·관리자 화면·상태·호출 순서
│   ├── AI_MAFIA_PLAN_INTEGRATION_NOTES.md  # 기획 문서 통합·수정 내역
│   ├── LLM_PROVIDER_IMPLEMENTATION_PLAN.md # LLM Provider 명칭 변경·구현 계획
│   ├── AI_MAFIA_MVP_PLAN.md          # (대체됨) MVP 설계 초안
│   ├── ai_mafia_game_engine분리규칙.md  # (대체됨) 엔진/Agent/MCP 분리 규칙
│   ├── mafia_game_plan.md            # (대체됨) 추리게임 기획안·확장 참고
│   └── ARCHITECTURE_REFACTOR_PLAN.md # 구조 개편 계획과 적용 기록
├── tests/{integration,e2e}/          # 서버 간·브라우저 검증 확장 위치
└── scripts/configure_google_oidc.py  # Google client JSON → Streamlit secrets 생성
```

`frontend_user`와 `frontend_admin`은 Backend만 HTTP로 호출합니다. Frontend가 DB,
Redis, MCP 서버에 직접 연결하거나 MCP 서버끼리 서로의 내부 모듈을 import하지
않습니다.

## 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한
- Google Cloud 프로젝트와 OAuth 2.0 웹 애플리케이션 client
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

```bash
uv sync --dev
```

uv를 사용하지 않는 Backend 환경에서는 운영 의존성을
`backend/requirements.txt`, 테스트·정적 검사 포함 환경을
`backend/requirements-dev.txt`로 설치할 수 있습니다.

현재 코드에 연결된 외부 자격증명은 Google OIDC뿐입니다. LLM은 기본적으로
`dummy` Provider를 사용하며, local·OpenAI·Gemini Provider 설정은 `.env.example`과
[LLM Provider 구현 계획](docs/LLM_PROVIDER_IMPLEMENTATION_PLAN.md)을 참고하세요.

## Backend 환경 설정

기존 `.env`에는 다른 로컬 설정이나 비밀값이 있을 수 있으므로 덮어쓰지 마세요.
파일이 없을 때만 예시를 복사하고 소유자 전용 권한을 적용합니다.

```bash
cp .env.example .env
chmod 600 .env
```

필수·기본 설정은 다음과 같습니다.

```dotenv
DATABASE_URL=postgresql://app_user:change-me@localhost:5432/Team4_Proj
DATABASE_NAME=Team4_Proj
INTERNAL_API_SECRET=REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS
INTERNAL_API_MAX_AGE_SECONDS=300
```

- `DATABASE_URL`의 사용자명, 비밀번호, 호스트와 포트를 실제 PostgreSQL에 맞춥니다.
- 앱은 URL의 원래 DB 경로 대신 `DATABASE_NAME`을 사용하며 기본값은 `Team4_Proj`입니다.
- `INTERNAL_API_SECRET`은 32자 이상의 독립적인 무작위 값이어야 합니다.
- 같은 `INTERNAL_API_SECRET`을 `frontend_user/.streamlit/secrets.toml`의
  `backend.internal_api_secret`에도 설정합니다. 브라우저나 소스 코드에는 넣지 않습니다.
- Backend의 기본 서명 허용 시간 오차는 300초이며 최대 3600초로 제한됩니다.
- `.env.example`의 `REDIS_URL`, `LLM_PROVIDER`, `LOCAL_LLM_BASE_URL`,
  `LOCAL_LLM_MODEL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `GEMINI_API_KEY`,
  `GEMINI_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`,
  `MAFIA_MCP_URL`, `BACKEND_INTERNAL_URL`, `MCP_INTERNAL_SECRET`,
  `GAME_SEED_ENCRYPTION_KEY` 등은 AI 마피아 MVP 설정입니다. API key와 실제
  운영 단가는 `.env`에만 보관합니다.
- 원격 LLM을 선택하면 `LLM_INPUT_COST_PER_MILLION_USD`와
  `LLM_OUTPUT_COST_PER_MILLION_USD`를 선택 모델의 현재 가격으로 설정합니다.
  Provider 선택과 구조화 응답 검증은 `backend/app/llm_provider/`가 담당합니다.

`Team4_Proj` 데이터베이스는 앱이 만들지 않습니다. 마이그레이션 전에 관리 도구로
데이터베이스를 생성하고 `.env` 계정에 연결·스키마 생성 권한을 부여하세요.

## 데이터베이스 마이그레이션

Backend가 소유하는 `backend/migrations/`의 SQL을 이름순으로 실행합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

현재 migration은 `pgcrypto`, `public.users`, `public.oauth_identities`, identity 유일
제약·조회 인덱스·`updated_at` trigger를 생성합니다. SQL은 재실행 가능하게 작성되어
있지만 임의의 기존 schema를 자동 교정하거나 데이터를 삭제하지 않습니다.

## Google OAuth와 Streamlit secrets

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

Backend를 먼저 실행합니다.

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

## 로그인과 내부 API 흐름

1. `frontend_user`가 Streamlit OIDC 로그인과 cookie session을 소유합니다.
2. 외부 claim을 길이·문자·HTTPS 규칙으로 정규화합니다.
3. `core/api_client.py`가 `timestamp.request_id.raw_body`를 HMAC-SHA256으로 서명합니다.
4. Backend가 UUID, 기본 300초 시간 오차, HMAC, 요청 schema를 모두 다시 검증합니다.
5. `IdentityService`가 PostgreSQL 저장소를 호출해 사용자를 생성하거나 갱신합니다.
6. 저장된 활성 사용자 응답을 받은 실행에서만 애플리케이션 접근을 허용합니다.

이메일은 변경 가능한 프로필일 뿐 계정 연결 키가 아닙니다. `(provider,
provider_subject)`만 외부 계정 연결에 사용하며 동시 첫 로그인은 PostgreSQL advisory
transaction lock으로 직렬화합니다. `request_id`는 현재 추적 상관관계에 사용하고,
Redis가 추가되는 후속 단계에서 짧은 TTL의 재전송 차단 키로 확장합니다.

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
마이그레이션은 자격 증명과 로컬 인프라가 필요하므로 별도 수동 검증 대상입니다.

## 보안 원칙과 알려진 제약

- `.env`, 실제 `secrets.toml`, OAuth JSON, token과 모든 실제 자격증명을 커밋하지 않습니다.
- OIDC cookie secret과 내부 API secret은 서로 다른 목적으로 생성하고 재사용하지 않습니다.
- Google client secret, cookie secret, 내부 API secret, DB URL, token을 응답·로그에 넣지 않습니다.
- Backend는 HMAC을 통과한 payload도 schema와 도메인 규칙으로 다시 검증합니다.
- 서명 실패·만료·DB 장애·비활성 계정에서는 저장과 애플리케이션 접근을 거부합니다.
- 외부 프로필은 HTML escape하며 아바타는 HTTPS URL만 허용합니다.
- 현재 timestamp 만료만 재전송 범위를 제한합니다. UUID nonce의 일회성 저장은 Redis
  연결 후 추가할 보안 확장 지점입니다.
- 현재 관리자 앱에는 인증·권한과 업무 기능이 없으며 준비 화면만 표시합니다.
- 현재 MCP는 `mcp_server/mcp_1`의 연결 뼈대만 실행하며 외부 API·DB를 호출하지 않습니다.
- 게임 MVP 구현 후에도 개발용 `X-User-Id`와 관리자 API는 인증 수단이 아니므로
  외부 공개 배포에 사용할 수 없습니다. MCP 전용 `MCP_INTERNAL_SECRET`은 Frontend와
  공유하지 않습니다.
- 게임 MVP의 사용자 즉시 삭제 API는 제공하지 않으며, 확정 보존 기간이 지난 데이터만
  Backend 복구 실행기가 정리하도록 설계되어 있습니다.

비밀값 노출이 의심되면 값을 다시 출력하지 말고 즉시 폐기·재발급한 뒤 Git 이력과
외부 로그를 별도로 점검하세요.

## 확장 지점

- OIDC 제공자 표시 설정: `frontend_user/auth/providers.py`
- claim 정규화: `frontend_user/auth/identity.py`
- Frontend 접근·저장 결과 정책: `frontend_user/auth/authorization.py`, `persistence.py`
- Backend API client: `frontend_user/core/api_client.py`
- identity API와 유스케이스: `backend/app/routers/identity_router.py`, `services/identity_service.py`
- 사용자 저장소: `backend/app/repositories/user_repository.py`
- schema 변경: `backend/migrations/`에 다음 번호의 순방향 SQL 추가
- Agent·LLM Provider·MCP client: `backend/app/agent/`, `backend/app/llm_provider/`, `backend/app/mcp/`
- LLM Provider 구현 순서와 공통 계약: [LLM Provider 구현 계획](docs/LLM_PROVIDER_IMPLEMENTATION_PLAN.md)
- 독립 MCP 기능: `mcp_server/mcp_1/`(게임 컨텍스트 MCP 예정) 또는
  `mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만 커밋이나
push를 자동 승인하지 않습니다.
