# AI 마피아 merge 이후 게임 테스트 준비·재점검

작성일: **2026-09-07** · 기준: **Hwanseok / merge `3157f17`**

이 문서는 이전 `5292c2a` 기준의 31개 미완료 항목을 새 merge 코드와 대조한 결과다.
착수 시 Git 작업 트리는 깨끗했다. 이번에는 의존성·가상환경·로컬 터미널 설정과
문서만 변경했으며 게임 기능은 수정하지 않았다.

**Python 테스트 환경은 준비되었고 외부 서비스 없는 테스트 171개가 통과했다.**
PostgreSQL 기본 실행 경로·AI worker·최소 FastMCP 연결은 이전보다 진행되었지만,
정보 격리·일부 규칙·마감 처리·Front 재개 공백 때문에 실제 게임 전체 테스트의
완료를 선언할 수는 없다. 아래 코드 판정과 실제 실행한 검증을 구분한다.

## 1. 이번 merge로 바뀐 판정

현재 기준은 [마스터플랜](개발상세플랜/AI_MAFIA_MASTER_PLAN.md) 상단의
**MVP 단순화·최소 FastMCP 프로파일**이다. custom bootstrap/HMAC/capability/session
registry, 복잡한 reconnect/backoff, Redis publisher 자동 실행은 현 MVP 요구사항에서
제외한다. 기존 M2~M5 복원을 미구현 과제로 다시 올리지 않는다.

| 이전 항목 | merge 이후 판정 | 현재 근거·한계 |
|---|---|---|
| D02 · 공개 게임 메모리 저장 | **기본 연결 해결** | [main.py](../backend/app/main.py) L115의 PostgreSQL runtime이 생성·목록·snapshot·저장·재개·행동·feedback을 담당한다. 관리자도 PostgreSQL을 사용한다. 실제 재시작·다중 프로세스 복구는 이번에 실행하지 않았다. |
| G11 · 카탈로그·개인 단서 미연결 | **기본 연결 해결** | [creation_service.py](../backend/app/services/game/creation_service.py) L122~178에서 직전 시나리오 제외·seed 선택·persona·좌석별 단서를 만든다. 제품 콘텐츠 승인은 별도 확인 사항이다. |
| D01 · 정상 seed도 실패하는 SQL | **코드 수정 확인** | [004 seed SQL](../backend/migrations/004_seed_scenarios_and_personas.sql) L361~379가 `count FILTER`로 바뀌었다. 실제 migration 최초·재실행은 미검증이다. |
| G01 · AI worker·실제 호출 없음 | **부분 해결** | [main.py](../backend/app/main.py) L48~59에서 worker를 관리하고 [postgres_runtime.py](../backend/app/services/game/postgres_runtime.py) L184~210, L247~293에서 MCP·Provider를 호출한다. GM 진행과 아래 AI 정보 격리는 남았다. |
| G02 · 조회마다 deadline 재설정 | **시간 계산·저장/재개 개선** | [action_timer_service.py](../backend/app/services/game/action_timer_service.py)의 밤 20초·투표 30초와 DB deadline 기반 잔여 시간·pause/resume을 사용한다. 만료 검증·해소 공백은 아래 표 참조. |
| G05 · 최종 토론 진입 불가 | **토론 경로 연결** | [discussion_transaction.py](../backend/app/services/game/discussion_transaction.py) L55~78에 최종 토론을 연결했다. 최종 지목은 여전히 첫 한 표로 판정한다. |
| F03 · SSE 1회 종료·재접속 없음 | **부분 해결** | Backend 지속 stream, Front 1초 재연결·변경 후 GET·sync 실패 시 GET 복구가 추가됐다. 지속 polling·visibility 복귀·중복 제거 등은 남았다. |
| M01~M05 · 구 MCP 계약 | **기존 프로파일 기준 판정 폐기** | 실제 FastMCP Resource template·Prompt·Tool·HTTP adapter가 있다. 현 문제는 actor context·응답 envelope·운영 Tool 연결이며 구 bootstrap 5-field 복구가 아니다. |
| D04~D05 · 운영 감사 sink·배포 TLS | **현 최소 프로파일 필수 범위에서 제외** | loopback 개발 프로파일이다. 사설망/운영 배포 범위 확대 시 별도 계약으로 다룬다. |
| 나머지 Front·규칙·정보 항목 | **대체로 잔존** | 특히 RESUME 화면, UUID 복구 저장, 조사·결과 상세, 2명 마피아·재투표·최종 판정은 아래 표에 갱신했다. |

## 2. 실제 게임 테스트 전 우선 확인할 공백

