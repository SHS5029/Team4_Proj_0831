# 기본 로그인 화면

Streamlit 네이티브 OIDC(`st.login`, `st.user`, `st.logout`)를 사용하는 Google 로그인 전용 화면입니다. 프로젝트 주제가 정해지기 전에도 사용할 수 있도록 중립적인 단일 카드 기본형으로 구성했으며, 로그인 후에는 안전하게 매핑한 사용자 프로필과 로그아웃 동작만 제공합니다.

## 실행 준비

저장소 루트에서 프로젝트와 개발 의존성을 함께 설치합니다.

```bash
uv sync --dev
```

OIDC 예제 파일을 복사한 뒤 실제 Google OAuth 값을 채웁니다. 실제 `secrets.toml`은 커밋하지 않습니다.

```bash
cp frontend/.streamlit/secrets.toml.example frontend/.streamlit/secrets.toml
```

Google Cloud Console의 승인된 리디렉션 URI도 아래 값과 정확히 같아야 합니다.

```text
http://localhost:8501/oauth2callback
```

앱은 저장소 루트의 `.env`를 백엔드 설정을 통해 읽으며, 백엔드가 강제하는 `Team4_Proj` 데이터베이스에 로그인 사용자를 저장합니다.

## 실행

저장소 루트에서 실행해야 `backend` 패키지와 동일한 환경을 사용합니다.

```bash
uv run streamlit run frontend/app.py
```

브라우저에서 `http://localhost:8501`을 엽니다. 로그인 설정이 빠졌거나 잘못된 경우 비밀값 대신 안전한 구성 안내만 표시됩니다.

## 테스트

```bash
uv run pytest frontend/tests
uv run ruff check frontend
```

테스트는 OIDC claim 매핑, 필수 secrets 구조 검사, 외부 사용자 값 HTML escaping, 공식 Google `G` 색상, 주제 중립 문구, 반응형·키보드 포커스 CSS 토큰을 검증합니다.

## 확장 경계

- `auth/providers.py`: provider별 표시 설정
- `auth/configuration.py`: Streamlit secrets 구조 검사
- `auth/identity.py`: `st.user`를 백엔드 `ExternalIdentity`로 변환
- `auth/authorization.py`: OIDC 설정과 활성 DB 사용자를 함께 확인하는 fail-closed 접근 경계
- `ui.py`: 상태와 무관한 HTML/CSS 표현
- `app.py`: Streamlit 상태 전환과 로그인 후 저장소 호출

브라우저 쿠키를 별도 서버 요청으로 복사하지 않습니다. 인증 세션은 Streamlit 네이티브 OIDC가 소유하고, 앱은 로그인된 `st.user`만 provider-neutral 모델로 변환합니다.
보호 기능을 추가할 때는 `st.user.is_logged_in`만 확인하지 말고, DB의 활성 사용자 저장까지 성공한 `application-access-granted` 세션 상태를 접근 경계로 사용해야 합니다.
