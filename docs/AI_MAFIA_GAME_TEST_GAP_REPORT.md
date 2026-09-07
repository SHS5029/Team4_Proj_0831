# AI 마피아 게임 테스트 관점 미구현·미완료 목록

작성일: **2026-09-07**

조사 기준: `Hwanseok` 브랜치, HEAD `5292c2a`와 **현재 미커밋 작업 파일 포함**. 특히 MCP의 WU-M3 Resource와 WU-M5 선행 감사 로그 구현을 포함한다.

## 1. 판정 범위

실제 사용자가 **UUID 준비 → 게임 생성 → 역할 공개·시작 → 낮 토론 → 밤 행동 → 투표 → 저장·재개 → 관전 → 종료·피드백**을 테스트한다고 가정하고 정본과 실제 실행 경로를 대조했다. 서비스나 브라우저를 실행한 테스트 결과가 아니라 **코드 기반 사전 점검표**다. 표의 영향은 코드에서 예상되는 결과이며 실제 환경 재현 결과와 구분한다.

현재는 화면·공개 API·규칙 엔진을 이용한 제한적인 fallback 게임 흐름이 존재한다. 그러나 **실제 AI가 대화하는 한 판, 정확한 시간 만료, 저장 후 재개, 다섯째 밤 이후 판정, 재시작 복구를 모두 갖춘 통합 게임 테스트 준비가 끝난 상태는 아니다.** 코드를 보유한 기능도 기본 앱에 연결되지 않았으면 미완료로 분류했다.

| 표기 | 의미 |
|---|---|
| 미구현 | 필요한 handler·화면 동선·처리 자체가 없음 |
| 미연결 | 관련 클래스·정책·화면은 있으나 기본 실행 경로에서 사용하지 않음 |
| 부분 구현·계약 불일치 | 동작은 있으나 정본의 규칙·데이터·복구 조건과 다름 |
| 확인 필요 | 소스만으로 환경 준비·배포·제품 승인 여부를 확정할 수 없음 |
| P0 | 해당 핵심 테스트 시나리오의 정상 완료 또는 올바른 판정을 막는 항목 |
| P1 | 주요 기능·정보 표시·복구의 완성도를 확인하기 전에 해결할 항목 |
| P2 | 부가 화면·운영 진단의 보완 항목 |

각 행의 WU는 **관련 책임 범위**이며 여러 WU의 동시 구현 지시나 완료 판정이 아니다. 후속 구현은 [AGENTS.MD](../AGENTS.MD)의 세션당 WU 1개 이하 규칙을 따른다. 근거의 행 번호는 작성 시점 기준이며 파일 링크와 심볼을 함께 참고한다.

## 2. 실제 게임 진행에서 막히거나 규칙이 다른 부분

기준: [마스터플랜](개발상세플랜/AI_MAFIA_MASTER_PLAN.md) 3~5절, [API 정본](개발상세플랜/AI_MAFIA_API_SPEC.md) 2·4·5절, [화면 정본](개발상세플랜/AI_MAFIA_SCREEN_FLOW.md) 8~12절.

