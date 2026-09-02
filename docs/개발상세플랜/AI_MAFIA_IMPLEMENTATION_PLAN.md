# AI 마피아 MVP 상세 구현 계획서 (3인 섹터 분담)

**문서 상태:** `mystery-v1` / `scenario-v1` 구현 착수용 상세 계약
**기준 문서:** [AI 마피아 MVP 최종 통합 플랜](../플랜/AI_MAFIA_MVP_FINAL_PLAN.md),
[최종 규칙](../초기기획안/mafia_game_rules.md),
[최종 시나리오](../초기기획안/mafia_game_scenarios.md)
**작업 규칙 원본:** [AGENTS.MD](../../AGENTS.MD) — 이 계획서의 모든 작업에 적용
**분담:** 3인 — Front 섹터, Backend 섹터, MCP Server·Data Infrastructure 섹터
**섹터별 작업 지침서 (착수 전 필독):**
[Front](SECTOR_PLAN_FRONT.md) ·
[Backend](SECTOR_PLAN_BACKEND.md) ·
[MCP Server](SECTOR_PLAN_MCP.md)

이 문서는 최종 통합 플랜을 실제 작업 단위로 쪼개고, 2026-09-02에
합의한 최종 규칙·시나리오를 `mystery-v1`·`scenario-v1` 계약으로
구체화한다. 섹터 간 병렬 작업이 가능하도록 **API 명세와 DB
설계서를 계약으로 먼저 고정**한다. 명세 변경이
필요하면 임의로 바꾸지 말고 3인 합의 후 이 문서를 먼저 갱신한 뒤 코드를
수정한다. 각 섹터의 작업 단위(WU) 분해, coding AI agent 사용 규칙(한 세션
= WU 1개 이하), 중간 merge·테스트 체크포인트는 섹터 지침서가 확정한다.

**2026-09-02 역할 변경:** PostgreSQL·Redis의 설치, 인스턴스·DB 생성, 기동,
중지, 접속 계정·권한 준비, migration 실행과 health 확인은 MCP 섹터가 맡는다.
Backend는 schema·migration SQL·repository와 Redis client·lock 등 애플리케이션
코드를 계속 소유한다. MCP 서버 runtime은 DB·Redis에 직접 접근하지 않고 기존처럼
Backend 내부 API만 호출한다.

**2026-09-02 규칙 계약 변경:** 게임 인원은 6~9명, 역할은
`MAFIA | DETECTIVE | DOCTOR | CITIZEN`으로 고정한다. 마피아는 다른
마피아의 정체를 모르며 진영 공개 채널을 사용하지 않는다. Backend만
전체 상태와 비공개 행동의 원본을 가지고, AI GM은 Backend가 필터한
공개 상태만 사용해 고정 진행 문구와 요약을 제공한다.

---

## 0. 공통 작업 지침 (AGENTS.MD 요약 — 전 섹터 필수)

아래 지침은 [AGENTS.MD](../../AGENTS.MD)의 요약이며, 충돌 시 AGENTS.MD 원문이
우선한다. 세 섹터 담당자 모두 작업 시작 전에 원문을 읽어야 한다.

### 0.1 브랜치와 Git

1. `main` 직접 커밋 금지, `origin/main` 직접 푸시 금지. 섹터별 작업 브랜치에서
   작업하고 검토 절차를 거쳐 병합한다.
   - 권장 브랜치 이름: `feat/front-<기능>`, `feat/backend-<기능>`,
     `feat/mcp-<기능>`
2. 사용자가 명시적으로 승인하지 않은 커밋은 만들지 않는다. 구현 요청은 파일
   변경 승인일 뿐 커밋·푸시 승인이 아니다.
3. 커밋 전 현재 브랜치와 변경 파일을 확인하고 타인 소유 변경을 덮어쓰지 않는다.
4. `git reset --hard`, 강제 푸시, 광범위 삭제는 명확한 요청과 대상 확인 없이
   실행하지 않는다.

### 0.2 커밋 메시지

`fix`, `update`, `work` 같은 단어만 있는 메시지는 금지. 최소한 다음이 드러나야
한다: **변경 목적 / 변경한 기능·파일·데이터 경계 / 실행한 테스트·lint 또는
검증을 생략한 이유.**

### 0.3 코드와 주석

1. 새로 작성·수정하는 모든 주석과 docstring은 **한국어**로, 구현 반복이 아니라
   의도·경계 조건·보안 이유·유지보수 주의점을 설명한다.
2. 기존 구조와 명명 규칙을 따르고, 요청 범위 밖 대규모 리팩터링을 섞지 않는다.
3. 인증 claim, DB 값, 사용자 입력, LLM/MCP 출력 등 외부 데이터는 신뢰하지 말고
   검증·정규화·escape 후 사용한다.

### 0.4 파일·디렉터리 구조

1. 구조를 임의로 생성·삭제·이동·개명하지 않는다. 이 계획서 4~6장에 명시된
   신규 파일 목록이 승인 범위이며, 그 밖의 구조 변경은 사전 고지·합의가 필요하다.
2. 구조를 변경한 경우 루트 README의 프로젝트 구조에 반드시 반영한다.

### 0.5 비밀정보

1. API 키, OAuth secret, 쿠키 secret, DB 비밀번호, token, 실제 `.env`·
   `secrets.toml`·Google OAuth JSON을 절대 커밋하지 않는다.
2. 비밀값을 코드, 테스트 fixture, 스냅샷, 로그, 오류 메시지, 문서, 커밋
   메시지에 복사하지 않는다. 예제에는 placeholder만 사용한다.
3. 노출 의심 시 값을 다시 출력하지 말고 즉시 알리고 폐기·재발급한다.

### 0.6 테스트와 검증 (위험도 비례)

- 문서·주석·스타일 변경: 자동 테스트 생략 가능, diff·링크 직접 확인.
- 한 파일·한 기능 변경: 가장 작은 관련 테스트, lint, import 확인만 실행.
- 일반 기능·버그 수정: 개발 중 focused test, 완료 직전 전체 회귀 1회.
- **인증·권한·보안·데이터 삭제·공개 계약·동시성(이 프로젝트의 게임 소유권,
  비공개 역할 격리, lock, 관리자 권한 전부 해당): 실패·거부 경로 테스트를
  먼저 또는 함께 작성하고 전체 회귀를 실행한다.**
- 외부 Cloud/유료 API 자동 테스트는 mock·fake·synthetic으로 대체한다.
  **유료 LLM을 회귀 테스트에서 호출하지 않는다.**
- 무관한 기존 테스트 실패는 원인·영향만 보고하고 임의 수정하지 않는다.

전체 회귀 명령 (완료 보고 기준):

```bash
uv run pytest
uv run python -m compileall -q backend frontend_user frontend_admin mcp_server
uv run ruff check .
```

### 0.7 README와 완료 점검

모든 작업은 완료 전에 루트 README.md를 현재 구현과 일치하게 갱신한다.
완료 전 점검: 범위 밖 파일 미변경 / 비밀정보 미포함 / 위험도에 맞는 검증 실행 /
README 갱신 / 구조 임의 변경 없음 / 승인 없는 커밋·푸시 없음.

---

## 1. 섹터 분담과 소유 경계

| 섹터 | 담당 디렉터리 (소유) | 주요 산출물 |
|---|---|---|
| **Front** | `frontend_user/`, `frontend_admin/` | 홈·생성·진행·불러오기·결과 화면, 관리자 KPI·로그·피드백 화면, API client 확장 |
| **Backend** | `backend/` (app 전체, migrations) | 게임 규칙 엔진, 상태 머신, 게임·관리자 API, DB schema·migration·repository, Redis application client·lock, Agent Manager, LLM client, MCP client·capability 정책 |
| **MCP Server·Data Infrastructure** | `mcp_server/mafia_game/` + PostgreSQL·Redis 실행 환경 | 게임 컨텍스트 MCP 서버(Resource/Tool), 세션·격리·감사 로그, Backend 내부 API 소비, PostgreSQL·Redis 구축·기동·migration 실행·health 확인 |

### 1.1 공유 파일 규칙

- `pyproject.toml`, `.env.example`, 루트 `README.md`, `docs/`는 공유 파일이다.
  수정 시 변경 내용을 다른 섹터에 고지한다.
- `backend/app/mcp/`(MCP client·capability)는 Backend 소유지만 **계약 협의는
  MCP 섹터와 공동**으로 한다. 계약 변경은 이 문서 5장(내부 API)과 6장(MCP
  명세) 갱신이 선행 조건이다.
- `backend/migrations/`와 `backend/app/infrastructure/redis/`는 Backend 코드
  소유다. MCP 담당자는 migration을 실행하고 Redis 서비스를 운영할 수 있지만
  이 파일과 DB·Redis application 계약을 임의로 수정하지 않는다.
- PostgreSQL·Redis 운영 책임은 새 저장소 디렉터리 소유권을 자동 부여하지
  않는다. provisioning 파일이나 Docker 구성이 필요하면 승인 파일 목록과
  README를 먼저 갱신한다.
- 다른 섹터 소유 디렉터리는 수정하지 않는다. 필요한 변경은 이슈/메시지로
  해당 섹터에 요청한다.

### 1.2 섹터 간 계약 (병렬 작업의 전제)

```text
Front  ──(2장 사용자·관리자 REST API + SSE)──────▶  Backend
MCP Server ──(5장 내부 Engine API, HMAC 서명)────▶ Backend
AI Agent(Backend가 구동) ──(6장 MCP Resource/Tool)──▶ MCP Server
MCP 섹터 ──(구축·기동·migration 실행·health)────▶ PostgreSQL / Redis
Backend ──(application connection)──────────────▶ PostgreSQL / Redis
```

- Front는 Backend 완성 전 **fake API client**(테스트 더블)로 화면을 개발한다.
- MCP Server는 Backend 완성 전 **fake Engine API**(로컬 stub)로 개발한다.
- Backend는 실제 LLM 없이 **fake LLM client**로 엔진·Agent Manager를 개발한다.

### 1.3 프로세스와 포트

| 프로세스 | 실행 명령 | 포트 |
|---|---|---:|
| Backend API | `uv run uvicorn backend.app.main:app --port 8000` | 8000 |
| 사용자 앱 | `uv run streamlit run frontend_user/app.py --server.port 8501` | 8501 |
| 관리자 앱 | `uv run streamlit run frontend_admin/app.py --server.port 8502` | 8502 |
| 게임 MCP 서버 | `uv run python -m mcp_server.mafia_game` (구현 시 확정) | 8100 |
| PostgreSQL | MCP 섹터 승인 환경에서 기동·health 확인 | 환경별 |
| Redis | MCP 섹터 승인 환경에서 기동·health 확인 | 환경별 |

PostgreSQL·Redis 행은 MCP **담당자의 운영 책임**을 뜻한다. 네트워크 연결은
Backend 프로세스가 직접 수행하며 MCP 서버 프로세스를 데이터 프록시로 사용하지
않는다.

---

## 2. 사용자·관리자 API 명세 (Front ↔ Backend 계약)

### 2.0 공통 규약

**인증(MVP 결정):** 브라우저가 Backend를 직접 호출하지 않는다. Streamlit
서버(신뢰된 내부 프로세스)가 기존 HMAC 내부 서명
(`X-Internal-Timestamp`, `X-Internal-Request-Id`, `X-Internal-Signature`,
canonical = `timestamp.request_id.raw_body`)으로 Backend를 호출하고, 행위
사용자는 서명된 요청 body의 `acting_user_id`(UUID, provision 응답의 내부
`user_id`)로 전달한다. Backend는 `acting_user_id`가 활성 사용자인지, 대상
게임의 소유자인지 항상 재검증한다. 서명이 곧 사용자 인증은 아니므로 이 방식은
Streamlit 서버를 신뢰 경계로 하는 MVP 한정 결정이며, 사용자 직접 호출이
필요해지는 시점에 짧은 수명 access token으로 교체한다(교체 지점:
`frontend_user/core/api_client.py`, `backend/app/infrastructure/security/`).

**공통 요청 필드 (GET 제외):**

```json
{
  "acting_user_id": "018f6f7c-0496-758e-981f-05985cb67210"
}
```

GET 요청은 body가 없으므로 `X-Acting-User-Id` 헤더로 전달하며 이 헤더도
서명 canonical에 포함한다: `timestamp.request_id.acting_user_id.raw_body`
(GET은 raw_body를 빈 문자열로 계산). 기존 identity API의 canonical은 바꾸지
않고, 게임 API 전용 서명 규칙으로 `backend/app/infrastructure/security/`에
추가한다.

**공통 오류 응답:**

```json
{
  "code": "GAME_STATE_CONFLICT",
  "message": "요청한 버전이 현재 게임 상태보다 오래되었습니다.",
  "details": {"expected_version": 17, "current_version": 19},
  "trace_id": "trace-uuid"
}
```

| HTTP | code | 의미 |
|---:|---|---|
| 401 | `INVALID_INTERNAL_SIGNATURE` | HMAC·timestamp·request id 검증 실패 |
| 403 | `INACTIVE_USER` | 비활성 사용자 |
| 403 | `ADMIN_ACCESS_DENIED` | 관리자 role 없음 |
| 404 | `GAME_NOT_FOUND` | 없는 게임 **또는 소유하지 않은 게임(동일 응답)** |
| 409 | `GAME_STATE_CONFLICT` | `expected_version` 불일치 |
| 409 | `ACTION_ALREADY_SUBMITTED` | 현재 단계에서 이미 확정한 행동을 변경하려는 요청 |
| 409 | `ACTION_DEADLINE_EXPIRED` | 서버 권위 마감 시각 이후 도착한 행동 |
| 422 | `ACTION_NOT_ALLOWED` | 현재 단계·역할에서 불가한 행동 |
| 422 | `INVALID_GAME_REQUEST` | schema·값 검증 실패 |
| 422 | `STALE_CAPABILITY` | 이전 phase·state version에 발급된 capability |
| 503 | `CONTRACT_VERSION_MISMATCH` | Backend·MCP ruleset/scenario/transport 계약 불일치 |
| 503 | `AGENT_TEMPORARILY_UNAVAILABLE` | agent 제어·bootstrap 요청 자체를 시작할 수 없는 일시 장애 |
| 503 | `GAME_PERSISTENCE_UNAVAILABLE` | DB/Redis 저장 실패 |

오류 code는 위 **13종**을 공통 schema와 contract test에서 고정한다.
`AGENT_TEMPORARILY_UNAVAILABLE`은 활성 게임 phase의 LLM provider 실패를
뜻하지 않는다. 예약된 turn의 MCP/LLM 장애는 4.3의 결정적 fallback으로 계속
진행하며 이 code를 사용자 행동 응답으로 반환하거나 게임을 자동 pause하지 않는다.

**공통 enum:**

