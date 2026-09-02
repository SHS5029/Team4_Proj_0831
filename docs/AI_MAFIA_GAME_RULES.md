# AI 마피아 `basic-v1` 게임 상태·로직 계약

이 문서는 규칙 엔진이 소유하는 유일한 상태 전이 기준이다. API는 명령을 전달하고 화면은 표현만 한다. 모든 전이는 `state_version + 1`, event append, snapshot 조건을 동반한다.

## 1. 구성·불변식

플레이어 5~6명은 마피아 1·탐정 1·의사 1·시민 나머지, 7~9명은 마피아 2·탐정 1·의사 1·시민 나머지다. 인간 1명과 AI 참가자로 구성하며 모든 player는 고유 seat·role·faction을 가진다. 시작 후 role은 종료 전 본인과 해당 agent에게만 공개한다. 살아 있는 참가자만 행동하고, 상태 변경은 Backend transaction이 최종 확정한다.

## 2. 상태 목록과 전이

| state/phase | 진입 로직 | 허용 입력·API | 종료 조건·다음 상태 |
|---|---|---|---|
| `ROLE_REVEAL` | role·persona를 deterministic seed로 배정, snapshot | 인간 `BEGIN_GAME` → `POST /commands` | 수락 시 `NIGHT_ACTION` |
| `NIGHT_ACTION` | 생존 마피아·탐정·의사의 행동 창을 동시에 열고 deadline 설정 | 인간 역할 command 또는 AI MCP proposal | 제출 완료/timeout → 밤 해소; 승패면 `FINISHED`, 아니면 `DAY_ANNOUNCEMENT` |
| `DAY_ANNOUNCEMENT` | 밤 공격·보호 결과를 공개 event로 생성, 사망 처리 | 자동 operation, 조회 `GET /games/{id}` | 발표 후 `DAY_DISCUSSION` |
| `DAY_DISCUSSION` | 생존자 순서대로 발언 turn 부여 | 인간 `SPEAK`, AI `game_speak` | 발언 완료/timeout → `DAY_VOTE` |
| `DAY_VOTE` | 생존자에게 1표씩 수집 | `CAST_VOTE`, AI `game_vote` | 최다 득표 1명 → 처형·승패 판정; 동점 → `DAY_REVOTE` |
| `DAY_REVOTE` | 최초 동점자만 target으로 재투표 | `CAST_VOTE` | 단독 최다 처형; 재동점이면 무처형. 승패 아니면 `NIGHT_ACTION` |
| `PAUSED` | 안전 지점 snapshot과 pause operation 확정 | `RESUME`, 탈락 인간의 `FAST_FORWARD` | resume은 저장 phase 복원; fast-forward는 다음 입력 phase/종료까지 진행 |
| `FINISHED` | winner·finish_reason·finished_at 확정 | `GET /result`, `POST /feedback` | 불변. 결과·timeline만 조회 |

`DAY_ANNOUNCEMENT`는 사용자 입력 phase가 아니며 별도 command를 제공하지 않는다. `PAUSE`는 active operation이 없을 때만 안전 지점에서 가능하다.

## 3. 밤 해소

마피아 target은 살아 있는 비마피아를 우선 허용하고, 마피아가 여러 명이면 각 선택을 집계해 최다 target을 공격한다. 동률이면 deterministic seat 순서로 선택한다. 의사의 보호 target이 공격 target과 같으면 사망하지 않는다. 탐정 조사는 해당 target의 faction 결과만 private event로 남긴다. 미제출·timeout·잘못된 proposal은 규칙 기본값(공격 없음, 조사 없음, 보호 없음)으로 처리하고 agent failure를 게임 전체 실패로 만들지 않는다.

## 4. 낮 판정·승패

투표는 생존자만 가능하며 timeout은 무투표다. 최다 득표가 없으면 처형하지 않는다. 처형 후 역할은 공개 event로 공개한다. `마피아 생존 수=0`이면 `CITIZEN`, `마피아 수>=시민 진영 생존 수`이면 `MAFIA`, 그 외는 다음 밤이다. 종료 시 전체 role은 결과 API에서만 공개하고 조사 private event는 timeline에 넣지 않는다.

## 5. 명령 검증 순서와 실패

Backend는 소유권 → status/phase → expected_version → 호출자 player·alive → command/role/turn → target alive·allowlist → 중복 제출 순으로 검증한다. 실패는 `409 ACTION_NOT_ALLOWED` 또는 `GAME_STATE_CONFLICT`이며 상태·version을 바꾸지 않는다. LLM/MCP timeout은 agent_run 기록과 fallback event를 남기고, token·의존성 한도 초과는 안전 snapshot 후 `PAUSED`다.

## 6. 필수 테스트

5·6·7·9명 role 배정, 모든 phase 전이, 밤 보호 성공·실패, 마피아 합의, 무투표·동점·재동점, 승패 경계, timeout fallback, version 충돌, 탈락 관전, snapshot replay, private event 격리를 fixture로 검증한다.