| ID·우선 | 테스트 장면·기대 동작 | 현재 상태와 남은 작업 | 코드 근거 | 관련 WU |
|---|---|---|---|---|
| G01 · P0 | 인간이 발언한 뒤 AI별 대화와 GM 진행을 기다린다 | **Agent 실행 미연결.** 공개 API는 AI 발언을 일괄 `PASS` 처리하고 인간 밤 행동·투표 직후 `force=True`로 해소한다. AgentOrchestrator·Provider adapter는 있으나 실제 공개 게임에 연결되지 않았다. 실제 AI 행동과 GM narration을 연결해야 한다. | [game_service.py](../backend/app/services/game_service.py) L821~898 `_apply_engine_command`; [orchestrator.py](../backend/app/agent/orchestrator.py) L79~170; [main.py](../backend/app/main.py) L40~110 | B5·B6·B7 |
| G02 · P0 | 밤 20초·투표 30초를 입력 없이 기다리고, 중간에 새로고침·저장·재개한다 | **서버 deadline 부분 구현.** 공개 snapshot은 조회 때마다 `now + 30초`를 만들며 저장도 실제 잔여 시간 대신 30,000ms를 사용한다. 기본 실행에 마감 해소 worker가 없다. 서버 권위 deadline·마감 제출 거부·무응답 처리·남은 시간 복원이 필요하다. | [game_service.py](../backend/app/services/game_service.py) L714~819, L858~870, L1069~1099; [main.py](../backend/app/main.py) `create_app` | B5·B6·B9 |
| G03 · P0 | 8~9인 게임에서 마피아 2명이 각각 공격 대상을 제출한다 | **밤 규칙 불일치.** 두 번째 공격 제출을 `FACTION_ACTION_ALREADY_SUBMITTED`로 거절하고 첫 공격 하나를 사용한다. 정본은 두 마피아의 독립 선택을 받아 같은 대상이면 그대로, 다른 대상이면 두 대상 중 결정적 RNG로 해소한다. | [game_engine.py](../backend/app/agent/game_engine.py) L250~269, L293~296, L317~320 | B4 |
| G04 · P0 | 처형 투표 동률 뒤 동률 후보만 대상으로 재투표한다 | **재투표 후보 제한 미구현.** 동률 후보를 보존하지 않고 표만 비우므로 재투표 제출과 자동 선택이 전체 생존자를 대상으로 한다. 동률 후보 집합을 저장하고 제출·자동 선택·공개 valid_targets에 동일하게 적용해야 한다. | [game_engine.py](../backend/app/agent/game_engine.py) L338~375; [fallback.py](../backend/app/agent/fallback.py) L28~43; [game_service.py](../backend/app/services/game_service.py) L1100~1106 | B4·B5 |
| G05 · P0 | 인간이 생존한 채 다섯째 밤을 지나 최종 발언·전원 최종 지목으로 종료한다 | **공개 진행 누락 및 판정 불일치.** `FINAL_DISCUSSION`은 공개 SPEAK/PASS 허용·action window·AI 진행에 연결되지 않아 저장 외 진행이 막힌다. 엔진 최종 지목도 첫 한 명의 선택으로 즉시 승패를 결정한다. 최종 발언 한 순환, 전원 표 집계, 최다 득표·동률 RNG 판정이 필요하다. | [game_service.py](../backend/app/services/game_service.py) L751~756, L876~885, L1038~1079; [game_engine.py](../backend/app/agent/game_engine.py) L389~419 | B4·B5·B6 |
| G06 · P1 | 의사와 투표자가 응답하지 않아 규칙 자동 선택이 발생한다 | **fallback 후보 규칙 불일치.** 의사 자동 보호에 본인을 포함한다. 정본은 의사·탐정 무응답 시 본인 제외다. 자동투표는 모든 역할에서 숨겨진 역할을 읽어 비마피아를 우선한다. 정본의 유효 후보 기반 결정적 선택으로 맞춰야 한다. 의사의 수동 자기 보호 허용과는 별개다. | [fallback.py](../backend/app/agent/fallback.py) L17~19, L28~43; 마스터플랜 3.5·3.7절 | B4 |
| G07 · P0 | 탐정이 조사하고 다음 낮 또는 사망 후 관전에서 기존 조사 결과를 확인한다 | **개인 정보 전달·표시 미완성.** 공개 snapshot의 `me.private_events`는 항상 빈 배열이다. Front 생존 패널은 `event.message`만 읽고 관전 패널에는 조사 이력 표시가 없다. 정본 `INVESTIGATION_RESULT`의 대상·round·`is_mafia` 판정을 본인에게 전달하고 표시해야 한다. | [game_service.py](../backend/app/services/game_service.py) L1013; [game_engine.py](../backend/app/agent/game_engine.py) L327~330; [game_page.py](../frontend_user/app_pages/game_page.py) L422, L524 | B5·B7·F3·F6 |
| G08 · P1 | 아침 사망자, 처형 역할, 후보별 최종 득표수와 재투표 사유를 확인한다 | **공개 결과 기록·표시 부분 구현.** 탈락 원인을 해소 후 phase로 기록해 처형 역할 공개 조건과 어긋날 수 있고, 밤·투표 해소 공개 이벤트가 충분히 만들어지지 않는다. Front도 `VOTE_RESOLVED`에 집계 확정 문구만 표시한다. 원인·round·득표수를 기록하고 밤 역할 비공개/처형 역할 공개를 구분해야 한다. | [game_service.py](../backend/app/services/game_service.py) L900~908, L963~971, L2297~2332; [game_page.py](../frontend_user/app_pages/game_page.py) L563 | B4·B5·B7·F3·F4·F6 |
| G09 · P1 | 인간 사망 후 아무 버튼 없이 관전하고, 필요하면 빠른 진행을 켠다 | **관전 자동 진행 미연결.** 독립 scheduler가 없어 AI가 계속 진행하는 흐름이 없다. `FAST_FORWARD`는 선택 상태를 저장하는 대신 한 요청에서 종료까지 반복 진행하고, snapshot은 선택 여부와 무관하게 인간 사망을 enabled로 표시한다. 관전 지속 진행과 빠른 진행 상태·deadline 계약을 연결해야 한다. | [game_engine.py](../backend/app/agent/game_engine.py) L462~485; [game_service.py](../backend/app/services/game_service.py) L873~874, L1001 | B5·B6·F6 |
| G10 · P1 | 종료 후 전체 역할·밤 행동·조사·개별 투표·주요 발언을 복기한다 | **결과 상세 부분 구현.** Backend 결과는 승패·종료 시각·역할 목록 위주이며 `nights`, `votes`, `public_event_ids` 등 정본 상세가 없다. Front에도 공격 선택·개별 ballot·조사 상세 대신 요약/건수만 표시하는 부분이 남았다. 원장부터 결과 응답·화면까지 연결해야 한다. | [game_service.py](../backend/app/services/game_service.py) L1112~1128; [result_page.py](../frontend_user/app_pages/result_page.py) L201~248 | B3·B5·B7·F6 |
| G11 · P1 | 새 게임을 반복 생성하고 모든 좌석의 시나리오·페르소나·개인 단서 배정을 확인한다 | **정적 카탈로그 미연결.** 5개 시나리오·90개 template 및 DB 생성 서비스는 존재한다. 공개 API는 하드코딩 시나리오 순회 선택과 인간 좌석 1의 고정 형식 문장을 사용한다. 현재도 연속 중복은 피하지만, 정본의 직전 시나리오만 제외한 후보 중 seed 선택과는 다르다. 이 선택 규칙과 각 AI 개인 단서·페르소나 배정을 실제 생성 경로에 연결해야 한다. | [game_service.py](../backend/app/services/game_service.py) L315~406, L464~482, L691~702; [004 seed SQL](../backend/migrations/004_seed_scenarios_and_personas.sql) | B2·B3·B5 |

