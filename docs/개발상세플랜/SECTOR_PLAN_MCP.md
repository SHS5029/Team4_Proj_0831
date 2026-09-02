# MCP Server 섹터 작업 지침서 (AI 마피아 MVP)

**대상 담당자:** MCP 섹터 개발자 1인 (별도 시스템에서 개발 후 merge)
**상위 계약 문서:** [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
— 5장(내부 Engine API)·6장(MCP 계획)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 지침서보다 우선한다.

이 문서는 MCP 섹터가 별도 시스템에서 독립 개발하고 통합 저장소에 merge하기
까지의 작업 단위, coding AI agent 사용 규칙, 중간 merge·테스트 체크포인트를
확정한다. 이 서버의 존재 이유는 **정보 격리**다: 에이전트에게 허용되지 않은
정보가 Resource·Tool 결과·로그 어디에도 나타나지 않게 하는 것이 모든 작업의
1순위 완료 기준이다.

---

## 1. 소유 경계와 금지 사항

### 1.1 수정 허용 (이 섹터의 소유)

```text
mcp_server/mafia_game/**
```

### 1.2 수정 금지 (다른 섹터 소유)

```text
backend/**                            → Backend 섹터
frontend_user/**, frontend_admin/**   → Front 섹터
mcp_server/mcp_2/**                   → 용도 미정 예약, 건드리지 않음
```

Backend 내부 Engine API(5장)의 요청·응답이 계약과 다르면 Backend 코드를
고치지 말고 구현 계획서 9장 절차로 보고한다.
`mcp_server/mafia_game`은 `backend.*` 모듈을 **import하지 않는다**
(HTTP로만 통신). `mcp_2` 등 다른 MCP 패키지의 내부 모듈도 import 금지.

### 1.3 조건부 수정 (사전 고지 필요)

- 공유 파일(`pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`):
  수정 시 다른 섹터에 즉시 고지.
- `mcp_server/mafia_game/README.md`: 구현 진행에 맞춰 갱신(의무).

### 1.4 신규 파일 (승인된 구조 변경 범위 — 이 목록이 전부다)

```text
mcp_server/mafia_game/__main__.py
mcp_server/mafia_game/server.py
mcp_server/mafia_game/api/resources/game_resources.py
mcp_server/mafia_game/api/tools/game_tools.py
mcp_server/mafia_game/core/config.py
mcp_server/mafia_game/core/session.py
mcp_server/mafia_game/core/audit.py
mcp_server/mafia_game/services/context_service.py
mcp_server/mafia_game/services/action_service.py
mcp_server/mafia_game/ports/engine_port.py
mcp_server/mafia_game/integrations/engine/__init__.py
mcp_server/mafia_game/integrations/engine/client.py
mcp_server/mafia_game/integrations/engine/fake.py
mcp_server/mafia_game/schemas/contracts.py
mcp_server/mafia_game/tests/__init__.py
mcp_server/mafia_game/tests/test_resources.py
mcp_server/mafia_game/tests/test_tools.py
mcp_server/mafia_game/tests/test_session_isolation.py
mcp_server/mafia_game/tests/test_audit.py
```

기존 계층(`api/ services/ ports/ integrations/ core/ schemas/ domain/`)을
사용하며 새 최상위 디렉터리를 만들지 않는다. 이 밖의 파일이 필요하면 착수
전에 이 문서와 구현 계획서를 갱신·합의한다.

`tests/` 디렉터리 추가로 루트 `pyproject.toml`의 `testpaths` 갱신이
필요하면(`mcp_server/mafia_game/tests` 추가) 공유 파일 고지 규칙을 따른다.

---

## 2. 별도 시스템 작업 환경 구성

```bash
git clone <repo-url> && cd Team4_Proj_0831
git checkout -b feat/mcp-<기능이름>          # 예: feat/mcp-resources
uv sync --dev
cp .env.example .env && chmod 600 .env       # 기존 .env 있으면 덮어쓰지 않음
uv run pytest                                 # baseline 통과 확인
```

- **개발 전 구간을 Backend 없이 진행 가능**해야 한다. WU-M1에서 만드는
  `integrations/engine/fake.py`(계약 5장의 정상·거부 응답 시나리오 재현)가
  모든 후속 WU와 자동 테스트의 기본 의존성이다.
- 실제 Backend 연동(WU-M4)은 CP-B4 이후 로컬에서 Backend를 기동해 수동
  확인한다. 자동 테스트는 계속 fake만 사용한다.
- `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`은 `.env`에만 둔다.
  Front용 `INTERNAL_API_SECRET`을 재사용하지 않는다.

### 2.1 브랜치·merge 규칙

- 작업 브랜치: `feat/mcp-<기능>` — WU 1~2개 규모.
- merge 대상: `develop`. **`main` 직접 커밋·푸시 금지.**
- merge 전 `develop`을 자기 브랜치에 반영해 충돌을 해소하고 3.4 검증 통과.
- 커밋은 승인 후에만, 메시지는 AGENTS.MD 형식(목적/범위/검증).

---

## 3. Coding AI Agent 사용 규칙 (필수)

1. **한 번에 모든 구현 지시 금지.** 한 세션 범위는 4장 WU 1개 이하.
2. 작업 범위는 이 문서 4장 WU 정의로 확정한다. 범위 밖 파일 수정·신규 파일
   제안 시 중단하고 재지시한다.
3. 프롬프트에 반드시 포함: 이 지침서·AGENTS.MD 선독, WU 범위 파일 제한,
   완료 기준, 검증 명령(3.4), 한국어 주석, **격리 규칙(아래 4.0)**.
4. agent 산출물 diff를 사람이 전수 검토한다. 특히: Engine 응답을 schema
   검증 없이 그대로 통과시키는 코드, `agent_id`를 입력으로 받는 Tool,
   감사 로그에 비밀정보·전체 payload를 남기는 코드.
5. 무의미한 테스트 금지. 격리 테스트는 실제로 접근이 **거부**되는지
   확인해야 한다(응답 형태만 확인하는 테스트 불가).
6. WU 완료 → 검증 → 사람 검토 → (승인 시) 커밋 → 다음 WU. 건너뛰기 금지.

### 3.4 WU 공통 검증 명령

```bash
uv run pytest mcp_server/mafia_game/tests   # focused
uv run ruff check mcp_server
uv run python -m compileall -q mcp_server
# merge 직전에만 전체 회귀:
uv run pytest
```

---

## 4. 작업 단위(WU) 분해

### WU-M0. 격리 불변식 (모든 WU의 공통 완료 조건)

아래 항목은 각 WU 완료 기준에 자동 포함된다.

- Tool 입력으로 `agent_id`·`actor_id`·`session_id`를 받지 않는다.
  세션이 actor를 결정한다.
- `me` 이외의 agent를 지정하는 조회 경로를 제공하지 않는다.
- Engine 응답은 `schemas/contracts.py`로 검증 후 **허용 필드만** 반환한다.
  알 수 없는 필드는 통과시키지 않고 제거한다(allowlist 방식).
- 다른 게임·다른 세션의 capability로 접근하면 거부한다.
- 감사 로그에 비밀값·전체 프롬프트를 기록하지 않고, 에이전트가 감사
  로그를 조회할 수단을 만들지 않는다.
- Tool 노출 제한은 편의 기능일 뿐 권한 검사가 아니다. 최종 판정은 Backend
  (이중 검증)라는 전제를 코드 주석에 명시한다.

### WU-M1. 골격 + 계약 schema + fake 엔진

- **범위 파일:** `core/config.py`, `schemas/contracts.py`,
  `ports/engine_port.py`, `integrations/engine/__init__.py`,
  `integrations/engine/fake.py`, `tests/__init__.py`(빈 테스트 포함 가능)
- **내용:** env 로딩(secret 32자 검증, placeholder 거부 — backend
  `core/config.py`의 검증 패턴 참고하되 import하지 말고 자체 구현),
  5장 요청·응답 계약의 pydantic(또는 dataclass) 모델,
  Engine Protocol과 fake 구현(정상 7종 resource + accepted/거부 actions
  + 401/422 시나리오).
- **완료 기준:** contracts 검증 테스트(허용 외 필드 제거 포함) 통과.

### WU-M2. 세션·Resource 7종

- **범위 파일:** `core/session.py`, `services/context_service.py`,
  `api/resources/game_resources.py`, `server.py`, `__main__.py`,
  `tests/test_resources.py`
- **내용:** MCP 서버 생성(포트 8100), 세션 생성 시 `game_id`·`agent_id`·
  `session_id`·capability_token 고정, `me` 해석. 최종 플랜 8.2의
  Resource 7종을 fake 엔진 기반으로 제공.
- **완료 기준:** Resource 7종 정상 응답 + 세션 없는 접근 거부 테스트 통과.

### WU-M3. Tool 6종 + 감사 로그

- **범위 파일:** `services/action_service.py`, `api/tools/game_tools.py`,
  `core/audit.py`, `tests/test_tools.py`, `tests/test_audit.py`
- **내용:** `game.speak/vote/kill/investigate/protect/end_turn`.
  1차 검증(speak 길이 1~200·제어문자 제거, 대상 UUID 형식), `/actions`
  전달, `proposal_id` 생성, 거부 응답 정제(`reason_summary`만 노출).
  allowed-actions 기반 Tool 노출 제한. 모든 조회·호출 감사 기록.
- **완료 기준:** Tool 6종 정상·거부 경로, actor 위조 시도 거부(입력에
  actor 필드가 있으면 전달 전 차단), 감사 로그 필수 필드 기록 테스트 통과.

### WU-M4. 실제 Engine HMAC 클라이언트

- **범위 파일:** `integrations/engine/client.py`,
  기존 테스트 확장(mock transport)
- **내용:** 5장 인증(별도 secret, canonical `timestamp.request_id.raw_body`)
  으로 `/context`·`/actions` 호출. timeout, 오류를 MCP 응답으로 변환
  (Engine 5xx → 에이전트에는 "일시 불가"만, 내부 상세는 감사 로그로).
- **완료 기준:** mock transport로 서명 생성·오류 변환 테스트 통과.
  실제 네트워크 자동 테스트 0회.
- **CP-M3 병행 작업:** Backend CP-B4 이후 로컬 Backend를 기동해 실제
  왕복 1회 수동 확인. 계약 불일치는 코드 수정 전에 문서 이슈로 보고.

### WU-M5. 격리·감사 강화 (카나리)

- **범위 파일:** `tests/test_session_isolation.py`, 필요한 서비스 보강
- **내용:** 최종 플랜 12.1 검증 규칙의 MCP 측 구현.
  - 세션 A가 세션 B의 게임·agent Resource에 접근 시 거부
  - fake 엔진에 agent별 카나리 값을 심고, 다른 세션의 모든
    Resource·Tool 결과에서 카나리가 발견되지 않음을 확인
  - 비간섭성: B의 비공개 상태 변경 후 A의 Resource 응답 불변
- **완료 기준:** 카나리·비간섭성·교차 세션 거부 테스트 전부 통과.

---

## 5. 중간 merge·테스트 체크포인트

| 체크포인트 | 포함 WU | merge 전 필수 검증 | 통합 상대 |
|---|---|---|---|
| **CP-M0 계약 확인** | (코드 없음) | 5·6장 리뷰 의견 제출 | 3인 합의 |
| **CP-M1 골격** | M1 | focused + 전체 회귀 | 없음 (독립) |
| **CP-M2 Resource·Tool** | M2, M3 | 회귀 + 격리 불변식(4.0) 확인 | 없음 (독립) |
| **CP-M3 Engine 연동** | M4 | 회귀 + 실 Backend 수동 왕복 1회 | **Backend CP-B4 이후** |
| **CP-M4 격리 완성** | M5 | 회귀 + 카나리 테스트 | Backend CP-B5와 함께 CP-ALL |

### 중간 테스트 규칙

- WU마다 focused, CP merge 직전 전체 회귀(3.4).
- CP-M3 merge 후 `develop`에서 통합 스모크(Backend 기동 → MCP 기동 →
  Resource 1종 조회 성공)를 실행하고 결과를 Backend 담당자와 공유한다.
- Backend 원인 실패는 임의 수정하지 않고 원인·영향만 보고.

---

## 6. 고위험 항목 (AGENTS.MD 테스트 규칙 직접 적용)

이 서버의 핵심 기능 자체가 보안 경계이므로, 다음은 **구현과 동시에 거부
경로 테스트를 작성**한다.

- 세션 위조·교차 세션 접근·타 게임 capability 사용 거부
- actor 관련 입력 필드 차단
- Engine 응답 allowlist 필터(모르는 필드 미통과)
- 감사 로그의 민감정보 부재
- Engine 장애 시 에이전트에게 내부 상세 미노출

## 7. 완료 보고 양식 (WU·CP 공통)

```text
[WU-M3 완료]
- 변경 파일: (목록)
- 실행 검증: uv run pytest mcp_server/mafia_game/tests → NN passed / ruff OK
- 격리 불변식 확인: (4.0 항목별 해당 테스트 이름)
- 생략 검증과 이유: 실 Backend 왕복은 CP-M3에서 수행 예정
- 범위 밖 변경: 없음
- 계약 이슈: (있으면 구현 계획서 장·절 지목)
- README 갱신 필요 여부: (실행 방법·env 변경 유무)
```
