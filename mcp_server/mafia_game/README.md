# Mafia Game Context MCP Server

AI 마피아 게임의 에이전트에게 허용된 게임 컨텍스트(Resource)와 행동 제안
(Tool)을 제공할 MCP 서버 패키지입니다. 제품·소유권은
[공통 마스터플랜](../../docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md), wire 계약은
[API 명세서](../../docs/개발상세플랜/AI_MAFIA_API_SPEC.md), 구현 순서는
[MCP 서버 설계서](../../docs/개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)를 따릅니다.
다섯 Resource의 상세 `data` schema는 API 명세 8.2절과 그 절이 명시적으로 참조하는
API 공통 모델만 정본입니다.

현재 `WU-M3`는 `WU-M2`의 stateful Streamable HTTP `/mcp`, MCP 세션 개설 토큰
(bootstrap token) 인증과 session cleanup을 유지하면서 consume 5-field binding과
다섯 Resource를 구현합니다. 운영 sink 결정과 독립적인 WU-M5 선행 로그 경계도
initialize·consume·Resource·Engine·session 종료에 연결했습니다. Tool은 아직 등록하지 않았으며
MCP 섹터 담당자는 이 package와 별도로
PostgreSQL·Redis 실행 환경의
구축·기동·migration 실행·health 확인을 담당합니다.

확정된 구조에서는 상위 `mcp_server/`가 독립 프로젝트 루트이고 공식 import
package는 `mafia_game`입니다. composition root는 `mafia_game/main.py`, module
진입점은 `mafia_game/__main__.py`, 검증 위치는 `mcp_server/tests/`입니다. Python
3.12와 MCP SDK 1.29.1을 독립 `pyproject.toml`·`uv.lock`으로 재현합니다.

Streamable HTTP session은 stateful로 운영합니다. 최초 initialize에서 bearer 세션
개설 토큰과 capability header를 검증·consume하고 후속 요청은 같은 bearer로 session
owner만 증명합니다. 정상 DELETE, 세션 개설 토큰 만료 또는 30초 idle 시 session
memory를 폐기하며 세션 개설 토큰 만료가 idle보다 이르면 만료 시각을 우선합니다.
각 headerless initialize는 `api/streamable_session_pool.py`에서 fresh low-level
`Server`와 그 child application 전용 stateful `StreamableHTTPSessionManager`를 하나씩
만듭니다. pool은 SDK 공개 constructor·`run()`·`handle_request()`만 사용하고 manager별
`run()` context를 정확히 한 번 소유합니다. manager는
`stateless=False`, `event_store=None`, `json_response=True`,
`session_idle_timeout=None`으로 고정하며 registry/middleware reaper만 30초 idle 종료를
소유합니다. terminal 승자는 route를 먼저 분리하고 공개 DELETE를 최대 한 번 시도한 뒤
결과와 무관하게 manager `run()`을 끝내 SDK transport·owner tombstone을 함께
폐기합니다. 테스트에서 `application.state.session_manager`는 이 pool을 가리키며 민감
식별자 없이 candidate·active·running count와 run-exit count만 제공합니다. initialize
응답은 route와 registry가 모두 준비된 뒤 commit token을 잡고 외부 start/body를
보내므로 중간에 DELETE·reaper가 끼어 manager를 먼저 종료할 수 없습니다.
consume 결과가 불명확하면 신규 HTTP code를 만들지 않고 `403 BOOTSTRAP_DENIED`로
fail-closed하며 같은 세션 개설 토큰과 기존 session ID를 재사용하지 않습니다. fresh
credential 조정 절차는 `WU-M7` 범위입니다.
공개 오류 code와 Engine HTTP 매핑은 API 명세 9.3.1절만 따릅니다.

consume 성공은 `status`, `allowed_resource_scopes`, `phase`, `state_version`,
`window_id` 다섯 field만 가진 폐쇄형 JSON이어야 합니다. bootstrap claim은 WU-M2
field를 그대로 유지하고 네 issuance 값은 claim에 복제하지 않습니다. AI player는
`public`, `me`, `turn`, `persona`, GM은 `public`, `gm-guide`의 canonical nonempty
부분집합만 받을 수 있으며 이 binding을 session memory에 보관해 list/read와 context
응답 교차 검증에 사용합니다.

`resources/list`는 binding만 canonical 순서로 반환하므로 Engine 호출이 없고 cursor가
존재하면 `-32602`입니다. descriptor는 `uri`, scope `name`,
`mimeType=application/json`만 가집니다. `resources/read`는 SDK `AnyUrl` 정규화 전 raw
URI를 exact 검사하고 미등록·미허용 요청은 `-32002`와 Engine 0회, 허용 요청은 Engine
GET 정확히 1회와 JSON text content 1개로 처리합니다. Resource template, pagination,
subscription, list-changed, context cache, retained response reference와 stale fallback은
없습니다.

