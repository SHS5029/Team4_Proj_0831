# AI 마피아 Frontend 화면·상태 계약 `minimum-v1`

Frontend는 Backend만 호출하고 API 응답의 `status`, `phase`, `allowed_commands`를 단일 진실로 사용한다. 화면 상태와 서버 상태를 섞지 않으며, 로컬 UI 상태는 새로고침 시 복구 가능한 값만 둔다.

## 1. 공통 상태·동작

공통 상태는 `INITIALIZING`, `LOADING`, `READY`, `SUBMITTING`, `STREAM_RECONNECTING`, `EMPTY`, `ERROR`, `FORBIDDEN`이다. `ERROR`는 `trace_id`와 재시도만 보여주고 오류 원문·private role을 노출하지 않는다. `409`는 상태 재조회 후 버튼을 다시 계산하고, `404`는 목록으로 이동한다. 모든 mutation 중복 클릭은 `SUBMITTING`에서 막는다.

## 2. 사용자 화면

| 화면 | 진입 | 표시·상태 | 호출과 전환 |
|---|---|---|---|
| `HOME` | 앱 시작 | `INITIALIZING→READY`; 새 게임, 저장 게임, 최근 게임 | `GET /games`; 새 게임→`CREATE_GAME`, 항목→`GAME` |
| `CREATE_GAME` | HOME | 인원 5~9, ruleset `basic-v1`, 유효성·제출중·실패 | `POST /games`; 201의 game_id로 `GAME` |
| `GAME` | 생성·목록·resume | 아래 phase별 view와 연결 상태, operation 상태, 메모 | 진입·resume 시 `GET /games/{id}`; mutation 후 operation polling/SSE |
| `SAVED_GAMES` | HOME | `IN_PROGRESS|PAUSED` 목록, empty/loading/error | `GET /games?status=...`; 선택→`GAME`, 삭제 버튼 없음 |
| `RESULT` | FINISHED | 승자·timeline·전체 역할·내 생존·평점 | `GET /result`; 평점은 `POST /feedback`, 완료 후 재제출 금지 |

### GAME phase view

`ROLE_REVEAL`: 내 role만 표시, `BEGIN_GAME` 버튼.  
`NIGHT_ACTION`: role이 허용한 `KILL|INVESTIGATE|PROTECT`와 valid target만 표시.  
`DAY_DISCUSSION`: 내 turn일 때만 입력·`SPEAK`, 그 외 읽기 전용.  
`DAY_VOTE`: 생존 target 선택·`CAST_VOTE`.  
`DAY_REVOTE`: 동점 target만 표시·`CAST_VOTE`.  
`PAUSED`: `RESUME`과 게임 요약.  
`FINISHED`: 결과 API로 이동. 인간 탈락 후에는 공개 정보 관전, `FAST_FORWARD`만 허용한다.

각 view는 `phase_deadline_at` countdown을 표시하되 시간 만료를 자체 판정하지 않는다. `allowed_commands`에 없는 버튼은 렌더링하지 않으며 `active_operation`이 있으면 mutation을 잠근다. `PAUSE`는 안전 지점에만 표시한다.

## 3. 이벤트·메모

GAME 진입 후 SSE `/events`를 연결하고 `Last-Event-ID`로 재연결한다. 45초 무응답이면 `STREAM_RECONNECTING→READY`; SSE가 계속 실패하면 5초 주기 operation/state polling으로 대체한다. `game.state_changed` 수신 시 상태를 재조회하고, event payload를 화면 상태의 원본으로 저장하지 않는다.

메모 카드는 게임 화면 하단에 둔다. `GET /notes`로 초기화하고 저장은 `PUT /notes`의 `expected_notes_version`을 사용한다. 메모는 다른 참가자·결과 timeline·관리자 화면에 표시하지 않는다.

## 4. 관리자 화면

`ADMIN_KPI`, `ADMIN_LOGS`, `ADMIN_FEEDBACK` 각각 `LOADING|READY|EMPTY|ERROR`를 가지며 `GET /admin/kpis`, `/logs`, `/feedback`만 호출한다. KPI는 기간 선택 후 조회, 로그·feedback은 cursor pagination이다. MVP에서는 편집·상태변경·삭제 UI를 만들지 않는다.

## 5. 접근성·완료 기준

키보드로 모든 command를 실행할 수 있고, countdown·SSE 변경은 live region으로 알린다. 입력은 HTML escape 후 표시하며 role은 API가 준 현재 사용자 projection만 렌더링한다. 화면별 정상·empty·loading·submit·409·503 상태와 새로고침 복구를 mock API로 확인하면 완료다.
