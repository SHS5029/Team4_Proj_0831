# AI 마피아

**AI 마피아**는 함께할 사람을 기다리지 않아도 1명의 인간 플레이어와 개성 있는
여러 AI 플레이어가 바로 한 판을 완주할 수 있도록 만드는 소셜 디덕션 게임입니다.
계획된 `mystery-v1`은 6~9명 규모의 마피아 게임에 다섯 개의 경량 사건 배경을
결합합니다. AI별 말투·공격성·기만 표현은 달리하되 MVP 밸런스 검증 중 추론
능력과 정보 접근 권한은 동일하게 유지합니다. 규칙과 승패는 Backend 게임 엔진이
결정하고 LLM은 허용된 정보 안에서 대화와 선택만 담당합니다.
제품 목표와 MVP 범위는
[AI 마피아 MVP 최종 통합 플랜](docs/플랜/AI_MAFIA_MVP_FINAL_PLAN.md)을 기준으로
합니다.

현재 저장소는 이 MVP를 구현하기 위한 기반 단계로, 일반 사용자용 Streamlit OIDC
로그인, 서명된 내부 요청을 받는 FastAPI Backend, PostgreSQL 사용자 저장을 독립
실행 단위로 분리했습니다. Google로 처음 로그인하면 내부 계정이 생성되고, 이후
로그인에서는 프로필과 최근 로그인 시각이 갱신됩니다. 실제 마피아 게임 엔진과
AI 플레이어 기능은 아래 계획에 따른 후속 구현 범위입니다.

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

LLM Agent loop, MCP Tool·Resource·Prompt, 관리자 업무 기능, Redis 연결은 아직
구현하지 않았습니다. 예약 모듈은 향후 연결 위치만 고정하며 외부 호출을 수행하지
않습니다. 상세 경계는 [아키텍처 개편 문서](docs/플랜/ARCHITECTURE_REFACTOR_PLAN.md)를
참고하세요.

현재 구조를 이용해 1명의 인간 플레이어와 AI 에이전트가 경량 사건 기반 마피아
게임을 진행하는 후속 MVP의 확정 설계는
[AI 마피아 MVP 최종 통합 플랜](docs/플랜/AI_MAFIA_MVP_FINAL_PLAN.md)에 정리되어
있습니다. 게임 규칙과 시나리오의 제품 정본은
[최종 규칙](docs/초기기획안/mafia_game_rules.md)과
[최종 시나리오](docs/초기기획안/mafia_game_scenarios.md)이며, 최종 통합 플랜은
이를 현재 저장소 구조와 보안 경계에 맞춘 구현 기준 문서입니다. 변경·결정 내역은
[통합·수정 내역](docs/플랜/AI_MAFIA_PLAN_INTEGRATION_NOTES.md)에 기록합니다.
계획 문서는 실제 구현 완료 범위를 확장했다고 간주하지 않습니다.

3인(Front / Backend / MCP Server·Data Infrastructure) 섹터 분담, 섹터 간
API·DB·MCP 계약 명세와
작업 순서는 [상세 구현 계획서](docs/개발상세플랜/AI_MAFIA_IMPLEMENTATION_PLAN.md)에
정리되어 있습니다. 이 계획서에는 [AGENTS.MD](AGENTS.MD)의 작업 지침 요약이
포함되어 있으며, 계약(명세) 변경은 계획서 갱신과 섹터 합의를 먼저 거칩니다.

섹터별 담당자는 별도 시스템에서 개발 후 merge하며, 착수 전에 자기 섹터
지침서를 반드시 읽어야 합니다. 각 지침서는 작업 단위(WU) 분해, coding AI
agent 사용 규칙(한 세션 = WU 1개 이하), 중간 merge·테스트 체크포인트를
확정합니다.