Engine read 결과는 SDK 응답으로 즉시 보내지 않고 먼저 버퍼링합니다. session gate
안에서는 송신 직전 bearer·binding 확인과 성공 commit 또는 route·registry terminal
소유권만 짧게 확정하고, 실제 ASGI send와 SDK DELETE·manager stop은 gate·registry lock
밖에서 수행합니다. Engine GET도 gate 밖에서 실행해 서로 다른 read의 병렬성을
유지합니다. terminal 전이가 먼저면 버퍼된 성공 context를 전송하지 않고, 성공
commit이 먼저면 response body 송신 완료 event 뒤에만 terminal cleanup을 시작합니다.
send가 실패하거나 취소돼도 commit 소유권을 반납한 뒤 cleanup을 수행합니다.
raw URI·validation 등 후속 요청의 고정 오류 응답 송신이 실패하는 경우에도 요청 시작에
확정한 binding identity만 gate-aware하게 멱등 종료하고 원래 예외를 전파합니다. 이미
닫힌 분기는 SDK DELETE를 반복하지 않으며 registry에 없던 session은 건드리지 않습니다.
Engine capability 403·404는 `-32002`로 응답한 뒤 해당 session을 terminal 처리하므로
후속 list/read는 성공할 수 없습니다. registry cleanup의 실제 승자만 SDK DELETE를
한 번 호출하며 동시 DELETE 패자는 추가 transport 호출 없이 고정
`404 SESSION_NOT_FOUND`로 끝납니다.

30초 reaper는 만료 후보마다 독립 cleanup task를 만들고 binding별 중복 dispatch를
억제합니다. A의 teardown이 지연되어도 같은 sweep의 B와 이후 sweep에서 만료된 C의
route 제거와 teardown 시작은 계속 진행됩니다. shutdown은 reaper task를 취소한 뒤
남은 session을 병렬 종료하며, cancellation point를 지키는 한 session의 지연이 전체
종료를 무기한 붙잡지 않도록 제한된 유예 뒤 manager run context를 닫습니다.

## 설정과 실행

MCP process는 공용 루트 `.env`를 읽지 않고 다음 allowlist 환경 변수만 조회합니다.

- `MCP_SERVER_AUTH_SECRET`: Backend가 세션 개설 토큰 서명에 사용하는 32자 이상 secret
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
정확한 5-field 응답 뒤에만 session을 활성화합니다. Resource read는 `GET
/internal/v1/agent-context?scope=...`를 호출합니다. Engine 요청은
API 8.1의 method·raw path·요청별 canonical query·raw body hash·timestamp·UUID v4
nonce를 HMAC-SHA256으로 서명하며 GET query는 RFC 3986 encoded key/value로 정렬합니다.

Context Engine 403·404는 `-32002`, timeout·연결 단절·원격 protocol 종료·429·5xx는
`-32003`, 그 밖의
status와 Content-Type·JSON·duplicate·200 schema 또는 binding 위반은 `-32004`로
고정합니다. 이 세 오류에는 정해진 한국어 message 외의 `data`, upstream body,
exception 원문을 반환하지 않습니다.
client 또는 Engine JSON이 약 10,000단계로 중첩되거나 5,000자리 정수로 Python decoder
한계를 넘는 경우도 예외 원문을 ASGI 밖으로 내보내지 않고 각각 `-32602`, `-32004`로
정규화합니다. Python decoder가 기본 허용하는 `NaN`, `Infinity`, `-Infinity`도
비표준 JSON 상수로 parsing 단계에서 모두 거부합니다. 이 입력·upstream validation
오류 자체는 정상 owner session을 terminal 처리하지 않습니다.

UTC RFC 3339 field는 `Z`와 `+00:00`을 둘 다 UTC로 허용하지만 0이 아닌 offset은
거부하며, 검증 후에도 Engine이 보낸 원본 UTC 문자열 표현을 유지합니다. `public`
응답은 AI subject가 공개 player 목록의 `kind=AI`와 일치하는지와 투표 집계가
알려진 player 인원을 넘지 않는지를 검증하고, `turn`의 낮 투표 target은
자기 자신을 거부합니다. 다른 scope를 추가 조회하거나 cross-scope provenance를
재판정하지는 않습니다.

현재 merge된 Backend의 `InternalEngineService.consume_bootstrap`은 status-only
`{"status":"CONSUMED"}`를 반환합니다. 이는 승인된 WU-M3 5-field 계약과 불일치하므로
실제 Backend에 연결한 initialize는 fail-closed합니다. MCP 계약을 완화하지 않으며
Backend `WU-B7` 정합화 뒤 `WU-M6`에서 실제 Backend↔MCP 왕복을 검증해야 합니다.