P0는 핵심 진행·판정·비공개 정보 경계를 막는 항목, P1은 주요 표시·복구·운영 준비
보완이다. 근거 행 번호는 merge 시점 기준이며, 테스트에서 해당 결함을 재현했다는
표시가 없는 행은 **정적 코드 조사 결과**다.

| ID·우선 | 테스트 장면 | 현재 남은 문제 | 근거·담당 |
|---|---|---|---|
| N01 · P0 | AI가 자신의 역할·단서만 받아 추론 | MCP가 인간 소유자 snapshot을 반환하고 Orchestrator가 같은 응답을 public/me/turn/persona에 재사용한다. 인간 `me.role/alibi/observation`이 AI Provider 입력에 들어가는 데이터 흐름이 있다. actor별 projection을 분리해야 한다. 실제 Provider 호출로 검증하지 않았다. | [mcp_registry_router.py](../backend/app/routers/mcp_registry_router.py) L39~40; [orchestrator.py](../backend/app/agent/orchestrator.py) L109~118, L175; [game_read_service.py](../backend/app/services/game/game_read_service.py) L330~337 · Backend/MCP |
| N02 · P0 | 밤 행동·개별 투표를 종료 전 비공개로 유지 | 인간 행동 제출 직후 `ACTION_RESOLVED`를 PUBLIC으로 기록하면서 `target_player_id`를 포함하고 sync에 그대로 전달한다. 해소 전 개별 선택이 공개 이벤트에 실리는 경로를 수정해야 한다. | [action_command.py](../backend/app/services/game/action_command.py) L165, L581~590; [event_sync_service.py](../backend/app/services/game/event_sync_service.py) L46~55 · Backend |
| N03 · P0 | 실제 Resource 조회 후 `submit_action` Tool로 행동 승인 | Backend는 `{status,source,context:snapshot}`을 반환하지만 client는 최상위 game/action_window를 찾는다. version/window가 빠질 구조다. Tool·Prompt는 등록됐으나 운영 worker는 Resource→Provider→Backend 직접 실행 경로를 주로 사용한다. Tool 미구현과 운영 미연결을 구분해야 한다. | [client.py](../backend/app/mcp/client.py) L132~171; [postgres_runtime.py](../backend/app/services/game/postgres_runtime.py) L269~289 · Backend/MCP |
| N04 · P0 | 마감 후 제출 거부·무응답 투표 자동 해소 | deadline 계산은 있으나 window 검증에 현재 시각 비교가 없고 worker에 투표 만료 해소가 없다. 밤 만료 해소는 잠금 뒤 deadline 재검사와 기존 제출 복원이 빠져 이미 제출한 선택을 무시할 수 있다. | [window_service.py](../backend/app/services/game/window_service.py) L54~83; [ai_progress_worker.py](../backend/app/services/game/ai_progress_worker.py) L57~153; [action_command.py](../backend/app/services/game/action_command.py) L285~310 · Backend |
| N05 · P0 | 마피아 2명 공격·동률 재투표·전원 최종 지목 | 두 번째 마피아 공격 거부, 재투표 후보 집합 미보존, 첫 한 명의 최종 선택으로 즉시 승패를 정하는 규칙이 남았다. 최종 토론의 공개 연결은 개선됐지만 최종 다수결·동률 RNG는 별개다. | [night.py](../backend/app/game_engine/phases/night.py) L41~44; [vote.py](../backend/app/game_engine/phases/vote.py) L51~56; [final_accusation.py](../backend/app/game_engine/phases/final_accusation.py) L19~35 · Backend |
| N06 · P0 | 저장 게임을 화면에서 재개 | Backend RESUME는 연결됐고 Front command enum도 있지만, SAVED 전용 화면·RESUME 제출 UI는 없다. 홈의 계속하기는 game 화면 이동만 수행한다. | [app.py](../frontend_user/app.py) L91; [home_page.py](../frontend_user/app_pages/home_page.py) L159; [commands.py](../frontend_user/core/commands.py) L34 · Front |
| N07 · P1 | 탐정 조사·사망/처형·대화 이력·종료 복기 | snapshot private_events는 빈 배열이고 조회 시 공개 이벤트 이력을 복원하지 않는다. 탈락 원인은 해소 후 phase를 기록하며 result는 기본 승패·역할 위주다. Front도 조사 상세·득표수·개별 행동/발언 복기가 불완전하다. | [game_read_service.py](../backend/app/services/game/game_read_service.py) L108~170, L337; [result_service.py](../backend/app/services/game/result_service.py) L16~29; [game_page.py](../frontend_user/app_pages/game_page.py) L464, L566, L605; [result_page.py](../frontend_user/app_pages/result_page.py) L201~248 · Backend/Front |
| N08 · P1 | 무응답 fallback·관전 빠른 진행 | 의사 자동 보호 후보에 본인을 포함하며 자동투표는 숨겨진 역할로 비마피아를 우선한다. 빠른 진행은 선택 상태 저장 대신 즉시 전체 진행, enabled는 인간 사망 여부로 표시한다. 사망 뒤 worker 진행 경로 자체는 추가됐다. | [fallback.py](../backend/app/game_engine/fallback.py) L17~19, L39~43; [action_command.py](../backend/app/services/game/action_command.py) L484; [game_read_service.py](../backend/app/services/game/game_read_service.py) L325 · Backend |
| N09 · P1 | SSE 장애·백그라운드 복귀·같은 batch 재수신 | 단순 재연결은 추가됐으나 지속 polling·visibility 처리가 없고 reducer가 마지막 sequence/index 0을 재적용할 수 있다. schema_version 검사도 없다. Backend SSE `id:`도 없어 Front의 cursor 처리와 함께 검증해야 한다. | [sync/index.js](../frontend_user/components/browser_components/sync/index.js) L19~67; [sync.py](../frontend_user/core/sync.py) L51~61, L139; [game_router.py](../backend/app/routers/game_router.py) L154~178 · Front/Backend |
| N10 · P1 | UUID 복구·홈 목록·countdown·응답 유실 재시도 | UUID 교체는 session만 바꾸고 localStorage는 갱신하지 않는다. 홈 cache/완료 목록/탭·최대 두 카드 제한, 정적 countdown, 생성·시작·저장 결과 불명 요청의 key 보존 공백이 남았다. | [settings_page.py](../frontend_user/app_pages/settings_page.py) L35; [session.py](../frontend_user/core/session.py) L30; [home_page.py](../frontend_user/app_pages/home_page.py) L58~143; [action_panel.py](../frontend_user/components/action_panel.py) L451, L513; [game_page.py](../frontend_user/app_pages/game_page.py) L760 · Front |
| N11 · P1 | 일반 피드백·관리자 조작·생성 참가자 표시 | 일반 피드백 폼 진입 UI, 관리자 UUID 입력·필터·주소 전달, 실제 참가자 이름 연결이 남았다. 관리자는 README의 개발자 도구 UUID→allowlist 등록으로 수동 접근할 수 있으므로 접근 자체가 불가능한 것은 아니다. | [home_page.py](../frontend_user/app_pages/home_page.py) L75; [frontend_admin/app.py](../frontend_admin/app.py) L34~65; [creation_complete_page.py](../frontend_user/app_pages/creation_complete_page.py) L8~38 · Front |
| N12 · P1 | Prompt 기본 인자·MCP 행동 성공 검사 | Prompt 생략 인자를 빈 문자열 UUID query로 보내므로 실제 Backend 422가 예상된다. process 통합 테스트는 Tool 오류 문자열도 통과시켜 실제 행동 승인 증거가 부족하다. | [MCP prompt](../mcp_server/mafia_game/api/prompts/__init__.py) L14~19; [engine_http.py](../mcp_server/mafia_game/integrations/engine_http.py) L86~92; [process test](../mcp_server/tests/test_process_backend_roundtrip.py) L170~193 · MCP/Backend |
| N13 · P1 | migration 계정·암호화 설정 확인 | runner는 여전히 runtime effective DSN을 사용한다. keyring이 없으면 runtime은 legacy_plaintext를 선택한다. 테스트 전 전용 DB·DDL/DML 대상과 keyring 준비를 확인해야 하며 항상 암호화된다고 가정하면 안 된다. | [migrations.py](../backend/app/infrastructure/migrations.py) L38; [postgres_runtime.py](../backend/app/services/game/postgres_runtime.py) L58~62; [game_repository.py](../backend/app/repositories/game_repository.py) L54~63 · Backend/Data |

