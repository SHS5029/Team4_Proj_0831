# Backend API

FastAPI가 외부 HTTP 요청을 받고 사용자 identity와 PostgreSQL 저장을 소유합니다.
Frontend는 DB에 직접 연결하지 않으며 공유 비밀로 HMAC 서명한 요청만 보냅니다.

## 실행

저장소 루트의 `.env`에 `DATABASE_URL`, `DATABASE_NAME`, 32자 이상의
`INTERNAL_API_SECRET`을 설정한 뒤 실행합니다.

requirements 파일로 설치할 때 운영 의존성은 `backend/requirements.txt`, 테스트와
정적 검사를 포함한 개발 환경은 `backend/requirements-dev.txt`를 사용합니다.

```bash
python -m pip install -r backend/requirements-dev.txt
```

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

## LLM Provider

Backend는 `LLM_PROVIDER` 값으로 `dummy`, `local`, `openai`, `gemini` 중 하나를
선택합니다. 기본값은 외부 호출이 없는 `dummy`이며, Local은 OpenAI 호환
`/chat/completions` endpoint를 사용합니다. OpenAI와 Gemini는 선택된 경우에만
각 API key와 model 설정을 요구합니다. 공통 구조화 응답 검증과 Provider 구현은
`backend/app/llm_provider/`에 있으며, Provider는 게임 상태를 직접 변경하지 않고
Backend가 검증할 proposal만 반환합니다.

회귀 테스트는 실제 유료 API를 호출하지 않고 mock/fake 응답을 사용합니다. API key,
prompt 원문, 비공개 게임 context와 raw model response는 로그에 기록하지 않습니다.
자세한 구현 순서와 설정은 루트의
`docs/LLM_PROVIDER_IMPLEMENTATION_PLAN.md`를 참고하세요.

## 보안 경계

`POST /api/v1/identity/provision`은 timestamp, UUID request id, raw JSON body를
결합한 HMAC-SHA256 서명을 검증합니다. 기본 허용 시간은 300초이며 서명이나 시간
검증에 실패하면 저장소를 호출하지 않습니다. 실제 secret, DB URL, OIDC token은
응답과 로그에 포함하지 않습니다.