## 3. 사용자·관리자 화면과 동기화에서 남은 부분

기준: [화면 정본](개발상세플랜/AI_MAFIA_SCREEN_FLOW.md) 2·5·9~15절, [API 정본](개발상세플랜/AI_MAFIA_API_SPEC.md) 3~7절.

| ID·우선 | 테스트 장면·기대 동작 | 현재 상태와 남은 작업 | 코드 근거 | 관련 WU |
|---|---|---|---|---|
| F01 · P1 | UUID를 복구·교체한 뒤 브라우저를 새로고침한다 | **복구 UUID 저장 미연결.** 설정 화면은 Python session만 바꾸고 브라우저 bridge는 기존 localStorage를 다시 읽는다. 교체 UUID를 localStorage에 쓰는 경로가 없다. 사용자 scope 초기화에서 `home.*`도 빠져 이전 UUID 목록이 남을 수 있다. | [settings_page.py](../frontend_user/app_pages/settings_page.py) L35~42; [session.py](../frontend_user/core/session.py) L30~38; [identity/index.js](../frontend_user/components/browser_components/identity/index.js) L8~11 | F1·F2 |
| F02 · P0 | 저장 게임의 계속하기를 눌러 같은 단계로 재개한다 | **RESUME 동선 미구현.** 홈은 game 화면으로만 이동하고 Front에는 RESUME 제출 경로가 없다. dispatcher도 `SAVED` 전용 분기가 없어 정상 재개가 안 된다. 저장 상태 안내→RESUME→확정 snapshot 재조회가 필요하다. | [home_page.py](../frontend_user/app_pages/home_page.py) L159~167; [app.py](../frontend_user/app.py) L91~97; [action_panel.py](../frontend_user/components/action_panel.py) L448 | F2·F4 |
| F03 · P0 | 화면을 켜 둔 채 다음 행동을 기다리고 SSE 단절·백그라운드 복귀를 거친다 | **지속 동기화 미연결.** Backend SSE는 최초 sync+heartbeat 후 종료하고 `id:`가 없다. delta도 게임 상태·일부 공개 이벤트만 만들어 생사·private·window·결과 갱신이 빠졌다. Front polling/retry 정책은 있으나 timer·재접속·visibility 복귀가 연결되지 않고 render 시 sync 1회만 호출한다. | [scaffold_game_router.py](../backend/app/routers/scaffold_game_router.py) L246~257; [game_service.py](../backend/app/services/game_service.py) L910~955; [sync/index.js](../frontend_user/components/browser_components/sync/index.js); [game_page.py](../frontend_user/app_pages/game_page.py) L193~214 | B5·B7·F5 |
| F04 · P1 | 같은 sync batch를 재수신해도 기록이 한 번만 보인다 | **중복 제거·schema 검증 부분 구현.** reducer 호출마다 index를 -1로 시작해 이미 반영한 마지막 sequence의 index 0부터 재적용할 수 있다. 이벤트는 단순 append하며 `schema_version` 검증도 없다. 완전히 적용한 batch 재수신 거부와 버전 검증이 필요하다. | [sync.py](../frontend_user/core/sync.py) L50~71, L106~109 | F5 |
| F05 · P1 | 밤·투표의 남은 시간이 줄고 0초에 입력이 잠긴다 | **화면 countdown 미구현.** `remaining_ms`를 정적인 문자열로 표시하며 서버 시각 보정·실시간 timer가 없다. 별도 rerun이 없으면 표시·제출 잠금이 시간 경과를 따라가지 못한다. G02의 서버 deadline 보완과 함께 확인해야 한다. | [action_panel.py](../frontend_user/components/action_panel.py) L186, L251, L280, L448, L471 | F4·F5 |
| F06 · P1 | 생성·저장·종료 후 홈 목록을 갱신하고 세 번째 게임·완료 게임·다음 페이지를 연다 | **목록 부분 구현.** 최초 `home.games` cache를 정상 상태에서 재조회하지 않는다. 탭은 HTML 장식이고 완료/실패 게임은 제외하며 최대 두 카드만 렌더링한다. 공개 목록 API도 cursor를 버리고 `next_cursor=None`을 반환한다. 상태 갱신·실제 필터·전체 목록·pagination 연결이 필요하다. | [home_page.py](../frontend_user/app_pages/home_page.py) L58~64, L98~116, L143~144; [scaffold_game_router.py](../backend/app/routers/scaffold_game_router.py) L162~170 | F2·B5 |
| F07 · P1 | 생성·시작·저장 POST의 응답이 유실된 뒤 안전하게 다시 확인한다 | **일부 멱등 UX 미완성.** 생성/시작의 `RETRYABLE_UNKNOWN`에서 원래 CTA가 열려 새 key로 기존 pending을 덮을 수 있다. 저장 버튼은 매번 새 key를 생성하며 결과 불명 pending을 보존하지 않는다. 기존 요청이 확정될 때까지 동일 요청·key를 유지하는 흐름이 필요하다. | [game_create_page.py](../frontend_user/app_pages/game_create_page.py) L90~106; [role_reveal_page.py](../frontend_user/app_pages/role_reveal_page.py) L149~153, L195; [game_page.py](../frontend_user/app_pages/game_page.py) L718~734 | F2·F3·F4 |
| F08 · P1 | 홈에서 일반 서비스 피드백을 작성한다 | **일반 피드백 진입 미연결.** GENERAL 폼·dispatcher·API는 있으나 해당 페이지로 이동시키는 UI가 없다. 홈의 피드백 문구는 `span`이다. 게임별 피드백은 별도 구현되어 있으므로 구분한다. | [app.py](../frontend_user/app.py) L56~64; [home_page.py](../frontend_user/app_pages/home_page.py) L75; [feedback_page.py](../frontend_user/app_pages/feedback_page.py) L97 | F2·F7 |
| F09 · P1 | 관리자가 등록 UUID로 접근하고 상태별 게임을 조회한다 | **관리자 화면 연결 일부 미구현.** UUID 직접 입력·교체 화면 없이 bridge가 UUID를 생성한다. 목록 status/phase 필터와 cursor 인자가 client에는 있지만 화면에서 연결되지 않았다. app은 Backend 주소도 client 기본 loopback 값으로 사용한다. UUID 입력·설정 전달·필터 동선이 필요하다. 공개 게임과 관리자 데이터 분리는 D02 참조. | [frontend_admin/app.py](../frontend_admin/app.py) L34~65; [관리자 identity bridge](../frontend_admin/components/identity_bridge.py) L28; [관리자 api_client.py](../frontend_admin/core/api_client.py) L31~48; [game_list_page.py](../frontend_admin/app_pages/game_list_page.py) L19 | F8 |
| F10 · P2 | 게임 생성 완료 화면과 실제 참가자 이름을 대조한다 | **목데이터 잔존.** 생성 완료 화면은 snapshot의 players 대신 고정 `PLAYER_NAMES`를 표시한다. 실제 생성 결과와 같은 참가자 표시로 연결해야 한다. | [creation_complete_page.py](../frontend_user/app_pages/creation_complete_page.py) L8, L38 | F2·F3 |

