# AI 마피아 에이전트 행동 유효성 시험 결과 보고서

시험 기준일: 2026-09-08  
보고서 작성일: 2026-09-09  
시험 대상: AI Player Agent의 게임 상태별 행동 선택·제출·검증 결과

## 1. 실험 목적

본 실험은 Agent가 현재 게임 상태에서 허용되지 않은 행동을 선택하거나 잘못된
대상을 제출하는지 확인하는 것을 목적으로 한다. Agent의 자연어 표현력이나 인간과
비교한 추론 능력을 평가하지 않고, 게임의 확정 원장과 Agent 실행 기록을 비교하여
행동의 유효성과 상태 정합성을 측정한다.

핵심 질문은 다음과 같다.

- 현재 phase와 action window에 맞는 행동을 선택했는가?
- actor에게 허용된 Context와 행동 범위만 사용했는가?
- 선택한 대상과 파라미터가 유효한가?
- 오래된 상태나 중복 요청을 잘못 반영하지 않았는가?
- 오류가 발생했을 때 fallback 또는 안전한 실패로 종료했는가?

## 2. 실험 기준과 정답 원장

AI Agent의 행동 1회를 다음 단위로 정의한다.

```text
Agent turn = game_id + actor_player_id + window_id + state_version
```

각 turn의 판정은 다음 정보를 기준으로 한다.

| 확인 정보 | 기준 데이터 | 판정 내용 |
|---|---|---|
| 게임 상태 | `games`, snapshot·runtime 상태 | 현재 phase·round·state version |
| 행동 창 | `action_windows` | window 종류·차례·마감·허용 상황 |
| AI 작업 | `agent_jobs` | job 종류·예약 version·최종 상태·failure code |
| 행동 제출 | `action_submissions` | action type·actor·target·source·관찰 version |
| 확정 결과 | `action_window_resolutions`, `game_events` | 집계·상태 전이·최종 반영 결과 |
| 실행 기록 | Agent activity·progress log | 선택·fallback·실패 단계와 순서 |

`action_submissions`와 Game Engine의 확정 결과를 게임 상태의 정답 원장으로 본다.
단, 검증 전에 거부된 proposal은 submission 행으로 저장되지 않을 수 있으므로,
거부 시도까지 포함한 오류율은 `agent_jobs`의 terminal 상태와 Agent activity/log를
함께 사용한다.

## 3. 오류 정의

### 3.1 Agent 행동 오류

다음 항목을 Agent 행동 오류율에 포함한다.

| 오류 코드 | 판정 기준 |
|---|---|
| `INVALID_ACTION` | 현재 phase·window·role에서 허용되지 않은 action type 선택 |
| `INVALID_TARGET` | 사망자·자기 자신·다른 게임·권한 밖 대상 선택 |
| `MISSING_PARAMETER` | 필수 target·message·ability 등 누락 |
| `FORBIDDEN_TOOL` | 현재 actor 또는 window에 허용되지 않은 Tool/행동 선택 |
| `CONTEXT_SCOPE_VIOLATION` | actor가 볼 수 없는 private Context 사용 또는 전달 |

### 3.2 Agent 오류와 분리할 운영 오류

다음은 Agent의 게임 판단 오류와 분리하여 별도 집계한다.

| 오류 코드 | 의미 |
|---|---|
| `STALE_STATE` | 판단 이후 state version 또는 window가 변경됨 |
| `DUPLICATE` | 이미 처리된 행동의 재제출 |
| `PROVIDER_ERROR` | Provider 응답 실패 또는 timeout |
| `MCP_ERROR` | MCP Resource·Tool 연동 실패 |
| `FALLBACK_APPLIED` | 오류 후 결정적 fallback으로 처리 성공 |
| `FAILED` | 재시도·fallback 이후 안전하게 실패 종료 |

## 4. 평가 지표

### 4.1 허용되지 않은 행동률

```text
(INVALID_ACTION + FORBIDDEN_TOOL) turn 수 ÷ 전체 Agent turn 수 × 100
```

### 4.2 잘못된 대상·파라미터 오류율

```text
(INVALID_TARGET + MISSING_PARAMETER) turn 수
÷ 대상 또는 파라미터가 필요한 전체 turn 수 × 100
```

### 4.3 Context scope 위반율

```text
CONTEXT_SCOPE_VIOLATION turn 수 ÷ Context가 생성된 전체 turn 수 × 100
```