<a id="frontend-text-contrast"></a>

### N14 · P1 · Frontend 수정 요청: 검은 버튼·텍스트 영역의 글자 가독성

**등록일:** 2026-09-07 · **상태:** 사용자 제보 접수, 미수정 · **담당:** Frontend

| 항목 | 전달 내용 |
|---|---|
| 사용자 제보 | 검은색 버튼과 텍스트 영역에서 글자가 보이지 않거나 읽기 어렵다. Frontend에서 해당 색상 조합을 수정하고 유사 영역도 확인한다. |
| 대표 위치 | 사용자 앱 `http://127.0.0.1:8501/` → 게임별 피드백 완료/이미 제출 안내 → **결과 화면으로** 버튼. [feedback_page.py](../frontend_user/app_pages/feedback_page.py)의 `_render_terminal` 참고. |
| 제공된 브라우저 근거 | `.st-key-feedback-terminal` 내부 버튼의 label `div`에 텍스트가 존재하며 `font-size: 16px`, `color: rgb(23, 32, 51)`(`#172033`)로 계산된다. 사용자는 버튼 배경이 검다고 보고했다. 첨부 정보에는 실제 버튼 배경색과 textarea의 computed style이 없어 색상 대비 수치·모든 발생 위치는 아직 확정하지 않았다. |
| 요소 식별 | `.st-key-feedback-terminal [data-testid="stButton"] button` 안의 **결과 화면으로** 텍스트. 생성된 `st-emotion-cache-*` 클래스보다 화면 key·testid·버튼 문구로 위치를 찾는다. |
| 원인 점검 후보 | [feedback_page.py](../frontend_user/app_pages/feedback_page.py)의 `--feedback-ink`가 label 색과 일치한다. terminal 컨테이너만 흰 배경이고 기본 버튼 자체의 배경·글자색 조합은 지정되지 않았다. [theme.py](../frontend_user/components/theme.py)의 공통 버튼·textarea 스타일, 페이지 CSS 상속, Streamlit 밝은/어두운 테마의 우선순위를 함께 확인한다. **원인 확정 전 점검 후보**다. |
| 수정 범위 | 검은 배경의 버튼 label과 텍스트/입력 영역에서 글자가 구별되도록 배경색·글자색을 함께 정리한다. 피드백 입력 textarea의 입력문자·placeholder·커서·label 및 같은 공통 스타일을 사용하는 다른 사용자 화면도 확인한다. |
| 완료 기준 | 밝은/어두운 테마에서 버튼의 기본·hover·focus·disabled 상태와 텍스트 영역의 일반·focus·disabled 상태를 직접 확인한다. 입력값·placeholder가 읽히고 focus가 구별되어야 한다. 피드백 성공/중복 안내와 **결과 화면으로** 이동 동작을 유지한다. |
| 검증 증거 | 수정 전후 같은 화면·테마의 캡처와 실제 버튼 배경/label, textarea 배경/글자 computed style을 남긴다. 사용자 제보 위치 외 유사 영역의 확인 결과도 기록한다. |

