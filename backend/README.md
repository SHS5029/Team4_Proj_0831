# Backend API

FastAPI가 외부 HTTP 요청을 받고 사용자 identity와 PostgreSQL 저장을 소유합니다.
Frontend는 DB에 직접 연결하지 않으며 공유 비밀로 HMAC 서명한 요청만 보냅니다.

## 실행

저장소 루트의 `.env`에 `DATABASE_URL`, `DATABASE_NAME`, 32자 이상의
`INTERNAL_API_SECRET`을 설정한 뒤 실행합니다.

```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

Health endpoint는 `GET http://127.0.0.1:8000/health`이며 정상 응답은
`{"status":"ok"}`입니다. 마이그레이션은 다음 명령으로 적용합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

## 보안 경계

`POST /api/v1/identity/provision`은 timestamp, UUID request id, raw JSON body를
결합한 HMAC-SHA256 서명을 검증합니다. 기본 허용 시간은 300초이며 서명이나 시간
검증에 실패하면 저장소를 호출하지 않습니다. 실제 secret, DB URL, OIDC token은
응답과 로그에 포함하지 않습니다.