### 4.4 정상 반영률

```text
검증된 Agent action이 APPLIED 된 turn 수 ÷ 전체 Agent turn 수 × 100
```

### 4.5 오류 처리율

```text
(FALLBACK_APPLIED + 안전한 FAILED) turn 수
÷ Provider·MCP·상태 오류가 발생한 전체 turn 수 × 100
```

`STALE`과 `DUPLICATE`는 정상적인 방어 결과일 수 있으므로 정상 반영률에서 제외하고,
잘못 반영된 경우만 실패로 판정한다.

## 5. 시험 시나리오

| ID | 시험 상황 | 기대 결과 |
|---|---|---|
| AGT-001 | DAY_DISCUSSION에서 SPEAK 선택 | 유효 proposal 및 제출 |
| AGT-002 | DAY_DISCUSSION에서 PASS 선택 | 허용 조건이면 제출 |
| AGT-003 | DAY_VOTE에서 생존자 투표 | 유효 target 제출 |
| AGT-004 | NIGHT_ACTION에서 역할에 맞는 행동 | role·target 검증 후 제출 |
| AGT-005 | 토론 중 VOTE 또는 NIGHT_ACTION 선택 | `INVALID_ACTION` 거부 |
| AGT-006 | 사망자·자기 자신을 target으로 선택 | `INVALID_TARGET` 거부 |
| AGT-007 | 필수 target·message 누락 | `MISSING_PARAMETER` 거부 또는 교정 |
| AGT-008 | actor가 볼 수 없는 Context 접근 | scope 거부·미반영 |
| AGT-009 | 이전 state version으로 제출 | `STALE`, 상태 미변경 |
| AGT-010 | 같은 window·actor의 재제출 | `DUPLICATE`, 중복 미반영 |
| AGT-011 | MCP 제출 중 오류 | 제한 재시도 후 fallback 또는 실패 |
| AGT-012 | 저장 후 응답 유실 | 새 window에 잘못된 재적용 금지 |

## 6. 현재 시험 결과

### 6.1 Agent 실행·검증 focused 시험

현재 기록상 B6 Agent 진행·로그·proposal·fallback 관련 focused 시험 48개가
통과했다. 이후 rollback 후 미제출 job의 저장 proposal 재사용과 격리 SQL을 포함한
후속 시험 40개도 통과했다. UTC Context projection parser 보완 후 관련 focused
시험 47개도 통과했다.

이 수치는 구현 작업별 focused 결과이며 서로 중복될 수 있다. 따라서 Agent 행동
오류율의 분모·분자를 의미하는 실제 turn 집계와는 구분한다.

### 6.2 확인된 행동 유효성·상태 방어

| 평가 항목 | 현재 판정 | 근거 |
|---|---|---|
| proposal 형식·행동 검증 | 통과 | Agent proposal 및 action service focused 시험 |
| actor·game·window binding | 통과 | reservation·binding·scope 시험 |
| stale 상태 거부 | 통과 | state version·window 변경 시험 |
| duplicate 처리 | 통과 | 동일 action 재처리 시험 |
| MCP 제출 실패 fallback | 통과 | synthetic MCP 실패 시험 |
| 저장 후 응답 유실 방어 | 통과 | 새 window 오적용 방지 시험 |
| rollback 후 `APPLIED` 방지 | 통과 | private batch rollback 시험 |
| fallback 사유 보존 | 통과 | activity reason/source 시험 |
| 민감한 진단 문자열 차단 | 통과 | activity 입력 검증 시험 |

### 6.3 실제 게임 실행 확인

격리 환경의 Dummy Provider 기반 8인 게임에서 최종 지목까지 진행하여
`COMPLETED`/`ENDED` 상태에 도달했다. 해당 실행에서 AI 89회의 실행 기록에
`STARTED → CONTEXT_READY → DECIDING → DECIDED → APPLIED` 순서가 남았다.

이 결과는 정상 실행 경로와 게임 원장 연결을 확인한 것이다. 해당 실행에는
`FALLBACK`·`FAILED`가 없었으므로, fallback의 실제 게임 발생률을 의미하지 않는다.
fallback과 오류 회복은 synthetic focused 시험 결과로 별도 확인했다.

## 7. DB 결과 집계 방법

실제 오류율을 산출할 때는 게임별·window별·actor별로 다음 순서로 집계한다.

