# Team4 Google OIDC 로그인

Streamlit의 네이티브 OIDC 인증과 PostgreSQL을 연결한 Google 로그인 예제입니다. 사용자는 별도의 회원가입 폼 없이 Google로 처음 로그인할 때 애플리케이션 계정이 자동 생성되며, 이후 로그인에서는 Google 프로필과 최근 로그인 시각이 갱신됩니다.

개발하거나 기여하기 전에 반드시 [AGENT.MD](AGENT.MD)의 브랜치, 커밋, 테스트, 주석 및 문서화 규칙을 확인하세요.

## 주요 기능

- Streamlit `st.login("google")`, `st.user`, `st.logout()` 기반 Google OIDC 로그인
- OIDC 설정 누락, placeholder, 취약한 쿠키 secret 및 안전하지 않은 URL 사전 검사
- Google `sub`를 기반으로 한 provider-neutral 사용자 식별
- 첫 로그인 시 `users`와 `oauth_identities` 레코드의 원자적 자동 생성
- 재로그인 시 이메일, 표시 이름, 아바타 및 최근 로그인 시각 갱신
- 비활성 사용자와 DB 저장 실패에 대해 fail-closed 방식으로 애플리케이션 접근 차단
- 외부 프로필 HTML escape와 HTTPS 아바타 URL 제한
- 실제 비밀값을 출력하지 않는 Streamlit secrets 생성 스크립트

## 프로젝트 구조

```text
.
├── AGENT.MD                         # 개발·기여 작업 규칙
├── README.md                        # 프로젝트 전체 설정·실행 안내
├── .env.example                    # PostgreSQL 환경 변수 예시
├── pyproject.toml                  # 런타임·개발 의존성과 도구 설정
├── backend/
│   ├── app/auth/models.py          # 외부 identity와 내부 사용자 도메인 모델
│   ├── app/core/config.py          # .env 로드 및 DB URL 검증
│   ├── app/db/migrate.py           # SQL 마이그레이션 실행기
│   └── app/db/users.py             # PostgreSQL 사용자 저장소
├── frontend/
│   ├── app.py                      # Streamlit 애플리케이션 진입점
│   ├── auth/                       # OIDC 설정·identity·접근 상태 경계
│   ├── ui.py                       # 로그인·프로필 UI와 스타일
│   └── .streamlit/
│       └── secrets.toml.example    # 커밋 가능한 OIDC 설정 예시
├── migrations/
│   └── 001_create_oauth_schema.sql # 사용자/OAuth 연결 스키마
└── scripts/
    └── configure_google_oidc.py    # Google client JSON → secrets.toml 생성기
```

## 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한
- Google Cloud 프로젝트
- Google OAuth 동의 화면과 OAuth 2.0 웹 애플리케이션 클라이언트
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

## 의존성 설치

개발 도구를 포함한 잠금 버전 의존성을 설치합니다.

```bash
uv sync --dev
```

`uv`를 사용하지 않는 경우 별도의 Python 3.12 이상 가상환경에 `pyproject.toml`의 런타임·개발 의존성을 설치해야 합니다.

## `.env`와 `Team4_Proj` 데이터베이스

기존 `.env`에는 다른 로컬 설정이나 비밀값이 있을 수 있으므로 덮어쓰지 마세요. 파일이 없을 때만 예시를 복사합니다.

```bash
cp .env.example .env
chmod 600 .env
```

최소 설정은 다음과 같습니다.

```dotenv
DATABASE_URL=postgresql://app_user:change-me@localhost:5432/Team4_Proj
DATABASE_NAME=Team4_Proj
```

- `DATABASE_URL`의 사용자명, 비밀번호, 호스트와 포트를 실제 PostgreSQL 환경에 맞게 변경합니다.
- `DATABASE_NAME`은 이 프로젝트의 대상 DB인 `Team4_Proj`로 유지합니다.
- 애플리케이션은 `DATABASE_URL`의 기존 DB 경로를 그대로 신뢰하지 않고 `DATABASE_NAME`으로 교체합니다. 호스트, 포트, 자격증명과 연결 옵션은 유지됩니다.
- `.env`는 Git 무시 대상입니다. 실제 비밀번호나 API 키를 `.env.example`, 소스 코드, 문서에 넣지 마세요.

`Team4_Proj` 데이터베이스 자체는 애플리케이션이 만들지 않습니다. 마이그레이션 전에 PostgreSQL 관리 도구로 같은 이름의 데이터베이스를 먼저 생성하고, `.env` 계정에 연결 및 스키마 생성 권한을 부여하세요.