## 4. 실제 AI·MCP 연결을 막는 부분

기준: [API 정본](개발상세플랜/AI_MAFIA_API_SPEC.md) 8~10절, [MCP 서버 설계](개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)의 WU-M4·M6·M7 및 미결정 사항. **MCP Resource 자체는 구현되어 있다.** 다음은 그 Resource를 실제 Backend 게임과 사용하는 데 남은 경계다.

| ID·우선 | 테스트 장면·기대 동작 | 현재 상태와 남은 작업 | 코드 근거 | 관련 WU |
|---|---|---|---|---|
| M01 · P0 | AI job이 새 자격으로 MCP에 연결해 Resource를 읽는다 | **실제 Agent MCP client 미구현·미연결.** AgentContextClient는 Protocol/Fake만 있고 기존 GameMcpClient는 인증 header 없이 구 `game_ping`, `game_get_context`, `game_submit_proposal` Tool을 호출한다. 정본 bootstrap·capability·Resource·session 종료를 지원하는 client가 필요하다. 환경 변수 설정만으로 해결되지 않는다. | [client.py](../backend/app/mcp/client.py) L13, L23; [game_client.py](../backend/app/mcp/game_client.py) L23~55 | B6·B7·M6 |
| M02 · P0 | 유효 자격으로 MCP initialize를 완료한다 | **consume 응답 계약 불일치.** Backend는 `status` 하나만 반환하지만 MCP는 status·scope·phase·state_version·window_id의 5-field binding을 요구한다. Backend를 정본에 맞춰야 하며 MCP 검증을 느슨하게 만들어서는 안 된다. 현재 조합은 유효 자격을 준비해도 이 응답 검증에서 실패한다. | [internal_engine_service.py](../backend/app/services/internal_engine_service.py) L88~115; [bootstrap schema](../mcp_server/mafia_game/schemas/bootstrap.py) L72~103 | B7·M6 |
| M03 · P0 | Resource 조회 및 proposal 제출이 실제 게임 상태를 사용한다 | **Engine handler 미연결·projection 보완 필요.** 기본 내부 API 조립에 context_provider/proposal_handler가 없어 해당 단계에서 503이 발생한다. 기존 public projection도 사망자의 탈락 phase/round를 null로 반환하고 처형 역할을 즉시 공개하지 않아 정본 보완이 필요하다. 실제 원본 상태·audience 검증을 갖춘 provider와 행동 반영기를 연결해야 한다. | [scaffold_mcp_router.py](../backend/app/routers/scaffold_mcp_router.py) L32~41; [internal_engine_service.py](../backend/app/services/internal_engine_service.py) L130, L172; [projections.py](../backend/app/agent/projections.py) L123~132 | B5·B7·M6 |
| M04 · P0 | AI가 발언·PASS·밤 행동·투표를 MCP Tool로 제출한다 | **Tool 미구현.** `api/tools`는 예약 패키지이고 main에는 Resource handler만 등록된다. 네 `propose_*` Tool, Engine proposal adapter, 동일 proposal 재시도 및 terminal 세션 처리가 필요하다. GM 행동 Tool은 정본상 대상이 아니다. | [api/tools/__init__.py](../mcp_server/mafia_game/api/tools/__init__.py); [MCP main.py](../mcp_server/mafia_game/main.py) L52~57; [engine_http.py](../mcp_server/mafia_game/integrations/engine_http.py) L108, L135 | M4·M6 |
| M05 · P1 | MCP 단절·재시작·consume 응답 유실 뒤 같은 유효 job을 복구한다 | **재접속 조정 미완료.** 서버의 거부·정리와 orchestrator fallback/revoke는 있지만 실제 client 및 fresh credential 재발급 왕복이 없다. Backend가 job 상태를 확인하고 기존 자격을 폐기한 뒤 새 capability·bootstrap·session으로 연결하는 검증이 남았다. | [orchestrator.py](../backend/app/agent/orchestrator.py) L105~151; [client.py](../backend/app/mcp/client.py); [MCP README](../mcp_server/mafia_game/README.md) 재접속·운영 제한 | B6·B7·M7 |