```text
GameStatus  = CREATED | IN_PROGRESS | PAUSED | FINISHED
Phase       = ROLE_REVEAL | DAY_ANNOUNCEMENT | DAY_DISCUSSION
            | NIGHT_ACTION | NIGHT_RESOLUTION | DAY_VOTE | DAY_REVOTE | VOTE_RESOLUTION
            | FINAL_DISCUSSION | FINAL_VOTE | FINAL_RESOLUTION | FINISHED
Role        = MAFIA | DETECTIVE | DOCTOR | CITIZEN     (종료 전 타인 역할 비공개)
Winner      = MAFIA | CITIZEN | null
PlayerKind  = HUMAN | AI
Visibility  = PUBLIC | PRIVATE | SYSTEM
Command     = SPEAK | CAST_VOTE | NIGHT_KILL | NIGHT_INVESTIGATE | NIGHT_PROTECT
            | PASS | SAVE_AND_EXIT | FAST_FORWARD
DiscussionCycle = PRIMARY | FOLLOWUP
VoteKind    = NORMAL | REVOTE | FINAL
FinishReason = ALL_MAFIA_ELIMINATED | MAFIA_PARITY
             | FINAL_TARGET_MAFIA | FINAL_TARGET_NON_MAFIA
FeedbackCategory = FUN | AI_QUALITY | RULE_ERROR | PERFORMANCE | ETC
FeedbackStatus   = NEW | REVIEWING | RESOLVED | WONT_FIX
```

`Role.DETECTIVE`의 한국어 UI 표시명은 "탐정"으로 고정한다. 기존
`POLICE`는 `mystery-v1` 계약에서 사용하지 않는다.
`FINAL_ACCUSATION`은 `FINAL_DISCUSSION → FINAL_VOTE → FINAL_RESOLUTION`을
통칭하는 합성 규칙명일 뿐 Phase enum이나 저장값으로 추가하지 않는다.

### 2.0.1 `mystery-v1` 규칙 불변식

| 전체 인원 | 마피아 | 탐정 | 의사 | 시민 |
|---:|---:|---:|---:|---:|
| 6 | 1 | 1 | 1 | 3 |
| 7 | 1 | 1 | 1 | 4 |
| 8 | 2 | 1 | 1 | 4 |
| 9 | 2 | 1 | 1 | 5 |

- 마피아가 2명이어도 서로의 역할·행동을 알 수 없다. 팀원 목록·진영
  이벤트·진영 채널을 생성하지 않고, 다른 마피아를 공격·투표할 수 있다.
- 탐정은 본인을 제외한 생존자 1명의 마피아 여부만 알고, 의사는 자기
  보호·연속 동일 대상 보호를 횟수 제한 없이 할 수 있다. 보호 성공 여부는
  개인 응답으로 알려주지 않는다.
- 밤 사망자는 이름·사망 상태만 공개하고 역할은 게임 종료 전까지 숨긴다.
  낮 투표로 탈락한 플레이어의 역할만 해소 즉시 공개한다.
- 투표 제출 중에는 개별 선택·중간 표수를 공개하지 않고, 해소 후에도 최종
  집계와 탈락 결과만 PUBLIC으로 발행한다. 개별 투표는 종료 결과에서만
  공개한다.
- AI GM은 PUBLIC 이벤트와 공개 시나리오만 받는다. 역할·알리바이·관찰
  정보·야간 원본 행동·seed를 조회하거나 상태를 변경하지 않는다.

### 2.0.2 상태 전이·토론·마감 계약

```text
CREATED → ROLE_REVEAL(round=0) → DAY_ANNOUNCEMENT(round=0, scenario 공개)
        → DAY_DISCUSSION(round=0, 첫날 투표 없음)
        → NIGHT_ACTION(round=1, 20s) → NIGHT_RESOLUTION → DAY_ANNOUNCEMENT
        ├─ 표준 승패 확정 → FINISHED
        ├─ 5번째 밤 해소 후 승패 미확정 → FINAL_DISCUSSION
        │   → FINAL_VOTE(30s) → FINAL_RESOLUTION → FINISHED
        └─ 그 외 → DAY_DISCUSSION → DAY_VOTE(30s) → VOTE_RESOLUTION
                         ├─ 일반 투표 동률 → DAY_REVOTE(30s) → VOTE_RESOLUTION
                         │                    ├─ 재동률 → 무탈락 → NIGHT_ACTION(round+1)
                         │                    ├─ 승패 확정 → FINISHED
                         │                    └─ 그 외 → NIGHT_ACTION(round+1)
                         ├─ 승패 확정 → FINISHED
                         └─ 승패 미확정 → NIGHT_ACTION(round+1)
```

`round`는 **현재 진행 중이거나 방금 해소한 밤 번호**다. 첫날 낮은 0이고 첫
`NIGHT_ACTION` 진입을 한 트랜잭션에서 1로 올린다. 그 밤 뒤의 announcement·낮·
투표는 같은 값을 유지하며, 다음 `NIGHT_ACTION` 진입 때만 1 증가한다. 따라서
5번째 밤과 그 아침·최종 단계는 모두 `round=5`이고 5를 초과하지 않는다.
완료한 밤 수는 성공 commit된 SYSTEM `NIGHT_RESOLVED` event 수로 계산하며, timeout·
재시도·재개가 같은 round 값을 다시 증가시키거나 완료 밤으로 중복 집계하지 않는다.

- `DAY_DISCUSSION`과 `FINAL_DISCUSSION`은 타이머가 아닌 좌석 순서 턴제다. 생존자가
  좌석 오름차순으로 각 1회 `SPEAK`(최대 200자) 또는 `PASS`를 확정한다.
  PRIMARY 1순환에서 전원이 `PASS`한 경우에만 AI GM이 "현재 가장 의심되는
  플레이어와 그 이유를 한 문장으로 말해 주세요."를 PUBLIC으로 발행하고 FOLLOWUP
  1순환을 추가한 뒤 종료한다. 발언이 하나라도 있으면 추가 순환은 없다.
- round 0 `DAY_ANNOUNCEMENT`에서 AI GM은 다음 시작 문구를 그대로 공개한다.
  "사건이 발생한 뒤, 현장에 있던 사람들은 범인을 찾기 위해 서로를 추궁하기
  시작했습니다. 그러나 범인은 자신의 정체가 드러나는 것을 막기 위해 밤마다
  다른 플레이어를 제거하려 합니다."
- `NIGHT_ACTION`은 20초, `DAY_VOTE`·`DAY_REVOTE`·`FINAL_VOTE`는 30초의
  **서버 권위 UTC deadline**을 갖는다. deadline 이후 요청은 거부하고 Backend가
  seed에 기반한 결정적 자동 선택을 적용한다. 의사의 자동 선택은 본인을
  제외한다. 행동은 한 번 확정하면 바꿀 수 없다.
- 마피아 2명의 공격 제안이 같으면 그 대상, 다르면 두 제안 중 seed로
  결정적 선택, 한 명만 제출하면 그 선택을 적용한다. 모두 미제출이면
  **생존 마피아 전원을 제외한** 생존자 중 한 명을 진영 단위로 한 번만
  결정적 자동 선택한다. 개별 마피아의 무응답용 가상 제안은 만들지 않는다.
- 밤 행동 자격은 밤 시작 시점에 고정하고 보호·공격·조사를 동시에 해소한다.
  같은 밤 공격받은 탐정·의사가 이미 제출한 조사·보호도 유효하며, 사망은
  해소가 끝난 다음 phase부터 행동 자격에 반영한다.
- 일반 투표 동률이면 최다 득표자만 후보로 재투표를 정확히 한 번 진행한다.
  재투표도 동률이면 그날은 탈락자 없이 밤으로 이동한다. 각 투표의 미제출자는
  자신을 제외한 당시 유효 후보 중 seed로 자동 선택하며 기권은 없다.
- 표준 승패는 밤·낮 해소마다 마피아 0명이면 시민, 생존 마피아 수가 생존
  비마피아 수 이상이면 마피아 승리로 판정한다.
- 5번째 밤 아침에 표준 승패(마피아 0명 / 마피아 ≥ 비마피아)가 없으면
  급사 판정을 시작한다. `FINAL_VOTE`의 최다 득표자가 마피아면 남은 마피아
  수와 무관하게 시민 승리, 비마피아면 마피아 승리다. 동률은 동률자 중
  seed로 한 명을 결정적 선택하며 재투표하지 않는다.
- `FINAL_VOTE` 직전 AI GM은 "이번 투표는 마지막 판정 투표입니다. 마피아를
  찾으면 시민이 승리하고, 시민을 선택하면 마피아가 승리합니다."를 그대로
  공개한다. AI GM 호출이 실패하면 Backend가 보유한 동일 고정 문구를 사용하며,
  AI GM은 토론 순환·phase·승패를 임의로 바꾸지 않는다. 공개 발언을 중립적으로
  요약할 뿐 모순을 정답·유죄 판단처럼 지적하거나 catalog 밖 사건 사실·알리바이·
  관찰을 만들어서는 안 된다.

### 2.0.3 `scenario-v1` 정적 catalog ID

| `scenario_id` | 공개 제목 |
|---|---|
| `broadcast-blackout` | 정전된 방송국 |
| `snow-lodge` | 눈 내리는 산장 |
| `museum-closing` | 폐관 직전의 박물관 |
| `hotel-banquet` | 호텔 만찬의 마지막 손님 |
| `night-train-stop` | 멈춰 선 야간열차 |

위 5개 ID와 제목은 `scenario-v1`의 불변 계약이다. 모든 항목의 `objective`는
"현장에 있던 플레이어 중 마피아를 찾아내세요."로 고정한다. catalog에는 초기
기획의 배경·피해자·장소와 WU-B2에서 제품 승인한 90개 이상 private template를
함께 version 고정하며, runtime LLM이나 섹터별 fake가 별도 ID·문구를 만들지 않는다.

### 2.1 `POST /api/v1/games` — 게임 생성

요청:

```json
{
  "acting_user_id": "uuid",
  "player_count": 6,
  "ruleset_version": "mystery-v1"
}
```

- `player_count`: 6~9 정수. 범위 밖은 422 `INVALID_GAME_REQUEST`.
- `ruleset_version`은 `mystery-v1`만 허용하고 시나리오 계약은 서버가
  `scenario-v1`으로 고정한다.
- 생성 시 인간 1명 + AI `player_count - 1`명, 역할 무작위 배정, persona preset
  무작위 배정, 시나리오·알리바이·관찰 정보 확정을 한 트랜잭션으로
  수행한다. random seed는 서버에만 기록한다.
- Backend의 `scenario-v1` 정적 catalog 5종 중 **해당 사용자가 직전에
  성공적으로 생성(트랜잭션 commit)한 게임 1건**의 `scenario_id`를 제외하고
  seed로 하나를 결정적 선택한다. 생성 실패·rollback은 직전 기록을 바꾸지
  않는다. 최초 성공 게임은 5종 전체가 후보다. 같은 사용자의 동시 생성은
  아래 한 가지 PostgreSQL 트랜잭션 방식으로만 직렬화한다.
  1. HMAC·세션 검증을 마친 owner UUID를 소문자 canonical UUID로 정규화한다.
     요청 body의 검증 전 식별자로 lock key를 만들지 않는다.
  2. `READ COMMITTED` transaction을 열고 첫 DB statement로
     `"team4:scenario-owner:v1:" + owner_uuid`의 SHA-256 앞 8바이트를
     big-endian signed 64-bit로 해석한 고정 key로
     `pg_advisory_xact_lock(:owner_lock_key)`을 획득한다.
  3. 같은 트랜잭션에서 직전 성공 게임을 `creation_order DESC`로 조회하고,
     scenario 선택과 게임·참가자·초기 event·snapshot INSERT를 모두 수행한 뒤
     commit한다. transaction-scoped lock이므로 commit·rollback 시 자동 해제된다.
     `creation_order`는 lock 획득 뒤 INSERT에서 PostgreSQL identity sequence로
     발급하므로 같은 owner의 직렬 commit 순서를 나타낸다. rollback으로 생긴
     sequence 공백은 허용하고 직전 기록으로 취급하지 않는다.
  4. 64-bit hash 충돌은 서로 다른 owner를 불필요하게 직렬화할 뿐이며, 실제
     조회는 항상 정확한 `owner_user_id` 조건을 사용하므로 데이터가 섞이지 않는다.
     key 고정 벡터·강제 충돌·첫 게임·동시 요청·rollback 테스트를 둔다.
- catalog·알리바이·관찰 문구는 Backend 코드의 검증된 정적 데이터다.
  LLM이 게임 생성 시 새로 만들지 않으며, 같은 seed·version은 같은 배정을
  재현해야 한다.

응답 `201` — 아래 2.3의 GameStateView와 동일 구조 (본인 역할 포함).

### 2.2 `GET /api/v1/games?status=saved` — 저장 게임 목록

본인 소유의 `IN_PROGRESS`·`PAUSED` 게임만 반환한다.

```json
{
  "games": [
    {
      "game_id": "uuid",
      "status": "PAUSED",
      "phase": "DAY_DISCUSSION",
      "round": 2,
      "scenario_id": "snow-lodge",
      "scenario_title": "눈 내리는 산장",
      "player_count": 6,
      "alive_count": 5,
      "created_at": "2026-09-01T05:00:00Z",
      "saved_at": "2026-09-01T05:12:00Z"
    }
  ]
}
```

### 2.2.1 `POST /api/v1/games/{game_id}/resume` — 저장 게임 재개

요청: `{"acting_user_id":"uuid","expected_version":17,"idempotency_key":"uuid"}`.
소유한 `PAUSED` 게임에만 허용한다. Backend는 game lock 안의 한 트랜잭션에서
snapshot/event 복구 검증과 version CAS를 수행하고 status를 `IN_PROGRESS`로 바꾼다.
일시 정지한 phase가 deadline phase면 저장한 `paused_remaining_ms`를 현재 서버
시각에 더해 새 `phase_deadline_at`을 발급하고 값을 비운다. deadline이 없는 토론
phase에는 새 deadline을 만들지 않는다. 모든 기존 AI reservation·MCP transport
session·capability는 재개 전에 폐기하고 현재 phase/version 기준으로 필요한
subject session·reservation·capability를 새로 발급한다. MCP instance `/bootstrap`은
instance·clock anchor가 없거나 만료된 경우에만 별도로 수행한다. timer index
등록까지 성공한 뒤 GameStateView를 반환한다.

같은 idempotency key의 재전송은 최초 resume outcome을 재사용하되 GameStateView는
현재 권한으로 다시 투영한다. 다른 요청으로 이미 재개된
게임이나 `FINISHED` 게임은 409 `GAME_STATE_CONFLICT`, 손상 상태를 3.1 방식으로도
복구할 수 없으면 503 `GAME_PERSISTENCE_UNAVAILABLE`이다. fake clock으로 남은 시간,
재시도, 재시작 직후 재개, 이전 capability 거부를 검증한다.

### 2.3 `GET /api/v1/games/{game_id}` — 현재 상태 (GameStateView)

