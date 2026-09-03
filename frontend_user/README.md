# 일반 사용자 Frontend

현재 사용자 앱은 `WU-F1`에 따라 로그인 없이 브라우저 UUID를 identity로 사용합니다.
앱은 UUID를 same-origin local storage의 `ai_mafia_user_id_v1` key에 저장하고,
Backend 공개 API 요청에는 `X-User-Id`와 `X-Request-Id` header만 전달합니다.

`WU-F2`에서는 홈의 이어하기·최근 완료 목록과 새 게임 설정을 제공합니다. 전체
인원은 6~9명으로 제한하고 역할 구성은 표시만 하며, 시나리오·역할·persona·닉네임은
사용자가 선택하지 않습니다. 게임 생성 요청은 `mystery-v1`과 `scenario-v1`을 사용하고
성공 후 Backend snapshot을 조회합니다.

홈과 새 게임 설정 화면은 공통 dark header, breadcrumb, 반응형 카드 레이아웃과
게임 방식 안내를 사용하며, 실제 입력은 기존 UUID·인원 선택·Backend 생성 계약만
사용합니다. 새 게임 설정의 인원 카드는 6~9명 선택과 기존 `ROLE_COUNTS` preview를
표현하고 생성 중에는 선택·취소 입력을 잠급니다.

`WU-F3`에서는 역할 공개·게임 shell을, `WU-F4`에서는 snapshot의 `legal_actions`와
`valid_targets`에 따른 발언·밤 행동·투표 panel을 제공합니다. Front는 승패나 자동
선택을 계산하지 않고 Backend command 결과를 확인한 뒤 snapshot을 다시 조회합니다.

역할 공개 화면에서 `BEGIN_GAME`이 허용된 경우에만 `expected_state_version`과
UUID v4 `Idempotency-Key`를 포함해 게임 시작 command를 제출합니다. 생성 응답만으로
phase를 변경하지 않고 command 성공 뒤 authoritative snapshot을 다시 조회합니다.
역할 공개 UI는 사건 정보, 본인 역할·능력·승리 조건, 알리바이·관찰 정보와 인원 정보를
하나의 반응형 private card에 표시하며, Backend 문자열은 unsafe HTML에 삽입하지 않습니다.
게임 시작은 `PENDING_TO_RENDER → IN_FLIGHT → terminal` 순서로 처리합니다.

F4 command는 `legal_actions`, `action_window`, `valid_targets`, `state_version`을
기준으로 구성하며, 마감·stale·중복 제출은 Backend가 최종 거부해야 합니다. Front는
자동 선택이나 자동 제출을 수행하지 않습니다.

낮 토론에서는 중앙 공개 timeline 아래에 현재 발언자 또는 본인 입력 panel을 표시하고,
본인 차례에만 최대 200자 발언과 `PASS`를 활성화합니다. 밤 행동에서는 공개 생존자와
본인 비공개 정보 사이의 중앙 영역을 어두운 대상 선택 panel로 전환합니다. 마피아·탐정·
의사 안내 문구는 역할에 맞게 달라지지만 command에는 역할이나 세부 행동을 넣지 않고
Backend가 제공한 `valid_targets`의 `target_player_id`만 전송합니다. 시민·제출 완료자는
입력 없이 대기 안내만 보며, 결과를 확인할 수 없는 재시도는 최초 Idempotency-Key를
그대로 사용합니다.

낮 투표·재투표·최종 지목에서는 중앙 영역을 공개 timeline 요약, Backend 기준 남은
시간, 후보 선택, 제출 버튼으로 구성합니다. 후보는 `valid_targets`만 표시하고 15초 이하
경고를 제공하며, 최초 제출 뒤에는 후보를 다시 선택할 수 없습니다. 집계 전에는 사용자의
선택이나 다른 플레이어의 개별 투표를 공개하지 않습니다.

F3 화면은 `ROLE_REVEAL`과 진행 phase를 Backend snapshot으로 구분합니다. 역할 공개
화면에는 본인의 role·alibi·observation만 표시하고, 게임 shell의 player·timeline에는
공개 projection만 표시합니다. 새로고침 시에도 Front가 phase나 승패를 계산하지 않고
`game_id`로 authoritative snapshot을 다시 요청합니다.
게임 shell은 desktop에서 생존자 목록·중앙 phase 작업 영역·내 정보의 3열 구조로
표시하고 768px 이하에서는 단일 열로 재배치합니다. 낮에는 중앙에 사건/공개 timeline과
발언·투표 panel을, 밤에는 역할별 대상 선택 panel을 표시합니다. 첫날에도 정본 snapshot의
scenario와 공개 event만 사용하며, 본인 role·알리바이·관찰·private event는 오른쪽
panel에만 표시합니다.

`WU-F5`에서는 browser `fetch` streaming SSE를 주 연결로 사용하고, 연결이 없거나
envelope 검증에 실패하면 동일 cursor의 `/sync` polling으로 전환합니다. operation은
`(game_id, front_sequence, operation_index)`로 deduplicate하며 gap·unknown·잘못된
snapshot은 부분 적용하지 않습니다.

F5 연동 시 Backend 팀은 `/events`와 `/sync`에 동일한 `front_sequence`와 operation
index를 제공하고, `Last-Event-ID` 재연결·CORS header·보존 범위 밖 SNAPSHOT 응답을
지원해야 합니다. Front는 gap이나 schema 오류를 자체 보정하지 않습니다.