## 5. 데이터·운영 준비에서 남은 부분

기준: [DB 설계](개발상세플랜/AI_MAFIA_DB_DESIGN.md), [마스터플랜](개발상세플랜/AI_MAFIA_MASTER_PLAN.md) 7~11절. DB·Redis 코드와 migration SQL은 Backend 소유이고, 인스턴스 준비·계정·migration 실행·health 확인은 MCP·Data 담당이다.

| ID·우선 | 테스트 장면·기대 동작 | 현재 상태와 남은 작업 | 코드 근거 | 관련 WU |
|---|---|---|---|---|
| D01 · P0 | 정상 seed 5개를 넣어 migration 004를 완료한다 | **SQL 정적 결함. DB 재현은 미실시.** 검증식이 정상 행 수가 아니라 비정상 조건에 맞는 행 수를 세고 `5 - count(*)`를 계산한다. 정상 5개라면 비정상 행은 0개여서 값 5가 되어 예외를 발생시킨다. Backend 수정 산출물과 실제 migration 최초/재실행 검증이 필요하다. | [004_seed_scenarios_and_personas.sql](../backend/migrations/004_seed_scenarios_and_personas.sql) L361~376 | B2·M1B |
| D02 · P0 | 생성·저장·피드백 후 Backend를 재시작하고, 여러 worker·관리자에서 같은 데이터를 조회한다 | **영속화·공통 저장소 미연결.** 기본 공개 게임·receipt·feedback은 InMemoryGameRepository이며 사용자 upsert와 관리자 저장소만 PostgreSQL이다. DB 생성/명령 서비스는 있지만 기본 router에 연결되지 않고 DB reader는 ROLE_REVEAL/version 1만 복원한다. 진행 상태 복원·DB transaction/Redis lock·outbox·관리자 조회를 같은 데이터에 연결해야 한다. 현재 게임·피드백은 재시작 시 소실되고 worker별로 분리된다. | [scaffold_game_router.py](../backend/app/routers/scaffold_game_router.py) L48~57; [game_service.py](../backend/app/services/game_service.py) L141~160, L2172~2173; [main.py](../backend/app/main.py) L99~107; [outbox_service.py](../backend/app/services/outbox_service.py) | B3·B5·B7·B8·B9 |
| D03 · P1 | migration 전용 DDL 계정과 Backend DML 계정을 분리해 실행한다 | **runner 설정 미완료.** runner는 `DATABASE_MIGRATION_URL`을 직접 선택하지 않고 `settings.effective_database_url`을 사용한다. README에 격리 주입 절차가 있지만 목표 전용 설정 경로와 다르다. 전용 DSN 선택 구현과 대상 환경 권한 확인을 나누어 완료해야 한다. | [migrations.py](../backend/app/infrastructure/migrations.py) L21~38; [README](../README.md) migration 안내; 마스터플랜 11절 | B2·M1A·M1B |
| D04 · P2 | 게임 테스트 장애를 허용된 metadata 로그로 추적한다 | **감사 로그 부분 구현.** MCP의 안전한 record·redaction·sink 주입과 기존 경로 계측은 있다. 기본 sink는 기록을 폐기하며 운영 sink·보존 정책·Tool 계측은 남았다. 기존 M5 선행 구현을 전체 미구현으로 보지 않는다. | [audit.py](../mcp_server/mafia_game/core/audit.py) L128; [MCP README](../mcp_server/mafia_game/README.md) 감사 로그 범위; 마스터플랜 8.3절 | M4·M5·M8 |
| D05 · P1 | 세 섹터를 별도 시스템에서 기동하고 정상 연결·중지·재시작을 확인한다 | **배포 운영 경로 미완료.** MCP entrypoint 설정은 loopback만 허용하고 배포 TLS·health 판정은 미결정이다. 기존 Backend MCP health도 구 Tool에 의존한다. 로컬 독립 실행 안내와 분리 배포 준비를 구분하고 실제 health·TLS·재시작 절차를 완성해야 한다. | [MCP config.py](../mcp_server/mafia_game/core/config.py) L45; [game_client.py](../backend/app/mcp/game_client.py) L15~29; [MCP 서버 설계](개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md) OPEN-05·OPEN-06, WU-M8 | M6·M8 |