**호출 사용자 권한에 맞게 필터한** 상태를 반환한다. 응답에 다른 참가자의
역할·알리바이·관찰 정보, 탐정 조사 결과, 보호 대상, 야간 원본 행동,
random seed를 절대 포함하지 않는다. 마피아 사용자에게도 다른 마피아를
표시하지 않는다.

```json
{
  "game_id": "uuid",
  "status": "IN_PROGRESS",
  "phase": "DAY_DISCUSSION",
  "round": 2,
  "state_version": 17,
  "ruleset_version": "mystery-v1",
  "scenario": {
    "scenario_id": "snow-lodge",
    "scenario_version": "scenario-v1",
    "title": "눈 내리는 산장",
    "background": "폭설로 고립된 산장에서 관리인이 사망했습니다.",
    "victim": "산장 관리인",
    "locations": ["거실", "주방", "복도", "관리인 방", "창고"],
    "objective": "현장에 있던 플레이어 중 마피아를 찾아내세요."
  },
  "initial_mafia_count": 1,
  "you": {
    "player_id": "uuid",
    "seat": 3,
    "role": "CITIZEN",
    "alive": true,
    "alibi": "저녁 식사 후 거실에 있었다.",
    "observation": {
      "text": "누군가 관리인 방 쪽에서 나오는 것을 봤다.",
      "target_seat": null,
      "anonymous": true
    }
  },
  "players": [
    {"player_id": "uuid", "seat": 1, "display_name": "냉정한 분석가",
     "kind": "AI", "alive": true, "eliminated_by": null,
     "revealed_role": null}
  ],
  "discussion": {
    "cycle": "PRIMARY",
    "current_speaker_player_id": "uuid",
    "fixed_question": null
  },
  "phase_timing": {
    "server_time": "2026-09-01T05:10:00Z",
    "deadline_at": null,
    "duration_seconds": null
  },
  "your_submission": {"submitted": false, "command": null},
  "allowed_commands": [
    {"command": "SPEAK", "max_length": 200},
    {"command": "PASS"}
  ],
  "timeline": [
    {"sequence": 41, "type": "MODERATOR_ANNOUNCEMENT",
     "message": "아침이 밝았습니다. 어젯밤 희생자는 없었습니다.",
     "created_at": "..."},
    {"sequence": 42, "type": "PLAYER_SPEECH", "player_id": "uuid",
     "message": "...", "created_at": "..."}
  ],
  "private_events": [
    {"sequence": 12, "type": "ROLE_ASSIGNED", "payload": {"role": "CITIZEN"}}
  ],
  "saved_at": "2026-09-01T05:12:00Z"
}
```

- `timeline`은 PUBLIC 이벤트만, `private_events`는 본인 PRIVATE 이벤트만
  담는다. `revealed_role`은 낮 투표 탈락자에게만 채우고 밤 사망자는
  `null`을 유지한다.
- `discussion`은 좌석 순환 커서이며 현재 발언자에게만 `SPEAK | PASS`를
  허용한다. `phase_timing.deadline_at`은 밤·일반 투표·재투표·최종 투표에서만
  UTC 시각을 갖고 Front는 `server_time`과의 차이로 표시 카운트다운을 보정한다.
- `your_submission`은 본인의 제출 여부만 나타낸다. 다른 플레이어의 제출 여부·대상은
  비공개다.
- `observation.target_seat`는 특정 좌석을 관찰한 항목에서만 현재 게임의 다른
  좌석 번호이고 `anonymous=false`다. 익명 문구는 `target_seat=null`과
  `anonymous=true`를 함께 저장·반환하며 Front·LLM이 임의 대상 이름을 붙이지 않는다.
- 인간 플레이어가 사망하고 게임이 아직 `FINISHED`가 아니면 관전 View로
  전환한다. `you`에는 식별자·좌석·`alive=false`만 남기고 역할·
  알리바이·관찰을 제거한다. `private_events`는 빈 배열, `your_submission`은
  `null`이며 행동 제출 명령을 노출하지 않는다. PUBLIC 상태·타임라인과
  `SAVE_AND_EXIT | FAST_FORWARD`만 관전 정책에 따라 제공한다. 전체 정보는
  `FINISHED` 후 2.6 결과 API에서만 공개한다.
- `?since_sequence=41` 쿼리로 증분 조회를 지원한다(폴링 대비).

### 2.4 `POST /api/v1/games/{game_id}/commands` — 행동 제출

```json
{
  "acting_user_id": "uuid",
  "command": "CAST_VOTE",
  "target_player_id": "uuid-or-null",
  "message": null,
  "expected_version": 17,
  "idempotency_key": "uuid"
}
```

- `SPEAK`: 현재 발언 좌석에서만 `message` 필수(정규화 후 1~200자,
  escape는 렌더링 시), 대상 없음. `PASS`도 현재 발언 좌석에서만 허용.
- `CAST_VOTE`: `target_player_id` 필수, 해당 투표의 후보 외·자기 자신 지정 시 422.
- `NIGHT_*`: 본인 역할·생존·단계·유효 대상을 검증한다. 탐정·마피아는
  본인을 대상으로 선택할 수 없고 의사의 직접 선택은 자기 보호를 허용한다.
- 마감 phase에서 deadline 이후 도착한 명령은 `ACTION_DEADLINE_EXPIRED`,
  이미 확정한 phase 행동을 바꾸는 명령은 `ACTION_ALREADY_SUBMITTED`로 거부한다.
- `SAVE_AND_EXIT`: 진행 중인 외부 LLM/MCP run이 없는 안전 지점에서
  `PAUSED`로 전환한다. 활성 deadline은 남은 밀리초를 snapshot에 보존하고 재개 시
  현재 서버 시각 기준으로 새 UTC deadline을 발급한다.
- `FAST_FORWARD`: 인간 사망 후에만 허용, 결과까지 자동 진행.
- 같은 `idempotency_key` 재전송은 PostgreSQL의 최초 command outcome/event를
  재사용해 행동을 중복 적용하지 않는다. GameStateView는 현재 권한으로 다시
  투영하며 Redis 24h 항목은 조회 cache일 뿐이다.

응답 `200`: 반영 후 GameStateView. 이후 진행(AI 턴 등)은 SSE/폴링으로 수신.

### 2.5 `GET /api/v1/games/{game_id}/events` — SSE 구독

`text/event-stream`. 폴링 대체 수단이며 Front는 SSE 실패 시 2.3 증분 조회로
폴백한다.

```text
event: game_update
data: {"game_id":"uuid","state_version":18,"phase":"DAY_VOTE",
       "server_time":"...","deadline_at":"...",
       "discussion":{"cycle":null,"current_speaker_player_id":null},
       "new_public_events":[...],"agent_status":"IDLE"}
```

`agent_status`: `IDLE | THINKING | FALLBACK` — AI 처리 중 표시용.
Front는 밤 10초 남음, 투표·재투표·최종 투표 15초·5초 남음에 경고하되,
표시 타이머를 권위 판정으로 사용하지 않는다. SSE 단절 시 폴링 응답의
`server_time`·`deadline_at`으로 복구한다.

### 2.6 `GET /api/v1/games/{game_id}/result` — 종료 결과

`FINISHED` 게임만. 그 외에는 409 `GAME_STATE_CONFLICT`.

```json
{
  "game_id": "uuid",
  "winner": "CITIZEN",
  "finish_reason": "FINAL_TARGET_MAFIA",
  "rounds": 5,
  "ruleset_version": "mystery-v1",
  "scenario": {
    "scenario_id": "snow-lodge",
    "scenario_version": "scenario-v1",
    "title": "눈 내리는 산장",
    "background": "폭설로 고립된 산장에서 관리인이 사망했습니다.",
    "victim": "산장 관리인",
    "locations": ["거실", "주방", "복도", "관리인 방", "창고"],
    "objective": "현장에 있던 플레이어 중 마피아를 찾아내세요."
  },
  "players": [
    {"player_id": "uuid", "seat": 1, "display_name": "...", "kind": "AI",
     "role": "MAFIA", "alive": false,
     "alibi": "저녁 식사 후 거실에 있었다.",
     "observation": {"text": "누군가 복도를 지나는 것을 봤다.",
                     "target_seat": null, "anonymous": true},
     "eliminated_by": "VOTE", "eliminated_round": 2}
  ],
  "timeline_highlights": [
    {"round": 1, "type": "PLAYER_KILLED", "summary": "..."}
  ],
  "night_history": [
    {"round": 1, "kill_proposals": ["player-uuid"],
     "resolved_target_player_id": "player-uuid",
     "protected_player_id": "player-uuid", "killed_player_id": null,
     "investigations": [{"detective_player_id": "uuid",
                          "target_player_id": "uuid", "is_mafia": false}]}
  ],
  "vote_history": [
    {"round": 2, "kind": "NORMAL",
     "ballots": [{"voter_player_id": "uuid", "target_player_id": "uuid"}],
     "totals": [{"target_player_id": "uuid", "votes": 3}],
     "resolved_target_player_id": "uuid"}
  ],
  "agent_decision_summaries": [
    {"player_id": "uuid", "round": 2,
     "summary": "공개 발언의 모순을 근거로 투표했습니다."}
  ],
  "human_summary": {"survived": false, "vote_accuracy": 0.67}
}
```

종료 결과에서는 전체 역할·알리바이·구조화 관찰·개별 야간 행동·개별 투표를
공개할 수 있다.
`agent_decision_summaries`는 행동 시점에 생성·정규화한 짧은 근거 요약만 담고,
chain-of-thought, 전체 prompt·응답, 비공개 메모리를 저장하거나 반환하지 않는다.

### 2.7 `POST /api/v1/feedback`

```json
{
  "acting_user_id": "uuid",
  "game_id": "uuid-or-null",
  "rating": 4,
  "category": "AI_QUALITY",
  "content": "정규화·검증된 자유 입력 (최대 2000자)"
}
```

응답 `201 {"feedback_id": "uuid"}`.

### 2.8 관리자 API (`frontend_admin` 전용)

관리자 권한은 `acting_user_id`가 `user_roles`에 `ADMIN` role을 가진 활성
사용자일 때만 허용한다. 실패 시 403 `ADMIN_ACCESS_DENIED`. 일반 사용자용
서명·세션을 관리자 권한 근거로 재사용하지 않는다.

| Method | Endpoint | 쿼리/바디 | 응답 요지 |
|---|---|---|---|
| `GET` | `/api/v1/admin/kpis` | `?period=today\|7d\|30d` | 신규 게임 수, 완주율, 평균 시간·밤 수, 재개율, 6~9명별 진영 승률, 보호 성공, 탐정 생존·조사 영향, mafia-on-mafia 공격·투표, 사용자 첫밤 사망, deadline 자동 선택, LLM 성공/timeout/fallback률, 평균 token·비용, 피드백 평균·미처리 |
| `GET` | `/api/v1/admin/logs` | `?from&to&trace_id&game_id&severity&event_type&page&size` | 민감 필드 제거된 감사·오류 로그 페이지 |
| `GET` | `/api/v1/admin/feedback` | `?status&category&page&size` | 피드백 목록과 집계 |
| `PATCH` | `/api/v1/admin/feedback/{feedback_id}` | `{"status": "REVIEWING"}` | 상태 변경 결과 |

로그 응답에는 전체 prompt, 비공개 역할 목록, 비밀정보를 포함하지 않는다.

---

## 3. DB·Redis 계약 (Backend 코드 소유 / MCP 실행 환경 소유)

### 3.0 원칙

- PostgreSQL이 영구 원본. Redis는 lock·cache·stream 전용(10장 최종 플랜 준수).
- 신규 schema는 `backend/migrations/002_create_mafia_game_schema.sql`부터
  기존 001 컨벤션(단일 트랜잭션, `IF NOT EXISTS`, 재실행 가능, 한국어 주석,
  `updated_at` 트리거 재사용)을 따른다.
- 검색·무결성 필드는 열로, 규칙별 확장 데이터는 검증된 JSONB로 둔다.
- 종료 전 비공개 정보(역할, 조사 결과)는 API 계층에서 필터하며, DB 접근은
  repository를 통해서만 한다.
- DB 자격증명은 분리한다. MCP 인프라 담당자의 migration 실행기만
  `DATABASE_MIGRATION_URL`(스키마 소유·DDL 권한)을 사용하고, Backend runtime은
  `DATABASE_URL`(필요한 테이블 DML·sequence 최소 권한)만 사용한다.
  Backend runtime에 DDL·role 관리 권한을 주지 않는다.
- 인프라 순서는 순환 의존을 금지한다. MCP가 먼저 PostgreSQL·Redis 기반
  인스턴스·migrator/runtime role·health를 준비한 뒤, Backend가 fake 검증을 마친
  migration 산출물을 전달하면 MCP가 적용·재실행하고, Backend가 같은
  환경에서 runtime 연결 스모크를 수행한다.
- MCP 서버 runtime은 이 운영 책임과 무관하게 DB·Redis에 직접 접근하지 않는다.

### 3.1 테이블 정의

#### `game_sessions` — 게임 헤더

| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | uuid | PK, `gen_random_uuid()` | 게임 식별자 |
| `owner_user_id` | uuid | NOT NULL, FK→`users(id)` | 소유 사용자 |
| `creation_order` | bigint | GENERATED ALWAYS AS IDENTITY, UNIQUE | advisory lock 획득 뒤 발급하는 생성 순서 |
| `status` | text | NOT NULL, CHECK in (`CREATED`,`IN_PROGRESS`,`PAUSED`,`FINISHED`) | 게임 상태 |
| `phase` | text | NOT NULL, CHECK (Phase enum) | 현재 단계 |
| `round` | int | NOT NULL DEFAULT 0, CHECK 0~5 | 현재/방금 해소한 밤 번호; 첫 `NIGHT_ACTION` 진입 시 1 |
| `winner` | text | NULL, CHECK in (`MAFIA`,`CITIZEN`) | 승리 진영 |
| `finish_reason` | text | NULL, CHECK (FinishReason enum) | 표준·최종 급사 종료 사유 |
| `player_count` | int | NOT NULL, CHECK 6~9 | 전체 인원 |
| `ruleset_version` | text | NOT NULL, CHECK = `mystery-v1` | 규칙 버전 |
| `scenario_id` | text | NOT NULL, CHECK in (2.0.3의 5개 ID) | catalog의 불변 ID |
| `scenario_version` | text | NOT NULL, CHECK = `scenario-v1` | 시나리오 버전 |
| `scenario_snapshot` | jsonb | NOT NULL | 공개 `title/background/victim/locations/objective`의 생성 시점 본 |
| `state_version` | int | NOT NULL DEFAULT 0 | optimistic lock 버전 |
| `random_seed` | text | NOT NULL | 재현용 seed. **API 응답 금지** |
| `phase_deadline_at` | timestamptz | NULL | 마감 phase의 서버 권위 UTC deadline |
| `paused_remaining_ms` | bigint | NULL, CHECK ≥0 | 일시 정지 시 남은 deadline |
| `next_wakeup_at` | timestamptz | NULL | deadline 또는 즉시 처리할 AI turn의 DB scheduler 원본 |
| `worker_claim_id` / `worker_claim_until` | uuid / timestamptz NULL | 다중 worker용 짧은 DB lease; 둘은 함께 NULL/값 |
| `saved_at` | timestamptz | NULL | 마지막 저장 시각 |
| `created_at` / `updated_at` | timestamptz | NOT NULL DEFAULT now | 001 트리거 재사용 |

