# 전체 프로젝트와 MCP 서버를 쉽게 이해하는 안내서

작성일: 2026-09-06  
기준: `Hwanseok` 브랜치의 `5292c2a`와 현재 미커밋 작업 파일  
성격: 학습·검토용 임시 설명서. 기존 설계 정본을 바꾸거나 대체하지 않는다.

이 문서는 처음 저장소를 보는 사람도 “어떤 프로그램들이 있고, 서로 무엇을 주고받으며,
MCP가 그중 어디에 있는지” 이해할 수 있도록 작성했다. 코드가 있는 부분과 실제 실행
경로에 연결된 부분을 구분한다. 실제 서버·DB·LLM을 가동해 확인한 운영 보고서는 아니다.

함께 볼 자료:

- [전체 섹터 구조도](sectors-overview.html): 큰 그림부터 볼 때.
- [MCP 상세 구조도](mcp-detail.html): MCP 내부 구성과 연결 상태를 볼 때.
- [구조도 설명·코드 근거·검증 결과](README.md): 확인한 파일과 줄 번호를 찾을 때.

## 1. 가장 먼저 기억할 다섯 문장

1. 이 프로젝트는 인간 한 명과 여러 AI가 마피아 게임을 하도록 만드는 프로젝트다.
2. Front는 게임을 보여 주고 입력을 받으며, Backend는 규칙에 맞는지 판단한다.
3. LLM은 대사와 선택을 만드는 역할이지, 게임 규칙이나 승패를 마음대로 바꾸는 심판이 아니다.
4. 이 프로젝트의 MCP 서버는 AI 측 프로그램에 **허용된 게임 정보만 제공하는 창구**다.
5. 현재 MCP의 세션·Resource 코드는 있지만, 실제 Backend 연결과 행동 Tool은 아직 남아 있다.

목표 게임은 전체 6~9명 중 인간 1명, AI 5~8명으로 구성된다. 낮에는 대화하고,
밤에는 역할별 행동을 하며, 투표와 규칙 판정을 거쳐 게임을 끝낸다. 이는 제품 목표의
설명이며, 현재 모든 사용자 흐름이 실제 AI와 연결되어 완주된다는 뜻은 아니다.
근거는 [공통 마스터플랜](../개발상세플랜/AI_MAFIA_MASTER_PLAN.md)의 2·3절이다.

## 2. 게임을 운영하는 사람들에 비유하면

| 구성요소 | 쉬운 비유 | 실제 책임 |
|---|---|---|
| 사용자 Front | 참가자가 보는 게임판과 버튼 | 상태 표시, 행동 입력, 결과 표시 |
| 관리자 Front | 운영자가 보는 상황판 | 허용된 지표·게임 목록·상세 조회 |
| Backend | 심판과 진행본부 | 규칙 판정, 상태 변경, 소유권·권한 확인 |
| LLM | AI 참가자의 대사·선택을 만드는 역할 | 허용된 자료를 바탕으로 구조화된 결과 생성 |
| Agent Manager | AI 차례를 배정하는 진행 담당자 | 작업 예약, 실행, 늦은 결과 거부, 실패 시 대체 처리 |
| MCP 서버 | 출입증을 확인하는 자료실 창구 | 허용된 자료 조회, 정해진 요청 형식과 정보 범위 검증 |
| PostgreSQL | 오래 보관하는 공식 장부 | 사용자·게임·권한 등의 영속 저장을 맡는 목표 저장소 |
| Redis | 빠른 임시 게시판과 작업 조정 장치 | 잠금·캐시·이벤트 전달을 맡는 목표 보조 저장소 |

이 비유에서 가장 중요한 점은 **자료실 직원이 심판의 결정을 대신하지 않는다**는 것이다.
MCP는 요청과 응답을 검사하지만, 누가 살아 있는지·지금 투표할 수 있는지·누가 이겼는지를
독자적으로 결정하지 않는다. 최종 판단은 Backend가 맡는다.

또한 위 표에는 목표 역할이 포함되어 있다. 현재 공개 게임은 메모리 저장소를 사용한다.
“PostgreSQL 코드가 있다”와 “공개 게임이 PostgreSQL에 저장된다”는 서로 다른 말이다.

## 3. 폴더를 읽는 지도

아래는 주요 경로만 추린 지도다. 모든 파일과 개발 도구 폴더를 나열한 목록은 아니다.

```text
Team4_Proj_0831/
├── backend/                  게임 판정·공개 API·내부 API
│   ├── app/
│   │   ├── main.py           Backend 구성요소를 조립하는 시작점
│   │   ├── routers/          URL별 요청을 받는 입구
│   │   ├── schemas/          요청·응답의 형식 검사
│   │   ├── models/           게임 상태·플레이어 등 내부 데이터 표현
│   │   ├── services/         생성·행동·조회 등 업무 처리
│   │   ├── agent/            규칙 엔진과 Agent 작업 조정 코드
│   │   ├── repositories/     데이터를 읽고 쓰는 코드
│   │   ├── infrastructure/   PostgreSQL·Redis·보안·transaction 구현
│   │   ├── llm_provider/     LLM 호출 방식의 차이를 감싸는 어댑터
│   │   └── mcp/              Backend 쪽 MCP 호출자 코드
│   ├── migrations/           DB 구조와 기초 데이터를 준비하는 SQL
│   └── tests/                Backend 검증
├── frontend_user/            일반 참가자용 화면
│   ├── app.py                화면을 선택하는 시작점
│   ├── app_pages/            홈·생성·진행·결과·설정·피드백 화면
│   ├── components/           공통 UI와 브라우저 UUID/SSE 연결 부품
│   ├── core/                 API 호출·화면 상태·command·동기화 처리
│   └── tests/                사용자 화면 검증
├── frontend_admin/           별도 관리자 화면과 조회 client
├── mcp_server/
│   ├── pyproject.toml        MCP 전용 의존성·검증 설정
│   ├── uv.lock               재현 가능한 MCP 의존성 버전 기록
│   ├── mafia_game/           실제 게임용 MCP 서버 패키지
│   ├── mcp_2/                후속 용도의 예약 패키지
│   └── tests/                MCP 독립·계약 검증
├── docs/
│   ├── 개발상세플랜/         제품·API·DB·화면·MCP의 정본
│   └── temp/                 현재 구조도와 이 임시 설명서
├── tests/                    통합·E2E 검증 확장 위치
├── scripts/                  보조 스크립트; 기존 OIDC 설정 도구 등
├── pyproject.toml            루트 Python 의존성·개발 도구 설정
└── README.md                 프로젝트 실행·설정·현재 상태 안내
```

