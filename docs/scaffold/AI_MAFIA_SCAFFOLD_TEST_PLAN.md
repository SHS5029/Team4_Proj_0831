# AI 마피아 연결 뼈대 테스트 계획

## 1. 단위 테스트

| 대상 | 검증 |
|---|---|
| schema | 필수 누락, UUID, player_count 범위, 추가 field 거부 |
| service | owner 확인, version 충돌, idempotency 동일·상이 body |
| repository | create/get/update operation, snapshot 기본값 |
| MCP service | action allowlist, session game/agent scope, 오류 mapping |
| frontend client | 2xx JSON 변환, 404/409/503 오류 변환 |

## 2. API contract test

1. `GET /health` → 200 `{"status":"ok"}`
2. `GET /api/v1/mcp/health` → connected 응답
3. `POST /api/v1/games` → 201과 `CreateGameResponse`
4. `GET /api/v1/games/{game_id}` → 200과 `GameStateResponse`
5. `POST .../commands` → 202와 operation_id
6. `GET .../operations/{operation_id}` → 200과 terminal status
7. `GET .../events` → SSE content type·heartbeat

## 3. 거부·장애 test

- `X-User-Id` 누락·잘못된 UUID → 400
- 타 사용자 game 조회 → 404
- 존재하지 않는 game/operation → 404
- 현재 version과 다른 `expected_version` → 409, DB 변경 없음
- 동일 key·동일 body → 최초 응답 재반환
- 동일 key·다른 body → 409
- MCP HMAC·session scope 실패 → MCP error
- MCP process 중단 → Backend dependency error, game 원본 유지
- Redis 중단 → DB 조회 가능, 실시간 기능만 fallback

## 4. 통합 완료 기준

깨끗한 venv에서 runbook의 smoke 순서를 수행하고 모든 API 응답을 JSON으로 확인한다. 이후 다음 명령을 통과시킨다.

```powershell
pytest backend/tests frontend_user/tests
python -m compileall -q backend frontend_user frontend_admin mcp_server
ruff check .
```

실제 OpenAI·Gemini·외부 OAuth·외부 MCP는 호출하지 않고 fake provider와 local MCP를 사용한다.
