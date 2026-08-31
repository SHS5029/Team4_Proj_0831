# Team4 Google 로그인

Streamlit의 네이티브 OIDC 인증으로 Google 로그인을 제공하는 로그인 화면입니다. 현재 범위는 로그인·로그아웃과 사용자 프로필 표시까지이며, 외부 제공자 정보와 애플리케이션 사용자를 분리해 이후 다른 OAuth 제공자나 서비스 기능을 붙이기 쉽게 구성합니다.

## 구성

- **UI / 인증:** Streamlit `st.login("google")`, `st.user`, `st.logout()`
- **인증 제공자:** Google OpenID Connect
- **데이터베이스:** PostgreSQL `Team4_Proj`
- **DB 접근:** 동기 `psycopg` 저장소
- **계정 식별:** 변경 가능한 이메일이 아닌 `(provider, provider_subject)`

주요 디렉터리는 다음과 같습니다.

```text
frontend/
  app.py                         # Streamlit 진입점
  auth/                          # OIDC 설정 검사와 provider-neutral identity 매핑
  .streamlit/
    secrets.toml.example         # 커밋 가능한 OIDC 설정 예시
backend/app/db/                  # PostgreSQL 사용자 저장소
migrations/
  001_create_oauth_schema.sql    # 사용자/OAuth 연결 스키마
.env.example                     # PostgreSQL 설정 예시
```

## 사전 준비

- Python 3.12 이상
- PostgreSQL
- Google Cloud 프로젝트와 OAuth 2.0 웹 애플리케이션 클라이언트
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

## 1. Python 의존성 설치

저장소 루트에서 개발 의존성을 포함해 설치합니다.

```bash
uv sync --dev
```

`uv`를 사용하지 않는 환경에서는 별도의 가상환경을 만든 뒤 `pyproject.toml`의 런타임·개발 의존성을 설치해야 합니다.

## 2. PostgreSQL 설정과 마이그레이션

기존 `.env`가 있다면 덮어쓰지 않습니다. `DATABASE_URL`의 호스트·포트·계정 정보를 사용하되, 애플리케이션은 안전하게 URL을 파싱해 대상 DB만 `DATABASE_NAME`(기본값 `Team4_Proj`)으로 바꿉니다. 새로 구성할 때만 예시 파일을 복사합니다.

```bash
cp .env.example .env
```

예시의 사용자명과 비밀번호를 실제 로컬 PostgreSQL 값으로 바꾼 뒤, 자격 증명을 출력하지 않는 Python 마이그레이션 러너를 실행합니다.

```bash
uv run python -m backend.app.db.migrate
```

연결 대상 데이터베이스는 미리 생성되어 있어야 합니다. 마이그레이션은 `public.users`, `public.oauth_identities`, 관련 인덱스·트리거만 추가하며 재실행할 수 있도록 작성되어 있습니다. 데이터 삭제 가능성이 있는 자동 롤백 스크립트는 제공하지 않습니다. `pgcrypto` 확장을 만들 권한이 없다면 데이터베이스 관리자가 먼저 활성화해야 합니다.

## 3. Google Cloud Console 설정

Google Cloud Console에서 동의 화면을 구성하고 **웹 애플리케이션** 유형의 OAuth 클라이언트를 만듭니다. 로컬 개발용 승인된 리디렉션 URI에는 아래 주소를 정확히 등록합니다.

```text
http://localhost:8501/oauth2callback
```

호스트, 포트, 경로 또는 스킴이 다르면 Google이 콜백을 거부합니다. 운영 배포에서는 실제 HTTPS 주소의 `/oauth2callback`을 Google Console과 Streamlit secrets 양쪽에 동일하게 등록해야 합니다.

그다음 커밋 가능한 예시를 실제 secrets 파일로 복사합니다.

```bash
cp frontend/.streamlit/secrets.toml.example frontend/.streamlit/secrets.toml
```

`frontend/.streamlit/secrets.toml`에서 다음 값을 설정합니다.

- `auth.redirect_uri`: 로컬에서는 `http://localhost:8501/oauth2callback`
- `auth.cookie_secret`: 최소 32바이트 이상의 강한 무작위 값
- `auth.google.client_id`: Google OAuth 클라이언트 ID
- `auth.google.client_secret`: Google OAuth 클라이언트 secret
- `auth.google.server_metadata_url`: Google OIDC discovery URL

쿠키 secret은 예를 들어 `openssl rand -hex 32`로 만들 수 있습니다. 실제 `secrets.toml`은 Git에서 제외되며, Google 자격 증명과 쿠키 secret을 `.env`나 소스 코드에 중복 저장하지 않습니다.

## 4. 실행

저장소 루트에서 실행합니다.

```bash
uv run streamlit run frontend/app.py
```

브라우저에서 `http://localhost:8501`을 열고 **Google로 계속하기**를 선택합니다. OIDC 설정이 빠진 경우 화면에는 안전한 구성 안내만 표시하고 secret 값은 표시하지 않습니다.

## 5. 검증

전체 테스트와 정적 검사를 실행합니다.

```bash
uv run pytest
uv run ruff check .
```

변경 범위별로 빠르게 확인하려면 다음 focused test를 사용할 수 있습니다.

```bash
uv run pytest frontend/tests
uv run pytest backend/tests
```

## 확장 설계

로그인 흐름은 다음 경계를 따릅니다.

1. Streamlit이 `st.login("google")`로 Google OIDC 흐름을 시작합니다.
2. 콜백 완료 후 `st.user`의 클레임을 provider-neutral identity로 변환합니다.
3. Google의 불변 `sub` 클레임을 `provider_subject`로 저장하고 `(provider, provider_subject)`로 내부 사용자를 찾거나 생성합니다.
4. 화면은 검증하고 escape한 공통 프로필을 표시하며, 로그아웃은 `st.logout()`으로 처리합니다.

새 제공자를 추가할 때는 Streamlit secrets에 제공자 설정을 추가하고, 제공자 클레임을 공통 identity 형식으로 변환하는 어댑터를 확장하면 됩니다. 데이터베이스는 한 사용자가 여러 외부 identity를 가질 수 있도록 사용자와 OAuth 연결을 별도 테이블로 유지합니다.

## 보안 원칙

- 이메일은 변경되거나 제공자마다 중복될 수 있으므로 로그인 식별키나 고유 제약으로 사용하지 않습니다.
- OAuth access token, refresh token, ID token은 `users` 또는 `oauth_identities`에 저장하지 않습니다.
- Google client secret, 쿠키 secret, 데이터베이스 비밀번호를 로그·오류 메시지·Git에 남기지 않습니다.
- 외부 표시 이름과 이메일은 신뢰할 수 없는 입력으로 취급하고, HTML에 표시할 때 escape합니다.
- 아바타는 HTTPS URL만 허용하고 그 외 스킴은 폐기합니다.
- 운영 환경에서는 HTTPS를 사용하고 Google Console의 redirect URI를 운영 주소로 제한합니다.
- 비활성화된 `users.is_active = false` 계정은 OAuth 인증 후에도 애플리케이션 계정 연결과 보호 기능 진입을 거부합니다.
- Streamlit의 로그인 쿠키는 OIDC 설정이 강한 secret과 안전한 URL 검사를 통과할 때만 처리하며, DB에 저장된 활성 사용자가 확인된 뒤에만 애플리케이션 접근 상태를 부여합니다.

OIDC 로그인은 사용자 인증만 제공합니다. 이후 Google API 접근 권한이 필요하다면 별도의 명시적 동의 범위, 토큰 암호화 저장소, 갱신·폐기 정책을 독립적으로 설계해야 합니다.