## 데이터베이스 마이그레이션

다음 명령은 `migrations/`의 SQL 파일을 이름순으로 실행합니다.

```bash
uv run python -m backend.app.db.migrate
```

현재 마이그레이션은 다음 객체를 생성합니다.

- UUID 기본값을 위한 `pgcrypto` 확장
- 애플리케이션 계정용 `public.users`
- 외부 제공자 연결용 `public.oauth_identities`
- `(provider, provider_subject)` 유일 제약, 조회 인덱스 및 `updated_at` 트리거

SQL은 재실행할 수 있도록 작성되어 있지만 기존 테이블의 임의 스키마를 자동 교정하지는 않습니다. `pgcrypto` 확장 생성 권한이 없다면 데이터베이스 관리자가 먼저 활성화해야 합니다. 자동 롤백이나 데이터 삭제 명령은 제공하지 않습니다.

## Google OAuth 설정

Google Cloud Console에서 OAuth 동의 화면을 구성한 뒤 **OAuth 클라이언트 ID → 웹 애플리케이션** 유형의 클라이언트를 만듭니다.

로컬 개발용 **승인된 리디렉션 URI**에는 다음 값을 정확히 등록합니다.

```text
http://localhost:8501/oauth2callback
```

스킴, 호스트, 포트, 경로 중 하나라도 다르면 Google이 콜백을 거부합니다. 앱도 동일한 URI로 실행해야 하므로 로컬 브라우저에서는 `http://localhost:8501`을 사용하세요.

운영 환경에서는 실제 HTTPS 도메인의 `/oauth2callback`을 Google Cloud Console과 Streamlit secrets 양쪽에 완전히 동일하게 등록합니다.

## 안전한 Streamlit secrets 생성

Google Cloud Console에서 웹 애플리케이션 클라이언트 JSON을 내려받습니다. 이 JSON에는 client secret이 있으므로 **저장소 밖의 안전한 경로에 보관**하고 Git에 추가하지 마세요.

다음 스크립트는 JSON에서 필요한 client ID와 client secret만 읽고, 32바이트 무작위 쿠키 secret을 생성해 `frontend/.streamlit/secrets.toml`에 기록합니다.

```bash
uv run python scripts/configure_google_oidc.py \
  --client-json /secure/path/google-oauth-client.json
```

기본 동작은 다음과 같습니다.

- redirect URI: `http://localhost:8501/oauth2callback`
- 출력 파일: `frontend/.streamlit/secrets.toml`
- owner 전용 파일 권한: `0600`
- 임시 파일을 이용한 원자적 저장
- client secret과 쿠키 secret을 터미널에 출력하지 않음
- 기존 출력 파일이 있으면 덮어쓰지 않고 중단

기존 설정을 의도적으로 교체할 때만 `--overwrite`를 사용합니다. 운영 URI나 별도 출력 경로가 필요하면 다음처럼 지정합니다.

```bash
uv run python scripts/configure_google_oidc.py \
  --client-json /secure/path/google-oauth-client.json \
  --redirect-uri https://app.example.com/oauth2callback \
  --output frontend/.streamlit/secrets.toml \
  --overwrite
```

수동 설정이 필요한 경우에만 예시 파일을 복사하고 값을 직접 채웁니다.

```bash
cp frontend/.streamlit/secrets.toml.example frontend/.streamlit/secrets.toml
chmod 600 frontend/.streamlit/secrets.toml
```

필수 키는 `auth.redirect_uri`, `auth.cookie_secret`, `auth.google.client_id`, `auth.google.client_secret`, `auth.google.server_metadata_url`입니다. 실제 `secrets.toml`은 Git 무시 대상입니다.

## 실행

마이그레이션과 OIDC 설정을 마친 뒤 저장소 루트에서 실행합니다.

```bash
uv run streamlit run frontend/app.py
```

