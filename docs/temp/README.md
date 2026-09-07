# MCP 상세 구조와 섹터 요약 — 임시 검토본

작성 기준: 2026-09-06, `Hwanseok` 브랜치의 `5292c2a` 및 현재 미커밋 작업 파일.
완성 목표가 아니라 **현재 코드에서 확인한 연결 상태**를 그렸다. 서비스 가동이나
실제 Backend↔MCP 통합 성공을 확인한 문서는 아니다. 정본을 대체하지 않는다.

사용자 요청에 따라 이번 산출물은 `docs/temp/`에만 저장했다. 루트 README와 기존
설계서·코드·설정은 수정하지 않았다. 기존 미커밋 변경도 그대로 유지했다.

## 구조도 열기

처음 읽는 경우 [전체 프로젝트와 MCP 서버를 쉽게 이해하는 안내서](PROJECT_AND_MCP_GUIDE.md)부터
보면 된다. 폴더별 역할, 사용자 요청 흐름, MCP의 자료·권한·세션·오류 처리와 현재 남은
연결 과제를 예시로 설명한다.

| 구조도 | 브라우저에서 열 파일 | 수정 가능한 원본 |
|---|---|---|
| MCP 상세 | [MCP 상세 구조도](mcp-detail.html) | [원본 JSON](mcp-detail.architecture.json) |
| 타 섹터 요약 | [전체 섹터 구조도](sectors-overview.html) | [원본 JSON](sectors-overview.architecture.json) |

HTML은 로컬 브라우저에서 직접 열 수 있는 독립 파일이다. 서버 실행·로그인·외부
서비스 연결은 필요 없다. 설명은 한국어지만 Archify가 지원하는 고정 Viewer 메뉴와
`html lang`은 영어로 유지된다. 기본 화면은 정적인 `READ`이며 애니메이션을 켜지 않았다.
노드의 보조 정보는 확대하거나 선택해서 확인할 수 있다.

## 읽는 방법

- 실선은 현재 구현의 호출·처리 경로를 뜻한다. 실제 배포·가동 완료 표시가 아니다.
- 보라색 점선과 명시적인 미연결/계약 불일치 문구는 운영 연결이 없는 경로를 뜻한다.
- MCP 왼쪽 호출자는 독립 SDK/ASGI 테스트의 요청 주체다. Backend의 실제 MCP
  클라이언트가 연결됐다는 의미가 아니다.
- 화살표는 요청·의존 방향을 요약하며 같은 연결의 응답은 역방향으로 돌아온다.
  SSE 역시 브라우저가 요청을 열고 Backend가 이벤트를 전달한다.
- 요약도는 모든 함수 호출을 펼친 call graph가 아니다. 공통 HTTP 어댑터, 로그 계측,
  상태 검증처럼 여러 경로가 공유하는 동작은 아래 카드와 이 문서에 보충했다.
- 미커밋 소스를 사용했으므로 GitHub의 특정 commit과 일치한다고 주장하는 자동
  source-link 기능은 넣지 않았다. 실제 확인한 파일과 줄 번호는 아래에 기록했다.

## MCP 상세 설명

`main.create_app`은 인증 미들웨어, 세션별 SDK pool, session registry, BootstrapService,
ResourceService, HTTP Engine 어댑터와 공통 AuditRecorder를 조립한다.