인덱스: `(owner_user_id, status)` — 저장 목록 조회,
`(owner_user_id, creation_order DESC)` — owner별 직전 **commit 성공** 게임의
시나리오 선택(롤백된 row는 조회되지 않음),
`(next_wakeup_at) WHERE status='IN_PROGRESS' AND next_wakeup_at IS NOT NULL` —
background scheduler due-row claim.

#### `game_players` — 참가자와 비공개 역할

| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | uuid | PK | 참가자 식별자 (`player_id`) |
| `game_id` | uuid | NOT NULL, FK→`game_sessions` ON DELETE CASCADE | |
| `user_id` | uuid | NULL, FK→`users(id)` | 인간이면 사용자, AI면 NULL |
| `kind` | text | NOT NULL, CHECK in (`HUMAN`,`AI`) | |
| `seat` | int | NOT NULL, UNIQUE(game_id, seat) | 발언 순서 좌석 |
| `display_name` | text | NOT NULL, 길이 1~40 | 표시 이름 |
| `role` | text | NOT NULL, CHECK in (`MAFIA`,`DETECTIVE`,`DOCTOR`,`CITIZEN`) | **비공개.** 응답 필터 필수 |
| `private_profile` | jsonb | NOT NULL | `alibi` 문자열 + `observation{text,target_seat,anonymous}`. 해당 플레이어와 종료 결과만 공개 |
| `alive` | boolean | NOT NULL DEFAULT true | |
| `eliminated_by` | text | NULL, CHECK in (`VOTE`,`NIGHT_KILL`) | |
| `eliminated_round` | int | NULL | |
| `persona_id` | uuid | NULL, FK→`agent_personas` | AI만 |
| `created_at` / `updated_at` | timestamptz | | |

제약: `kind='HUMAN'`이면 `user_id NOT NULL AND persona_id IS NULL`,
`kind='AI'`이면 `user_id IS NULL` (CHECK).
진영은 승패 계산 시 `role == MAFIA`인지로 내부 파생하며 별도 `faction` 열을
저장하지 않는다. API·event·MCP 응답에도 `faction`/`FACTION` 필드를 만들지 않는다.
`private_profile.observation`은 `(target_seat IS NOT NULL AND anonymous=false)`와
`(target_seat IS NULL AND anonymous=true)` 중 정확히 하나의 형태만 허용한다.
target은 현재 인원의 다른 유효 좌석이어야 하며 문자열·marker를 snapshot·event와
GameStateView에서 동일하게 보존한다.

#### `game_events` — append-only 게임 기록

| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | uuid | PK | |
| `game_id` | uuid | NOT NULL, FK CASCADE | |
| `sequence` | bigint | NOT NULL, UNIQUE(game_id, sequence) | 게임 내 단조 증가 |
| `type` | text | NOT NULL | 이벤트 유형 (3.2 목록) |
| `visibility` | text | NOT NULL, CHECK in (`PUBLIC`,`PRIVATE`,`SYSTEM`) | |
| `audience_player_id` | uuid | NULL, FK→`game_players` | PRIVATE 대상 |
| `payload` | jsonb | NOT NULL DEFAULT '{}' | 유형별 데이터 |
| `created_at` | timestamptz | NOT NULL | |

제약(CHECK): `visibility='PRIVATE'`→`audience_player_id NOT NULL`, 그 외은
`audience_player_id IS NULL`. UPDATE/DELETE 금지는 repository 규율로 강제
(트리거는 후속 검토).
인덱스: `(game_id, sequence)`, `(game_id, visibility, sequence)`.

#### `game_snapshots` — 저장·복구

| 열 | 타입 | 제약 |
|---|---|---|
| `game_id` | uuid | FK CASCADE, PK(game_id, version) |
| `version` | int | 저장 시점 `state_version` |
| `state` | jsonb | 전체 엔진 상태 직렬화(역할 포함, **SYSTEM 등급**) |
| `checksum` | text | state 정규화 SHA-256 |
| `last_event_sequence` | bigint | 이 snapshot이 반영한 마지막 이벤트 |
| `created_at` | timestamptz | |

복구 규칙: checksum·schema·ruleset/scenario version 검증에 실패한 snapshot은
**절대 상태 원본으로 사용하지 않는다.** 최신부터 역순으로 첫 번째
유효 snapshot을 찾아 그 `last_event_sequence` 다음부터 재생한다. 유효 snapshot이
하나도 없으면 `GAME_CREATED`·초기 배정 이벤트(genesis)부터 전체 재생한다.
이벤트 sequence 공백·checksum 실패는 감사 이벤트로 기록하되 손상 snapshot을
복구에 혼합하지 않는다.

#### `game_command_receipts` — 영구 멱등 원본

| 열 | 타입 | 제약/설명 |
|---|---|---|
| `id` | uuid | PK |
| `game_id` | uuid | FK CASCADE |
| `requester_kind` / `requester_id` | text / uuid | `USER`의 user id 또는 `AGENT`의 player id |
| `operation` / `idempotency_key` | text / uuid | command·`RESUME`·Engine Tool / API key 또는 `proposal_id` |
| `request_hash` | text | 검증·정규화한 요청의 canonical SHA-256 |
| `http_status` / `response_code` | int / text NULL | 최초 command outcome 상태·공통 오류 code |
| `canonical_outcome` | jsonb | 민감정보 없는 accepted/result event id·version·자동선택 seed 참조만 |
| `committed_event_id` | uuid NULL | 행동을 commit한 `game_events.id` |
| `created_at` | timestamptz | NOT NULL |

`UNIQUE(game_id, requester_kind, requester_id, operation, idempotency_key)`를 두고
최초 판정·event와 receipt를 같은 PostgreSQL transaction에서 commit한다. 같은 key와
같은 `request_hash`는 Redis 유무·프로세스 재시작과 무관하게 저장한 최초
`canonical_outcome`을 재사용해 같은 event·판정을 반환한다. 같은 key에 다른 hash는
409 `GAME_STATE_CONFLICT`로 거부한다. receipt에 GameStateView, role, private profile,
PRIVATE/SYSTEM event나 원본 action을 저장하지 않는다. 사용자 API의 View는 재시도
시점의 소유권·생존 상태를 다시 검증한 뒤 **현재 audience projector로 새로 생성**한다.
따라서 생존 중 만든 receipt를 사망 후 재전송해도 PUBLIC 관전 View만 반환한다.
Redis 24시간 key는 이 테이블의 조회 가속일 뿐 원본이 아니다.
동시 중복, 응답 유실 뒤 재시도, Redis flush·Backend 재시작, Engine `proposal_id`,
resume 재전송에서 event·자동 선택이 중복되지 않는지, 사망 전 receipt→사망 후 replay가
역할·알리바이·관찰·PRIVATE event를 다시 노출하지 않는지 검증한다.

#### `agent_personas` — 버전 고정 페르소나 프리셋

| 열 | 타입 | 제약 |
|---|---|---|
| `id` | uuid | PK |
| `name` | text | NOT NULL, UNIQUE(name, version) |
| `version` | int | NOT NULL DEFAULT 1 |
| `parameters` | jsonb | NOT NULL — 공격성·친화성 등 표현 성향과 `display_name`,`speech_style`,`backstory` |
| `active` | boolean | NOT NULL DEFAULT true |
| `created_at` / `updated_at` | timestamptz | |

시드 데이터: 차분한 분석가, 성급한 리더, 조용한 관찰자, 친화적 중재자,
능숙한 블러퍼 5종을 migration에서 INSERT … ON CONFLICT DO NOTHING으로 등록.
모든 플레이어 agent는 동일한 model·추론 제약·컨텍스트 필터·Tool 권한
규칙을 사용한다. persona는 말투·표현·사회적 태도만 변경하고 추론 정확도,
정보 접근 범위, timeout/token 상한을 변경하지 않는다.

#### `agent_runs` — LLM 호출 품질·비용 지표

| 열 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | run 식별자 |
| `game_id` / `player_id` | uuid FK | 대상 |
| `phase` | text | 실행 단계 |
| `status` | text CHECK in (`SUCCESS`,`TIMEOUT`,`INVALID_OUTPUT`,`FALLBACK`,`ERROR`) | |
| `latency_ms` | int | |
| `prompt_tokens` / `completion_tokens` | int | 사용량 |
| `model_code` | text | 예: `openai:gpt-4.1-mini` |
| `error_code` | text NULL | 실패 분류. **프롬프트·응답 원문 저장 금지** |
| `created_at` | timestamptz | |

#### `user_feedback`

| 열 | 타입 | 제약 |
|---|---|---|
| `id` | uuid PK / `user_id` uuid FK NOT NULL / `game_id` uuid FK NULL | |
| `rating` | int NOT NULL CHECK 1~5 | |
| `category` | text CHECK in (`FUN`,`AI_QUALITY`,`RULE_ERROR`,`PERFORMANCE`,`ETC`) | |
| `content` | text, 길이 ≤2000 | 저장 전 정규화 |
| `status` | text CHECK in (`NEW`,`REVIEWING`,`RESOLVED`,`WONT_FIX`) DEFAULT `NEW` | |
| `created_at` / `updated_at` | timestamptz | |

#### `user_roles` — 관리자 권한 (신규)

| 열 | 타입 | 제약 |
|---|---|---|
| `user_id` | uuid FK→`users` CASCADE | PK(user_id, role) |
| `role` | text CHECK in (`ADMIN`) | |
| `granted_at` | timestamptz NOT NULL | |

관리자 부여는 운영자가 SQL로 직접 수행(MVP에는 부여 API 없음).

#### `audit_logs` — 관리자·보안·MCP 감사

| 열 | 타입 | 설명 |
|---|---|---|
| `id` uuid PK / `trace_id` text | 요청 상관관계 |
| `source_instance_id` / `audit_id` | uuid NULL / uuid NULL | MCP `audit-v1` receipt 식별자; 둘은 함께 NULL 또는 함께 값 |
| `payload_hash` | text NULL | 승인 필드만 canonical JSON으로 직렬화한 SHA-256; MCP receipt일 때 필수 |
| `actor_type` | text CHECK in (`USER`,`ADMIN`,`AGENT`,`SYSTEM`) | |
| `actor_id_hash` | text | 원본 id 대신 해시 |
| `action` | text | 예: `MCP_TOOL_CALL`,`MCP_DENIED`,`ADMIN_FEEDBACK_UPDATE` |
| `target_type` / `target_id` | text | 예: `GAME`, game_id |
| `allowed` | boolean | 허용/거부 |
| `metadata` | jsonb | 민감 필드 제거된 요약만 |
| `created_at` | timestamptz | |

MCP receipt에는 partial unique index
`UNIQUE(source_instance_id, audit_id) WHERE source_instance_id IS NOT NULL`을 두고,
세 receipt 열은 모두 NULL이거나 모두 채워지도록 CHECK한다. `/audit` 재전송 시
기존 `payload_hash`가 같으면 duplicate 성공, 다르면 409로 처리한다. 이 제약으로
프로세스 재시작 뒤에도 메모리 비교에 의존하지 않고 5.4의 멱등 계약을 지킨다.

#### `audit_outbox` — 감사 전달 재시도

| 열 | 타입 | 설명 |
|---|---|---|
| `id` / `audit_id` | uuid PK / uuid NOT NULL | outbox·감사 레코드 식별자 |
| `source` | text CHECK in (`BACKEND`,`MCP`) | 생성 주체 |
| `source_instance_id` | uuid NOT NULL | 생성 runtime instance; Backend도 기동 시 UUID 발급 |
| `sanitized_payload` | jsonb | 비밀·prompt·역할 명단을 제거한 허용 schema |
| `status` | text CHECK in (`PENDING`,`DELIVERED`) | 전달 상태 |
| `attempts` / `next_attempt_at` | int / timestamptz | 유한 backoff 재시도 |
| `created_at` / `delivered_at` | timestamptz | 생성·전달 시각 |

멱등 제약은 `UNIQUE(source, source_instance_id, audit_id)`로 고정한다. MCP sink의
정본 idempotency key도 `(instance_id, audit_id)`이며, instance가 다른 같은 UUID를
임의로 같은 사건으로 합치지 않는다.

감사 sink 실패는 이미 검증된 게임 행동·원본 `game_events` commit을
롤백하지 않는다. 게임 트랜잭션에 정규화한 outbox 레코드 또는 동등한
SYSTEM 재시도 이벤트를 같이 남기고, `audit_id`로 멱등 전달한다. outbox마저
영구 저장할 수 없으면 요청은 `GAME_PERSISTENCE_UNAVAILABLE`로 안전 중단한다.

### 3.2 game_events `type` 초기 목록

```text
PUBLIC : GAME_CREATED, SCENARIO_REVEALED, PHASE_CHANGED, PLAYER_SPEECH,
         PLAYER_PASSED, MODERATOR_ANNOUNCEMENT, MODERATOR_FIXED_QUESTION,
         VOTE_RESULT(집계만), REVOTE_STARTED, FINAL_VOTE_STARTED,
         PLAYER_EXECUTED(역할 공개 포함), PLAYER_KILLED(역할 미포함),
         NO_DEATH, GAME_FINISHED
PRIVATE: ROLE_ASSIGNED, PRIVATE_PROFILE_ASSIGNED, INVESTIGATION_RESULT,
         ACTION_ACCEPTED
SYSTEM : VOTE_BALLOTS_RAW, NIGHT_ACTIONS_RAW, ACTION_AUTO_SELECTED,
         NIGHT_RESOLVED, RESOLUTION_DETAIL, AGENT_TURN_RESERVED, AGENT_TURN_STALE,
         AGENT_FALLBACK, DEADLINE_EXPIRED, AUDIT_DELIVERY_PENDING, SEED_RECORDED
```

`NIGHT_RESOLVED`는 해당 round의 보호·공격·조사와 공개 결과를 모두 같은
transaction에서 정상 확정할 때 정확히 한 번 기록하는 완료 marker다. repository는
`(game_id, round, NIGHT_RESOLVED)`를 멱등하게 강제하고 이 marker가 없는
`NIGHT_RESOLUTION` 진입·재시도는 완료 밤 수로 세지 않는다.

### 3.3 Redis Key 설계 (최종 플랜 10장 그대로 채택)

