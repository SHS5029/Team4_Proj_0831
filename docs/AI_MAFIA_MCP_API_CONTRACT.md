# AI 마피아 게임 전용 MCP 서버 계약 `minimum-v1`

상태: 구현 전 확정 계약  
소유자: `mcp_server/mcp_1`  
호출자: Backend Agent Manager 및 AI Agent  
범위: 게임 context Resource와 행동 proposal Tool만 제공

이 서버는 게임 규칙의 최종 판정자, DB 원본 저장소, Frontend API가 아니다. MCP는
게임 관련 기능만 제공하며 여행·날씨 등 다른 도메인은 이 계약에 추가하지 않는다.
최종 상태 변경은 항상 Backend가 수행한다.

## 1. 연결과 인증

전송은 Streamable HTTP MCP이며 기본 endpoint는 `POST /mcp`(initialize와 JSON-RPC
message), 상태 확인은 `GET /health`다. Backend가 세션을 만들 때 다음 헤더를 보낸다.

```http
X-MCP-Session-Id: uuid
X-MCP-Game-Id: uuid
X-MCP-Agent-Id: uuid
X-MCP-Phase: DAY_DISCUSSION
X-MCP-State-Version: 18
X-MCP-Capabilities: base64url(canonical-json)
X-Internal-Timestamp: 1725000000
X-Internal-Request-Id: uuid
X-Internal-Signature: lowercase-hex-hmac-sha256
```

서명 원문은 `METHOD + "\n" + normalized_path + "\n" + timestamp + "\n" +
request_id + "\n" + session_id + "\n" + game_id + "\n" + agent_id + "\n" +
sha256(raw_body)`다. `MCP_INTERNAL_SECRET`은 Backend와 MCP만 공유한다. MCP는
UUID·±60초 시간·request_id 중복·session capability·game/agent scope를 검증한다.
검증 실패는 JSON-RPC error `MCP_NOT_AUTHORIZED`이며 secret이나 원문 body를 반환하지 않는다.

## 2. 공통 JSON-RPC 결과

성공 결과는 MCP 표준의 `result.content`를 사용하며 text content의 JSON은 아래
공통 envelope을 따른다.

```json
{"schema_version":"1.0","game_id":"uuid","agent_id":"uuid","state_version":18,"data":{}}
```

오류 code는 `MCP_NOT_AUTHORIZED`, `MCP_INVALID_ACTION`, `MCP_CONTEXT_UNAVAILABLE`,
`MCP_VERSION_CONFLICT`, `MCP_CAPABILITY_DENIED`다. MCP가 반환하는 모든 데이터는 해당
agent에게 허용된 projection이어야 한다.

## 3. Resources

Backend는 session capability에 허용된 URI만 노출한다. Resource read는 읽기 전용이며
MCP가 DB·Redis를 직접 읽지 않고 Backend 내부 context port를 통해 얻는다.

| URI | data | 공개 범위 |
|---|---|---|
| `mafia://games/{game_id}/rules/basic-v1` | 역할, phase, 제한시간, 승패, action schema | 모든 agent |
| `mafia://games/{game_id}/public-state` | phase, round, 생존자, 공개 event·발언·투표 | 모든 agent |
| `mafia://games/{game_id}/self` | 현재 agent의 role, faction, alive, persona 식별자 | 해당 agent |
| `mafia://games/{game_id}/allowed-actions` | 현재 허용 tool, target, state_version | 해당 agent |
| `mafia://games/{game_id}/timeline` | agent에게 공개된 사건 timeline | capability에 포함된 경우 |

`rules`의 최소 schema는 `ruleset_version,roles,phases,commands,win_conditions`다.
`public-state`는 `game_id,state_version,phase,round,living_players,events`다.
`self`는 `agent_id,role,faction,alive,persona`다. `allowed-actions`는
`state_version,actions[{name,target_player_ids}]`다.

다른 agent role·private event·원본 snapshot·random seed·prompt·provider 응답은 어떤
Resource에도 포함하지 않는다. Resource URI의 game_id가 session game_id와 다르면 거부한다.

## 4. Tools

모든 Tool은 proposal만 반환하고 상태를 확정하지 않는다. 호출 주체는 body가 아니라
session의 `agent_id`다. 모든 input은 추가 필드를 거부한다.

### `game_speak`

입력: `{"message":"1~280자","expected_version":18}`  
출력: `{"proposal_id":"uuid","action":"SPEAK","message":"...","state_version":18}`

### `game_vote`

입력: `{"target_player_id":"uuid","expected_version":18}`  
출력: `{"proposal_id":"uuid","action":"VOTE","target_player_id":"uuid","state_version":18}`

### `game_kill`, `game_investigate`, `game_protect`

입력: `{"target_player_id":"uuid","expected_version":18}`. 출력은 공통
`proposal_id,action,target_player_id,state_version`이며 action은 각각 `KILL`,
`INVESTIGATE`, `PROTECT`다.

### `game_end_turn`

입력: `{"expected_version":18}`. 출력은
`proposal_id,action=END_TURN,state_version`다.

MCP는 capability, phase, alive, 역할, target allowlist, version과 입력 길이를
빠르게 검증할 수 있으나, Backend는 동일 검사를 다시 수행한다. 재전송은
`X-Internal-Request-Id` 단위로 중복을 거부하며, Tool 호출만으로 게임 event를 append하거나
phase를 전환하지 않는다. Backend가 proposal을 승인·기록한 뒤 agent에게 허용된 결과만
다시 MCP context에 반영한다.

## 5. Backend 연결 port

MCP 독립 구현은 다음 추상 port만 의존한다.

```text
get_agent_context(session_id, game_id, agent_id, state_version) -> FilteredAgentContext
submit_action_proposal(session_id, proposal) -> ProposalReceipt
```

`FilteredAgentContext`에는 위 Resource schema에 필요한 필드만 넣으며 raw DB model을
노출하지 않는다. Backend가 404·409·503에 해당하는 결과를 주면 MCP는 각각
`MCP_CONTEXT_UNAVAILABLE`, `MCP_VERSION_CONFLICT`, `MCP_CONTEXT_UNAVAILABLE`로
정규화한다.

## 6. 독립 구현 완료 조건

MCP inspector로 initialize·resource list/read·tool list/call을 재현할 수 있어야 한다.
정상 호출 외에 잘못된 HMAC, 만료 시각, 다른 game/agent, capability 밖 URI·Tool,
숨은 role 요청, version 충돌, 중복 request를 fixture로 검증한다. Frontend는 MCP endpoint를
호출하지 않는다.
