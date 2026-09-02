# AI 마피아 연결 뼈대 실행 절차

실행환경은 `mini_agent_03_mcp_0827`와 `mini_agent_03_tool_0824`의 로컬 Python·venv·uvicorn·Streamlit 방식을 따른다. 명령은 저장소 루트 기준이며 실제 secret은 입력하지 않는다.

## 1. 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` 최소값:

```env
DATABASE_URL=postgresql://app_user:change-me@127.0.0.1:5432/Team4_Proj
REDIS_URL=redis://127.0.0.1:6379/0
LLM_PROVIDER=dummy
MAFIA_MCP_URL=http://127.0.0.1:8010/mcp
MCP_INTERNAL_SECRET=replace-with-local-random-secret
BACKEND_API_URL=http://127.0.0.1:8000
```

## 2. 기동 순서

터미널 1:

```powershell
python -m mcp_server.mcp_1
```

확인: MCP inspector에서 `initialize`와 `tools/list` 실행

터미널 2:

```powershell
uvicorn backend.app.main:app --reload --port 8000
```

확인: `Invoke-RestMethod http://127.0.0.1:8000/health`

Backend를 처음 실행하기 전 migration을 적용한다.

```powershell
py -3.12 -m backend.app.infrastructure.migrations
```

터미널 3:

```powershell
py -3.12 -m streamlit run frontend_user/game_scaffold_app.py --server.port 8501
```

관리자 화면은 별도 터미널에서 `py -3.12 -m streamlit run frontend_admin/app.py --server.port 8502`로 실행한다. OIDC 로그인 앱과 뼈대 smoke 앱은 서로 다른 진입점으로 실행한다.

## 3. smoke 순서

```powershell
$headers = @{"X-User-Id"="00000000-0000-4000-8000-000000000001"}
$body = @{player_count=5; ruleset_version="scaffold-v1"; idempotency_key="00000000-0000-4000-8000-000000000010"} | ConvertTo-Json
$game = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/games -Method Post -Headers $headers -ContentType "application/json" -Body $body
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/games/$($game.game_id)" -Headers $headers
$command = @{command="PING"; expected_version=1; idempotency_key="00000000-0000-4000-8000-000000000012"} | ConvertTo-Json
$op = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/games/$($game.game_id)/commands" -Method Post -Headers $headers -ContentType "application/json" -Body $command
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/games/$($game.game_id)/operations/$($op.operation_id)" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/games/$($game.game_id)/proposal" -Method Post -Headers $headers
```

기대 결과는 생성 201, 상태 조회 200, command 202, operation 200이다. 다른 UUID로 조회하면 404, `expected_version=0` 또는 현재와 다른 값은 409, 같은 idempotency key의 동일 body는 같은 응답을 반환해야 한다.

Swagger UI는 `http://127.0.0.1:8000/docs`에서 확인한다. MCP는 MCP inspector 또는 Backend의 `/api/v1/mcp/health`로 확인한다. Backend health는 MCP의 `initialize`와 `game_ping` 성공 여부를 검사한다.

## 4. 장애 확인

MCP 서버를 종료한 뒤 `/api/v1/mcp/health`는 503 또는 `status=disconnected`를 반환하고 게임 데이터는 손상되지 않아야 한다. Redis를 중지해도 game GET·operation GET은 PostgreSQL 또는 in-memory fallback으로 동작해야 한다.