`team4:game:{game_id}:lock`(30s) / `:runtime`(30m) / `:events`(stream) /
`team4:game:deadlines`(sorted set, PostgreSQL deadline의 가속 인덱스) /
`team4:idempotency:{user_id}:{key}`(24h) / `team4:agent:{run_id}:status`(15m) /
`team4:agent:{game_id}:{player_id}:reservation`(외부 호출 상한) /
`team4:rate:{user_id}`. lock token 소유자만 해제하고 DB commit 전 cache·stream을
갱신하지 않는다. deadline sorted set·reservation은 손실 가능한 가속 데이터이며
재시작 시 PostgreSQL `next_wakeup_at`·`phase_deadline_at`에서 재구성한다.
시나리오 생성 직렬화는 Redis TTL lock을 사용하지 않고 2.1의 PostgreSQL
transaction-scoped advisory lock만 사용한다.

---

## 4. Backend 섹터 상세 계획

### 4.1 신규 파일 (승인된 구조 변경 범위)

```text
backend/app/models/game.py            # 게임 도메인: 역할표, 상태 머신, 판정
backend/app/models/scenario.py        # scenario-v1 정적 catalog·결정적 배정
backend/app/models/persona.py         # 페르소나 값 객체와 검증
backend/app/services/game_service.py  # 생성·명령·저장·조회 유스케이스
backend/app/services/game_timer_service.py # deadline·자동 선택·재시작 복구
backend/app/services/admin_service.py # KPI·로그·피드백 유스케이스
backend/app/repositories/game_repository.py
backend/app/repositories/feedback_repository.py
backend/app/repositories/admin_repository.py
backend/app/routers/game_router.py
backend/app/routers/feedback_router.py
backend/app/routers/admin_router.py
backend/app/routers/engine_internal_router.py   # 5장 내부 Engine API
backend/app/schemas/game_schema.py
backend/app/schemas/admin_schema.py
backend/app/agent/manager.py          # Agent Manager 실행 루프
backend/app/agent/context.py          # 에이전트별 최소 컨텍스트·격리 검사
backend/app/agent/prompts.py          # 공통 제약/개성 프롬프트 2계층
backend/app/llm/providers.py          # OpenAI·Gemini 어댑터 (+fake)
backend/app/mcp/capability.py         # game/subject/phase/version 회전 capability
backend/app/mcp/transport_auth.py     # MCP transport 단기 token·TLS 정책
backend/app/infrastructure/redis/client.py
backend/app/infrastructure/redis/locks.py
backend/app/infrastructure/security/game_request.py # 게임 API 서명 검증
backend/migrations/002_create_mafia_game_schema.sql
backend/tests/test_game_rules.py, test_game_state_machine.py,
  test_game_scenarios.py, test_game_timers.py, test_game_api.py,
  test_game_repository.py, test_game_receipts.py, test_snapshot_replay.py,
  test_audit_outbox.py,
  test_agent_manager.py, test_context_isolation.py, test_admin_api.py,
  test_engine_internal_api.py, test_mcp_transport_auth.py, test_redis_locks.py
```

기존 파일 중 `backend/app/core/config.py`,
`backend/app/infrastructure/migrations.py`, `backend/tests/test_config.py`,
`backend/tests/test_migrations.py`는 WU-B3의 migration 전용 설정 경계 보정을
위해 수정할 수 있다. 이 네 파일은 신규 파일이 아니며 다른 설정 리팩터링으로
범위를 넓히지 않는다.

### 4.2 작업 순서 (최종 플랜 14장 단계와 대응)

아래 B1~B9가 Backend coding AI agent의 WU이며 **한 세션은 WU 1개 이하**로
제한한다. 섹터 지침서의 WU·CP 번호도 이 계약에 맞게 동기화한다.

1. **WU-B1. `mystery-v1` 규칙 엔진(LLM·DB 없음)** — 6~9명 역할표,
   blind mafia, 첫날 낮 무투표, 좌석 1순환·전원 PASS 추가 1순환, 밤 해소,
   일반·재·최종 투표, 표준·최종 급사 승패를 순수 함수로 구현한다.
   *완료 기준: 결정적 seed, 사망 역할·투표 비공개 불변식, 6~9명 fake 완주.*
2. **WU-B2. `scenario-v1` 엔진** — 정적 catalog 5종, owner별 직전
   commit 성공 게임 1건을 입력받는 결정적 selector와 2.1의 stable 64-bit
   owner lock-key 순수 함수를 구현한다(DB 호출 없음).
   초기 기획의 사건별 예시 1개는 제품용 catalog로 충분하지 않으므로, 5개
   scenario마다 최대 9개 좌석의 알리바이 1개와 관찰 1개, 즉 **최소 90개
   정적 template record**를 작성한다. 각 관찰에는 유효한 `target_seat` 또는
   명시적 `anonymous` marker가 있어야 하며, 역할중립·좌석 범위·상호 무모순을
   정적 검증한다. *완료 기준: 5종×6/7/8/9명 seed 재현·비누설, lock-key 고정
   벡터와 전체 문구의
   제품 리뷰 승인. 콘텐츠 승인 전에는 CP-B1을 완료 처리할 수 없다.*
3. **WU-B3. DB 계약·영속화** — migration 002, repository, append-only event,
   optimistic version, 영구 command/proposal receipt, audit outbox, 손상 snapshot
   배제→이전 유효 snapshot→genesis
   재생을 구현한다. 2.1의 PostgreSQL transaction-scoped advisory lock을 첫 DB
   statement로 얻은 뒤 직전 성공 commit 조회→scenario 선택→게임·snapshot insert를
   같은 `READ COMMITTED` transaction에서 수행한다. `creation_order` identity,
   첫 게임·같은 owner 동시 요청·강제 hash 충돌·rollback sequence 공백을 검증한다.
   migration CLI/process는 `DATABASE_MIGRATION_URL`만 필수
   소비하도록 `core/config.py`·`infrastructure/migrations.py`를 분리하고 누락·
   placeholder를 fail-closed한다. Backend runtime Settings·연결은 계속
   `DATABASE_URL`만 사용하며 migration URL을 보유하거나 로그에 남기지 않는다.
   *완료 기준: `test_config.py`·`test_migrations.py`의 URL 경계·누락·placeholder
   거부와 repository fake 검증 후 migration 산출물을 MCP CP-M1B에 전달하고,
   실제 동시 transaction 검증은 CP-M1B 뒤 CP-B2 smoke에서 완료.*
4. **WU-B4. Redis 애플리케이션 연동** — game lock, idempotency,
   runtime cache, deadline 인덱스, event stream을 fake Redis로 검증한다. Redis 손실 시
   PostgreSQL 원본에서 복구한다. scenario 생성 lock은 이 WU에 포함하지 않는다.
5. **WU-B5. 사용자 API** — 2장의 시나리오·private profile·토론 커서·
   resume·deadline·종료 이력 명세, 소유권·필터·영구 idempotency·SSE를 구현한다.
   serializer는 scenario의 공개 allowlist
   `scenario_id/scenario_version/title/background/victim/locations/objective`를
   빠짐없이 사용한다. *완료 기준: 오류 표 전 경로, 공개 scenario 필드 계약,
   타인 비공개·seed·중간 투표 미포함 스냅샷.*
6. **WU-B6. 서버 권위 타이머** — fake clock으로 20/30초 deadline,
   자동 선택, 일시 정지·재개, 프로세스 재시작 복구, 중복 해소 방지를 구현한다.
   API lifespan startup에서 PostgreSQL `next_wakeup_at` 원본을 sweep해 Redis deadline
   index를 재구성하고, 실행 중에는 due row를 조건부 UPDATE/RETURNING으로 짧게
   lease claim한다. 여러 API worker는 `worker_claim_id/until`과 game version CAS로
   정확히 한 worker만 해소하며 만료 lease는 다른 worker가 회수한다. `PAUSED`는
   wakeup·claim을 비우고, 재개 시 다시 등록한다. 시작 시 이미 지난 deadline은
   즉시 결정적 해소한다. 테스트에서 실제 sleep을 사용하지 않는다.
7. **WU-B7. 내부 Engine API·capability·transport auth** — 5장의 bootstrap,
   context, actions, audit sink, phase/version별 회전 capability, MCP transport 단기 token·TLS
   정책을 구현한다. *완료 기준: 이전 token·타 game·actor 위조·Front secret 전부 거부.*
8. **WU-B8. Agent Manager + LLM/MCP client** — fake LLM으로 루프를 먼저
   완성하고 공개 전용 GM, 컨텍스트 카나리, 구조화 출력, 예산이 허용할 때만
   교정 1회, 회전 capability, 짧은 근거 요약을 구현한다. MCP 컨텍스트 조회가
   실패했을 때도 raw snapshot을 넘기지 않고, checksum·schema·ruleset/scenario
   version·연속 event sequence를 검증해 현재 version까지 복구한 상태를 Backend의
   **동일 Context projector와 audience allowlist**로 다시 투영한다. agent는 PUBLIC과
   현재 actor의 PRIVATE만, GM은 PUBLIC만 받을 수 있다. 다른 actor의 PRIVATE,
   SYSTEM, seed, 원본 행동·투표가 들어 있는 `game_snapshots.state` 자체는 prompt나
   MCP/LLM client 경계를 넘지 않는다. 검증·재투영에 실패하면 외부 호출 없이
   결정적 fallback을 사용한다. 두 LLM provider가 모두 실패해도 토론은 `PASS`,
   밤·투표는 규칙 엔진의 유효 대상 결정적 선택으로 진행하며 자동 pause하지 않는다.
   `MAFIA_MCP_URL`은 `/mcp`까지 포함한 full endpoint이며 client가 경로를 다시
   붙이지 않는다. 운영 endpoint는 5.1의 TLS 정책에 따라 `https://.../mcp`여야 한다.
   *완료 기준: 다른 플레이어 비밀·SYSTEM marker를 주입한 fallback 카나리와
   출력 비간섭성, GM의 유죄 단정·catalog 외 사실 생성 거부, 20초 절대 deadline
   fake-clock, 늦은 결과 CAS 거부 테스트.
   deadline 없는 토론에서 현재 좌석이 AI면 `next_wakeup_at=now()`로 등록해 client·
   SSE 접속 없이도 처리하고, restart 후 pending AI turn을 이어가는 테스트.*
9. **WU-B9. 관리자 API** — `user_roles` 검증, 6~9명·scenario별 KPI,
   보호 성공·탐정 생존/조사 영향·mafia-on-mafia·사용자 첫밤 사망·deadline
   자동 선택 지표, outbox 지연 가시성, 로그 민감 필드 제거를 구현한다.

### 4.3 Backend 고위험 주의 (AGENTS.MD 0.6 적용)

게임 소유권, 역할·private profile·중간 투표 비공개, deadline 경합, lock,
capability 회전, transport 인증, 감사 outbox, 관리자 권한은 **실패·거부
경로 테스트를 구현과 함께** 작성한다. seed·역할·알리바이·관찰 전문·
prompt·response·transport/capability token을 로그에 남기지 않는다.

Agent Manager는 LLM·MCP 네트워크 호출 동안 게임 lock을 보유하지 않는다.

```text
lock 획득 → phase/version 검증 → reservation 이벤트·CAS 버전 commit → lock 해제
→ MCP/LLM 외부 호출
→ lock 재획득 → reservation·phase·version·deadline 재검증
→ 유효하면 CAS 반영, stale이면 폐기·SYSTEM 기록 → lock 해제
```

같은 밤·투표에 여러 AI가 행동해야 할 때는 각 actor reservation을 짧은 lock 구간에서
확정한 뒤 외부 호출을 provider 한도 내에서 병렬 실행한다. actor 수만큼 timeout을
순차 합산하거나 개별 호출마다 deadline을 새로 시작하지 않는다. 모든 run이 같은
`phase_deadline_at`을 공유하고 결과는 actor별 idempotent CAS로 반영하며, deadline
worker가 아직 미확정인 actor만 결정적 fallback 처리한다.

개별 timeout만으로 20초 밤 deadline을 보장할 수 없으므로 모든 agent turn은
`phase_deadline_at` 기준 **end-to-end 절대 예산**을 사용한다.

- reservation commit 직후 남은 시간을 다시 계산하고, DB commit·lock 재획득·
  네트워크 지연용 `AGENT_COMMIT_NETWORK_RESERVE_SECONDS`(기본·권장 3초)를
  먼저 제외한다. `/context`와 LLM을 시작할 때는 그 3초뿐 아니라 마지막
  MCP `/actions`용 `MCP_TIMEOUT_SECONDS`(기본·최대 3초)도 후속 필수 reserve로 뺀다.
- 각 호출 직전 `remaining_phase = deadline - now`,
  `remaining_external = external_budget - external_spent`를 다시 구한다. context와
  LLM timeout은
  `min(configured_timeout, remaining_phase-action_reserve-commit_reserve,
  remaining_external-action_reserve)`, 마지막 `/actions`는
  `min(MCP_TIMEOUT_SECONDS, remaining_phase-commit_reserve, remaining_external)`다.
  계산값이 0 이하이면 해당 선택 호출을 건너뛰고 즉시 phase별 결정적 fallback을
  준비한다. `LLM_TIMEOUT_SECONDS=15`는 단일 호출 상한일 뿐 전체 deadline 보장이
  아니며 두 번째 provider failover도 새 호출로 같은 계산을 다시 통과해야 한다.
- 구조화 출력 교정은 최대 1회이며, 교정 뒤에도 `/actions` 3초와 commit 3초를
  보존할 수 있을 때만 시도한다. 기본값에서 phase 한계만 보면 최악 경로는
  `context 3초 + LLM ≤11초 + actions 3초 + commit 3초 = 20초`이고, 총 외부
  budget 16초가 실제 LLM 상한을 더 줄일 수 있다. LLM 결과를 더 기다리면 후속
  reserve를 침범하는 시점에는 즉시 취소·폐기하고 fallback으로 전환한다.
- lock 재획득 뒤 reservation·phase·version·생존·deadline을 다시 검사한다.
  늦은 성공 결과는 반드시 CAS 거부하고, deadline worker 또는 현재 요청이
  `SPEAK=PASS`, 밤·투표=seed 기반 유효 대상 선택을 한 번만 commit한다. 외부
  provider 장애만으로 게임을 자동 pause하거나 사용자에게 재시도를 요구하지 않는다.

fake clock으로 20초 밤의 MCP 지연·첫 LLM timeout·교정 생략·두 provider 장애를
각각 재현하고, deadline 안에 정확히 한 행동 또는 fallback이 확정되며 늦은 결과가
상태를 바꾸지 않음을 검증한다. 4개 AI 밤 행동과 최대 8개 AI 투표 run도 공유
deadline 아래 병렬 실행되어 `N × timeout` 지연이 생기지 않는지 검증한다.
context가 3초를 소진한 경우 LLM이 남은 action 3초+commit 3초를 침범하기 전에
clamp/취소되는 경계도 별도 검증한다.

