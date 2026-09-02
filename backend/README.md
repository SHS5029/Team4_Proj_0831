# Backend API

FastAPI가 외부 HTTP 요청을 받고 사용자 identity와 PostgreSQL 저장을 소유합니다.
Frontend는 DB에 직접 연결하지 않으며 공유 비밀로 HMAC 서명한 요청만 보냅니다.

섹터 분담에서는 Backend가 DB schema·migration·repository와 Redis application
코드를 작성하고, MCP 섹터가 PostgreSQL·Redis 실행 환경 구축·기동·migration
실행·health 확인을 담당합니다. Backend는 MCP 담당자가 준비한 서비스에 직접
연결하며 MCP 서버 runtime을 데이터 프록시로 사용하지 않습니다.

## 실행

MCP 담당자가 PostgreSQL을 기동하고 migration 상태를 확인한 후, 저장소 루트의
`.env`에 전달받은 `DATABASE_URL`, `DATABASE_NAME`과 32자 이상의
`INTERNAL_API_SECRET`을 설정해 Backend를 실행합니다.

```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

Health endpoint는 `GET http://127.0.0.1:8000/health`이며 정상 응답은
`{"status":"ok"}`입니다. 마이그레이션 파일과 실행기는 Backend 소유지만 다음
실제 적용 명령은 MCP 담당자가 실행합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

## 보안 경계

`POST /api/v1/identity/provision`은 timestamp, UUID request id, raw JSON body를
결합한 HMAC-SHA256 서명을 검증합니다. 기본 허용 시간은 300초이며 서명이나 시간
검증에 실패하면 저장소를 호출하지 않습니다. 실제 secret, DB URL, OIDC token은
응답과 로그에 포함하지 않습니다.