### 3.1 같은 이름처럼 보여도 다른 두 폴더

`backend/app/mcp/`는 **MCP에 요청을 보내는 쪽**이다. 반대로
`mcp_server/mafia_game/`는 **MCP 요청을 받는 쪽**이다.

전화에 비유하면 앞은 전화를 거는 단말기이고, 뒤는 전화를 받는 창구다. 둘 다 코드가
있더라도 전화번호·인증 방법·요청 형식이 맞아야 통화할 수 있다. 현재 Backend에는
과거 scaffold client와 별개로 새 Agent용 client 인터페이스와 테스트용 Fake가 있다.
하지만 새 MCP endpoint·인증·Resource 계약으로 통신하는 실제 client 연결은 아직 없다.
근거: [Backend MCP client](../../backend/app/mcp/client.py).

Backend의 `schemas/`는 HTTP 요청·응답 양식을 뜻한다. DB 테이블을 만드는 SQL schema와
같은 것이 아니다. `models/`는 코드 안에서 게임 상태 등을 표현하고, `migrations/`의
SQL은 DB 저장 구조를 준비한다.

### 3.2 폴더가 있다고 실행되는 것은 아니다

`mcp_2/`, MCP의 `api/tools/`·`api/prompts/`, `integrations/database/`·`redis/`·`embedding/`
등에는 예약용 파일이 있다. 이것만 보고 두 번째 MCP 서버, 행동 Tool, DB 직접 연결이
구현됐다고 판단하면 안 된다. 실제 시작점에서 어떤 객체와 handler를 등록하는지 봐야 한다.

사용자 Front의 OIDC 관련 `auth/`, `login_page.py` 등도 과거 코드가 남은 경우다.
현재 UUID 기반 시작 흐름과 구분해서 읽어야 한다. 파일 이름이 `scaffold_game_router.py`인
Backend 라우터에는 현재 정본 게임과 과거 호환 경로가 함께 있으므로, 이름만 보고
전체를 사용하지 않는 코드라고 판단해서도 안 된다.

## 4. 실제로는 여러 프로그램이 나누어 실행된다

저장소 하나가 프로그램 하나를 뜻하지는 않는다. 주요 실행 단위는 다음과 같다.

| 실행 단위 | 개발 시 안내 주소·포트 | 역할 |
|---|---|---|
| 사용자 Streamlit | `:8501` | 인간 플레이어의 화면 |
| 관리자 Streamlit | `:8502` | 관리자용 별도 조회 화면 |
| Backend FastAPI | `:8000` | 공개 API와 내부 Engine API |
| Mafia Game MCP | `127.0.0.1:8100/mcp` | AI 측 MCP 요청 처리 |

주소는 개발 설정을 이해하기 위한 값이지, 지금 해당 서버가 실행 중이라는 표시가 아니다.
MCP는 별도 Python 환경을 갖고 있으며 현재 `mcp_server/pyproject.toml`은 Python 3.12와
MCP SDK `1.29.1`을 기준으로 고정한다. 루트의 의존성 설정과 혼용하지 않는 것이 중요하다.

Front에는 Python으로 실행되는 Streamlit 부분과 브라우저에서 실행되는 JavaScript
컴포넌트가 함께 있다. 따라서 “프론트에서 호출한다”는 말도 실행 위치를 나누어 봐야 한다.

- 게임 생성·command·sync·피드백 REST 호출: Streamlit의 Python API client.
- 사용자 이벤트 스트림 SSE 호출: 브라우저 JavaScript의 `fetch`.
- UUID 보관: 브라우저 local storage. 게임 전체 상태를 여기에 보관한다는 뜻은 아니다.

## 5. 사용자가 버튼을 누르면 무슨 일이 생길까?

예를 들어 현재 허용된 투표 버튼을 누르는 상황을 생각해 보자.

1. **화면이 현재 상태를 읽는다.** Backend가 준 snapshot과 `legal_actions`를 기준으로
   무엇을 보여 줄지 결정한다. snapshot은 “지금 화면에 필요한 상태 묶음”이다.
   모든 플레이어의 비밀을 포함한 게임 원본이나 저장 파일을 뜻하지 않는다.
2. **Front가 행동 요청을 만든다.** 게임 ID, 행동 종류, 선택 대상 등을 정해진 command
   형식으로 만든다. `X-User-Id`에는 현재 사용자 식별자를 넣는다.
3. **중복·오래된 요청을 구분할 정보를 붙인다.** 변경 요청에는 `Idempotency-Key`,
   게임 command에는 `expected_state_version`을 사용한다.
4. **Backend가 다시 판단한다.** 사용자 소유 게임인지, 지금 가능한 행동인지, 대상과
   상태 버전이 맞는지 확인한다. 화면에서 버튼을 보였다는 이유만으로 승인하지 않는다.
5. **게임 서비스와 규칙 엔진이 처리한다.** 유효한 요청의 결과를 현재 저장소에 반영한다.
6. **Front가 서버 결과로 화면을 갱신한다.** 성공을 미리 추측해 확정하지 않고 응답과
   snapshot/sync를 기준으로 표시한다.