설정 검증은 `LLM_TIMEOUT_SECONDS=15`, `MCP_TIMEOUT_SECONDS=3`,
`AGENT_EXTERNAL_CALL_BUDGET_SECONDS=16`,
`AGENT_COMMIT_NETWORK_RESERVE_SECONDS=3`을 기본으로 한다. timeout·budget·reserve는
양수여야 하고 총 외부 budget은 가장 짧은 20초 phase에서 reserve를 뺀 값 이하여야
한다. 더 큰 개별 timeout은 시작 시 오류를 내기보다 위 공식으로 매 호출 clamp하되,
파싱 실패·0·음수와 budget/reserve 불가능 조합은 기동 시 fail-closed한다.

MCP 조회 장애의 snapshot fallback은 3.1의 복구 검증을 통과한 snapshot과 공백 없는
후속 event로 현재 version을 재구성한 뒤에만 허용한다. Backend는 정상 `/context`와
동일한 projector를 호출해 agent에는 PUBLIC+현재 actor PRIVATE, GM에는 PUBLIC만
재투영한다. raw `game_snapshots.state`, 다른 actor PRIVATE, SYSTEM은 어떤 경우에도
prompt 입력으로 전달하지 않는다. 검증된 최소 컨텍스트가 없으면 위 결정적 fallback을
사용한다. 정상 경로와 fallback 경로에 동일 비밀 카나리를 주입하고 prompt·결정·감사
요약이 그 값에 따라 달라지지 않는 비간섭성 테스트를 둔다.

---

## 5. 내부 Engine API (Backend ↔ MCP Server 계약)

MCP 서버는 DB에 직접 접근하지 않고 Backend의 내부 HTTP API만 호출한다.
인증은 기존 HMAC 방식과 동일 canonical(`timestamp.request_id.raw_body`)에
**별도 secret `ENGINE_INTERNAL_API_SECRET`**을 사용한다(Front용과 분리).
bootstrap·context·actions·audit 전체에 HMAC·timestamp·request id replay 방지를
적용한다. context·actions에는 Backend가 발급한 `capability_token`을
추가로 요구하고 매 호출에서 독립적으로 재검증한다.
Backend 응답도 `X-Engine-Response-Timestamp`, 원 요청 ID,
`X-Engine-Response-Signature`로 인증한다. 응답 canonical은
`response_timestamp.request_id.status_code.raw_body`이며 MCP는 body 사용 전에
`ENGINE_INTERNAL_API_SECRET`으로 검증한다. TLS가 이 응답 무결성 검사를 대체하지 않는다.

베이스 경로: `/internal/v1/engine` (외부 공개 금지, 문서화도 내부 한정).

| Method | Endpoint | 용도 |
|---|---|---|
| `POST` | `/internal/v1/engine/bootstrap` | MCP instance·계약 버전·시계 검증 |
| `POST` | `/internal/v1/engine/context` | subject별 허용 컨텍스트 조회 (Resource 데이터 원천) |
| `POST` | `/internal/v1/engine/actions` | Tool 행동 제안 제출 → 엔진 최종 검증·반영 |
| `POST` | `/internal/v1/engine/audit` | MCP 조회·행동·거부 감사 batch sink |

### 5.1 bootstrap·capability·transport 인증

MCP server는 기동 시 `/bootstrap`에 다음과 같이 자신의 계약을 선언한다.

```json
{
  "instance_id": "runtime-generated-uuid",
  "client_time": "2026-09-01T05:10:00Z",
  "ruleset_versions": ["mystery-v1"],
  "scenario_versions": ["scenario-v1"],
  "transport_contract_version": "mcp-transport-v1",
  "audit_schema_version": "audit-v1"
}
```

Backend는 버전·시계 편차·instance 형식을 검증하고
`{"accepted":true,"server_time":"...","max_clock_skew_seconds":30}`를 반환한다.
불일치면 `CONTRACT_VERSION_MISMATCH`로 fail-closed하고 Resource/Tool을 열지 않는다.

MCP는 bootstrap 요청 직전·응답 직후의 monotonic 시각과 인증된 `server_time`을
하나의 clock anchor로 저장한다. 최초 wall-clock 편차가 허용치 30초를 넘거나
왕복 시간이 설정 상한을 넘으면 bootstrap을 거부한다. 비대칭 RTT에서 유효 행동을
조기 거부하지 않도록 수신 시 보수적 하한
`anchor_server_lower_bound = server_time`, `anchor_mono = received_mono`로 고정한다.
이 하한 때문에 최대 허용 RTT만큼 늦은 요청을 MCP가 1차 허용할 수 있으나 Backend의
권위 deadline 재검증이 최종 거부한다. 이후 `deadline_at`의
남은 시간은 OS wall clock을 다시 읽어 계산하지 않고, anchor의 server lower bound에
`monotonic_now - monotonic_anchor`를 더해 계산한다. 인증된 control 응답으로만
anchor를 갱신하며 anchor 누락·만료·monotonic 역행은 fail-closed 후 재-bootstrap한다.
wall clock을 앞뒤로 변경해도 20초 phase의 허용·거부 경계가 달라지지 않고,
유효 행동을 조기 거부하지 않으며, 하한 오차로 늦게 통과한 Tool은 Backend가
거부하는 fake-clock 테스트를 둔다.

Agent Manager가 MCP transport 세션을 열 때 Backend가 발급한 짧은 수명의
Bearer token을 사용한다. token은 `MCP_SERVER_AUTH_SECRET`으로 서명하고
audience, instance, session, game, `subject_kind`, `subject_id`, expiry를 묶는다.
`subject_kind=PLAYER`이면 `subject_id=agent_player_id`, `subject_kind=GM`이면
Backend가 해당 game/run에 발급한 불투명 `gm_run_id`다. MCP는 매 연결·요청에서
서명·audience·expiry·session binding을 검증한다. 개발·테스트의 평문 HTTP는
loopback에서만 허용하고, 생산은 Backend↔MCP·MCP↔Engine 모두 TLS,
인증서·hostname 검증, 평문 fallback 금지를 강제한다.

agent capability는 영구 세션 자격증명이 아니다. token은
`game_id + subject_kind + subject_id + phase + state_version + reservation_id + expiry`에 귀속되며
Agent Manager가 각 agent turn 직전 발급한다. phase 또는 state version이 바뀌면
이전 token을 즉시 폐기하고 새 token을 발급한다. MCP session에는 game/subject
정체성만 고정하며 capability를 영구 저장·재사용하지 않는다. Backend는
이전 version, 만료, 다른 reservation·game·subject의 token을 `STALE_CAPABILITY`로
거부한다.

GM도 예외가 아니다. announcement/요약 run마다 `subject_kind=GM`인 reservation과
phase/version capability를 새로 발급하고 run 종료·취소 즉시 session과 함께 폐기한다.
GM capability의 Resource scope는 PUBLIC rules·현재 scenario·public-state·
public-timeline뿐이며 allowed Tool은 항상 빈 목록이다. `/actions`는 GM subject의
모든 요청을 `ACTION_NOT_ALLOWED`로 거부한다. PLAYER와 GM subject kind를 바꾸거나
다른 game의 `gm_run_id`를 재사용하는 테스트를 둔다.

AI 플레이어의 사망이 commit되면 Agent Manager는 해당 agent의 활성 reservation,
transport session, capability를 즉시 폐기한다. 늦게 도착한 LLM/MCP 결과는
생존·version CAS에서 거부하고 `AGENT_TURN_STALE`만 SYSTEM으로 남긴다.

### 5.2 `POST /context`

요청: `{"capability_token": "...", "resource": "allowed-actions"}`
(`resource` ∈ `rules | scenario | public-state | public-timeline | me |
private-state | allowed-actions | persona`)

응답은 Backend가 **agent별 View로 필터 완료한** JSON. 예(`allowed-actions`):

```json
{
  "game_id": "uuid", "subject_kind": "PLAYER", "agent_player_id": "uuid",
  "phase": "NIGHT_ACTION",
  "state_version": 17,
  "reservation_id": "uuid",
  "server_time": "2026-09-01T05:10:00Z",
  "deadline_at": "2026-09-01T05:10:20Z",
  "actions": [
    {"tool": "game.kill", "required": true,
     "valid_targets": ["uuid1", "uuid2"]}
  ]
}
```

PLAYER 응답은 `agent_player_id`를 포함하고 GM 응답은 이를 생략한 채
`subject_kind="GM"`, `gm_run_id`와 PUBLIC data만 포함한다.
모든 `/context` Resource 응답에는 인증된 `server_time`을 포함해 5.1의
monotonic anchor를 갱신한다. `deadline_at`은 `NIGHT_ACTION`, `DAY_VOTE`,
`DAY_REVOTE`, `FINAL_VOTE`에서만 UTC 값이고 나머지 phase에서는 명시적 null이다.

`scenario`는 `scenario-v1`의 공개 allowlist인 `scenario_id`, `scenario_version`,
`title`, `background`, `victim`, `locations`, `objective`만 반환한다.
`private-state`는 해당 agent의 역할·알리바이·관찰·조사 결과만 반환하며
마피아에게도 다른 마피아 정보를 반환하지 않는다.
이 endpoint와 Agent Manager의 MCP 장애 fallback은 동일 Context projector를
호출해야 한다. 복구 검증 전 raw snapshot이나 projector 이전 도메인 object를
응답·prompt로 전달하는 별도 코드 경로를 만들지 않는다.

### 5.3 `POST /actions`

```json
{
  "capability_token": "...",
  "tool": "game.vote",
  "arguments": {"target_player_id": "uuid"},
  "proposal_id": "uuid"
}
```

- `actor`는 항상 capability에서 결정한다. arguments에 actor 관련 필드가
  있으면 422로 거부한다.
- 응답: `{"accepted": true, "event_id": "uuid"}` 또는
  `{"accepted": false, "code": "ACTION_NOT_ALLOWED", "reason_summary": "..."}`
- `proposal_id`는 중복 제출 방지(idempotency).
- Backend는 capability의 phase·version·reservation·deadline과 역할·생존·대상·
  중복을 **token 파싱 결과와 무관하게 다시 조회·검증**한다. 행동 commit
  후 capability를 폐기하고 다음 version에서 재발급한다.
- 투표 제안은 해소 전 SYSTEM에만 저장하고 중간 표수·투표자 목록을
  PUBLIC Resource에 포함하지 않는다. 마피아 제안도 다른 마피아에게 전달하지
  않는다.

### 5.4 `POST /audit`

MCP Server가 자신의 Resource·Tool 호출·거부 결과를 Backend 감사 sink로
멱등 전달한다. 거부·만료 capability와 같이 유효한 agent capability가
없는 사건도 기록해야 하므로 `/audit`은 Engine HMAC·bootstrap instance 인증을
사용하고 agent capability를 요구하지 않는다.

```json
{
  "instance_id": "uuid",
  "audit_schema_version": "audit-v1",
  "records": [
    {
      "audit_id": "uuid",
      "request_id": "uuid",
      "trace_id": "uuid",
      "event_id": "uuid-or-null",
      "game_id": "uuid-or-null",
      "actor_player_id_hash": "sha256:<64-lower-hex>-or-null",
      "session_id_hash": "sha256:<64-lower-hex>-or-null",
      "operation": "RESOURCE_READ",
      "resource_or_tool": "mafia://games/.../public-state",
      "allowed": true,
      "reason_code": null,
      "occurred_at": "2026-09-01T05:10:00Z"
    }
  ]
}
```

한 batch는 1~100건이다. `operation`은 `BOOTSTRAP | TRANSPORT_AUTH |
RESOURCE_READ | TOOL_CALL | AUDIT_RETRY`, `reason_code`는 2장의 공통 오류 코드나
승인된 transport/audit 거부 코드만 허용하며 자유 서술을 받지 않는다.
`resource_or_tool`은 해당 operation에서만 허용하고 나머지는 null,
`event_id`는 Backend가 수락·commit한 Tool에만 허용한다. 모든 object는
`additionalProperties=false`다. Backend는 `(instance_id, audit_id)`로 멱등 처리하고
다음 응답을 반환한다.

```json
{
  "accepted_ids": ["uuid"],
  "duplicate_ids": ["uuid"],
  "rejected": [{"audit_id": "uuid", "code": "INVALID_AUDIT_RECORD"}]
}
```

재전송된 동일 payload는 `duplicate_ids`로 성공 취급하고, 같은 key의 다른 payload는
409로 거부해 감사 변조를 숨기지 않는다. payload는 위 허용 schema만 받으며 raw
actor/session ID, 임의 metadata, capability/transport token, prompt/response,
역할·private profile, 행동 인자 전문을 거부한다. sink 장애 시 MCP는 로컬 bounded outbox에
보관하고 backoff 재시도하며, 이미 Backend가 commit한 게임 행동을 취소하거나
재제출하지 않는다. Backend 내부 감사 저장 실패는 3.1의 `audit_outbox`
규칙을 따른다.

MCP 메모리 outbox의 MVP 한계는 record당 4 KiB, 1,000건 또는 총 4 MiB 중
먼저 도달한 값, 최대 보유 15분, exponential backoff 0.5초 시작·30초 cap
(jitter 포함), shutdown flush 최대 3초로 고정한다. 가득 찬 상태에서는 Engine
호출 **전** 새 Resource·Tool을 `GAME_PERSISTENCE_UNAVAILABLE`로 fail-closed한다.
Engine이 이미 action을 commit한 뒤 sink가 실패했다면 응답을 실패로 바꾸거나
action을 재제출·rollback하지 않고 bounded retry와 민감정보 없는 운영 경고만
수행한다. 크기·개수·시간·backoff·shutdown 경계는 fake clock으로 검증한다.

---

## 6. MCP Server·Data Infrastructure 섹터 상세 계획 (`mcp_server/mafia_game`)

### 6.0 Data Infrastructure 운영 책임

MCP 섹터는 MCP 서버 코드와 별도로 PostgreSQL·Redis 실행 환경을 담당한다.

- PostgreSQL 인스턴스, `Team4_Proj` DB, schema 소유·DDL용 migrator role과
  최소 DML용 runtime role을 서로 다른 자격증명으로 준비하고 서비스를
  기동·중지한다.
- CP-M1A에서 migration 없이 기반 DB·role·Redis health를 먼저 확정한다.
  Backend WU-B3가 fake 검증한 `backend/migrations/*.sql`을 전달한 뒤
  CP-M1B에서 MCP 담당자가 `DATABASE_MIGRATION_URL`로 적용·재실행하고,
  CP-B2에서 Backend가
  `DATABASE_URL`로 스모크한다. 적용 파일명·결과만 비밀값 없이 기록한다.
- Redis를 기동·중지하고 연결과 `PING`을 확인한다. key·TTL·lock 의미는
  Backend가 정의한 3.3 계약을 그대로 사용한다.
- `DATABASE_MIGRATION_URL`, `DATABASE_URL`, DB 비밀번호, `REDIS_URL`은
  비밀 채널과 로컬 `.env`에서만
  전달하며 문서·로그·commit에 복사하지 않는다.
- 운영 책임을 이유로 MCP runtime에 DB·Redis client를 추가하거나 Backend
  migration·repository·Redis client 파일을 수정하지 않는다.

### 6.1 신규 파일 (승인된 구조 변경 범위)

