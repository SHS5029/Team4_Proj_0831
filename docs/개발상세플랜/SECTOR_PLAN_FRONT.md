# Front 섹터 작업 지침서 (AI 마피아 MVP)

**대상 담당자:** Front 섹터 개발자 1인 (별도 시스템에서 개발 후 merge)
**상위 계약 문서:** [상세 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
— 2장(API 명세)·7장(Front 계획)·8장(마일스톤)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 지침서보다 우선한다.

이 문서는 Front 섹터가 **자기 시스템에서 독립적으로 개발하고 통합 저장소에
merge하기까지**의 작업 단위, coding AI agent 사용 규칙, 중간 merge·테스트
체크포인트를 확정한다. 여기에 없는 작업 범위는 임의로 착수하지 않는다.

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
착수하지 않는다.

### WU-F1. 게임 API 클라이언트 + fake transport

- **범위 파일:** `frontend_user/core/game_api.py`,
  `frontend_user/tests/test_game_api.py`
- **내용:** 구현 계획서 2장 명세 그대로의 클라이언트.
  - 기존 `api_client.py`의 HMAC 서명 패턴을 재사용하되 게임 API용
    canonical(`timestamp.request_id.acting_user_id.raw_body`, GET은
    raw_body 빈 문자열)을 구현한다.
  - 2.0의 오류 코드 표를 예외 타입으로 변환한다(코드별 분기 가능하게).
  - transport 주입이 가능해야 하며, 테스트·후속 WU가 쓸
    **FakeGameTransport**(정상·각 오류 응답 시나리오)를 같은 파일 또는
    테스트 모듈에 제공한다.
- **완료 기준:** 2장 엔드포인트 7종 + 오류 9종 매핑 테스트 통과.
  실제 네트워크 호출 0회.

### WU-F2. GameStateView 표시 모델

- **범위 파일:** `frontend_user/core/game_view.py`,
  `frontend_user/tests/test_game_view.py`
- **내용:** 2.3 응답 JSON을 화면용 모델로 파싱·검증. 누락 필드,
  잘못된 enum, 음수 sequence 등 방어적 처리. Phase·Command enum 상수 정의.
- **완료 기준:** 정상·비정상 payload 파싱 테스트 통과.
  **응답에 없는 정보(타인 역할 등)를 추정해 채우는 코드가 없어야 한다.**

### WU-F3. 공통 게임 UI 컴포넌트

- **범위 파일:** `frontend_user/components/game_ui.py`,
  `frontend_user/tests/test_game_pages_smoke.py`(초안)
- **내용:** 타임라인, 좌석/생존자 패널, 행동 버튼 그룹, 저장 상태 표시.
  기존 `components/ui.py`의 escape 패턴 재사용 — **모든 발언·표시 이름은
  렌더링 전 HTML escape** (마피아 발언에 스크립트가 섞여도 안전해야 한다).
- **완료 기준:** escape 검증 테스트(악성 문자열 입력) 포함 통과.

### WU-F4. 홈·생성·불러오기 화면

- **범위 파일:** `home_page.py`, `game_create_page.py`, `game_load_page.py`,
  `frontend_user/app.py`(라우팅 최소 수정), smoke 테스트 갱신
- **내용:** 7.2 규칙 준수. 인원 5~9 선택(기본 6)과 역할표 안내,
  저장 목록(2.2 응답), 이어하기. fake transport로 동작.
- **완료 기준:** smoke 테스트 통과, 로그인 흐름 기존 테스트 무손상.

### WU-F5. 진행·결과 화면

- **범위 파일:** `game_play_page.py`, `game_result_page.py`, smoke 테스트
- **내용:** GameStateView 기반 렌더링, `ADVANCE_PHASE` 버튼형 턴제,
  허용 명령만 버튼 노출, 관전·`FAST_FORWARD`, `SAVE_AND_EXIT`,
  결과 화면(2.6)과 피드백 제출(2.7). 새로 고침 시 `game_id` 재조회.
  오류 코드별 고정 안내(409 새로고침 / 503-AGENT 재시도 / 503-PERSISTENCE
  저장 실패·입력 보존).
- **완료 기준:** fake 시나리오(정상 진행, 각 오류, 인간 사망 관전)
  smoke 테스트 통과.

### WU-F6. SSE/폴링 연동 계층

- **범위 파일:** `game_api.py`·`game_play_page.py` 확장, 관련 테스트
- **내용:** 2.5 SSE 구독, 실패 시 `?since_sequence` 증분 폴링 폴백.
  `agent_status`(THINKING 등) 표시.
- **완료 기준:** SSE 실패→폴링 전환 테스트(fake) 통과.

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
| **CP-F3 1차 통합** | F6, F8 | 회귀 + 실 Backend 수동 완주 | Backend CP-B3 이후 |
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