브라우저에서 [http://localhost:8501](http://localhost:8501)을 열고 **Google로 계속하기**를 선택합니다. 설정이 없거나 안전성 검사를 통과하지 못하면 로그인 버튼이 비활성화되고 비밀값 대신 안전한 구성 안내만 표시됩니다.

## 회원가입과 재로그인 동작

별도의 이메일·비밀번호 회원가입 화면은 없습니다. Google OIDC 인증이 성공하고 검증된 이메일을 포함한 identity가 확인되면 다음 순서로 처리합니다.

1. Google의 불변 `sub`를 `provider_subject`로 정규화합니다.
2. `(provider, provider_subject)`로 기존 OAuth 연결과 내부 사용자를 조회합니다.
3. 첫 로그인이라면 하나의 DB 트랜잭션에서 `users`를 만들고 `oauth_identities`에 연결합니다.
4. 기존 사용자라면 현재 이메일, 표시 이름, HTTPS 아바타와 최근 로그인 시각을 갱신합니다.
5. `users.is_active = false`이면 프로필을 갱신하지 않고 트랜잭션을 롤백하며 애플리케이션 접근을 거부합니다.

이메일은 변경 가능한 프로필 속성일 뿐 계정 연결 키가 아닙니다. 동시 첫 로그인은 PostgreSQL advisory transaction lock으로 직렬화하며, DB 저장과 활성 상태 확인이 성공한 경우에만 `application-access-granted` 세션 상태가 부여됩니다. 성공 결과는 영구적인 권한으로 캐시하지 않고 Streamlit rerun마다 DB에서 다시 확인합니다.

## 테스트와 정적 검사

전체 회귀 테스트와 lint를 실행합니다.

```bash
uv run pytest
uv run ruff check .
```

변경 범위별 focused test는 다음과 같습니다.

```bash
uv run pytest frontend/tests
uv run pytest backend/tests
uv run pytest backend/tests/test_users_repository.py
```

OIDC와 사용자 저장소 자동 테스트는 synthetic identity와 가짜 DB 연결을 사용합니다. 환경 설정 테스트는 로컬 `.env`의 연결 형식만 읽으며 실제 DB에 접속하지 않습니다. 따라서 테스트 스위트는 Google OAuth 왕복이나 운영 DB를 호출하지 않고, 실제 Google 로그인은 Google Cloud 설정과 로컬 secrets를 준비한 뒤 브라우저에서 별도로 확인해야 합니다.

## 보안 원칙

- `.env`, 실제 `secrets.toml`, Google OAuth 다운로드 JSON 및 모든 자격증명을 커밋하지 않습니다.
- `.env`와 `secrets.toml`은 최소 `0600` 권한으로 유지합니다.
- Google client secret, 쿠키 secret, DB URL, access token, refresh token, ID token을 로그나 사용자 오류 메시지에 포함하지 않습니다.
- `users`와 `oauth_identities`에는 OAuth token을 저장하지 않습니다.
- 이메일이 같다는 이유만으로 서로 다른 provider identity를 자동 연결하지 않습니다.
- OIDC claim과 외부 프로필은 신뢰하지 않고 길이·형식 검증과 HTML escape를 적용합니다.
- 아바타 URL은 HTTPS만 허용합니다.
- OIDC 설정이나 DB 저장에 실패하면 애플리케이션 접근을 허용하지 않습니다.
- 운영 환경에서는 HTTPS를 사용하고 redirect URI를 정확한 운영 주소로 제한합니다.
- 비밀값이 Git, 로그 또는 외부 시스템에 노출됐다고 의심되면 즉시 폐기·재발급하고 Git 이력도 별도로 정리합니다.

OIDC 로그인은 사용자 인증만 제공합니다. 향후 Google API 접근이 필요하면 별도의 명시적 동의 범위, token 암호화 저장소, 갱신 및 폐기 정책을 설계해야 합니다.

## 확장 지점

- 새 OIDC 제공자: `frontend/auth/providers.py`와 Streamlit provider 설정 추가
- claim 변환: `frontend/auth/identity.py`의 provider-neutral 매핑 확장
- 접근 정책: `frontend/auth/authorization.py`와 `frontend/auth/persistence.py`의 fail-closed 경계 확장
- 사용자 저장소: `backend/app/db/users.py`의 repository 인터페이스 확장
- 스키마 변경: `migrations/`에 다음 번호의 순방향 SQL 추가
- 보호 기능: `application-access-granted`가 참인 활성 DB 사용자에게만 노출
- Google API 연동: 로그인 OIDC 흐름과 분리된 권한·token 수명 주기 구현

## 구조 개편 계획

현재 기능을 유지하면서 `backend`, `frontend_user`, `frontend_admin`, `mcp_server`를
독립 실행 단위로 정리하는 계획은 [docs/ARCHITECTURE_REFACTOR_PLAN.md](docs/ARCHITECTURE_REFACTOR_PLAN.md)에
기록되어 있습니다. 이번 단계에서는 LLM Agent와 MCP Tool을 실제로 추가하지 않고,
향후 연결을 위한 디렉터리와 서버 경계만 마련합니다.

## 기여

작업을 시작하기 전에 [AGENT.MD](AGENT.MD)를 읽고, 브랜치 정책과 사용자 승인, 검증 수준, README 갱신 규칙을 따르세요.