- Front: [docs/개발상세플랜/SECTOR_PLAN_FRONT.md](docs/개발상세플랜/SECTOR_PLAN_FRONT.md)
- Backend: [docs/개발상세플랜/SECTOR_PLAN_BACKEND.md](docs/개발상세플랜/SECTOR_PLAN_BACKEND.md)
- MCP Server·Data Infrastructure: [docs/개발상세플랜/SECTOR_PLAN_MCP.md](docs/개발상세플랜/SECTOR_PLAN_MCP.md)

## 개발상세플랜 문서 업데이트 (2026-09-02)

`docs` 루트에 섞여 있던 문서를 `규칙`, `초기기획안`, `플랜`,
`개발상세플랜`으로 분류했습니다. 이 중 `docs/개발상세플랜/`에는 구현 착수 시
직접 사용하는 공통 계약과 섹터별 작업 지침서만 배치했습니다.

| 문서 | 기록된 내용 |
|---|---|
| [AI_MAFIA_IMPLEMENTATION_PLAN.md](docs/개발상세플랜/AI_MAFIA_IMPLEMENTATION_PLAN.md) | Front·Backend·MCP 공통 API·DB·MCP 계약, 승인된 파일 범위, 마일스톤과 계약 변경 절차 |
| [SECTOR_PLAN_FRONT.md](docs/개발상세플랜/SECTOR_PLAN_FRONT.md) | Front 소유 경계, WU-F1~F8, CP-F0~F4와 검증 기준 |
| [SECTOR_PLAN_BACKEND.md](docs/개발상세플랜/SECTOR_PLAN_BACKEND.md) | Backend 소유 경계, WU-B1~B9, CP-B0~B5와 고위험 검증 기준 |
| [SECTOR_PLAN_MCP.md](docs/개발상세플랜/SECTOR_PLAN_MCP.md) | MCP Server·DB·Redis 실행 환경 책임, WU-M1A·M1B·M2~M8, CP-M0·M1A·M1B·M2~M8과 컨텍스트 격리 기준 |

문서 이동에 맞춰 루트 `AGENTS.MD`, README, 환경 설정 예시와 패키지 안내의
참조 경로도 갱신했습니다. 이번 분류는 문서 위치와 탐색 경로를 정리한 것이며,
각 계획서에 적힌 후속 기능을 구현 완료 상태로 변경하지는 않습니다.

### 게임 규칙 계약 개정 (2026-09-02)

기획안 전체와 공통·섹터별 상세 플랜을 대조해 다음 후속 구현 계약을
`mystery-v1`·`scenario-v1`로 확정했습니다.

- 전체 6~9명, 탐정·의사·시민과 서로 정체를 모르는 마피아
- 첫날 낮은 좌석순 1회 발언 후 무투표로 밤 진입
- 텍스트 토론은 200자 이하의 턴 방식, 밤 행동은 20초·투표는 30초의
  Backend 권위 deadline
- 다섯 개 시나리오와 플레이어별 알리바이·관찰 정보를 검증된 seed 기반
  카탈로그로 배정하고 사용자별 직전 시나리오 제외
- 최대 다섯째 밤 뒤 표준 승패가 없으면 최종 지목으로 종료
- 투표는 후보별 집계만 공개하고 밤 사망 역할은 숨기며 처형 역할만 공개
- AI GM은 공개 확정 이벤트만 받고 전체 비공개 상태는 Backend만 보유