이때 `Idempotency-Key`는 “같은 주문을 두 번 배달하지 않도록 붙이는 주문번호”에
가깝다. `expected_state_version`은 “내가 보고 누른 게임판이 몇 번째 수정본인가”다.
마지막으로 본 상태가 오래됐다면 Backend가 그대로 처리하지 않도록 돕는다.

현재 사용자 게임의 주 경로는
[scaffold_game_router.py](../../backend/app/routers/scaffold_game_router.py)의
`canonical_service`와 [game_service.py](../../backend/app/services/game_service.py)다.
게임 상태 기본 저장소는 메모리지만 사용자 최초 쓰기 준비는 PostgreSQL을 사용한다.
따라서 **메모리 게임이라는 이유로 DB 없이 기본 앱을 실행할 수 있다고 보면 안 된다.**

SSE는 “새 소식이 생기면 보내 주는 연결”, polling은 “새 소식이 있나요 하고 다시 묻는
방식”으로 이해하면 된다. 현재 SSE bridge와 `/sync` 코드는 있지만 자동 재접속·주기
타이머·지속적인 outbox 전달까지 완성된 것은 아니다.

### 5.1 실제 예시: 역할을 확인하고 ‘게임 시작’을 누를 때

다음은 현재 코드에서 따라갈 수 있는 `BEGIN_GAME` 경로다.

1. [역할 확인 화면](../../frontend_user/app_pages/role_reveal_page.py)은 `legal_actions`에
   `BEGIN_GAME`이 있을 때 시작 버튼을 보여 준다. 클릭하면 현재 상태 버전과 새 중복 방지
   키를 기억한다.
2. [Front API client](../../frontend_user/core/api_client.py)가
   `POST /api/v1/games/{game_id}/commands`로 `BEGIN_GAME` command를 보낸다.
3. [Backend 라우터](../../backend/app/routers/scaffold_game_router.py)가 요청 형식을
   확인한 뒤 게임 서비스로 넘긴다.
4. [게임 서비스](../../backend/app/services/game_service.py)가 소유권·중복·상태 버전·허용
   행동을 확인하고, 순수 규칙 엔진의 `begin_game`을 적용한다. 상태 변경에 대한 sync
   기록도 준비한다.
5. POST 응답은 전체 화면 데이터가 아니라 **처리 영수증**이다. command ID, 처리 전후
   상태 버전, sync 주소 등을 돌려준다.
6. Front는 게임 화면으로 이동하며 다시 실행되고,
   [app.py](../../frontend_user/app.py)에서 별도 GET으로 최신 snapshot을 읽어 화면을 만든다.

즉 “행동을 접수·처리하는 요청”과 “최신 화면 상태를 읽는 요청”은 다르다. 현재 이 경로에
실제 LLM 호출이나 MCP 자료 조회가 자동으로 끼어 있다고 보면 안 된다.

### 5.2 규칙 엔진·Agent 조정자·LLM은 서로 다른 부품

- **GameEngine:** 현재 상태와 행동을 받아 규칙에 따른 결과를 만든다. 투표·밤 행동·승패
  같은 판정 담당이며 DB·Redis·LLM·MCP를 직접 호출하지 않는 순수 로직이다.
- **AgentOrchestrator:** AI 작업을 예약하고, 필요한 자격·자료·provider를 연결하는 조정
  코드다. 규칙을 대신 만들지 않으며, 현재 공개 게임의 실제 AI 실행 경로에는 아직
  연결되지 않았다.
- **LLM provider:** 모델 서비스를 호출하는 방식의 차이를 감싼다. 모델이 만든 대사나
  선택도 게임 상태에 반영하려면 Backend의 검사를 거쳐야 한다.

`backend/app/agent/` 안에 있다고 모두 모델 호출 코드는 아니다. 현재 공개 게임의 AI
발언 자리는 실제 Agent 실행 대신 PASS 대체 처리를 사용한다. 이 구분을 기억하면
“규칙 엔진이 구현됐다”를 “AI 참가자까지 실제로 플레이한다”로 오해하지 않을 수 있다.
근거: [GameEngine](../../backend/app/agent/game_engine.py),
[AgentOrchestrator](../../backend/app/agent/orchestrator.py),
[공개 게임 서비스](../../backend/app/services/game_service.py).

## 6. MCP란 무엇이며 이 프로젝트에서는 왜 분리했을까?