## 운영 수집기와 독립적인 로그 경계

`create_app(settings, audit_sink=collector)`로 `AuditSink.emit(record)`를 구현한 신뢰된
수집기를 주입할 수 있습니다. 기본 `audit_sink=None`은 기록을 폐기하며 파일·표준 출력·
DB·Redis·queue를 선택하지 않습니다. 운영 수집기와 보존 기간인 `OPEN-04`는 미결정입니다.
수집기는 호출을 블로킹하지 않아야 하고, 수집기 예외는 게임 결과를 변경하지 않으며
실패한 record를 재전송하거나 별도 spool에 쓰지 않습니다.

전달하는 필드는 API 9.4의 `request_id`, `correlation_id`, `operation`, `status`,
`duration_ms`, `error_class`뿐입니다. 로그 ID는 HTTP header·RPC ID·session·game·agent
식별자를 복사하지 않는 독립 UUID입니다. SDK 장수 worker에서도 현재 HTTP 요청의
안전한 ID만 복원하므로 Resource 요청과 Engine 조회를 같은 상관관계로 확인할 수 있습니다.
operation·status·error class는 폐쇄형 enum이고 duration은 유한한 0 이상의 값입니다.
요청·응답 payload, token·capability·secret, private context와 exception 원문은 받지 않습니다.

실제 계측 범위는 initialize, consume, Resource list/read, Engine context, protocol 요청,
session teardown입니다. context는 schema·직렬화까지 통과한 뒤 성공으로 기록하며, 송신
실패·취소·teardown 실패도 고정 분류로 기록합니다. Tool 계측은 WU-M4 구현 뒤 연결합니다.
`core/audit.py`의 검증기와 `ports/audit.py`의 출력 경계는 운영 저장소와 분리돼 있습니다.

SDK·HTTP 라이브러리와 Uvicorn 오류·TRACE 원문은 `isolate_dependency_logs()`가 표준
logging filter로 formatter 전에 폐기합니다. 중첩·동시 app 수명은 참조계수로 보호하고
마지막 종료 때 기존 설정을 복원합니다. 독립 entrypoint는 Uvicorn access log도 끄고
서버 시작부터 종료 오류 처리까지 이 보호를 유지합니다. 다른 ASGI host에 내장할 때도
host의 access/error handler가 raw 요청·예외를 따로 기록하지 않도록 같은 경계를 적용해야
합니다. 의존성 갱신 때는 고정된 logger 목록과 민감 marker 테스트를 함께 확인합니다.

## 확정된 로컬 실행·종료 절차

1. `mcp_server/`에서 `uv sync --locked --dev`로 독립 환경을 준비하고 아래 검증을 실행합니다.
2. 승인된 비밀 전달 경로로 이 README의 다섯 환경 변수만 MCP 프로세스에 주입합니다.
   공용 루트 `.env`를 로드하거나 DB·Redis·LLM 자격증명을 함께 전달하지 않습니다.
3. `uv run --locked python -m mafia_game.main`으로 loopback에서 실행합니다. 실제 요청은
   Backend의 5-field consume과 context 처리기가 준비된 뒤에만 확인할 수 있습니다.
4. foreground 프로세스는 `Ctrl-C`로 정상 종료합니다. 종료 처리는 reaper를 취소하고
   세션 route·registry·SDK manager와 소유 HTTP client를 정리합니다.
5. 재시작은 기존 세션을 복원하지 않습니다. Backend가 새 job 자격을 발급해야 하며 이전
   bearer·capability·session ID를 재사용하지 않습니다.

현재 MCP 자체 health endpoint는 없습니다. 테스트 통과는 독립 코드 검증이며 실제
인프라 health나 Backend 통합 완료 증거가 아닙니다. TLS·readiness·운영 rotation·실제
장애 복구와 제3자 재현을 포함한 WU-M8 전체 완료는 해당 OPEN 결정과 WU-M6/M7 이후입니다.

## 검증

실제 Backend·DB·Redis·유료 API 없이 fake Engine과 HTTP ASGI transport를 사용합니다.

```bash
uv run --locked pytest tests
uv run --locked ruff check mafia_game tests
uv lock --check
```