이 규칙은 아직 구현되지 않았습니다. Backend 규칙·시나리오·deadline WU와
Front·MCP 계약을 차례로 완료한 뒤 사용할 수 있습니다. 규칙 수준의 밸런스는
유료 LLM 없이 6~9명별 heuristic bot 시뮬레이션으로 검증하고, 실제 LLM은 비용
승인된 소수 표본에만 사용합니다. 시나리오 문서의 개인 정보 문장은 현재 방향
예시이며, WU-B2에서 최대 9좌석용 최소 90개 template record를 작성·제품 검수해야
`scenario-v1` 콘텐츠가 완료됩니다.

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
│   ├── app/{agent,llm,mcp}/          # 후속 Agent 연결 예약 위치
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
│   ├── 규칙/
│   │   └── ai_mafia_game_engine분리규칙.md # (대체됨) 엔진/Agent/MCP 분리 규칙
│   ├── 초기기획안/
│   │   ├── mafia_game_rules.md        # mystery-v1 게임 규칙 제품 정본
│   │   ├── mafia_game_scenarios.md    # scenario-v1 경량 시나리오 제품 정본
│   │   └── mafia_game_plan.md         # (대체됨) 복합 추리극 확장 참고
│   ├── 플랜/
│   │   ├── AI_MAFIA_MVP_FINAL_PLAN.md # AI 마피아 MVP 최종 통합 플랜(구현 기준)
│   │   ├── AI_MAFIA_MVP_PLAN.md       # (대체됨) MVP 설계 초안
│   │   ├── AI_MAFIA_PLAN_INTEGRATION_NOTES.md # 기획 문서 통합·수정 내역
│   │   └── ARCHITECTURE_REFACTOR_PLAN.md # 구조 개편 계획과 적용 기록
│   └── 개발상세플랜/
│       ├── AI_MAFIA_IMPLEMENTATION_PLAN.md # 3인 섹터 분담 상세 구현 계획·API·DB 명세
│       ├── SECTOR_PLAN_FRONT.md       # Front 섹터 작업 지침서(WU·CP)
│       ├── SECTOR_PLAN_BACKEND.md     # Backend 섹터 작업 지침서(WU·CP)
│       └── SECTOR_PLAN_MCP.md         # MCP 섹터 작업 지침서(WU·CP)
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
- Google Cloud 프로젝트와 OAuth 2.0 웹 애플리케이션 client
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

```bash
uv sync --dev
```

현재 코드에 연결된 외부 자격증명은 Google OIDC뿐입니다. AI 마피아 MVP에서
후속 연결할 OpenAI·Gemini API 키와 Redis 주소는 `.env.example`의 예약 항목을
참고하세요.

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
- `DATABASE_MIGRATION_URL`은 MCP 담당자가 migration을 실행할 때만 사용하는 DDL
  계정이며 Backend runtime 프로세스에 전달하지 않습니다.
- 앱은 URL의 원래 DB 경로 대신 `DATABASE_NAME`을 사용하며 기본값은 `Team4_Proj`입니다.
- `INTERNAL_API_SECRET`은 32자 이상의 독립적인 무작위 값이어야 합니다.
- 같은 `INTERNAL_API_SECRET`을 `frontend_user/.streamlit/secrets.toml`의
  `backend.internal_api_secret`에도 설정합니다. 브라우저나 소스 코드에는 넣지 않습니다.
- Backend의 기본 서명 허용 시간 오차는 300초이며 최대 3600초로 제한됩니다.
- `.env.example`의 `REDIS_URL`, `LLM_PROVIDER`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `MAFIA_MCP_URL`, `MCP_SERVER_AUTH_SECRET`,
  `ENGINE_INTERNAL_API_SECRET`,
  `ENGINE_API_URL` 등은 AI 마피아 MVP용 예약 항목입니다.
  아직 코드가 읽지 않으며 실제 키 값은 승인된 비밀 저장소나 로컬의 권한 제한
  파일에만 보관합니다.
  `MCP_SERVER_AUTH_SECRET`은 Backend→MCP session bootstrap,
  `ENGINE_INTERNAL_API_SECRET`은 MCP→Backend 내부 경계용입니다. 두 값과
  `INTERNAL_API_SECRET`은 모두 서로 다른 값을 사용해야 합니다. 운영 MCP 연결은
  검증된 TLS를 사용합니다.
- 예약값 `LLM_TIMEOUT_SECONDS=15`, `MCP_TIMEOUT_SECONDS=3`, 외부 작업 총예산
  16초와 commit·network 예약 3초는 호출 상한입니다. 실제 예산은 서버 deadline과
  이 값 중 더 이른 경계를 사용하며, 부족하면 교정을 생략하고 결정적 fallback으로
  진행합니다. LLM·MCP 호출 동안 Redis game lock을 보유하지 않습니다.