1. `agent_jobs`에서 AI Player job의 terminal 결과를 추출한다.
2. `game_id`, `player_id`, `window_id`, 예약 state version으로 당시 게임 상태와 연결한다.
3. `action_windows`에서 phase, window kind, turn과 마감 조건을 확인한다.
4. `normalized_result` 또는 activity에 기록된 action type·target을 확인한다.
5. `action_submissions`의 `source=AGENT` 행과 연결한다.
6. `game_events`·`action_window_resolutions`에서 실제 확정 반영 결과를 확인한다.
7. 기대 허용 행동·유효 대상과 Agent 결과를 비교한다.
8. 오류 코드를 분류하고 위 지표를 계산한다.

최소 연결 키는 다음과 같다.

```text
game_id + window_id + player_id + reserved_state_version
```

동일 키에 재시도·fallback이 여러 번 존재할 수 있으므로 attempt 또는 job ID를
함께 사용한다. 최종 상태만 보고 판단하지 않고, 첫 proposal이 잘못되었는지와
fallback 이후 최종 반영되었는지를 분리한다.

## 8. 결과 기록 표준

실제 DB 집계를 완료하면 아래 표를 채운다. 현재 문서에는 근거 없는 수치를 넣지 않는다.

| 지표 | 오류·결과 건수 | 전체 건수 | 비율 | 산출 근거 |
|---|---:|---:|---:|---|
| 허용되지 않은 행동률 | 미집계 | 미집계 | 미집계 | `agent_jobs` + activity |
| 잘못된 대상 오류율 | 미집계 | 미집계 | 미집계 | proposal + `action_submissions` |
| 필수 파라미터 오류율 | 미집계 | 미집계 | 미집계 | proposal validation 결과 |
| Context scope 위반율 | 미집계 | 미집계 | 미집계 | Context projection trace |
| 정상 반영률 | 미집계 | 미집계 | 미집계 | `action_submissions` + resolution |
| fallback 처리율 | 미집계 | 미집계 | 미집계 | `agent_jobs.status` |
| stale·duplicate 방어율 | 미집계 | 미집계 | 미집계 | job status + receipt |

현재 저장소의 테스트 기록은 focused 시험과 특정 게임 실행 결과를 보존하지만,
모든 Agent turn을 위 지표로 자동 집계한 표본 리포트는 아직 생성하지 않았다.
따라서 위 표의 “미집계”를 임의의 성공률로 바꾸지 않는다.

## 9. 실험의 한계

- Fake·Dummy Provider 중심이므로 실제 LLM의 Tool 선택·자연어 추론 품질은 측정하지 않았다.
- 성찰 루프 적용 전후를 동일 데이터셋으로 비교한 baseline은 확보하지 않았다.
- 8인 게임 1회의 정상 완주는 장기 전략과 전체 서비스 안정성을 보장하지 않는다.
- `action_submissions`에 저장되지 않은 검증 전 proposal은 activity·job 기록이 없으면 DB만으로 복원할 수 없다.
- 오류율 산출을 위해서는 모든 Agent 시도에 안정적인 job·attempt·proposal 연결이 필요하다.

## 10. 결론

현재 확인 가능한 결과는 Agent가 생성한 행동을 Backend·Game Engine의 검증 경계에
두고, stale·duplicate·MCP 오류·응답 유실·rollback 상황에서 잘못된 상태 변경을
방지한다는 것이다. Dummy Provider 기반 실제 게임에서도 Agent 실행과 게임 원장
연결을 확인했다.

다만 현재 자료만으로 전체 Agent turn의 허용되지 않은 행동률이나 실제 LLM의 추론
정확도를 단정할 수는 없다. 최종 시험 보고서의 정량 결론은 `agent_jobs`, Agent
activity, `action_submissions`, `game_events`를 연결한 DB 집계를 완료한 뒤 작성해야
한다.

## 11. 근거 문서

- [Agent 아키텍처 설계서](06_AGENT_ARCHITECTURE_DESIGN.md)
- [전체 시스템 아키텍처 설계서](AI_MAFIA_SYSTEM_ARCHITECTURE_DESIGN.md)
- [DB·Redis 설계서](01_DB_REDIS_DESIGN.md)
- [게임 테스트 공백·재점검 보고서](../AI_MAFIA_GAME_TEST_GAP_REPORT.md)
- [병렬 투표 버그 보고서](../AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md)