## 6. 미구현으로 단정하지 않고 실행·승인을 확인할 항목

| 확인 항목 | 현재 확인 범위 | 실제 게임 테스트 전에 필요한 증거 |
|---|---|---|
| PostgreSQL·Redis 인스턴스와 계정 | 코드·문서만 확인했다. 로컬 또는 팀 서버가 실제로 준비되어 있는지는 조사하지 않았다. | 정확한 대상의 기동·health, DDL/DML 권한 분리, migration 최초·재실행 결과. 인프라가 없다고 단정하지 않는다. |
| 시나리오 콘텐츠 제품 승인 | 90개 template 및 정적 검사 코드가 있다. DB의 approved 값만으로 별도 제품 검수가 끝났다고 보지 않는다. | 6~9명별 역할 중립성·무모순·개인 단서 배치에 대한 제품 승인 기록. |
| 실제 통합 E2E | [test_end_to_end_game.py](../backend/tests/test_end_to_end_game.py)는 heuristic 규칙 시뮬레이션이다. B5·B7·MCP 테스트는 메모리 저장소·fake handler·fake Engine 등으로 경계를 대체한다. | Front→Backend→DB/Redis→MCP→Backend의 생성·진행·종료·복구 왕복. LLM은 먼저 fake로 검증하고, 유료 호출은 명시적 필요가 있을 때만 수행한다. |
| 브라우저 복구·반응형·접근성 | 코드 분기만 확인했으며 실제 페이지, 320px 화면, 확대, storage 실패, 네트워크 전환은 실행하지 않았다. | 새로고침·다중 탭·응답 유실·백그라운드 복귀, 좁은 화면·키보드 조작 확인. 레이아웃 불량을 이번 조사에서 재현했다고 보지 않는다. |