2026-09-05 검증 결과는 package 전체 **255 passed**이며 Ruff와 offline lock 검증도
통과했습니다. 실행 명령은 기존 독립 환경의 `.venv/bin/python -m pytest tests -q --tb=short`,
`.venv/bin/ruff check mafia_game tests`, `uv lock --check --offline`입니다.
M3에서 UTF-8 직렬화 불가능한 단독 surrogate 거부와 임의 정밀도 RFC3339 소수초 비교를
보강했고, 해당 schema 테스트 63개가 통과했습니다. M5 전용 테스트는 record·sink 경계
30개와 SDK/ASGI runtime 경계 11개이며 전체 결과에 포함됩니다. 실제 Backend·DB·Redis·
Provider 연결이나 migration은 실행하지 않았습니다.

테스트는 MCP SDK-level initialize/DELETE/list/read, canonical HMAC consume/context GET,
token 형식·서명·폐쇄형
claim·무유예 만료·120초 상한·세션 개설 토큰의 nonce를 포함한 canonical UUID claim
binding,
opaque capability hash, nonce replay, Engine HMAC nonce UUID v4, Engine 거부, 후속 bearer
owner와 capability 재전송 거부를 확인합니다. 또한 consume 5-field, subject 2×5
allowlist, list cursor·raw duplicate·exact URI 거부, 다섯 context schema, binding
mismatch, 송신 직전 만료, capability terminal cleanup, 고정 오류 redaction,
반복·동시 read 무캐시, 성공 response와 capability·reaper terminal의 사건 순서,
SDK idle reaper 비활성화와 registry 30초 단일 소유권, 세션별 manager run-exit과
candidate·route cleanup, A/B/C reaper 비간섭, session ID 재사용 old-owner fencing, 동시
DELETE·DELETE/reaper·cancellation·shutdown·고정 오류 send 실패의 단일 transport 종료,
깊은 JSON·5,000자리 정수·비표준 비유한 상수 정규화와
단일 runtime 내 session/audience 비간섭성을
검증합니다. 원본 bearer·capability·job·subject는 SDK
scope와 transport tombstone에 전달하지 않고 session-local 난수 owner로 치환합니다.

## WU-M3 제약

- 행동 Tool과 proposal은 `WU-M4` 범위입니다.
- `WU-M5`는 기존 경로의 로그 검증·전달만 선행 구현했습니다. Tool 계측과 운영
  sink·보존 정책이 남아 있어 WU-M5 전체 완료로 표시하지 않습니다. payload는 어느
  sink·DB·queue·파일에도 기록하지 않습니다.
- DB·Redis client, health endpoint, legacy `game_ping`·`game_get_context`·
  `game_submit_proposal` alias를 제공하지 않습니다.
- 실제 Backend의 job reservation·세션 개설 토큰 발급·consume 구현과 통합은 Backend
  `WU-B6`·`WU-B7` 및 MCP `WU-M6`의 선행 완료가 필요합니다. 특히 현재 Backend
  status-only consume은 5-field로 바뀌기 전 실제 initialize와 호환되지 않습니다.

## 책임 경계

- 이 서버는 게임 상태의 최종 판정자가 아닙니다. 모든 행동 제안은 Backend
  내부 Engine API로 전달되고 Backend 게임 엔진이 최종 검증·반영합니다.
- DB, Redis에 직접 접근하지 않으며 Backend의 내부 HTTP API만 호출합니다.
- 세션은 `subject_type`과 `subject_id`를 고정합니다. AI player는 `public`, `me`,
  `turn`, `persona` 중 capability가 허용한 정보만 받고 다른 에이전트를 선택할 수
  없습니다. GM은 `public`과 `gm-guide`만 받으며 `me`와 행동 Tool을 사용할 수 없습니다.
- 각 `agent_jobs` reservation은 새 capability·세션 개설 토큰·session을 사용합니다.
  현재 구현된 reconnect 경계에서는 소비한 세션 개설 토큰, 기존 capability와 session
  ID를 재사용하지 않습니다. Tool 결과에 따른 job terminal 연동은
  `WU-M4`에서 같은 원칙을 적용합니다.
- GM narration은 MCP Tool이 아니라 LLM adapter에서 Backend Agent Manager로 직접
  반환되고, Backend가 공개 범위와 fencing 조건을 검증해 저장하거나 fallback합니다.

PostgreSQL·Redis 운영은 **담당자의 인프라 역할**이며 MCP 서버 runtime의 책임이
아닙니다. DB schema·migration SQL·repository와 Redis client·key·TTL·lock 계약은
Backend가 작성하고, MCP 담당자는 이를 수정하지 않은 채 실제 환경에서 실행·검증해
비밀값 없는 결과만 공유합니다.

의존 방향은 `api → services → ports ← integrations`입니다. `domain`에는
MCP·HTTP 구현을 모르는 순수 게임 개념만 두고, `schemas`는 공개 입출력 계약만
검증합니다. 다른 MCP 서버의 내부 모듈은 import하지 않습니다.
