# 일반 사용자 Frontend

Streamlit 네이티브 OIDC(`st.login`, `st.user`, `st.logout`)를 사용하는 Google
로그인 앱입니다. 로그인 화면과 외부 claim 정규화는 이 서버가 담당하지만 사용자
저장은 DB 직접 연결 없이 서명된 Backend API로 요청합니다.

## 실행 준비

저장소 루트에서 통합 의존성을 설치합니다.

```bash
uv sync --dev
```

OIDC 예시를 복사하고 실제 Google OAuth 값과 Backend 연결 값을 채웁니다.

```bash
cp frontend_user/.streamlit/secrets.toml.example \
  frontend_user/.streamlit/secrets.toml
chmod 600 frontend_user/.streamlit/secrets.toml
```

`[backend].api_url`은 로컬에서 `http://127.0.0.1:8000`을 사용하며,
`internal_api_secret`은 Backend `.env`의 `INTERNAL_API_SECRET`과 같은 32자
이상의 무작위 값이어야 합니다. 이 값은 브라우저로 전달하지 않습니다.

Google Cloud Console의 로컬 승인 redirect URI는 다음 값과 정확히 같아야 합니다.

```text
http://localhost:8501/oauth2callback
```

## 실행

Backend를 먼저 실행한 뒤 별도 터미널에서 사용자 앱을 시작합니다.

```bash
uv run streamlit run frontend_user/app.py --server.port 8501
```

브라우저에서 `http://localhost:8501`을 엽니다. OIDC 설정이 빠졌거나 잘못되면
로그인 버튼을 비활성화합니다. Backend 설정·서명·저장에 실패하면 애플리케이션 접근을
허용하지 않고 비밀값 없는 고정 안내만 표시합니다.

## 테스트

```bash
uv run pytest frontend_user/tests
uv run ruff check frontend_user
```

테스트는 OIDC claim·secrets 검증, HMAC 요청 생성, Backend 오류 매핑, 외부 값 HTML
escape, 로그인 화면 smoke 경로를 synthetic 데이터와 mock transport로 검증합니다.

## 책임 경계

- `app.py`: `app_pages.login_page.main()`만 호출하는 실행 진입점
- `app_pages/login_page.py`: Streamlit 상태 전환과 화면 조율
- `auth/configuration.py`: OIDC secrets 구조 검사
- `auth/identity.py`: `st.user`를 provider-neutral identity로 정규화
- `auth/authorization.py`: fail-closed 접근 상태
- `auth/persistence.py`: Backend 결과를 저장·차단·재시도 UI 상태로 변환
- `components/ui.py`: 문맥별 escape가 적용된 HTML·CSS 표현
- `core/api_client.py`: Backend 주소 검증, JSON 직렬화, HMAC, HTTP 호출

Frontend는 PostgreSQL, Redis, MCP 서버를 직접 호출하지 않습니다. 보호 기능은 OIDC
로그인 플래그만 신뢰하지 않고 Backend에서 활성 사용자 저장이 확인된
`application-access-granted` 상태를 접근 경계로 사용해야 합니다.