MCP는 Model Context Protocol의 약자다. AI 애플리케이션과 외부 기능 제공 프로그램이
정해진 메시지 형식으로 자료와 기능을 주고받게 하는 약속이다. 일반적인 구조에는
전체를 조정하는 Host, 연결을 담당하는 Client, 자료·기능을 제공하는 Server가 있다.
[MCP 공식 아키텍처 설명](https://modelcontextprotocol.io/specification/2025-11-25/architecture)

이 프로젝트의 목표 구조에 대입하면 Backend의 Agent 실행 부분이 AI 작업을 조정하고,
그 안의 MCP client가 독립 Mafia Game MCP 서버에 요청한다. **모델 자체가 네트워크
프로그램을 대신 실행하는 것은 아니다.** 모델의 입력·출력과 서버 호출을 실제로
연결하는 애플리케이션 코드가 필요하다. 그 실제 연결이 아직 미완료다.

MCP를 별도로 둔 이유는 다음처럼 이해할 수 있다.

- AI에게 보이는 자료의 종류와 호출 형식을 한 곳에서 명확히 관리한다.
- 특정 AI의 정보가 다른 AI나 GM에게 섞이지 않도록 경계를 둔다.
- Backend의 내부 HTTP 형식을 MCP 메시지로 바꾸는 책임을 분리한다.
- 가짜 Backend를 주입해도 MCP 자체의 검증·세션 처리를 시험할 수 있다.

이것은 게임 정보 접근 경계에 관한 설명이다. MCP를 두었다는 사실만으로 모든 보안
문제가 자동 해결되거나, Backend의 권한 검사가 필요 없어지는 것은 아니다.

### 6.1 MCP 서버와 LLM 서버는 다르다

LLM은 문장을 만들거나 선택을 추론하는 쪽이다. 이 프로젝트의 MCP runtime은 모델을
호출하지 않는다. 이미 정해진 권한 범위에서 자료를 가져와 형식과 대상이 맞는지
검사하고 전달한다. 모델 API key나 비용·토큰 집계 기능도 MCP의 책임이 아니다.

### 6.2 여기서 설명하는 MCP 버전 범위

이 문서는 프로젝트에 고정된 SDK와 정본 계약을 설명한다. 현재 세션 테스트의
`initialize` 요청은 `protocolVersion=2025-11-25`를 사용한다.
일반 개념의 공식 참고 링크도 해당 버전을 사용했다. 최신 MCP 문서의 다른 기능이나
연결 방식을 이 프로젝트에 이미 적용했다고 읽으면 안 된다.

## 7. Resource와 Tool은 어떻게 다를까?

**Resource는 읽을 자료, Tool은 실행할 기능**으로 먼저 구분하면 쉽다.
공식 MCP에서 Resource는 URI로 식별되는 컨텍스트 자료이고, Tool은 client가 호출할 수
있는 기능이다. 이 프로젝트는 그 일반 기능 중 게임에 필요한 일부만 구현한다.
[Resource 명세](https://modelcontextprotocol.io/specification/2025-11-25/server/resources),
[Tool 명세](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

### 7.1 현재 구현된 다섯 Resource

모든 URI는 `mafia://session/`으로 시작한다. 아래는 용도 설명이며 상세 데이터 schema를
새로 정의한 표가 아니다. 실제 schema 정본은 [API 명세](../개발상세플랜/AI_MAFIA_API_SPEC.md)
8.2절이다.

| 끝부분 | 쉬운 설명 | 접근 가능한 주체 |
|---|---|---|
| `public` | 현재 공개된 게임 상황·플레이어·이벤트 | AI 플레이어와 GM |
| `me` | 해당 AI 본인의 역할·개인 사실·허용된 비공개 정보 | AI 플레이어 |
| `turn` | 현재 작업 차례·행동 허용 범위·대상·기한 관련 정보 | AI 플레이어 |
| `persona` | 해당 AI에게 배정된 말투·성격 설정 | AI 플레이어 |
| `gm-guide` | GM이 공개 상황을 설명하는 데 쓸 지침 | GM |

이 표의 접근 가능은 최대 범위다. 각 작업에서 발급된 capability가 허용한 **비어 있지
않은 부분집합**만 사용할 수 있다. AI라고 네 자료를 언제나 모두 받는 것은 아니다.

`me`는 “원하는 사람의 자료”가 아니라 “현재 세션에 묶인 내 자료”다. URI에 다른
플레이어 ID를 붙여 대상을 바꿀 수 없다. GM도 진행자라는 이유로 모든 역할과 비밀을
보지 않으며, `public`과 `gm-guide` 범위만 사용한다.

`resources/list`는 책의 **목차**를 보는 것과 비슷하다. 현재 세션이 읽을 수 있는
Resource 목록만 반환하며 Backend 조회는 하지 않는다. `resources/read`는 목차에서
선택한 **내용**을 가져오는 요청이다. 허용된 read 하나마다 Backend GET을 한 번 한다.

목록에 있는 URI는 인터넷 웹페이지 주소가 아니다. `/mcp`에 보낼 JSON-RPC 요청 안에서
어떤 자료를 읽을지 지정하는 식별자다. 이 서버는 URI 철자와 형태를 정확히 비교하며
대소문자·추가 slash·인코딩 변형을 임의로 같은 주소로 취급하지 않는다.

### 7.2 아직 구현되지 않은 행동 Tool

정본이 계획한 Tool은 `propose_speech`, `propose_pass`, `propose_night_action`,
`propose_vote`다. 각각 발언, 차례 넘기기, 밤 행동, 투표를 **제안**한다.
현재 MCP 서버에는 이 Tool들이 등록되지 않았다.

이름에 `propose`가 붙는 이유가 중요하다. 목표 경로에서도 MCP의 Tool 요청만으로
게임 상태가 확정되지 않는다. Backend가 권한·차례·대상·버전·기한을 재검증한 결과가
최종 결과다. GM은 행동 Tool을 쓰지 않고 생성한 설명을 Backend Agent Manager에
직접 반환하도록 계획되어 있다.

## 8. 세션과 출입증을 구분해서 이해하기

게임 한 판, AI 한 명, AI의 작업 한 건은 서로 다르다. 한 AI도 게임 중 여러 번 말하거나
투표한다. 여기서 `job`은 “이번 차례에 수행할 한 번의 AI 작업”에 가깝다.
목표 계약은 작업을 예약할 때마다 새 자격과 새 MCP 세션을 발급하는 것이다.

| 용어 | 비유 | 실제 의미 |
|---|---|---|
| Bootstrap token | 입장할 때 확인하는 서명된 초대장 | 누가 어떤 작업으로 세션을 열 수 있는지 증명 |
| Agent capability | 작업 범위가 제한된 출입증 | Backend가 발급하고 확인하는 불투명한 권한 값 |
| MCP session ID | 입장 후 받은 접수번호 | 서버가 어떤 활성 세션인지 찾는 번호 |
| Issuance binding | 입장 당시 고정한 작업 내용 | 허용 scope·phase·state version·window |
| HMAC 서명 | 서버 요청에 붙이는 위변조 확인표 | MCP→Backend 내부 요청의 내용·발신 경계 검증 |

초대장, 출입증, 접수번호를 같은 것으로 보면 안 된다. 특히 **session ID만 알아서는
후속 요청의 owner 확인을 통과할 수 없다.** 같은 세션의 후속 요청에도 기존 bearer를
보내고 owner·만료를 다시 확인한다.

또 다른 혼동도 있다. MCP의 `capabilities.resources` 같은 값은 “서버가 어떤 기능을
지원하는가”를 알리는 프로토콜 기능 선언이다. 이 프로젝트의 `X-Agent-Capability`는
“이번 job이 무엇을 할 수 있는가”를 나타내는 별도 권한 값이다. 이름이 비슷하지만 다르다.

Bootstrap token은 최초 입장 때 한 번 consume된다. 후속 요청에서 같은 bearer를
보내는 것은 입장권을 다시 소비하는 게 아니라 owner 확인에 쓰는 것이다.
`X-Agent-Capability`는 initialize 때만 전달하고 후속 요청에는 다시 보내지 않는다.

MCP는 capability 안에서 권한을 해독하지 않는다. Backend가 의미를 아는 불투명한 값으로
보관·전달한다. MCP는 consume 성공 응답에서 받은 허용 scope와 binding을 사용한다.

## 9. MCP 세션이 열리는 과정

다음은 **올바른 Backend 응답이 주어진 경우 현재 MCP 코드가 처리하는 순서**다.
현재 실제 Backend는 아래 5번의 성공 응답 계약이 맞지 않아 이 흐름이 끝까지 성립하지 않는다.

1. Client가 `POST /mcp`로 `initialize` 요청을 보낸다. bearer token과
   `X-Agent-Capability`를 함께 전달한다.
2. `BootstrapAuthMiddleware`가 요청 형식을 확인하고 `BootstrapService`에 검증을 맡긴다.
3. token의 서명·claim·기한·capability 연결을 확인하고, 이미 사용한 nonce인지 검사한다.
   nonce는 같은 입장 요청의 재사용을 구분하는 일회성 값이다.
4. MCP의 HTTP 어댑터가 HMAC으로 서명한
   `POST /internal/v1/mcp-bootstrap/consume` 요청을 Backend에 보낸다.
5. 성공 응답에 `status`, `allowed_resource_scopes`, `phase`, `state_version`,
   `window_id` 다섯 필드가 계약대로 있는지 확인한다. 응답을 기다리다가 token이
   만료됐을 가능성도 다시 확인한다.
6. 통과한 경우에만 세션별 SDK 처리기와 registry binding을 준비하고 세션 응답을 내보낸다.

단순히 HTTP `200`이나 `CONSUMED`라는 글자를 받았다고 통과시키지 않는다. 비유하면
“입장 가능”이라는 말뿐 아니라 **어느 작업·어느 시점·어느 자료에 대한 입장인가**까지
확인해야 하기 때문이다.

현재 Backend의 [consume_bootstrap](../../backend/app/services/internal_engine_service.py)는
`{"status":"CONSUMED"}`만 반환한다. MCP는 이를 불충분한 응답으로 거부한다.
이 동작은 검사를 느슨하게 해서 해결할 문제가 아니라 두 섹터의 계약을 맞춰야 하는 지점이다.

## 10. 자료 하나를 읽을 때는 무엇을 검사할까?

예를 들어 허용된 AI 세션이 `mafia://session/me`를 읽는 경우다.

1. 세션이 살아 있고 bearer가 같은 owner인지 확인한다.
2. raw URI가 등록된 정확한 문자열인지, 현재 세션에 허용된 scope인지 확인한다.
3. 허용됐다면 `GET /internal/v1/agent-context?scope=me`를 한 번 호출한다.
4. Backend는 capability와 현재 상태를 기준으로 해당 주체가 읽을 자료를 판단해야 한다.
5. MCP는 받은 응답의 주체·scope·발급 binding·데이터 schema를 검사한다.
6. 통과한 결과를 같은 URI의 `application/json` text content 한 개로 만든다.
7. 응답을 실제로 보내기 직전 세션 종료와 충돌하지 않는지 확인한 뒤 전송한다.

등록되지 않은 URI나 허용되지 않은 자료는 Backend를 호출하기 전에 거부한다.
Backend가 예기치 않은 필드나 다른 주체의 정보를 섞어 보냈다면, 문제 필드만 조용히
지우고 성공한 것처럼 처리하지 않는다. 응답 전체를 계약 위반으로 거부한다.

### 10.1 왜 매번 Backend에서 다시 가져올까?

마피아 게임은 차례·생존자·권한이 계속 바뀐다. 이전에 허용됐던 자료를 재사용하면
오래된 권한이나 시점의 정보가 전달될 수 있다. 이 프로젝트는 그런 재사용을 피하려고
MCP의 session-local context 캐시도 두지 않는다.

읽는 동안 검사·직렬화를 위한 임시 변수는 존재한다. 하지만 요청이 끝난 뒤 다음 요청에
재사용할 Resource JSON·모델·문자열을 보관하지 않는다. Backend 장애가 나도 예전 자료를
대신 반환하지 않는다. 세션 자격을 잠시 보관하는 것과 게임 자료를 캐시하는 것은 다르다.

### 10.2 응답을 보내는 도중 세션이 닫히면?

자료를 가져오는 사이 token이 만료되거나 DELETE가 도착할 수 있다. 그래서 “자료를
받았으니 무조건 전송”하지 않고 성공 전송과 종료 중 무엇이 먼저 확정됐는지 조정한다.

- 종료가 먼저 확정됐으면 늦게 도착한 성공 자료를 보내지 않는다.
- 성공 전송이 먼저 확정됐으면 해당 전송이 끝난 뒤 종료 정리를 진행한다.

이를 위한 `gate`는 같은 세션 안의 중요한 순간을 짧게 조정하는 문으로 이해하면 된다.
느린 Backend HTTP 요청 전체를 잠금 안에서 기다리도록 만들지는 않았다.

## 11. 언제 세션이 끝나며 무엇이 남을까?

현재 구현은 명시적 DELETE, token 만료, 30초 idle, Backend의 capability 거부,
shutdown 등의 종료 경계를 처리한다. token 만료가 먼저 오면 30초를 더 기다리지 않는다.

종료 시에는 새 요청이 들어올 경로를 먼저 분리하고, registry의 binding과 해당 SDK
manager의 수명주기를 정리한다. 같은 세션을 여러 경로에서 동시에 닫아도 실제 종료를
중복 수행하지 않도록 조정한다. 한 세션의 정리가 늦어져도 다른 세션 정리를 막지 않도록
독립 작업으로 처리하는 reaper가 있다. reaper는 “만료된 접수 건을 치우는 정리 담당자”다.

MCP 세션은 DB나 파일에 저장해 복원하지 않는다. 서버를 다시 시작한다고 기존 세션이
살아나지 않는다. 응답 유실·재접속 상황에서 이전에 소비한 token과 기존 session ID를
그대로 재사용하지 않는다. 살아 있는 job에 새 자격을 발급할지는 Backend가 조정해야
하며, 실제 시스템의 조정 절차는 아직 남은 통합 과제다.

## 12. MCP 코드 파일을 쉬운 말로 읽기

| 경로 | 쉬운 설명 | 중요하게 볼 점 |
|---|---|---|
| `main.py` | 부품을 조립하고 켜고 끄는 곳 | 실제 등록된 기능과 의존성 확인 |
| `api/bootstrap_auth.py` | 입구 경비와 응답 출구 관리 | 인증·owner·raw 요청·종료/송신 충돌 검사 |
| `api/streamable_session_pool.py` | 세션마다 전용 처리 공간을 배정 | fresh Server·stateful manager의 시작과 종료 |
| `api/resources/handlers.py` | MCP 메시지를 Python 작업으로 연결 | `resources/list`, `resources/read` 등록 |
| `services/bootstrap.py` | 입장 심사 절차를 순서대로 실행 | verify → replay 예약 → consume → 재검증 |
| `services/resources.py` | 자료 조회와 결과 검사를 순서대로 실행 | GET 1회 → schema 검사 → JSON 직렬화 |
| `domain/session.py` | 세션 명부와 순수 상태 규칙 | 누구의 어떤 작업인지·언제 만료되는지 |
| `domain/resource.py` | 정확한 자료 주소 목록 | 다섯 URI와 scope의 대응 |
| `schemas/bootstrap.py` | 초대장·consume 응답의 양식 검사 | 누락·추가 필드와 발급 binding 검증 |
| `schemas/context.py`, `common.py` | 자료 응답의 상세 양식 검사 | 주체·시점·값·문자열·UTC 시각 불변식 |
| `ports/` | 외부 부품이 지켜야 하는 약속 | Engine 조회·consume·AuditSink 인터페이스 |
| `integrations/engine_http.py` | Backend와 실제 HTTP로 대화 | HMAC 서명·상태 코드 분류·연결 종료 |
| `core/config.py` | MCP에 들어올 설정을 제한 | 필요한 환경 변수만 읽기 |
| `core/security/errors.py` | 외부로 공개할 고정 오류 분류 | 민감한 오류 원문 노출 금지 |
| `core/audit.py` | 기록해도 되는 정보만 생성·전달 | 여섯 필드 제한·원문 로그 차단 |

모든 경로는 [mafia_game 패키지](../../mcp_server/mafia_game)를 기준으로 한다.
처음부터 가장 긴 미들웨어를 다 읽기보다 `main.py`에서 조립 관계를 본 다음 service,
port, adapter, schema 순으로 따라가면 이해하기 쉽다.

`port`라는 이름은 여기서 `8100` 같은 네트워크 포트가 아니다. “자료를 가져오는 부품은
이 함수를 제공해야 한다”라는 코드 인터페이스를 뜻한다. 실제 HTTP 어댑터도, 테스트용
가짜 Engine도 같은 약속을 지키면 service에 연결할 수 있다.

## 13. DB·Redis와 MCP 섹터의 관계

**MCP 섹터 담당자의 업무**와 **MCP 서버 프로그램이 하는 일**은 다르다.

| 일 | 소유 주체 |
|---|---|
| DB 테이블·제약·migration SQL 작성 | Backend |
| repository·Redis lock/cache/publisher 코드 작성 | Backend |
| PostgreSQL·Redis 실행 환경 준비, 계정·권한 준비 | MCP·Data Infrastructure 섹터 |
| Backend가 작성한 migration 실행·재실행·health 확인 | MCP·Data Infrastructure 섹터 |
| 게임 자료를 DB에서 읽어 적절한 범위로 투영 | Backend |
| AI 측 요청을 받고 Backend 내부 HTTP로 자료 조회 | MCP runtime |

DB 설계의 목표는 PostgreSQL을 영속 원본으로 두고 Redis를 재구성 가능한 보조 상태로
쓰는 것이다. 현재는 사용자·관리자·내부 권한 경로가 PostgreSQL adapter를 사용하고,
canonical 공개 게임은 아직 메모리를 기본으로 쓴다. 관리자 화면이 사용자 화면과 같은
메모리 게임 목록을 자동으로 볼 것이라고 가정해서도 안 된다.

MCP 프로그램은 DB·Redis client를 직접 호출하지 않는다. MCP를 고쳤다고 DB SQL이나
공개 게임 저장 경로가 자동으로 바뀌는 것도 아니다.
근거: [DB 설계 원칙](../개발상세플랜/AI_MAFIA_DB_DESIGN.md),
[Backend 조립 코드](../../backend/app/main.py),
[공개 게임 의존성](../../backend/app/routers/scaffold_game_router.py).

## 14. 안전 로그와 오류는 왜 이렇게 제한할까?

보통 개발 중에는 요청과 응답을 통째로 출력하고 싶어진다. 하지만 이 게임에서는 그
기록에 다른 AI의 역할, 비공개 사실, 출입증 같은 정보가 섞일 수 있다. “화면에만 안
보이면 된다”가 아니라 로그에도 남기지 않는 경계가 필요하다.

현재 AuditRecorder가 전달할 수 있는 필드는 다음 여섯 가지다.

| 필드 | 의미 |
|---|---|
| `request_id` | 안전한 요청 추적 UUID |
| `correlation_id` | 관련 내부 작업을 묶는 안전한 UUID |
| `operation` | initialize·조회·종료 등 어떤 작업인지 |
| `status` | 성공·거부·실패·취소 중 어떤 결과인지 |
| `duration_ms` | 작업에 걸린 시간 |
| `error_class` | 비밀정보 없는 고정 오류 종류 |

추적 ID에는 game/player/session 식별자를 그대로 넣지 않는다. 로그 수집기를 뜻하는
`sink`는 주입할 수 있지만 기본값은 `None`, 즉 기록 폐기다. 따라서 “안전 로그 코드가
있으니 현재 파일이나 DB에 감사 기록이 쌓인다”는 해석은 틀리다.

수집기가 실패해도 payload를 다른 파일에 비상 저장하거나 재전송하지 않는다.
SDK·HTTP 라이브러리·Uvicorn의 진단 원문이 이 경계를 우회하지 않도록 필터를 적용하고,
독립 실행 진입점은 access log도 끈다. 다른 서버에 내장할 때는 그 host의 로그 경계도
별도로 지켜야 한다. 실제 운영 수집기와 보존 기간 결정은 아직 남아 있다.

외부 오류 역시 자세한 내부 사정을 그대로 보여 주지 않는다. 예를 들면 Resource 접근
거부는 `-32002`, Backend 연결 실패 계열은 `-32003`, 응답 계약 위반은 `-32004`로
정규화한다. “무엇이 잘못됐는지 모르면 일단 통과”하지 않는 원칙을 `fail-closed`라고 한다.

## 15. 설정은 무엇을 준비해야 할까?

현재 MCP 독립 진입점은 공용 루트 `.env`를 자동으로 읽지 않는다. 프로세스에 전달된
다음 allowlist 설정만 읽는다. 이 문서는 실제 값을 포함하지 않는다.

| 환경 변수 | 의미 |
|---|---|
| `MCP_SERVER_AUTH_SECRET` | Backend가 서명한 bootstrap token을 검증하는 공통 비밀 |
| `ENGINE_INTERNAL_API_SECRET` | MCP→Backend 내부 HTTP 요청 서명용 비밀 |
| `ENGINE_API_URL` | Backend Engine의 기본 URL |
| `MCP_LISTEN_HOST` | MCP가 요청을 받을 호스트; 기본 loopback |
| `MCP_LISTEN_PORT` | MCP가 요청을 받을 포트; 기본 8100 |

두 secret은 각각 32자 이상이며 서로 다른 값이어야 한다. 하나는 세션 입장 경계,
다른 하나는 내부 HTTP 요청 경계이므로 역할이 다르다. MCP에 DB·Redis·LLM 자격증명을
함께 넣지 않는다.

현재 진입점은 TLS가 준비되지 않은 상태에서 loopback 주소만 허용한다. 이 개발 설정을
인터넷 공개 서비스의 안전한 배포 구성으로 취급하지 않는다. MCP 자체 health endpoint도
아직 정해져 있지 않다. Backend의 `/health`와 MCP의 준비 상태를 같은 것으로 보면 안 된다.

승인된 환경이 준비된 경우의 실행 절차는
[MCP 패키지 README](../../mcp_server/mafia_game/README.md)를 참고한다. 다만 프로세스가
시작됐다는 사실과 실제 게임·Agent·MCP가 정상 연동된다는 사실은 별개다.

## 16. 어디까지 됐고 무엇이 남았을까?

아래 상태는 현재 소스와 기존 검증 기록을 읽은 결과다. 이번 문서 작성에서 서비스를
기동하거나 회귀 테스트를 다시 실행한 결과가 아니다.

| 영역 | 현재 확인한 범위 | 남은 핵심 |
|---|---|---|
| 사용자 Front | UUID·게임 화면·REST client·SSE bridge·결과 표시 | 자동 재접속·주기 polling·RESUME 마무리 |
| 관리자 Front | 접근 확인·지표·게임 목록·상세 조회 | UUID 직접 입력/복구 등 화면 계약 마무리 |
| Backend 게임 | 순수 엔진·공개 API·메모리 게임 처리 | canonical 게임 PostgreSQL/Redis 운영 연결 |
| Backend Agent | job·lease·fallback·LLM 관련 구성요소 | 공개 게임에서 실제 Agent 실행 연결 |
| MCP M2/M3 | 세션·인증·다섯 Resource·응답 검증·종료 처리 | 실제 Backend와 맞춘 통합 증거 |
| MCP M4 | 행동 Tool 계약과 예약 위치 | Tool 구현과 proposal 정책 정합화 |
| MCP M5 선행 | 안전 record·기존 경로 계측·주입 sink 경계 | Tool 계측·운영 sink·보존 정책 |
| 통합·운영 | 일부 독립 검증과 로컬 실행 안내 | 실제 장애·재접속·TLS·health·운영 재현 |

지금 실제 Backend↔MCP 연결에서 먼저 확인해야 할 것은 세 가지다.

1. consume 응답을 승인된 5-field 계약에 맞추는 일.
2. Backend의 `context_provider`와 `proposal_handler`를 실제 게임 처리에 연결하는 일.
3. Backend Agent의 실제 MCP client를 새 endpoint·인증·Resource 계약에 맞추는 일.

현재 내부 처리기는 권한 검사 이후 필요한 handler가 없으면 `503`을 반환한다.
MCP Tool도 아직 없으므로 “설정값만 넣으면 AI가 플레이한다”고 안내할 수 없다.
이 문서는 남은 작업을 설명할 뿐, 타 섹터 코드를 수정하거나 새 계약을 승인하지 않는다.

## 17. 테스트가 통과했다는데 왜 실제 연결은 안 될 수 있을까?

콘센트에 꽂기 전에 부품을 각각 검사하는 것과, 완성된 기계를 실제 환경에서 돌리는
것의 차이로 이해하면 쉽다.

- **단위 검증:** 특정 함수가 올바른 입력과 잘못된 입력을 구분하는지 확인한다.
- **계약 검증:** 약속된 요청·응답·권한·오류 형식을 지키는지 확인한다.
- **통합 검증:** 실제 Backend와 MCP를 연결했을 때 두 구현이 같은 약속으로 대화하는지 확인한다.
- **운영 검증:** 재시작·연결 단절·DB 상태·TLS 등 실제 환경까지 포함해 확인한다.

MCP 독립 테스트는 fake Engine과 SDK/ASGI transport를 사용한다. fake Engine은 실제
게임 DB 대신 계약에 맞는 응답이나 오류를 주는 시험용 부품이다. 정상 응답뿐 아니라
만료·권한 거부·취소·동시 종료·민감정보 비노출 같은 실패 상황도 반복해서 확인할 수 있다.

[기존 MCP 검증 기록](../../mcp_server/mafia_game/README.md)에는 2026-09-05 기준
255개 테스트와 Ruff·lock 검증 통과가 기록되어 있다. **이번 문서 작성에서는 이를
재실행하지 않았다.** 이 숫자는 MCP 내부 검증의 증거이지 실제 Backend의 현재 응답이
MCP 계약과 호환된다는 증거는 아니다.

## 18. 처음 코드를 읽는 순서

1. [전체 섹터 구조도](sectors-overview.html)에서 Front·Backend·MCP의 위치를 본다.
2. [사용자 app.py](../../frontend_user/app.py)에서 사용자가 어느 화면으로 가는지 본다.
3. [Backend main.py](../../backend/app/main.py)에서 등록된 라우터와 저장소를 본다.
4. [공개 게임 라우터](../../backend/app/routers/scaffold_game_router.py)에서
   canonical 경로와 legacy 경로를 구분한다.
5. [MCP main.py](../../mcp_server/mafia_game/main.py)에서 부품 조립 관계를 본다.
6. [BootstrapService](../../mcp_server/mafia_game/services/bootstrap.py)와
   [ResourceService](../../mcp_server/mafia_game/services/resources.py)에서 처리 순서를 본다.
7. [HTTP 어댑터](../../mcp_server/mafia_game/integrations/engine_http.py)와
   [Resource handler](../../mcp_server/mafia_game/api/resources/handlers.py)를 연결해서 읽는다.
8. 마지막으로 [API 정본](../개발상세플랜/AI_MAFIA_API_SPEC.md) 8·9절과
   [MCP 상세 설계](../개발상세플랜/AI_MAFIA_MCP_SERVER_DESIGN.md)를 대조한다.

코드를 읽다가 `WU`를 만나면 작업 단위, `CP`는 체크포인트, `OPEN`은 아직 결정이
남은 항목이라고 생각하면 된다. 폴더·클래스·테스트의 존재와 WU 전체 완료는 구분한다.

## 19. 자주 나오는 질문

### MCP를 켜면 AI가 자동으로 말하나요?

아니다. 누가 언제 말할지 예약하고 LLM을 호출하며 결과를 반영할 Backend Agent 실행
경로가 필요하다. MCP는 그 과정에서 필요한 자료 창구 역할을 한다.

### MCP가 Backend를 다시 호출하면 같은 일을 두 번 하는 것 아닌가요?

책임이 다르다. Backend는 게임의 원본 상태와 최종 권한 판단을 소유하고, MCP는
AI 측에 공개할 프로토콜·세션·자료 형식을 관리한다. 두 프로그램이 별도 계약을 지키며
대화하는 구조다.

### AI 플레이어가 `me` 대신 다른 사람 ID를 보내면 볼 수 있나요?

그런 선택 인터페이스를 제공하지 않는다. 주체는 세션에 고정되고 URI는 다섯 고정
값만 허용된다. Backend도 capability의 주체와 현재 권한을 확인해야 한다.

### 로그를 남기면 문제를 찾기 쉬운데 왜 원문을 막나요?

문제 추적보다 더 큰 비공개 정보 유출을 만들 수 있기 때문이다. 현재는 무엇을 했고,
성공했는지, 얼마나 걸렸는지, 어떤 고정 오류인지 같은 안전한 메타데이터만 허용한다.

### 관리자라면 게임 데이터를 수정할 수 있나요?

현재 MVP 관리자 계약은 조회 전용이다. 강제 종료·수정·삭제 기능으로 확대해서 읽으면
안 된다. UUID allowlist 역시 공개 인터넷용 강한 인증으로 볼 수 없다.

### 이 문서를 정본으로 삼아 코드를 바꾸면 되나요?

이 문서는 이해를 돕는 임시 설명서다. 제품 규칙은 마스터플랜, DB는 DB 설계서,
요청·응답은 API 명세, 화면은 화면 흐름도, MCP 구현 구조는 MCP 설계서를 먼저 확인해야 한다.
서로 다른 섹터의 약속을 바꾸는 경우에는 해당 정본과 섹터 간 합의가 필요하다.

## 20. 이 문서에서 확인한 것과 하지 않은 것

- 현재 소스·기존 정본·기존 검증 기록과 공식 MCP 개념 문서를 대조했다.
- 새 설명서는 `docs/temp/`에만 추가했고, 같은 폴더의 안내 목록에 링크를 추가했다.
- 기존 구조도 HTML·JSON, 루트 README, 정본 설계서, 실행 코드는 수정하지 않았다.
- 로컬 문서 링크와 변경 범위를 확인했다. 실행 동작을 바꾸지 않는 문서 작업이므로
  Backend·Front·MCP 자동 테스트와 실제 DB·Redis·LLM 통합 호출은 생략했다.
- 커밋·푸시는 하지 않았다.