`WU-F6`에서는 인간 player가 사망하면 action widget을 제거하고 관전 안내와 공개
timeline만 표시합니다. `FAST_FORWARD`와 `SAVE_AND_EXIT`은 Backend의
`legal_actions`에 있을 때만 요청하며, `COMPLETED` 결과는 snapshot의 `result`만
사용합니다. `FAILED`에서는 마지막 공개 상태와 복구 불가 안내만 표시합니다.

관전 화면은 생존자·사망자 공개 목록, 공개 event timeline, 이미 허용된 본인의 역할·
알리바이·관찰·탈락 시점만 표시하는 3열 구조입니다. 빠른 진행은 Backend의
`fast_forward_enabled`가 확정되기 전까지 완료로 표시하지 않으며, 결과 불명 시 최초
body와 Idempotency-Key로만 재확인합니다. 다른 플레이어의 역할, 사망 원인, private
event나 개별 행동은 관전 화면에서도 추론하거나 공개하지 않습니다.

게임 종료 화면은 `result.winner`, `win_reason`, `finished_at`, 전체 `players`, `nights`,
`votes`, `public_event_ids`를 승리 영역·게임 요약·전체 역할·게임 기록으로 구분해
표시합니다. 밤과 투표 기록은 Backend가 확정한 대상·집계·탈락자만 이름으로 변환하며,
Front가 승패나 결정적 선택을 다시 계산하지 않습니다. `FAILED` 또는 result 누락 상태는
전체 역할을 공개하지 않고 복구 불가 안내와 이동 제어만 제공합니다.

`WU-F7`에서는 일반·게임별 feedback의 별점·의견·태그를 검증하고 제출 중에는 입력을
잠급니다. 결과가 불명확한 경우에만 동일 idempotency key로 재시도하며, Backend의
409 응답을 이미 제출한 상태로 표시합니다.

## 실행 준비

기존 컴포넌트별 가상환경을 재사용하며, 설치는 반드시 해당 환경의 Python으로
실행합니다.

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m pip install -r ".\frontend_user\requirements-dev.txt"
```

Python 3.12 설치 경로가 바뀌어 기존 `.venv`가 실행되지 않으면 환경을 재생성한
뒤 같은 명령을 실행합니다. 실제 비밀값이나 DB·Redis·MCP 설정은 Frontend에
넣지 않습니다.

## 실행

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m streamlit run ".\frontend_user\app.py" --server.port 8501
```

첫 실행 시 브라우저 UUID를 생성합니다. 저장소가 차단된 브라우저에서는 session-only
UUID로 동작하며 새로고침 뒤 게임 복구가 보장되지 않는다는 경고를 표시합니다.
설정 화면에서 UUID를 확인·복사하거나 UUID v4를 입력해 scope를 교체할 수 있습니다.

## 테스트·검증

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m pytest ".\frontend_user\tests"
& ".\frontend_user\.venv\Scripts\python.exe" -m ruff check ".\frontend_user"
```

현재 확인된 Python 3.12 설치 경로는
`C:\Users\Playdata\AppData\Local\Programs\Python\Python312\python.exe`이며,
위 테스트는 `frontend_user\.venv`가 이 Python을 정상적으로 참조할 때 실행합니다.

## 책임 경계

- `app.py`: UUID bootstrap과 화면 dispatcher
- `components/identity_bridge.py`: 브라우저 local storage bridge
- `components/browser_components/identity/`: UUID만 반환하는 정적 browser component
- `core/identity.py`: UUID v4 검증·생성
- `core/session.py`: identity mirror와 UUID scope 초기화
- `core/api_client.py`: UUID 공개 Backend API client
- `app_pages/settings_page.py`: UUID 확인·복구·교체 UI

`frontend_user/auth/`와 `app_pages/login_page.py`는 legacy OIDC 코드로 남아 있지만
현재 `app.py` 실행 경로에서는 호출하지 않습니다. Frontend는 PostgreSQL, Redis,
MCP 서버에 직접 연결하지 않습니다.

## 팀 전달 사항

<!--
팀 합의 게이트 전달용 요약:
CP-0: 정본·fixture·API header와 CORS 계약을 먼저 고정한다.
CP-1: F1 UUID-only 요청을 Backend B1·MCP M1A와 함께 확인한다.
CP-5: F2~F7 사용자 흐름과 Backend 공개 API B5를 통합 테스트한다.
CP-6: F8 관리자 guard·read-only API와 Backend B8을 운영 환경에서 검증한다.
각 게이트 전에는 계약이 바뀐 경우 관련 정본 문서를 먼저 갱신한다.
-->

- `CP-0`: 정본·fixture·API header·CORS 계약 고정
- `CP-1`: F1 UUID-only 요청 + Backend B1 + MCP M1A 확인
- `CP-5`: F2~F7 사용자 흐름 + Backend B5 통합 테스트
- `CP-6`: F8 관리자 guard·read-only API + Backend B8 운영 검증

- Backend는 `X-User-Id`와 `X-Request-Id`를 공개 사용자 API 계약으로 처리합니다.
- Frontend는 Authorization, OIDC token, email, Front HMAC을 보내지 않습니다.
- Backend CORS 또는 proxy는 `X-User-Id`, `X-Request-Id`, `Idempotency-Key`,
  `Last-Event-ID`를 허용해야 합니다.
- `GET /api/v1/games/{game_id}/sync`와 SSE `/events`는 동일한 Front sequence를
  사용해야 하며, 보존 범위를 벗어난 cursor에는 완전한 snapshot을 반환해야 합니다.
- UUID는 인증 자격증명이 아니므로 공개 인터넷 배포 전 별도 인증 계약이 필요합니다.