| 영역 | 현재 동작 | 확인한 코드 |
|---|---|---|
| 조립·수명주기 | Starlette app, session pool, reaper 및 shutdown 정리 | [main.py](../../mcp_server/mafia_game/main.py), 28·48·65·86행 |
| `/mcp` 입구 | initialize 검증, 후속 bearer owner 확인, raw URI·송신 gate | [bootstrap_auth.py](../../mcp_server/mafia_game/api/bootstrap_auth.py), 376·456·623·915행 |
| 세션 인증 | 서명·만료·replay 검사 뒤 consume 5-field 결과 검증 | [bootstrap.py](../../mcp_server/mafia_game/services/bootstrap.py), 59·80·98행 |
| 세션 메모리 | job·subject·발급 binding 고정, idle·만료·DELETE·shutdown 폐기 | [session.py](../../mcp_server/mafia_game/domain/session.py), 24·39·86·149행 |
| SDK 격리 | 세션별 fresh Server와 stateful manager, 공개 lifecycle pool | [streamable_session_pool.py](../../mcp_server/mafia_game/api/streamable_session_pool.py) |
| Resource handler | list/read만 등록하고 binding으로 허용 scope 확인 | [handlers.py](../../mcp_server/mafia_game/api/resources/handlers.py), 65행 |
| Resource service | 허용 read당 GET 1회, binding·schema 검증 후 JSON 반환 | [resources.py](../../mcp_server/mafia_game/services/resources.py), 20·57행 |
| HTTP 어댑터 | consume POST와 context GET에 canonical HMAC 적용 | [engine_http.py](../../mcp_server/mafia_game/integrations/engine_http.py), 23·63·108·135행 |
| 안전 로그 | 여섯 필드만 허용, 주입 sink로 전달, 기본값은 폐기 | [audit.py](../../mcp_server/mafia_game/core/audit.py), 87·128·172행 |

Resource는 `mafia://session/` 아래 `public`, `me`, `turn`, `persona`, `gm-guide` 다섯
URI다. AI는 앞의 네 scope, GM은 `public`·`gm-guide` 중 발급 capability가 허용한
비어 있지 않은 부분집합만 읽는다. list는 Engine 0회, 허용 read는 GET 1회, 거부 read는
Engine 0회다. context 캐시나 stale 응답 재사용은 없다.

BootstrapService도 ResourceService와 같은 HTTP 어댑터를 사용한다. 감사 계측은 그림의
대표 연결 외에도 initialize·consume·protocol 요청·Engine context·teardown에 적용된다.
로그에 payload·token·capability·원문 exception을 보내지 않으며 운영 sink는 미선정이다.

아직 연결되지 않은 경계:

1. Backend consume이 `status`만 반환하므로 MCP가 요구하는 5-field 계약과 불일치한다.
2. Backend의 context/proposal handler가 기본 실행 경로에 주입되지 않았다.
3. 실제 Backend Agent MCP client와 행동 Tool은 아직 연결/등록되지 않았다.
4. 운영 sink·TLS·health·응답 유실 뒤 fresh credential 조정 정책은 남아 있다.

근거: [InternalEngineService](../../backend/app/services/internal_engine_service.py),
71·115·130·172행 및 [MCP 설계서](../개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)의
3·15.4·16절. 상세 wire schema는 [API 정본](../개발상세플랜/AI_MAFIA_API_SPEC.md)의
8·9절을 따르며 이 임시 문서에 별도 계약을 만들지 않았다.

## 타 섹터 요약 설명

| 섹터·경로 | 현재 확인한 내용 | 확인한 코드 |
|---|---|---|
| 사용자 화면 | UUID 시작, 홈·게임·관전·결과·피드백 화면 분기 | [사용자 app.py](../../frontend_user/app.py), 36·55·80·92행 |
| 사용자 REST | Streamlit Python client가 게임·command·sync·feedback 요청 | [사용자 api_client.py](../../frontend_user/core/api_client.py), 95·107·121·128·145·158행 |
| 사용자 SSE | 브라우저 fetch가 Backend 이벤트 endpoint 직접 호출 | [SSE index.js](../../frontend_user/components/browser_components/sync/index.js), 4·5행 |
| 동기화 적용 | SSE envelope 또는 `/sync` 결과를 화면 상태에 적용 | [game_page.py](../../frontend_user/app_pages/game_page.py), 193·199·209행 |
| 관리자 화면 | UUID 접근 확인 뒤 지표·게임 목록·상세를 조회 | [관리자 app.py](../../frontend_admin/app.py), 38·46·57·65·73행 |
| 관리자 HTTP | Streamlit client가 `/api/v1/admin/*` GET 호출 | [관리자 api_client.py](../../frontend_admin/core/api_client.py), 46·65·70행 |
| Backend 진입 | 공개·관리자·내부 라우터, 사용자·관리자 repository 연결 | [Backend main.py](../../backend/app/main.py), 89·102행 |
| 공개 게임 저장 | canonical 게임은 `InMemoryGameRepository` 기본값 | [scaffold_game_router.py](../../backend/app/routers/scaffold_game_router.py), 48·54행 |
| 내부 권한 저장 | nonce/capability 처리에 PostgreSQL adapter 연결 | [scaffold_mcp_router.py](../../backend/app/routers/scaffold_mcp_router.py), 35행 |

