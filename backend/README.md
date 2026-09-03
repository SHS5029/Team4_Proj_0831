# Backend API

FastAPI가 외부 HTTP 요청, 게임 판정과 PostgreSQL 저장을 소유합니다. 현재 코드에는
legacy identity·Front HMAC route가 남아 있지만 목표 MVP에서는 제거하고 UUID v4
`X-User-Id`만 사용합니다. Frontend는 어떤 상태에서도 DB에 직접 연결하지 않습니다.

섹터 분담에서는 Backend가 DB schema·migration·repository와 Redis application
코드를 작성하고, MCP 섹터가 PostgreSQL·Redis 실행 환경 구축·기동·migration
실행·health 확인을 담당합니다. Backend는 MCP 담당자가 준비한 서비스에 직접
연결하며 MCP 서버 runtime을 데이터 프록시로 사용하지 않습니다.

## 실행

MCP 담당자가 PostgreSQL을 기동하고 migration 상태를 확인한 후, 저장소 루트의
`.env`에 전달받은 `DATABASE_URL`, `DATABASE_NAME`과 32자 이상의
`INTERNAL_API_SECRET`을 설정해 Backend를 실행합니다.

현재 `backend/requirements.txt`에는 Backend 실행과 회귀 테스트·정적 검사 의존성이
함께 있습니다. 저장소 전체 개발 환경은 루트 `pyproject.toml`을 사용합니다.

```bash
python -m pip install -r backend/requirements.txt
```

```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

Health endpoint는 `GET http://127.0.0.1:8000/health`이며 정상 응답은
`{"status":"ok"}`입니다. 마이그레이션 파일과 실행기는 Backend 소유지만 다음
실제 적용 명령은 MCP 담당자가 실행합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

현재 migration은 `001`·`002` legacy/scaffold 기반, `003` canonical `mystery-v1`
schema, `004` 최소 정적 콘텐츠 순서로 실행됩니다. `004`는 시나리오 5개와 시나리오별
알리바이·관찰 각 9개, 활성 persona 한 개를 고정 key로 멱등 등록합니다.

현재 `mcp_server/mafia_game`에는 실행 가능한 서버 entrypoint가 없습니다. 따라서 MCP
연결 endpoint는 호환 서버를 별도로 준비한 경우에만 확인할 수 있고, canonical MCP
서버 실행 명령은 `WU-M2`에서 entrypoint를 구현한 뒤 이 문서에 추가합니다.

현재 게임 smoke API는 `X-User-Id`와 `ruleset_version=scaffold-v1`을 사용합니다. Swagger는
`http://127.0.0.1:8000/docs`, MCP 연결 확인은
`GET http://127.0.0.1:8000/api/v1/mcp/health`입니다. canonical `mystery-v1`은
[공통 마스터플랜](../docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md)의 후속 WU입니다.

## LLM Provider

Backend는 `LLM_PROVIDER` 값으로 `dummy`, `local`, `openai`, `gemini` 중 하나를
선택합니다. 기본값은 외부 호출이 없는 `dummy`이며, Local은 OpenAI 호환
`/chat/completions` endpoint를 사용합니다. OpenAI와 Gemini는 선택된 경우에만
각 API key와 model 설정을 요구합니다. 공통 구조화 응답 검증과 Provider 구현은
`backend/app/llm_provider/`에 있으며, Provider는 게임 상태를 직접 변경하지 않고
Backend가 검증할 proposal만 반환합니다.

회귀 테스트는 실제 유료 API를 호출하지 않고 mock/fake 응답을 사용합니다. API key,
prompt 원문, 비공개 게임 context와 raw model response는 로그에 기록하지 않습니다.
MVP에서는 앱 수준의 LLM timeout, token 상한·사용량과 비용·예산 기능을 구현하지
않습니다. 세부 경계는
[API 명세서](../docs/개발상세플랜/AI_MAFIA_API_SPEC.md)를 따릅니다.

## 보안 경계

현재 `POST /api/v1/identity/provision`은 legacy HMAC 검증을 수행하며 `WU-B1`에서 route와
함께 제거합니다. 목표 공개 API의 UUID는 인증 수단이 아니므로 개인 개발·사설망으로
배포 범위를 제한합니다. Backend↔MCP 내부 HMAC·capability는 별도 보안 경계로 유지하며
실제 secret, DB URL과 token은 응답과 로그에 포함하지 않습니다.