```text
mcp_server/mafia_game/__main__.py              # 서버 기동 진입점 (포트 8100)
mcp_server/mafia_game/server.py                # MCP 서버 생성·의존성 조립
mcp_server/mafia_game/api/resources/game_resources.py
mcp_server/mafia_game/api/tools/game_tools.py
mcp_server/mafia_game/core/config.py           # env 로딩(secret 검증)
mcp_server/mafia_game/core/session.py          # 세션↔subject 고정, capability 회전
mcp_server/mafia_game/core/transport_auth.py   # Bearer token·TLS fail-closed
mcp_server/mafia_game/core/audit.py            # bounded outbox·감사 sink 재시도
mcp_server/mafia_game/services/context_service.py   # Resource 유스케이스
mcp_server/mafia_game/services/action_service.py    # Tool 제안 유스케이스
mcp_server/mafia_game/ports/engine_port.py     # Engine API Protocol
mcp_server/mafia_game/integrations/engine/__init__.py
mcp_server/mafia_game/integrations/engine/client.py # 5장 API HMAC 클라이언트
mcp_server/mafia_game/integrations/engine/fake.py   # 개발·테스트용 fake 엔진
mcp_server/mafia_game/schemas/contracts.py     # 입출력 계약 검증
mcp_server/mafia_game/tests/__init__.py
mcp_server/mafia_game/tests/ (test_contracts.py, test_resources.py, test_tools.py,
  test_engine_client.py, test_session_isolation.py, test_bootstrap.py,
  test_transport_auth.py, test_capability_rotation.py, test_audit.py)
```

패키지 이름은 예약명 `mcp_1`에서 `mafia_game`으로 변경 완료(2026-09-01,
사용자 승인). README도 게임 컨텍스트 MCP 책임으로 갱신되어 있다.

기존 계층(`api/ services/ ports/ integrations/ core/ schemas/`)을 그대로
사용하며 새 최상위 디렉터리를 만들지 않는다. `mcp_2`는 건드리지 않는다.

### 6.2 Resource / Tool 구현 명세 (최종 플랜 8장 준수)

Resources — 모두 5장 `/context`를 호출해 반환하고, MCP 서버는
게임 상태 원본을 갖지 않는다(세션 binding·회전 capability·bounded audit
outbox만 운영 상태로 유지):

```text
mafia://rules/mystery-v1
mafia://scenarios/scenario-v1/{scenario_id}
mafia://games/{game_id}/public-state
mafia://games/{game_id}/public-timeline
mafia://games/{game_id}/agents/me
mafia://games/{game_id}/agents/me/private-state
mafia://games/{game_id}/agents/me/allowed-actions
mafia://personas/{persona_id}
```

Resource 필드 경계는 다음을 정본으로 한다.

- `rules/mystery-v1`: `ruleset_version`, 6~9 역할표, Phase·승패·토론·
  20/30초 deadline·최종 판정 규칙과 2.0.2의 고정 AI GM 문구만 반환한다.
- `games/.../public-state`: `game_id/status/phase/round/state_version`, 공개
  scenario 7필드, `initial_mafia_count`, 참가자의
  `player_id/seat/display_name/kind/alive/eliminated_by/revealed_role`, discussion
  cursor와 `server_time/deadline_at`만 반환한다. `revealed_role`은 낮 투표 탈락만
  채우고 진행 중 ballot·제출 여부는 넣지 않는다.
- `games/.../public-timeline`: `game_id/from_sequence/next_sequence`와 3.2의
  PUBLIC event 배열만 반환한다. `VOTE_RESULT`는 후보별 aggregate뿐이고
  `PLAYER_KILLED`에는 role이 없다.
- `agents/me`: 현재 session actor의 `player_id`, `display_name`, `alive`,
  `persona_id`만 반환하는 identity Resource다. 역할이나 개인 사건 정보는 넣지 않는다.
- `agents/me/private-state`: 현재 actor의 `role`, `alibi`, `observation`, 본인의
  PRIVATE event와 행동 접수만 반환한다. `observation`은 2.3과 같은 구조화
  `text/target_seat/anonymous`이고 다른 actor의 값과 `faction`은 금지한다.
- `agents/me/allowed-actions`: `game_id/phase/round/state_version/reservation_id`,
  `server_time/deadline_at`과 각 허용 Tool의 `tool/required/valid_targets`만 반환한다.
  토론 Tool은 현재 좌석 actor에게만, deadline 경과 뒤에는 시간 제한 Tool을
  반환하지 않는다.
- `scenarios/scenario-v1/{scenario_id}`: 현재 session game에 저장된
  `scenario_id`와 URI가 일치할 때만
  `scenario_id/scenario_version/title/background/victim/locations/objective`를
  반환한다. 다른 catalog ID 열람과 임의 version은 거부한다.
- `personas/{persona_id}`: 현재 PLAYER subject에 배정된 ID와 일치할 때만
  `persona_id/name/version/display_name/speech_style/backstory`를 반환한다.
  model·추론 설정·token/timeout·Tool 권한은 persona 응답에 넣지 않는다.
- GM session은 `rules`, `public-state`, `public-timeline`, 현재 공개 scenario만
  허용하며 `agents/me*`와 persona/private Resource를 허용하지 않는다.

모든 Resource object와 중첩 object는 `additionalProperties=false`로 검증하고
Engine의 알 수 없는 필드를 그대로 전달하지 않는다. `server_time`과
`deadline_at`의 MCP 로컬 비교는 5.1의 monotonic anchor를 사용한다.

Tools — 모두 5장 `/actions`로 전달하는 **행동 제안**이며 상태를 직접 바꾸지
않는다:

| Tool | 입력 | MCP 서버 1차 검증 |
|---|---|---|
| `game.speak` | `{"message": str}` | 길이 1~200, 제어문자 제거 |
| `game.vote` | `{"target_player_id": str}` | UUID 형식 |
| `game.kill` | `{"target_player_id": str}` | UUID 형식 |
| `game.investigate` | `{"target_player_id": str}` | UUID 형식 |
| `game.protect` | `{"target_player_id": str}` | UUID 형식 |
| `game.pass` | `{}` | 현재 토론 좌석의 PASS에서만 노출 |

핵심 규칙:

- `agent_id`·`actor_id`를 Tool 입력으로 받지 않는다. 세션이 actor를 결정한다.
- 다른 `agent_id` 조회 API를 제공하지 않는다(`me`만 존재).
- 세션은 game/subject identity만 고정하고 capability는 각 phase/state version에서
  갱신한다. 이전 capability로 Resource를 읽거나 Tool을 호출하면 거부한다.
- 현재 phase·역할에 맞는 Tool만 노출하되(allowed-actions 기반), 노출 제한을
  권한 검사로 삼지 않는다 — 최종 판정은 Backend(이중 검증).
- Engine 응답을 그대로 통과시키지 말고 schema 검증 후 허용 필드만 반환한다.
- 모든 Resource 조회·Tool 호출·bootstrap·transport 거부를 5.4 감사 sink로
  멱등 전달한다. sink 실패는 게임 행동 commit을 롤백하지 않고 bounded
  outbox에서 재시도한다. agent가 감사 로그를 조회할 Resource/Tool은 없다.
- 생산 시 `MCP_REQUIRE_TLS=true`를 fail-closed로 강제하고, 유효한 단기
  transport token이 없으면 MCP 세션·Resource·Tool을 모두 거부한다.

### 6.3 작업 순서

아래 WU-M1A, WU-M1B, WU-M2~M8을 **한 세션에 하나씩** 수행한다. CP는 같은 번호의
WU 완료 경계이며 축약·병합하지 않는다.

1. **WU-M1A. 기반 Data Infrastructure (CP-M1A)** — migration 없이 PostgreSQL DB,
   migrator/runtime 분리 role, Redis를 구축·기동하고 자격증명 경계·health를 검증한다.
2. **WU-M1B. migration 인수 (CP-M1B)** — Backend WU-B3의 검증된 migration
   산출물을 전달받은 후에만 `DATABASE_MIGRATION_URL`로 적용·재실행하고
   runtime `DATABASE_URL`의 DML 성공·DDL 거부를 확인한다. CP-M1A의
   진입 조건으로 Backend migration을 요구하지 않는다.
3. **WU-M2. schema·fake Engine (CP-M2)** — MCP 서버 골격, 5장 입출력
   schema, 공통 오류 code 13종, fake Engine, 버전 불일치 fake를 구현한다.
   config test는 MCP timeout 3초, clock-sync 최대 RTT 2초, audit queue 최대
   1,000건의 기본값과 0·음수·상한 초과·placeholder secret 거부를 고정한다.
4. **WU-M3. bootstrap·capability (CP-M3)** — bootstrap 버전·시계 검증,
   transport token, 세션 game/subject binding, phase/version별 capability 교체·폐기,
   인증된 `server_time`↔monotonic clock anchor를 구현한다. 30초 wall-clock skew,
   wall clock 전·후 이동, anchor 만료·monotonic deadline 거부를 fake clock으로 검증한다.
5. **WU-M4. Resources (CP-M4)** — Resource 8종 URI·schema, `/context` 전달,
   위 `me`/`private-state` 분리, 현재 game과 다른 scenario ID, stale capability·
   타 game/subject·blind-mafia 비누설 거부를 구현한다.
6. **WU-M5. Tools (CP-M5)** — Tool 6종 입력 검증, `/actions` 전달,
   monotonic anchor로 계산한 deadline·actor 위조·중복 거부를 구현한다.
7. **WU-M6. audit/outbox (CP-M6)** — `/audit` 멱등 batch, bounded outbox,
   `audit-v1` 승인 필드와 `(instance_id,audit_id)` 멱등성, sink 장애 backoff
   재시도와 게임 행동 commit 보존을 구현한다. 5.4의 record 4 KiB·queue
   1,000건/4 MiB·15분 보유·0.5~30초 backoff·3초 shutdown flush 한계 및
   가득 찬 queue의 호출 전 fail-closed를 fake clock으로 검증한다.
8. **WU-M7. 실 Engine HMAC 연동 (CP-M7)** — Backend CP-B4 후 bootstrap,
   Engine 요청·응답 HMAC, transport token, 인증된 context `server_time`, TLS·
   timeout·오류 변환을 실제 내부 API와 연동한다.
9. **WU-M8. 격리 강화 (CP-M8)** — Backend CP-B5와 함께 무인증 transport,
   다른 game/subject, 이전 capability, 사망 AI session 재사용을 거부하고
   카나리·TLS·감사 종단 통합을 검증한다.

*완료 기준: fake Engine 기반 전체 테스트 통과(외부 호출 0), 세션·
transport·capability 위조·타 agent 조회 거부, 감사 sink 장애 후 복구,
CP-M1A→WU-B3→CP-M1B→CP-B2, CP-B4→CP-M7, CP-B5+CP-M8→CP-ALL
순서의 통합 검증 기록.*

---

## 7. Front 섹터 상세 계획

### 7.1 신규 파일 (승인된 구조 변경 범위)

```text
frontend_user/app_pages/home_page.py        # 홈: 새 게임/이어하기/불러오기
frontend_user/app_pages/game_create_page.py # 인원 6~9 선택, 역할표·규칙 안내
frontend_user/app_pages/game_play_page.py   # 진행: 타임라인·행동·관전·저장
frontend_user/app_pages/game_load_page.py   # 저장 목록
frontend_user/app_pages/game_result_page.py # 결과·피드백 진입
frontend_user/core/game_api.py              # 2장 게임 API 클라이언트
frontend_user/core/game_view.py             # GameStateView 파싱·표시 모델
frontend_user/components/game_ui.py         # 타임라인·좌석·행동 버튼 렌더링
frontend_user/tests/ (test_game_api.py, test_game_view.py,
  test_game_pages_smoke.py)

frontend_admin/app_pages/kpi_page.py
frontend_admin/app_pages/logs_page.py
frontend_admin/app_pages/feedback_page.py
frontend_admin/core/admin_api.py
frontend_admin/tests/ (신설: test_admin_api.py, test_admin_pages_smoke.py)
```

`frontend_user/app.py`는 로그인 후 `home_page`로 라우팅하도록 최소 수정한다
(기존 login_page 동작 보존).

### 7.2 구현 규칙

- 화면 상태의 근거는 항상 Backend 응답(GameStateView)이다. URL·세션만 믿지
  않고 새로 고침 시 `game_id`로 재조회한다.
- 모든 사용자·AI 발언, 표시 이름은 렌더링 전 HTML escape한다(기존
  `components/ui.py` 패턴 재사용).
- 생성 화면은 6~9명 역할표와 `mystery-v1` 규칙을 표시한다. 게임 시작 후
  공개 시나리오와 본인의 알리바이·관찰만 렌더링하고 타인 정보를
  추론·보완하지 않는다. 구조화 관찰은 `text`를 표시하고 `anonymous=true`면
  target 이름을 만들지 않는다. `DETECTIVE`의 UI 명은 "탐정"이다.
- 토론은 Backend가 지정한 현재 좌석에게만 `SPEAK | PASS`를 노출한다.
  Front가 phase를 임의로 전진시키지 않는다. 밤·투표 deadline은 `server_time`으로
  보정한 카운트다운·경고만 표시하고 최종 판정은 Backend에서만 한다.
- SSE를 우선 사용하고 실패 시 `?since_sequence` 폴링으로 전환한다.
  전환 후에도 deadline·토론 커서·본인 제출 여부를 재동기화한다.
- 밤 사망자의 역할과 투표 중 개별 표를 표시하지 않고 집계만 표시한다.
  종료 화면에서만 전체 역할·행동·개별 투표·정제된 판단 요약을 표시한다.
- 인간 플레이어가 사망한 View를 받으면 메모리·session state에 남은 역할·
  알리바이·관찰·PRIVATE event·행동 접수를 즉시 폐기하고 PUBLIC 관전 정보만
  렌더링한다. 이전 응답 cache로 비공개 panel을 계속 보여주지 않는다.
- 오류 코드별 고정 안내: version/deadline/already-submitted 409→상태 재조회,
  503(AGENT)→제어 요청 재시도와 상태 재조회(진행 phase를 pause로 추정하지 않음),
  503(PERSISTENCE)→저장 실패 안내(입력 보존).
- API client는 fake transport 주입이 가능해야 하며 테스트는 mock으로만 실행.
- 관리자 앱은 로그인 후 `acting_user_id`로 관리자 API를 호출하고 403이면
  기능 화면을 렌더링하지 않는다(fail-closed).

### 7.3 작업 순서

아래 F1~F5는 [Front 섹터 지침서](SECTOR_PLAN_FRONT.md)의 WU-F1~F8로
세분화되어 있다. coding AI agent 세션은 WU 단위로만 지시한다.

1. **F1. game_api + fake transport** — 2장의 scenario·구조화 observation·
   private profile·discussion·resume·deadline·result 명세 그대로 클라이언트·모델.