이번 추가 요청은 **수정 지시를 문서에 남기는 범위**로 처리했다. 첨부 DOM과 관련
스타일 코드·[화면 정본의 접근성 원칙](개발상세플랜/AI_MAFIA_SCREEN_FLOW.md#18-접근성반응형)을
대조했으며 Frontend 코드 변경·브라우저 재현·자동 테스트는 수행하지 않았다.
아래 171개 통과 기록은 이전 환경 준비 결과이며 이 시각 결함의 해결 증거가 아니다.

## 3. 가상환경·의존성 준비 결과

| 환경 | 상태 | 확인 |
|---|---|---|
| 루트 `.venv` | 기존 Python 3.12.11 재사용, `uv sync --locked --dev` | merge 후 stale lock을 갱신하고 루트 dev에 Backend TestClient용 httpx2 추가. 75개 설치 패키지 호환 검사 통과 |
| `backend/.venv` | Python 3.12.11 생성, Backend requirements 설치 | 58개 패키지, pytest 8.4.2·pytest-asyncio 1.4.0·httpx2 2.12.0, 호환 검사 통과 |
| `frontend_user/.venv` | Python 3.12.11 생성, 사용자 requirements-dev 설치 | 39개 패키지, Streamlit 1.63.0·pytest 8.4.2, 호환 검사 통과 |
| `frontend_admin/.venv` | Python 3.12.11 생성, 관리자 requirements와 pytest 설치 | 39개 패키지, Streamlit 1.63.0·pytest 8.4.2, 호환 검사 통과 |
| `mcp_server/.venv` | 기존 Python 3.12.11 재사용, 독립 locked dev 설치 | 36개 패키지, MCP SDK 1.29.1, 호환 검사 통과 |
| macOS 터미널 | 로컬 `.vscode`의 zsh profile·router 준비 | 새 interactive terminal의 루트/Backend 시작, 모든 컴포넌트와 하위 폴더 이동, 루트 복귀 및 저장소 밖 해제 확인 |

루트와 MCP lock은 `uv lock --check`로 확인했다. requirements 기반 컴포넌트는 범위
설치이므로 루트 lock과 일부 패치 버전이 다르다. `.vscode/`·`.venv/`는 Git 제외
대상이며 기존 사용자 shell 설정을 먼저 읽는다. 새 VS Code 터미널에서 적용되고
외부 터미널에는 자동 적용되지 않는다. 설치·활성화 명령은 [README](../README.md)의
로컬 가상환경 절을 따른다.

## 4. 이번에 직접 실행한 테스트

| 범위 | 결과 | 실행 경계 |
|---|---|---|
| Backend | **128 passed** | 실제 DB 테스트 2파일 제외, synthetic DSN·dummy Provider, pytest-asyncio·AnyIO plugin 명시 |
| 사용자 Front | **34 passed** | fake HTTP/순수 함수/JS 소스 검사, 실제 브라우저 실행 아님 |
| 관리자 Front | **3 passed** | fake HTTP·응답 경계 검사 |
| MCP | **6 passed** | 4파일의 fake·MockTransport·ASGI 왕복, 실제 프로세스 DB 테스트 제외 |
| 합계 | **171 passed, 실패 0** | 외부 서비스 없는 선정 범위의 결과이며 전체 통합 회귀 결과는 아님 |

Backend의 과거 async plugin 미설치 상태는 해소했다. 각 범위는 해당 컴포넌트의
Python으로 한 번 실행했고, 전체 lint나 같은 테스트의 반복 실행은 하지 않았다.
실행 가능한 정확한 명령과 제외 파일은 [README 테스트 절](../README.md#테스트와-정적-검사)에 기록했다.

## 5. 실제 DB·브라우저 게임 테스트 준비 상태

현재 설정 파일을 값 노출 없이 점검한 결과 `.env`는 존재하고 설정 파싱은 성공했다.
**외부 TEAM_DATABASE_URL 우선 경로와 OpenAI Provider가 선택되어 있고 keyring은
설정되어 있지 않다.** 실제 주소·계정·비밀번호·API key는 출력하거나 문서에 복사하지
않았고 `.env`·실제 secrets는 변경하지 않았다. DB·Redis 연결, migration, Provider 호출은
실행하지 않았다.

| 다음 테스트 | 이번에 실행하지 않은 이유·필요한 준비 |
|---|---|
| `backend/tests/test_b5_game_api.py` | 이제 메모리 테스트가 아니다. 실제 DB에 쓰고 autouse cleanup에서 삭제한다. 전용 테스트 DB와 migration/seed 준비가 필요하다. |
| `backend/tests/test_postgres_game_flow.py` | 실제 PostgreSQL 쓰기·삭제와 Redis cleanup을 수행한다. 공유 게임 데이터와 분리한 DB·Redis 대상을 확인해야 한다. |
| `mcp_server/tests/test_process_backend_roundtrip.py` | 실제 Backend/MCP subprocess·DB 생성/삭제를 수행한다. 기존 환경과 worker가 활성화되므로 전용 DB 및 dummy Provider가 필요하다. MCP 독립 환경에는 Backend 의존성이 없어서 루트 환경·PYTHONPATH로 실행해야 한다. |
| 전체 게임 UI | 위 데이터 준비 후 Backend→MCP→사용자/관리자 Front 순으로 기동하고 생성·낮/밤·투표·저장/재개·관전·종료·feedback을 확인한다. N01/N02 정보 경계와 N04~N06 핵심 진행 문제를 먼저 해결해야 한다. |

실제 DB 테스트 세 파일에 자동 skip/opt-in guard가 없으므로 `pytest` 또는 MCP
`pytest tests`를 전체 실행하면 실제 환경에 접근할 수 있다. `TEAM_DATABASE_URL`은
`DATABASE_URL`보다 우선한다. 운영 DSN이 남은 상태에서 로컬 DATABASE_URL만 바꾸어
격리됐다고 판단하지 않는다. Provider는 우선 `dummy`로 검증하며 유료 호출은 이번
준비 범위에 포함하지 않았다.

## 6. 변경·검증 범위

- 변경: 루트 dev 의존성·lock, README, 본 점검표, 현재 코드 상태 문서, 로컬 가상환경과 `.vscode`.
- 확인: 171개 선정 테스트, 5개 환경 의존성 호환, 2개 lock 정합성, zsh 전환·설정 문법, 문서 링크·diff.
- 생략: 실제 DB/Redis 통합·migration·유료 Provider·브라우저 E2E, 기능 미변경에 따른 전체 lint.
- 게임 기능·DB·실제 비밀 설정을 변경하지 않았으며 커밋·푸시도 하지 않았다.