- `MAFIA_MCP_URL`은 `/mcp`를 포함한 전체 endpoint이며 Backend client가 경로를
  다시 붙이지 않습니다.
- `MCP_REQUIRE_TLS=false`는 loopback 개발 기본값뿐입니다. 운영은 `true`와 검증된
  CA 경로를 강제하며, MCP clock anchor 왕복은 기본 2초 이내여야 합니다.

| 환경 소비자 | 허용하는 AI 마피아 관련 키 | 주입 금지 |
|---|---|---|
| Front 서버 | OIDC 설정, `INTERNAL_API_SECRET` | DB·Redis·LLM·MCP/Engine secret |
| Backend runtime | `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, LLM 설정, `MAFIA_MCP_URL`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `INTERNAL_API_SECRET` | `DATABASE_MIGRATION_URL` |
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

## 구현 완료: Google 로그인

Google OIDC 인증부터 내부 사용자 계정 연결, 로그인 프로필 표시와 로그아웃까지
구현되어 있습니다. 로그인 성공 후 현재 제공되는 화면은 연결된 계정의 프로필과
로그아웃 UI이며, AI 마피아 홈·게임 화면은 개발상세플랜에 따른 후속 구현 범위입니다.

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
- OIDC cookie secret과 내부 API secret은 서로 다른 목적으로 생성하고 재사용하지 않습니다.
- Google client secret, cookie secret, 내부 API secret, DB URL, token을 응답·로그에 넣지 않습니다.
- Backend는 HMAC을 통과한 payload도 schema와 도메인 규칙으로 다시 검증합니다.
- Backend만 전체 역할·야간 행동·seed를 보유하고, AI GM과 각 플레이어 Agent에는
  공개 상태 및 자기에게 허용된 개인 정보만 전달합니다.
- MCP capability는 game·agent·phase·state version·deadline에 묶어 agent turn마다
  갱신하며, 이전 session과 capability는 재사용하지 않습니다.
- 서명 실패·만료·DB 장애·비활성 계정에서는 저장과 애플리케이션 접근을 거부합니다.
- 외부 프로필은 HTML escape하며 아바타는 HTTPS URL만 허용합니다.
- 현재 timestamp 만료만 재전송 범위를 제한합니다. UUID nonce의 일회성 저장은 Redis
  연결 후 추가할 보안 확장 지점입니다.
- 현재 관리자 앱에는 인증·권한과 업무 기능이 없으며 준비 화면만 표시합니다.
- 현재 MCP 디렉터리에는 실행 서버와 Tool이 없고 외부 API를 호출하지 않습니다.

비밀값 노출이 의심되면 값을 다시 출력하지 말고 즉시 폐기·재발급한 뒤 Git 이력과
외부 로그를 별도로 점검하세요.

## 확장 지점

- OIDC 제공자 표시 설정: `frontend_user/auth/providers.py`
- claim 정규화: `frontend_user/auth/identity.py`
- Frontend 접근·저장 결과 정책: `frontend_user/auth/authorization.py`, `persistence.py`
- Backend API client: `frontend_user/core/api_client.py`
- identity API와 유스케이스: `backend/app/routers/identity_router.py`, `services/identity_service.py`
- 사용자 저장소: `backend/app/repositories/user_repository.py`
- schema 변경: Backend가 `backend/migrations/`에 다음 번호의 순방향 SQL을
  추가하고 MCP 담당자가 실제 환경에서 실행·재실행 검증
- Agent·LLM·MCP client: `backend/app/agent/`, `llm/`, `mcp/`
- 독립 MCP 기능: `mcp_server/mafia_game/`(게임 컨텍스트 MCP 예정) 또는
  `mcp_server/mcp_2/` 내부 계층에만 추가

## 기여

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만 커밋이나
push를 자동 승인하지 않습니다.