주의할 차이:

- 사용자 Front 노드는 Streamlit 서버와 브라우저 컴포넌트를 함께 요약한다. REST와
  SSE의 실행 위치는 서로 다르다. Front→MCP·DB·Redis·LLM 직접 연결은 없다.
- 현재 UUID는 식별값이며 강한 인증이 아니다. 관리자도 UUID allowlist에 의존한다.
- 자동 SSE 재접속·주기 polling 타이머와 저장 게임의 `RESUME` command 흐름은
  완성됐다고 표시하지 않았다. 관리자 UUID 직접 입력/복구 화면도 완성으로 보지 않는다.
- 공개 게임의 메모리 저장과 사용자·관리자·내부 권한의 PostgreSQL 경로를 분리했다.
  canonical 게임이 PostgreSQL에 영속 저장된다고 표시하지 않았다.
- Redis는 legacy scaffold 연결만 확인했다. canonical Redis·outbox·지속 SSE의
  운영 왕복 연결은 아니다. Agent/Outbox 구성요소는 코드 존재와 운영 연결을 구분했다.
- MCP 섹터는 DB·Redis 환경 준비·기동·중지·migration 실행·health 확인을 맡는다.
  schema·migration SQL·repository·Redis application code는 Backend 소유다.

## 검증 결과

Archify `2.16.0`의 `architecture` 모드와 `showcase` 검증을 사용했다.

| 검증 | MCP 상세 | 섹터 요약 |
|---|---|---|
| schema·배치·연결선·라벨 | 9/9 통과, 오류 0·경고 0 | 9/9 통과, 오류 0·경고 0 |
| HTML 전달 | 성공 | 성공 |
| 1440×900 / 1600×1000 / 1920×1080 / 2048×1320 | 가로·세로 overflow 없음 | 가로·세로 overflow 없음 |
| 화면 직접 확인 | 큰 화면 밝은 테마·작은 화면 어두운 테마 확인 | 큰 화면 밝은 테마·작은 화면 어두운 테마 확인 |
| 시각 검토 후 수정 | 1회 | 1회 |

최종 캡처에서 노드·라벨 겹침, 연결선 교차, 카드 잘림이 없고 두 테마의 대조 및
큰 화면의 세로 배치를 확인했다. 자동 `visual-check` 영수증의 `visualReview: pending`은
도구 원본대로 유지했으며, 사람에게 보여 줄 이미지의 직접 검토 결과는 별도
[검증 영수증](validation-receipts.json)에 `visual_review: passed`로 기록했다.
검색·포커스·내보내기 등 모든 Viewer 상호작용을 별도 E2E 테스트한 것은 아니다.

- [MCP 화면 캡처 모음](mcp-detail.visual-check.html)
- [섹터 요약 화면 캡처 모음](sectors-overview.visual-check.html)
- [MCP 자동 화면 검증](mcp-detail.visual-check.json)
- [섹터 요약 자동 화면 검증](sectors-overview.visual-check.json)

실행 명령은 각 원본과 HTML에 대해 다음 순서로 적용했다.

```bash
node /Users/shsmac/.agents/skills/archify/bin/archify.mjs validate architecture <원본.json> --quality showcase --json
node /Users/shsmac/.agents/skills/archify/bin/archify.mjs deliver architecture <원본.json> <결과.html> --quality showcase --json
node /Users/shsmac/.agents/skills/archify/bin/archify.mjs visual-check <결과.html> --json
```

구조도·설명 문서만 작성했으므로 프로젝트의 Backend·Front·MCP 회귀 테스트와
실제 DB·Redis·LLM·Backend 통합 호출은 실행하지 않았다. 커밋·푸시는 하지 않았다.
