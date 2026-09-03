# Mafia Game Context MCP Server

AI 마피아 게임의 에이전트에게 허용된 게임 컨텍스트(Resource)와 행동 제안
(Tool)을 제공할 MCP 서버 패키지입니다. 제품·소유권은
[공통 마스터플랜](../../docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md), wire 계약은
[API 명세서](../../docs/개발상세플랜/AI_MAFIA_API_SPEC.md), 구현 순서는
[MCP 서버 설계서](../../docs/개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)를 따릅니다.
다섯 Resource의 상세 `data` schema는 API 명세 8.2절과 그 절이 명시적으로 참조하는
API 공통 모델만 정본입니다.

현재 `WU-M2`는 stateful Streamable HTTP `/mcp`, bootstrap 인증, Backend Engine
consume adapter와 session cleanup까지만 구현합니다. Resource·Tool은 아직 등록하지
않았으며 MCP 섹터 담당자는 이 package와 별도로 PostgreSQL·Redis 실행 환경의
구축·기동·migration 실행·health 확인을 담당합니다.

확정된 `WU-M2` 구조에서는 상위 `mcp_server/`가 독립 프로젝트 루트이고 공식 import
package는 `mafia_game`입니다. composition root는 `mafia_game/main.py`, module
진입점은 `mafia_game/__main__.py`, 검증 위치는 `mcp_server/tests/`입니다. Python
3.12와 MCP SDK 1.29.1을 독립 `pyproject.toml`·`uv.lock`으로 재현합니다.

Streamable HTTP session은 stateful로 운영합니다. 최초 initialize에서 bearer
bootstrap과 capability header를 검증·consume하고 후속 요청은 같은 bearer로 session
owner만 증명합니다. 정상 DELETE, bootstrap 만료 또는 30초 idle 시 session memory를
폐기하며 bootstrap 만료가 idle보다 이르면 만료 시각을 우선합니다. consume 결과가
불명확하면 신규 HTTP code를 만들지 않고 `403 BOOTSTRAP_DENIED`로 fail-closed하며 같은
bootstrap과 기존 session ID를 재사용하지 않습니다. fresh credential 조정 절차는
`WU-M7` 범위입니다.
공개 오류 code와 Engine HTTP 매핑은 API 명세 9.3.1절만 따릅니다.

## 설정과 실행

MCP process는 공용 루트 `.env`를 읽지 않고 다음 allowlist 환경 변수만 조회합니다.

- `MCP_SERVER_AUTH_SECRET`: Backend가 bootstrap token 서명에 사용하는 32자 이상 secret
- `ENGINE_INTERNAL_API_SECRET`: MCP→Engine canonical HMAC 전용 32자 이상 secret
- `ENGINE_API_URL`: path·query 없는 Backend Engine base URL
- `MCP_LISTEN_HOST`: 선택값, 기본 `127.0.0.1`; WU-M2는 TLS가 없어 loopback만 허용
- `MCP_LISTEN_PORT`: 선택값, 기본 `8100`

두 secret은 서로 다른 synthetic/운영 값을 사용하고 실제 값은 Git·문서·로그·공용
`.env`에 기록하지 않습니다. 독립 환경 설치와 실행 명령은 다음과 같습니다.

```bash
cd mcp_server
uv sync --locked --dev
uv run --locked python -m mafia_game.main
```

기본 endpoint는 `http://127.0.0.1:8100/mcp`입니다. MCP runtime은 최초 initialize의
bearer와 capability header를 검증하고 `POST /internal/v1/mcp-bootstrap/consume`의
정확한 `{"status":"CONSUMED"}` 응답 뒤에만 session을 활성화합니다. Engine 요청은
API 8.1의 method·raw path·빈 canonical query·raw body hash·timestamp·UUID v4 nonce를
HMAC-SHA256으로 서명합니다.

## 검증

실제 Backend·DB·Redis·유료 API 없이 fake Engine과 HTTP ASGI transport를 사용합니다.

```bash
uv run --locked pytest tests
uv run --locked ruff check mafia_game tests
uv lock --check
```

테스트는 MCP SDK-level initialize/DELETE, canonical HMAC consume, token 형식·서명·폐쇄형
claim·무유예 만료·120초 상한·bootstrap nonce를 포함한 canonical UUID claim binding,
opaque capability hash, nonce replay, Engine HMAC nonce UUID v4, Engine 거부, 후속 bearer
owner와 capability 재전송 거부를 확인합니다. 원본 bearer·capability·job·subject는 SDK
scope와 transport tombstone에 전달하지 않고 session-local 난수 owner로 치환합니다.

## WU-M2 제약

- Resource와 subject별 allowlist는 `WU-M3`, 행동 Tool과 proposal은 `WU-M4` 범위입니다.
- 구조화 운영 로그·redaction은 `WU-M5` 범위이므로 이번 runtime은 payload를 별도
  sink·DB·queue·파일에 기록하지 않습니다.
- DB·Redis client, health endpoint, legacy `game_ping`·`game_get_context`·
  `game_submit_proposal` alias를 제공하지 않습니다.
- 실제 Backend의 job reservation·bootstrap 발급·consume 구현과 통합은 Backend
  `WU-B6`·`WU-B7` 및 MCP `WU-M6`의 선행 완료가 필요합니다.

## 책임 경계

- 이 서버는 게임 상태의 최종 판정자가 아닙니다. 모든 행동 제안은 Backend
  내부 Engine API로 전달되고 Backend 게임 엔진이 최종 검증·반영합니다.
- DB, Redis에 직접 접근하지 않으며 Backend의 내부 HTTP API만 호출합니다.
- 세션은 `subject_type`과 `subject_id`를 고정합니다. AI player는 `public`, `me`,
  `turn`, `persona` 중 capability가 허용한 정보만 받고 다른 에이전트를 선택할 수
  없습니다. GM은 `public`과 `gm-guide`만 받으며 `me`와 행동 Tool을 사용할 수 없습니다.
- 각 `agent_jobs` reservation은 새 capability·bootstrap·session을 사용합니다.
  현재 구현된 reconnect 경계에서는 소비한 bootstrap, 기존 capability와 session ID를
  재사용하지 않습니다. 이후 terminal 처리 연동은 `WU-M4`에서 같은 원칙을 적용합니다.
- GM narration은 MCP Tool이 아니라 LLM adapter에서 Backend Agent Manager로 직접
  반환되고, Backend가 공개 범위와 fencing 조건을 검증해 저장하거나 fallback합니다.

PostgreSQL·Redis 운영은 **담당자의 인프라 역할**이며 MCP 서버 runtime의 책임이
아닙니다. DB schema·migration SQL·repository와 Redis client·key·TTL·lock 계약은
Backend가 작성하고, MCP 담당자는 이를 수정하지 않은 채 실제 환경에서 실행·검증해
비밀값 없는 결과만 공유합니다.

의존 방향은 `api → services → ports ← integrations`입니다. `domain`에는
MCP·HTTP 구현을 모르는 순수 게임 개념만 두고, `schemas`는 공개 입출력 계약만
검증합니다. 다른 MCP 서버의 내부 모듈은 import하지 않습니다.