2. **F2. 홈·생성·불러오기** — 6~9명 역할표, 시나리오 요약, fake 데이터로 화면 완성.
3. **F3. 진행·결과 화면** — 토론 커서, SPEAK/PASS, 20/30초 표시 타이머,
   투표 집계, 최종 급사, 관전·빠른 진행, 저장·재개, 종료 이력.
4. **F4. Backend 연동** — 실제 API 전환, 오류 안내, SSE/폴링,
   deadline·새로 고침·재연결 동기화.
5. **F5. 관리자 화면** — KPI·로그·피드백 3화면과 fail-closed 권한 처리.

---

## 8. 마일스톤과 통합 순서

각 섹터는 별도 시스템에서 개발한 뒤 통합 브랜치로 merge한다. 섹터별 작업
단위(WU)·coding AI agent 사용 규칙·체크포인트(CP) 상세는 섹터 지침서를
따른다.

- Front: [SECTOR_PLAN_FRONT.md](SECTOR_PLAN_FRONT.md) (WU-F1~F8, CP-F0~F4)
- Backend: [SECTOR_PLAN_BACKEND.md](SECTOR_PLAN_BACKEND.md) (WU-B1~B9, CP-B0~B5)
- MCP: [SECTOR_PLAN_MCP.md](SECTOR_PLAN_MCP.md) (WU/CP-M1A, M1B, M2~M8)

다른 섹터 문서가 참조할 **단일 CP 매핑**은 다음과 같다.

| 섹터 CP | 포함 WU/활동 | 완료 경계 |
|---|---|---|
| CP-F0~F4 | Front WU-F1~F8 | Front 지침서 매핑 유지 |
| CP-B0 | 코드 없음 | `mystery-v1`·`scenario-v1`·2·3·5·6장 계약 합의 |
| CP-B1 | WU-B1~B2 | 규칙·시나리오 순수 엔진, 90개 이상 template 제품 리뷰 승인, 6~9명 fake 완주 |
| CP-B2 | WU-B3~B4 + CP-M1B 후 runtime smoke | DB·Redis·snapshot·outbox 영속화 |
| CP-B3 | WU-B5~B6 | 사용자 API·SSE·서버 deadline |
| CP-B4 | WU-B7 | bootstrap·내부 API·회전 capability·transport auth |
| CP-B5 | WU-B8~B9 | Agent Manager·공개 GM·관리자 API |
| CP-M1A | WU-M1A | migration 없는 DB·role·Redis health |
| CP-M1B | WU-M1B, Backend WU-B3 후 | migration 적용·재실행, runtime DML·DDL 경계 |
| CP-M2 | WU-M2 | schema·fake Engine 골격 |
| CP-M3 | WU-M3 | bootstrap·transport auth·회전 capability |
| CP-M4 | WU-M4 | Resource 8종 fake 완성 |
| CP-M5 | WU-M5 | Tool 6종 fake 완성 |
| CP-M6 | WU-M6 | audit sink·bounded outbox |
| CP-M7 | WU-M7, Backend CP-B4 후 | 실 Engine HMAC·TLS 연동 |
| CP-M8 | WU-M8, Backend CP-B5와 통합 | 격리·사망 session·감사 종단, CP-ALL 진입 |

| 마일스톤 | Front | Backend | MCP | 통합 검증 |
|---|---|---|---|---|
| **M-A 계약 고정** | CP-F0 | CP-B0 | 공통 계약 승인(코드 없음) | 이 문서 리뷰 3인 합의 |
| **M-B 단독 완성** | CP-F1~F2 (fake) | CP-B1, WU-B3~B4 fake | CP-M1A, CP-M2~M5 | 기반 health + 규칙·시나리오·fake 섹터 회귀 |
| **M-C 영속화·사용자 통합** | CP-F3 | CP-B2~B3 | CP-M1B, CP-M6 | migration 적용 후 인간 1 + fake AI로 deadline·audit 포함 한 판 완주 |
| **M-D 에이전트 통합** | CP-F3 안정화 | CP-B4~B5 | CP-M7~M8 | 회전 capability·격리·감사, 실제 LLM 수동 1회(비용 승인 후) |
| **M-E 관리자·알파** | CP-F4 | CP-B5 | CP-M8 | 6~9명 각 최소 100회(가능하면 1,000회) offline 시뮬레이션, 밸런스 gate, fake 전체 회귀 |

### 8.1 중간 merge 절차 (전 섹터 공통)

1. 섹터 브랜치(`feat/<섹터>-<기능>`)에서 CP 단위로만 merge를 요청한다.
   CP를 건너뛴 대량 merge는 금지한다.
2. merge 전: `develop`을 자기 브랜치에 반영해 충돌을 자기 쪽에서 해소하고
   전체 회귀(`uv run pytest` + compileall + ruff)를 통과시킨다.
3. merge 후: `develop`에서 통합 스모크를 실행하고 결과를 팀에 공유한다.
   - CP-M1A: migration 없는 PostgreSQL·Redis·role health 확인
   - WU-B3 전달 후 CP-M1B → CP-B2: MCP migration 재실행·role 경계
     확인 → Backend `DATABASE_URL` persistence smoke 1회
   - CP-B3 + CP-M1B 후 CP-F3: Backend 기동 → `/health` 200 → 게임 생성·
     deadline 포함 fake AI 완주 1회
   - CP-B4 후 CP-M7: Backend + MCP 기동 → bootstrap → Resource 1종 조회 성공
   - CP-B5 + CP-M8: 사망 AI session 폐기·격리·감사 종단 후 CP-ALL
4. 통합 스모크 실패 시 원인 섹터가 수정 브랜치로 후속 조치한다. 다른
   섹터 코드를 임의 수정하지 않는다.
5. `main` 병합은 M-C 이후 사용자 승인 시에만.

### 8.2 섹터 간 의존 순서 (병렬 계획의 기준)

```text
CP-M1A(기반 인프라) ──▶ WU-B3(migration 산출물)
WU-B3 ──▶ CP-M1B(migration 적용) ──▶ CP-B2(runtime 검증)
CP-B3(사용자 API·deadline) + CP-M1B ──▶ CP-F3(Front 실연동)
CP-B4(내부 Engine API) ──▶ CP-M7(MCP 실 Engine 연동)
CP-B5 + CP-M8 ──▶ CP-ALL ──▶ M-E 통합 알파
그 외 모든 CP는 fake 기반으로 상호 독립 진행 가능
```

### 8.3 알파 밸런스 gate

동일 model·추론 설정과 정적 scenario를 사용해 6·7·8·9명별 최소 100회,
가능하면 1,000회씩 seed 고정 offline 시뮬레이션한다. 시민·마피아 승률은 각각
45~55%를 목표로 하고 40~60%까지를 허용한다. 어느 한 진영이라도 60%를 넘으면
알파 완료가 아니라 조정 대상으로 판정한다.

승률과 함께 평균 완료 밤 수·게임 시간, 의사 보호 성공 횟수, 탐정 생존 기간·
조사 영향, 마피아끼리 서로 공격·투표한 횟수, 인간 사용자의 첫날 밤 사망률,
deadline timeout·결정적 자동 선택 횟수를 인원·scenario별로 기록한다. 조정 시
여러 규칙을 동시에 바꾸지 않고 AI 행동 수준 또는 규칙 하나만 변경한 뒤 같은 seed
set을 재실행한다. `mystery-v1` 규칙 변경이면 9장의 계약 변경 절차와 새 version이
선행되어야 한다.

## 9. 계약 변경 절차 (추후 수정 가능 원칙)

1. 변경 제안자는 이 문서의 해당 절(2·3·5·6장)을 수정하는 diff를 먼저 공유한다.
2. 영향 섹터 담당자 동의 후 문서를 갱신하고, 그 다음 코드에 반영한다.
3. DB 변경은 기존 migration 수정이 아니라 **새 번호의 순방향 SQL 추가**로만.
4. 변경 이력은 이 장 아래 표에 기록한다.

| 날짜 | 변경 | 사유 | 합의 |
|---|---|---|---|
| 2026-09-01 | 초판 작성 | — | — |
| 2026-09-01 | `mcp_server/mcp_1` → `mcp_server/mafia_game` 개명 | 예약명 대신 담당 게임 도메인이 드러나는 이름 사용 | 사용자 승인 |
| 2026-09-02 | 섹터별 작업 지침서 3종 분리, 8장을 CP 기반 중간 merge·통합 스모크 절차로 개정 | 별도 시스템 개발 후 merge 전제의 세부 지침과 AI agent 세션 범위(WU 1개 이하) 강제 | 사용자 요청 |
| 2026-09-02 | PostgreSQL·Redis 구축·기동·migration 실행·health 책임을 Backend에서 MCP 섹터로 이동 | 인프라 실행 책임을 MCP 담당자에게 일원화하고 Backend는 application code·data contract에 집중 | 사용자 요청 |
| 2026-09-02 | `mystery-v1`·`scenario-v1` 계약으로 개정 | 6~9명 역할표, DETECTIVE, blind mafia, 첫날 무투표, 하이브리드 토론, 20/30초 deadline, 5번째 밤 급사, 시나리오 5종을 최종 규칙에 반영 | 사용자 승인 |
| 2026-09-02 | API·DB·MCP 보안·복구 계약 보강 | 서버 deadline, 관전 PUBLIC-only, snapshot 손상 배제, migrator/runtime role 분리, 회전 capability, transport auth/TLS, audit outbox, 외부 호출 중 lock 해제를 명시 | 사용자 승인 |
| 2026-09-02 | WU·CP 단일 매핑 개정 | Backend WU-B1~B9, MCP WU/CP-M1A·M1B·M2~M8을 1세션 1WU로 분리하고 CP-M1A→WU-B3→CP-M1B→CP-B2 순서로 인프라 순환 의존 제거 | 사용자 승인 |
| 2026-09-02 | scenario catalog·생성 원자성 보강 | 5개 불변 ID, 90개 이상 template 제품 gate, 구조화 관찰, owner advisory lock·creation_order·rollback 불변을 고정 | 사용자 승인 및 타당성 점검 |
| 2026-09-02 | 재개·scheduler·멱등 계약 보강 | 명시적 resume API, DB wakeup/worker lease, 영구 command receipt와 재시도 시 현재 audience 재투영을 추가 | 사용자 승인 및 타당성 점검 |
| 2026-09-02 | Engine/MCP 종단 계약 보강 | PLAYER/GM subject capability, 응답 HMAC·monotonic clock, audit-v1 필드·정량 outbox, snapshot fallback 재투영, 절대 deadline 예산을 고정 | 사용자 승인 및 타당성 점검 |

## 10. 환경 변수 (전 섹터 공통, `.env.example` 참조)

| 변수 | 사용 섹터 | 용도 |
|---|---|---|
| `DATABASE_URL` / `DATABASE_NAME` | MCP(runtime role 준비·전달), Backend(소비) | 최소 DML 권한 PostgreSQL runtime 연결 |
| `DATABASE_MIGRATION_URL` | MCP 인프라 담당자만 | DDL·schema 소유 migration 연결; Backend runtime 주입 금지 |
| `INTERNAL_API_SECRET` | Front·Backend | Front→Backend HMAC (기존) |
| `ENGINE_INTERNAL_API_SECRET` | Backend·MCP | MCP→Backend 내부 HMAC (**Front용과 다른 값**) |
| `MCP_SERVER_AUTH_SECRET` | Backend·MCP | Backend→MCP 단기 Bearer token 서명; Engine HMAC와 다른 값 |
| `MCP_REQUIRE_TLS` / `MCP_TLS_CA_FILE` | Backend·MCP | 개발 기본 false는 loopback만; 생산은 true·실 CA 경로로 fail-closed |
| `REDIS_URL` | MCP(구축·실행·전달), Backend(소비) | lock·cache·stream |
| `LLM_PROVIDER` / `OPENAI_*` / `GEMINI_*` | Backend | LLM 이중 공급자 |
| `LLM_TIMEOUT_SECONDS` / `GAME_MAX_TOKENS_PER_RUN` | Backend | run 제한; LLM timeout 기본 15초는 단일 호출 상한 |
| `MCP_TIMEOUT_SECONDS` | Backend·MCP | 기본 3초; MCP/Engine 단일 호출 상한이며 절대 phase deadline보다 우선할 수 없음 |
| `AGENT_EXTERNAL_CALL_BUDGET_SECONDS` | Backend | 기본 16초; Agent Manager의 MCP+LLM 총 외부 작업 상한 |
| `AGENT_COMMIT_NETWORK_RESERVE_SECONDS` | Backend | deadline 전 CAS·commit·네트워크 여유, 기본·권장 3초 |
| `MCP_CLOCK_SYNC_MAX_RTT_SECONDS` | MCP | bootstrap monotonic clock anchor의 최대 허용 왕복 시간, 기본 2초 |
| `MCP_AUDIT_OUTBOX_MAX_RECORDS` | MCP | 기본·최대 1,000; 낮출 수 있으나 초과 설정은 fail-closed. record 4 KiB·총 4 MiB·15분 등 나머지 한계는 5.4 적용 |
| `MAFIA_MCP_URL` | Backend | `/mcp`를 포함한 full endpoint(개발 기본 `http://127.0.0.1:8100/mcp`); client suffix 추가 금지 |
| `ENGINE_API_URL` | MCP | Backend 내부 API 주소 (8000) |

각 프로세스는 다음 **env allowlist만 주입**받는다. `.env.example`은 전체
프로세스의 가능한 변수를 모은 카탈로그일 뿐이며, 생산에서 한 프로세스가
파일 전체를 통째로 로드하거나 무관한 secret을 상속받아서는 안 된다.

- **Backend runtime:** `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`,
  `LLM_PROVIDER`, 필요한 `LLM_*`·`OPENAI_*`·`GEMINI_*`, `MAFIA_MCP_URL`,
  `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`(내부 Engine 요청 검증),
  `INTERNAL_API_SECRET`, 이 문서에 명시한 타임아웃·token 상한·TLS CA 같은
  비밀이 아닌 설정만 허용한다. `DATABASE_MIGRATION_URL`은 금지한다.
- **Migration 실행 프로세스:** `DATABASE_MIGRATION_URL`과 실행기가 정말 필요로
  하는 비밀이 아닌 `DATABASE_NAME`만 허용한다. `DATABASE_URL`, Redis, LLM,
  Front/Engine/MCP secret은 금지한다.
- **MCP runtime:** `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`,
  `ENGINE_API_URL`, host/port·TLS CA·`MCP_REQUIRE_TLS`·timeout·bounded outbox 상한 같은
  비밀이 아닌 MCP 설정만 허용한다. DB·Redis·LLM 연결값과
  `INTERNAL_API_SECRET`은 금지한다.
- **Front runtime:** 기존 OIDC·session 최소 설정, Backend 주소,
  `INTERNAL_API_SECRET`만 허용하고 DB·Redis·LLM·Engine/MCP secret을 주입하지 않는다.

모든 secret은 32자 이상 무작위 값, `.env`에만 보관, 로그·응답 출력 금지.
