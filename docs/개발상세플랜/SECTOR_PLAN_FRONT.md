# Front 섹터 작업 지침서 (AI 마피아 MVP)

**대상 담당자:** Front 섹터 개발자 1인 (별도 시스템에서 개발 후 merge)
**상위 계약 문서:** [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
— 2장(API 명세)·7장(Front 계획)·8장(마일스톤)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 지침서보다 우선한다.

이 문서는 Front 섹터가 **자기 시스템에서 독립적으로 개발하고 통합 저장소에
merge하기까지**의 작업 단위, coding AI agent 사용 규칙, 중간 merge·테스트
체크포인트를 확정한다. 여기에 없는 작업 범위는 임의로 착수하지 않는다.

**적용 계약:** `ruleset_version=mystery-v1`, `scenario_version=scenario-v1`.
게임은 인간 1명을 포함한 6~9명이며 역할 식별자는
`MAFIA | DETECTIVE | DOCTOR | CITIZEN`만 사용한다. `DETECTIVE`의 한국어 표시명은
`탐정`이고 `POLICE`는 사용하지 않는다. 마피아가 2명이어도 팀원 목록·표시·진영
공유 이벤트를 Front에 전달하거나 추정하지 않는다.

Front가 처리할 Phase enum은 다음 목록과 철자만 허용한다.

```text
ROLE_REVEAL | DAY_ANNOUNCEMENT | DAY_DISCUSSION | NIGHT_ACTION |
NIGHT_RESOLUTION | DAY_VOTE | DAY_REVOTE | VOTE_RESOLUTION |
FINAL_DISCUSSION | FINAL_VOTE | FINAL_RESOLUTION | FINISHED
```

첫날은 `round=0`의 안내·좌석순 발언 1순환 뒤 투표 없이 밤으로 전환한다.
각 발언은 200자 이하의 `SPEAK` 또는 `PASS`이고, 기본 순환에서 전원이 `PASS`한
경우에만 고정 질문 뒤 추가 1순환을 표시한다. 밤 행동은 20초, 일반·재·최종 투표는
각 30초의 서버 권위 deadline을 따른다. Front 카운트다운은 안내용이며 상태 전이,
자동 선택과 `FINAL_*` 급사 판정은 Backend 응답만 신뢰한다.

---

## 1. 소유 경계와 금지 사항

### 1.1 수정 허용 (이 섹터의 소유)

```text
frontend_user/**        (단, auth/·기존 login 흐름은 1.3 참고)
frontend_admin/**
```

### 1.2 수정 금지 (다른 섹터 소유)

```text
backend/**              → Backend 섹터
mcp_server/**           → MCP 섹터
```

Backend 계약(요청·응답 형식)에 문제가 있으면 코드를 고치지 말고 구현
계획서 9장의 계약 변경 절차(문서 diff 공유 → 합의 → 반영)를 따른다.

### 1.3 조건부 수정 (사전 고지 필요)

- `frontend_user/app.py`, `app_pages/login_page.py`: 로그인 후 홈 라우팅
  연결에 필요한 **최소 수정만** 허용. 기존 OIDC 로그인·오류 처리 동작을
  바꾸지 않는다.
- `frontend_user/core/api_client.py`: 기존 identity 서명 로직은 수정하지
  않는다. 게임 API는 신규 파일 `core/game_api.py`에 분리 구현한다.
- 공유 파일(`pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`):
  수정 시 다른 섹터에 즉시 고지한다.

### 1.4 신규 파일 (승인된 구조 변경 범위 — 이 목록이 전부다)

```text
frontend_user/app_pages/home_page.py
frontend_user/app_pages/game_create_page.py
frontend_user/app_pages/game_play_page.py
frontend_user/app_pages/game_load_page.py
frontend_user/app_pages/game_result_page.py
frontend_user/core/game_api.py
frontend_user/core/game_view.py
frontend_user/components/game_ui.py
frontend_user/tests/test_game_api.py
frontend_user/tests/test_game_view.py
frontend_user/tests/test_game_pages_smoke.py
frontend_admin/app_pages/kpi_page.py
frontend_admin/app_pages/logs_page.py
frontend_admin/app_pages/feedback_page.py
frontend_admin/core/admin_api.py
frontend_admin/tests/__init__.py
frontend_admin/tests/test_admin_api.py
frontend_admin/tests/test_admin_pages_smoke.py
```

이 밖의 파일·디렉터리 생성이 필요하면 착수 전에 이 문서와 구현 계획서를
먼저 갱신하고 합의를 받는다(AGENTS.MD 구조 규칙).
`mystery-v1`·`scenario-v1` 반영은 위 승인 목록 안에서 수행하며 신규 Front 파일을
추가하지 않는다.

---

## 2. 별도 시스템 작업 환경 구성

각 담당자는 자기 시스템에서 다음 순서로 환경을 만든다.

```bash
git clone <repo-url> && cd Team4_Proj_0831
git checkout -b feat/front-<기능이름>        # 예: feat/front-game-pages
uv sync --dev
cp .env.example .env && chmod 600 .env       # 기존 .env 있으면 덮어쓰지 않음
uv run pytest                                 # baseline 70개+ 통과 확인
```

- Front 개발은 **Backend·MCP·PostgreSQL·Redis 없이 진행 가능**해야 한다.
  모든 화면·클라이언트는 fake transport(WU-F1)로 개발·테스트한다.
- 실제 Backend 연동 환경의 PostgreSQL·Redis 구축·기동은 MCP 섹터가 담당한다.
  Front 담당자는 DB·Redis를 직접 설치·실행하거나 접속하지 않는다.
- OIDC secrets는 화면 수동 확인 시에만 필요하다. 실제
  `secrets.toml`·`.env`는 절대 커밋하지 않는다.
- 통합 확인 단계(CP-2 이후)에서만 Backend 프로세스를 로컬 기동한다.

### 2.1 브랜치·merge 규칙

- 작업 브랜치: `feat/front-<기능>` — WU(작업 단위) 1~2개 규모로 유지한다.
- merge 대상: 통합 브랜치 `develop`. **`main` 직접 커밋·푸시 금지.**
- merge 전 필수: `develop`을 자기 브랜치로 rebase 또는 merge해 충돌을
  자기 쪽에서 해소하고, 3.4의 검증 명령을 모두 통과시킨다.
- 커밋은 사용자(팀) 승인 후에만 만들고, 커밋 메시지는 AGENTS.MD 형식
  (목적/범위/검증)을 지킨다.

---

## 3. Coding AI Agent 사용 규칙 (필수)

이 섹터에서 coding AI agent(Claude, Codex 등)를 사용할 때 다음을 강제한다.

1. **한 번에 모든 구현을 지시하는 것을 금지한다.** 한 세션(또는 한 지시)의
   범위는 아래 4장의 WU(작업 단위) **1개 이하**로 제한한다.
2. 작업 범위는 이 문서 4장의 WU 정의로 확정한다. agent가 범위 밖 파일을
   수정하거나 새 파일을 제안하면 중단하고 범위를 재지시한다.
3. agent에게 작업을 지시할 때 다음을 프롬프트에 반드시 포함한다:
   - 이 지침서와 [AGENTS.MD](../../AGENTS.MD)를 먼저 읽을 것
   - 해당 WU의 "범위 파일" 밖 수정 금지
   - 완료 기준과 검증 명령(3.4)
4. agent 산출물은 merge 전에 사람이 diff 전체를 검토한다. 특히:
   비밀정보 포함 여부, escape 누락, 범위 밖 변경, 주석 한국어 여부.
5. agent가 생성한 테스트가 실제 동작을 검증하는지 확인한다(항상 통과하는
   무의미한 테스트 금지).
6. 하나의 WU가 끝나면 검증 → 사람 검토 → (승인 시) 커밋 후에 다음 WU를
   시작한다. WU를 건너뛰거나 병합하지 않는다.

### 3.4 WU 공통 검증 명령

```bash
uv run pytest frontend_user/tests frontend_admin/tests   # focused
uv run ruff check frontend_user frontend_admin
uv run python -m compileall -q frontend_user frontend_admin
# merge 직전에만 전체 회귀:
uv run pytest
```

테스트는 mock/fake transport만 사용한다. 실제 Backend·Google·유료 API를
자동 테스트에서 호출하지 않는다.

---

## 4. 작업 단위(WU) 분해

각 WU는 coding AI agent 1세션 규모다. 순서를 지키고, 선행 WU 미완료 상태로
착수하지 않는다. 특히 F1~F6은 공유 파일이 있더라도 합쳐 지시하지 않고, 각 WU의
범위와 완료 기준만 한 세션에 수행한다.

### WU-F1. 게임 API 클라이언트 + fake transport

- **범위 파일:** `frontend_user/core/game_api.py`,
  `frontend_user/tests/test_game_api.py`
- **내용:** 구현 계획서 2장 `mystery-v1`·`scenario-v1` 명세 그대로의 API
  클라이언트와 fake 계약을 만든다.
  - 기존 `api_client.py`의 HMAC 서명 패턴을 재사용하되 게임 API용
    canonical(`timestamp.request_id.acting_user_id.raw_body`, GET은
    raw_body 빈 문자열)을 구현한다.
  - 생성·저장 목록·재개·GameStateView·명령·SSE·결과·피드백 8개 사용자 API를
    구현하고, 모든 변경 명령에 `expected_version`과 `idempotency_key`를 전달한다.
  - 2.0의 오류 코드 13종을 예외 타입으로 변환한다. 특히
    `GAME_STATE_CONFLICT`, `ACTION_ALREADY_SUBMITTED`,
    `ACTION_DEADLINE_EXPIRED`, `CONTRACT_VERSION_MISMATCH`를 구별한다.
  - transport 주입이 가능해야 하며, 테스트·후속 WU가 쓸
    **FakeGameTransport**를 같은 파일 또는 테스트 모듈에 제공한다. fake는
    6~9명 역할표, `round=0`, 정확한 Phase enum, 공개 시나리오, 본인 개인 정보,
    deadline과 `FINAL_*` 정상·오류 응답을 재현한다.
  - fake 응답에도 타인 역할·알리바이·관찰, 마피아 팀원, 비공개 야간 행동과
    개별 진행 중 투표를 넣지 않는다.
- **완료 기준:** 사용자 API 8종 + 공통 오류 13종 매핑, HMAC canonical,
  idempotency 재전송 테스트 통과. 실제 네트워크 호출 0회.

### WU-F2. GameStateView 표시 모델

- **범위 파일:** `frontend_user/core/game_view.py`,
  `frontend_user/tests/test_game_view.py`
- **내용:** 2.3 응답 JSON을 화면용 불변 모델로 파싱·검증한다.
  - `ruleset_version=mystery-v1`, `scenario.scenario_version=scenario-v1`, 6~9명,
    `DETECTIVE`와 이 문서 서두의 Phase enum만 허용한다.
  - 공개 `scenario`의 ID·제목·배경·피해자·장소·게임 목표를 보존한다. 생존 중인
    본인의 `you`에는 역할·생존·알리바이·관찰을 별도 필드로 보존한다.
    관찰은 `text`, 다른 현재 좌석인 `target_seat` 또는 `null`, `anonymous`를
    검증하고 대상형(`target_seat` 있음/anonymous=false)과 익명형
    (`target_seat=null`/anonymous=true) 외 조합을 거부한다.
  - 공개 `initial_mafia_count`를 보존하되 현재 생존 마피아 수나 정체를 추정하는
    파생 필드는 만들지 않는다.
  - `discussion.cycle/current_speaker_player_id/fixed_question`,
    `phase_timing.server_time/deadline_at/duration_seconds`, `your_submission`,
    `allowed_commands`, PUBLIC `timeline`과 본인 `private_events`를 검증한다.
  - 인간이 사망하고 아직 `FINISHED`가 아니면 `you`에는 식별자·좌석·
    `alive=false`만 허용하고 역할·알리바이·관찰은 없어야 한다. 이 관전 변형에서는
    `private_events=[]`, `your_submission=null`과 행동 명령 부재를 요구한다.
  - 각 alive/관전 변형에서 필수인 필드의 누락, 잘못된 enum·버전, 음수
    sequence·seat, timezone 없는 시각과
    현재 Phase에 맞지 않는 deadline을 fail-closed로 처리한다.
  - 타인의 `revealed_role`은 낮 처형으로 공개된 경우만 표시 모델에 유지하고,
    밤 사망자는 반드시 `null`이어야 한다. 마피아 사용자에게도 팀원 필드를
    만들거나 다른 마피아를 추정하지 않는다.
- **완료 기준:** 모든 Phase와 정상·비정상 payload 파싱 테스트 통과.
  `round=0` 첫날, `DETECTIVE` 표시명, 밤 사망 역할 숨김, 공개 시나리오 목표·
  최초 마피아 수와 자기 알리바이·관찰 보존을 검증하며 응답에 없는 정보를 채우는
  코드가 없어야 한다.

### WU-F3. 공통 게임 UI·카운트다운 컴포넌트

- **범위 파일:** `frontend_user/components/game_ui.py`,
  `frontend_user/tests/test_game_pages_smoke.py`(초안)
- **내용:** 순수 표시 컴포넌트로 타임라인, 좌석·생존자, 공개 시나리오,
  자기 역할·알리바이·관찰, 투표 집계, 행동 버튼, 저장 상태와 카운트다운 외형을
  구현한다.
  - 마피아 팀원 패널이나 진영 공유 표시는 만들지 않는다.
  - 관전 View에서 제거된 역할·알리바이·관찰을 빈 문자열이나 이전 session state로
    복원하지 않고 해당 개인 패널을 숨긴다.
  - 밤 사망자의 역할은 숨기고 낮 처형자의 `revealed_role`만 표시한다.
  - 투표 중에는 중간 표·개별 선택을 표시하지 않고 해소된 후보별 집계만 표시한다.
  - `SPEAK` 입력은 정규화 후 1~200자이며 `PASS`와 구분한다.
  - 카운트다운은 F6가 계산한 남은 초와 경고 수준을 입력으로 받는 표시 전용
    컴포넌트다. 스스로 Phase를 전환하거나 deadline을 확정하지 않는다.
  - 기존 `components/ui.py`의 패턴을 재사용해 **발언, 표시 이름, 시나리오,
    알리바이·관찰, 오류 상세 등 모든 외부 문자열을 HTML escape**한다.
- **완료 기준:** 악성 문자열 escape, 200자 경계, blind-mafia 무표시,
  밤 사망 역할 숨김, 집계만 공개와 카운트다운 상태 렌더링 테스트 통과.

### WU-F4. 홈·생성·불러오기 화면

- **범위 파일:** `frontend_user/app_pages/home_page.py`,
  `frontend_user/app_pages/game_create_page.py`,
  `frontend_user/app_pages/game_load_page.py`, `frontend_user/app.py`(라우팅 최소 수정),
  `frontend_user/tests/test_game_pages_smoke.py`
- **내용:** 7.2 규칙을 준수해 6~9명 생성, 저장 목록과 이어하기를 fake
  transport로 구현한다.
  - 인원 선택은 6~9만 허용하고 기본값은 6이다. 역할표는 6명 `1/1/1/3`,
    7명 `1/1/1/4`, 8명 `2/1/1/4`, 9명 `2/1/1/5` 순서로
    마피아/탐정/의사/시민 수를 정확히 안내한다.
  - `mystery-v1`과 `scenario-v1`을 표시하고 시나리오는 정적 카탈로그 5종 중
    사용자별 직전 생성 항목을 제외해 서버가 선택한다는 점을 설명한다.
  - 생성 전에는 실제 선택 시나리오, 역할, 알리바이·관찰을 미리 추정하거나
    노출하지 않는다. 생성 응답 뒤 공개 시나리오와 자기 정보만 보여준다.
  - 저장 목록에는 시나리오 제목, 인원, 생존자 수, Phase, round와 저장 시각을
    표시한다. 이어하기는 `expected_version`·새 idempotency key로 resume API를
    호출하고 성공 응답의 GameStateView를 사용하며, 충돌 시 최신 상태를 재조회한다.
- **완료 기준:** 5명 거부, 6~9 생성·역할표, 시나리오 안내, 저장 목록·이어하기
  smoke 테스트 통과. 기존 로그인 흐름 테스트 무손상.

### WU-F5. 진행·결과 화면

- **범위 파일:** `frontend_user/app_pages/game_play_page.py`,
  `frontend_user/app_pages/game_result_page.py`,
  `frontend_user/tests/test_game_pages_smoke.py`
- **내용:** Backend의 GameStateView와 `allowed_commands`만으로 진행·관전·결과
  화면을 렌더링한다. Front 전용 `ADVANCE_PHASE` 명령은 만들지 않는다.
  - `ROLE_REVEAL → DAY_ANNOUNCEMENT(round=0) → DAY_DISCUSSION(round=0)`에서
    공개 시나리오와 자기 역할·알리바이·관찰을 보여주고 첫날 투표 UI를 숨긴다.
  - 현재 발언 좌석에만 200자 이하 `SPEAK`와 `PASS`를 표시한다. 전원 PASS 뒤의
    고정 질문과 추가 1순환은 Backend의 `discussion`·PUBLIC 이벤트를 그대로
    렌더링하며 Front가 자체 판단해 추가하지 않는다.
  - 인간 사망 시 행동 컨트롤을 모두 숨기고 공개 정보만 보는 관전 모드와
    허용될 때만 `FAST_FORWARD`를 제공한다. `SAVE_AND_EXIT`도 허용 명령일 때만
    노출한다.
  - `FINAL_DISCUSSION → FINAL_VOTE → FINAL_RESOLUTION → FINISHED`를 별도 급사
    흐름으로 표시하고, 결과 화면에서 승리 진영·`finish_reason`, 전체 역할과
    종료 후 공개 가능한 야간·개별 투표 기록을 보여준다. 급사 결과는
    `FINAL_TARGET_MAFIA`와 `FINAL_TARGET_NON_MAFIA`를 구별해 설명한다.
  - 진행 중 투표는 후보별 확정 집계만, 밤 사망 역할은 숨기고 낮 처형 역할만
    표시한다. 새로 고침 시 `game_id`로 최신 상태를 재조회한다.
  - 오류 코드별 고정 안내를 제공한다. 409 상태 충돌·중복 제출은 최신 상태 재조회,
    503-AGENT는 재시도, 503-PERSISTENCE는 입력을 보존한 저장 실패 안내로 처리한다.
- **완료 기준:** first-day `round=0` 무투표, 일반·전원 PASS 추가 순환, 인간 사망
  관전·빠른 진행, 밤 사망 비공개, 낮 처형 공개, `FINAL_*` 양쪽 종료 사유와 오류
  경로의 fake smoke 테스트 통과.

### WU-F6. 서버 시간 동기화 + SSE/폴링 연동 계층

- **범위 파일:** `frontend_user/core/game_api.py`,
  `frontend_user/app_pages/game_play_page.py`, `frontend_user/tests/test_game_api.py`,
  `frontend_user/tests/test_game_pages_smoke.py`
- **내용:** 2.5 SSE를 구독하고 실패 시 `?since_sequence` 증분 폴링으로
  전환한다. 모든 전체·증분 응답의 `server_time`과 `deadline_at`으로 시계 차이를
  다시 계산하고 `agent_status=IDLE | THINKING | FALLBACK`을 표시한다.
  - `deadline_at`이 있는 `NIGHT_ACTION`은 10초, `DAY_VOTE`·`DAY_REVOTE`·
    `FINAL_VOTE`는 15초와 5초가 남을 때 경고한다. 경고는 각 threshold를 한 번만
    표시하며 deadline이 없는 토론 Phase에는 카운트다운을 만들지 않는다.
  - 브라우저 로컬 시각만으로 deadline을 연장·확정하지 않는다. SSE 재연결이나
    폴링 전환 뒤에도 새 `server_time` 기준으로 보정하고 이미 지난 경고를 반복하지 않는다.
  - `state_version`이 낮거나 sequence가 중복된 지연 이벤트는 무시한다. sequence
    공백을 발견하면 마지막 정상 sequence부터 증분 조회하고 필요하면 전체 상태를
    재조회한다.
  - 표시 카운트다운 0만으로 `allowed_commands`를 제거하거나 제출을 최종 차단하지
    않는다. Backend가 새 상태를 확정하기 전 사용자가 제출하면 같은 idempotency key로
    한 번 전송하고 성공·거부 응답을 따른다. 늦게 도착한 성공 응답은 반영하고
    `ACTION_DEADLINE_EXPIRED`, `ACTION_ALREADY_SUBMITTED`, `GAME_STATE_CONFLICT`는
    같은 idempotency key로 재전송하지 않은 채 최신 GameStateView를 조회한다.
- **완료 기준:** SSE 실패→폴링 전환, 브라우저 시계 오차 보정, 15·10·5초 경고
  1회, 중복·역순·sequence 공백, deadline 직전 지연 명령의 성공과 만료 거부,
  토론 Phase 무카운트다운 fake 테스트 통과.

### WU-F7. 관리자 API 클라이언트 + 3화면

- **범위 파일:** `frontend_admin/core/admin_api.py`, `kpi_page.py`,
  `logs_page.py`, `feedback_page.py`, `frontend_admin/tests/*`
- **내용:** 2.8 명세. 403 `ADMIN_ACCESS_DENIED` 시 기능 화면을 렌더링하지
  않는 fail-closed. 로그·피드백 표시값 escape.
- **완료 기준:** 403 fail-closed 거부 경로 테스트 **필수** 포함 통과.

### WU-F8. 실 Backend 연동 확인 (CP-2 체크포인트 작업)

- **범위 파일:** 버그 수정 한정 (신규 기능 금지)
- **내용:** 로컬에서 Backend(8000) 기동 후 실제 API로 생성→진행→저장→
  재개→결과 1회 수동 완주. 계약 불일치 발견 시 코드 수정이 아니라
  **계약 문서 이슈로 보고**가 우선.
- **완료 기준:** 수동 완주 기록(스크린샷·로그 아님, 텍스트 요약)과
  전체 회귀 통과.

---

## 5. 중간 merge·테스트 체크포인트

구현 계획서 8장 마일스톤과 대응한다. 각 CP에서 `develop`에 merge하며,
CP를 건너뛰고 대량 merge하는 것을 금지한다.

| 체크포인트 | 포함 WU | merge 전 필수 검증 | 통합 상대 |
|---|---|---|---|
| **CP-F0 계약 확인** | (코드 없음) | 2장 명세 리뷰 의견 제출 | 3인 합의 |
| **CP-F1 클라이언트 골격** | F1~F2 | focused + 전체 회귀 | 없음 (독립) |
| **CP-F2 화면 완성(fake)** | F3~F5 | 회귀 + 화면 수동 확인 | 없음 (독립) |
| **CP-F3 1차 통합** | F6, F8 | 회귀 + 실 Backend 수동 완주 | Backend CP-B3 + MCP CP-M1 이후 |
| **CP-F4 관리자** | F7 | 회귀 + 403 거부 경로 확인 | Backend CP-B5 이후 |

### 중간 테스트 규칙

- 각 WU 완료 시 focused 테스트, 각 CP merge 직전 전체 회귀(3.4)를 실행한다.
- CP-F3부터는 merge 후 `develop`에서 **통합 스모크**(Backend 기동 → 게임
  생성 API 1회 호출 성공)를 실행하고 결과를 팀에 공유한다.
- 다른 섹터 원인으로 실패하는 테스트는 임의 수정하지 않고 원인·영향만
  보고한다(AGENTS.MD).

---

## 6. 완료 보고 양식 (WU·CP 공통)

```text
[WU-F3 완료]
- 변경 파일: (목록)
- 실행 검증: uv run pytest frontend_user/tests → 12 passed / ruff OK
- 생략 검증과 이유: 전체 회귀는 CP merge 시 실행 예정
- 범위 밖 변경: 없음
- 계약 이슈: (있으면 구현 계획서 장·절 지목)
- README 갱신 필요 여부: (변경된 사용자 동작 유무)
```

README 갱신은 CP 단위로 모아서 해도 되지만, **merge 되는 시점의 README는
반드시 그 시점 구현과 일치**해야 한다(AGENTS.MD).