## 7. 이미 존재하는 구현과 의도된 제외

| 범위 | 현재 존재하는 구현 |
|---|---|
| 사용자 기본 흐름 | UUID 최초 생성·브라우저 저장, X-User-Id client, 6~9명 생성, snapshot 조회, 역할·알리바이·관찰 표시, BEGIN_GAME |
| 행동·규칙 | SPEAK/PASS·역할별 밤 행동·투표 UI/API, 순수 엔진과 결정적 RNG, 사망자 행동 제한, 저장·재개 엔진 메서드. 위 표의 계약 불일치와 실제 연결 문제는 별도다. |
| 관전·종료·피드백 | 관전 화면·FAST_FORWARD 호출, 서버 결과 기반 승패·전체 역할 표시, 일반/게임별 피드백 폼·validation·POST. 모든 진입 동선과 상세 데이터가 완성됐다는 뜻은 아니다. |
| Backend 기반 | PostgreSQL repository·일부 영속 명령 서비스, Redis lock/cache/outbox, 내부 API 인증 경계, read-only 관리자 API·allowlist·redaction |
| MCP | WU-M2 bootstrap·세션·idle/DELETE 정리, WU-M3 다섯 Resource·subject allowlist·폐쇄형 schema·HMAC context adapter, WU-M5 선행 로그 경계 |

