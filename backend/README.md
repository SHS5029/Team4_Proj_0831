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

연결 뼈대에서는 별도 MCP 프로세스를 먼저 실행합니다.

```bash
python -m mcp_server.mcp_1
uvicorn backend.app.main:app --reload --port 8000
```

게임 smoke API는 `X-User-Id`와 `ruleset_version=scaffold-v1`을 사용합니다. Swagger는
`http://127.0.0.1:8000/docs`, MCP 연결 확인은
`GET http://127.0.0.1:8000/api/v1/mcp/health`입니다. 실제 게임 규칙과 `basic-v1`은
연결 뼈대 완료 후 별도 단계에서 추가합니다.

## 보안 경계

`POST /api/v1/identity/provision`은 timestamp, UUID request id, raw JSON body를
결합한 HMAC-SHA256 서명을 검증합니다. 기본 허용 시간은 300초이며 서명이나 시간
검증에 실패하면 저장소를 호출하지 않습니다. 실제 secret, DB URL, OIDC token은
응답과 로그에 포함하지 않습니다.