OAuth/OIDC 로그인, 멀티 인간 플레이, 마피아 전용 채팅·상호 인지, 사용자 메모, LLM token·비용·timeout 운영 UI, GM 행동 Tool, MCP runtime의 DB·Redis 직접 접근은 정본상 제외다. 이 목록에 미구현 기능으로 추가하지 않는다.

## 8. 후속 테스트 순서와 이번 검증

1. **환경·데이터:** D01·D03 수정/연결 후 대상 DB·Redis·migration을 확인하고 D02 영속 경로를 완성한다.
2. **fake 기반 한 판:** G02~G10의 규칙·정보·종료 공백, F02~F07의 재개·동기화를 먼저 검증한다. 6·7·8·9인과 인간 사망·다섯째 밤 경로를 포함한다.
3. **실제 Agent·MCP:** M01~M04와 G01을 연결한 후 정상 왕복, M05의 장애 복구, audience 격리를 확인한다.
4. **사용자·운영 마무리:** UUID 복구·홈·일반 피드백·관리자 동선, 콘텐츠 승인, 감사 로그·분리 배포 증거를 확보한다.

위 순서는 의존 관계를 정리한 것이며 이번 요청에서 기능 수정은 수행하지 않았다.

| 이번 검증 | 결과 |
|---|---|
| 저장소 지침·정본·실제 composition root·호출 경로·테스트 대체 경계 조사 | 완료. 미커밋 구현을 포함해 Front/Backend/MCP를 대조했다. |
| 보고서·README diff, 문서 내부 파일 링크, 표 구조 확인 | 완료. 기존 사용자 변경을 유지하고 보고서와 안내만 추가했다. |
| 자동 테스트·전체 회귀·브라우저 게임 테스트 | **미실행.** 문서 작성·읽기 전용 조사이므로 저장소의 테스트 0단계를 적용했다. 과거 통과 수치를 이번 실행 결과로 사용하지 않았다. |
| DB·Redis·migration·실제 Provider·Backend↔MCP 호출 | **미실행.** 실제 환경의 성공·실패를 이번 점검 결과로 주장하지 않는다. |
| 커밋·푸시 | 수행하지 않았다. |
