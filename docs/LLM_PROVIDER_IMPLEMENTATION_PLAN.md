# LLM Provider 명칭 변경 및 실제 Provider 구현 계획

## 1. 목적과 현재 기준

이 문서는 `backend/app/llm/`을 `backend/app/llm_provider/`로 변경하고,
현재 예약되어 있는 `dummy`, `local`, `openai`, `gemini` Provider를 실제 게임
Agent가 사용할 수 있는 공통 계약으로 구현하기 위한 작업 기준이다.

현재 저장소에는 다음 상태가 반영되어 있다.

| 항목 | 현재 상태 | 이 계획에서의 처리 |
|---|---|---|
| `backend/app/llm_provider/` | 공통 계약과 네 Provider 구현 추가 | 실제 게임 proposal action 확장과 운영 관측성 보강 |
| `LLM_PROVIDER` | `dummy`, `local`, `openai`, `gemini` 허용 | 선택된 Provider에 필요한 설정만 검증 |
| Local API | OpenAI 호환 `/chat/completions` 호출 | 비동기 공통 계약과 엄격한 응답 검증으로 변경 |
| OpenAI/Gemini SDK | `pyproject.toml`에 의존성 선언 | 실제 SDK adapter와 mock 기반 계약 테스트 추가 |
| 게임 proposal | `PING`, `state_version` 중심 scaffold 계약 | 기본 계약은 보존하고 실제 게임용 proposal 필드를 확장 |
| 최종 상태 변경 | Backend/MCP가 담당 | LLM Provider는 proposal 생성만 담당 |

현재 작업 브랜치와 커밋을 기준으로 진행하며, 구현 중 기존 사용자 변경을
되돌리거나 덮어쓰지 않는다. 커밋과 push는 구현·검증 후 별도 승인을 받아 진행한다.

## 2. 목표 구조

```text
backend/app/llm_provider/
├── __init__.py
├── base.py              # Provider Protocol, 요청·응답 공통 모델
├── schemas.py           # 구조화 응답과 게임 proposal 검증 모델
├── errors.py            # timeout·인증·rate limit·응답 형식 오류
├── factory.py           # LLM_PROVIDER에 따른 구현 선택
├── dummy.py             # 외부 호출 없는 결정적 Provider
├── local.py             # OpenAI 호환 로컬 endpoint
├── openai_provider.py   # OpenAI 공식 SDK adapter
└── gemini_provider.py   # Google GenAI 공식 SDK adapter
```

추가 디렉터리는 만들지 않는다. 공통 계약이 안정된 뒤 테스트는 기존
`backend/tests/` 아래에 둔다.

## 3. 확정할 공통 계약

Provider별 SDK 타입을 Router나 Service에 노출하지 않기 위해 다음 계약을
먼저 확정한다.

```python
class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        ...
```

`LLMRequest`에는 다음 필드를 둔다.

- `messages`: system/user 메시지 목록
- `response_schema`: 허용된 JSON 응답 스키마
- `max_output_tokens`
- `timeout_seconds`
- `trace_id` 또는 `agent_run_id`

`LLMResponse`에는 다음 필드를 둔다.

- `provider`, `model`
- 검증이 끝난 구조화 `output`
- `input_tokens`, `output_tokens`
- `finish_reason`
- `request_id`가 있으면 정규화한 값
- `latency_ms`

게임 proposal은 별도 모델로 변환한다. 최소 필드는 `action`,
`target_player_id`, `source_state_version`이며 실제 게임 규칙이 확정되면
`message` 등 필요한 필드를 추가한다. Provider는 proposal을 반환할 뿐이고,
현재 phase·역할·생존 여부·소유권·version 검증과 상태 변경은 Backend가 담당한다.

## 4. 구현 단계

### 단계 A — 패키지 명칭 변경

1. 기존 `backend/app/llm/` 구현을 `backend/app/llm_provider/`로 이동한다.
2. 다음 코드 참조를 수정한다.
   - `backend/app/routers/scaffold_game_router.py`
   - `backend/app/agent/`에서 새 Provider를 호출하는 코드
   - 관련 테스트의 import
3. 다음 문서의 경로와 확장 지점을 수정한다.
   - `README.md`
   - `docs/ARCHITECTURE_REFACTOR_PLAN.md`
   - `docs/scaffold/AI_MAFIA_MIN_CONNECTION_PLAN.md`
   - `docs/scaffold/AI_MAFIA_SCAFFOLD_FILE_PLAN.md`
4. 검색 결과에 실행 코드의 `backend.app.llm` import가 남지 않아야 한다.
   과거 계획 문서의 일반적인 `llm` 표현은 구현 경로와 혼동되지 않는 범위에서만 유지한다.

### 단계 B — 공통 계약과 기존 Provider 분리

1. `base.py`에 Protocol과 공통 request/response 타입을 작성한다.
2. `schemas.py`에 JSON 파싱 후의 Pydantic 검증을 작성한다.
3. `errors.py`에 Provider 독립 예외를 정의한다.
4. 기존 Dummy 동작을 `dummy.py`로 옮긴다.
   - 외부 네트워크 호출 없음
   - 같은 입력에 같은 결과
   - scaffold 테스트에서 계속 기본 Provider로 사용
5. Local 구현을 `local.py`로 옮긴다.
   - `httpx.AsyncClient` 사용
   - `${LOCAL_LLM_BASE_URL}/chat/completions` 호출
   - `LOCAL_LLM_MODEL` 사용
   - 연결 timeout과 전체 요청 timeout을 제한
   - 응답의 `choices[0].message.content` 존재 여부 확인
   - code fence 제거에 의존하지 말고 JSON 파싱 실패를 명시적 오류로 처리

### 단계 C — 설정과 Factory

`backend/app/core/config.py`의 `Settings`에 다음 필드를 추가한다. API key는
`repr`에서 제외하고, 오류나 로그에 원문을 포함하지 않는다.

| 설정 | 사용 Provider | 규칙 |
|---|---|---|
| `LOCAL_LLM_BASE_URL` | `local` | 비어 있지 않은 URL |
| `LOCAL_LLM_MODEL` | `local` | 필수 |
| `OPENAI_API_KEY` | `openai` | 선택된 경우 필수 |
| `OPENAI_MODEL` | `openai` | 선택된 경우 필수 |
| `GEMINI_API_KEY` | `gemini` | 선택된 경우 필수 |
| `GEMINI_MODEL` | `gemini` | 선택된 경우 필수 |
| `LLM_TIMEOUT_SECONDS` | 전체 | 양의 정수, 상한 적용 |
| `LLM_MAX_OUTPUT_TOKENS` | 전체 | 양의 정수, 상한 적용 |
| `GAME_MAX_TOTAL_TOKENS` | Agent 정책 | 양의 정수 |
| `LLM_INPUT_COST_PER_MILLION_USD` | 원격 Provider | 0 이상인 수 |
| `LLM_OUTPUT_COST_PER_MILLION_USD` | 원격 Provider | 0 이상인 수 |

`factory.py`는 다음 매핑을 제공한다.

```text
dummy  -> DummyProvider
local  -> LocalProvider
openai -> OpenAIProvider
gemini -> GeminiProvider
```

선택되지 않은 원격 Provider의 키는 요구하지 않는다. 원격 Provider의 키가
없으면 애플리케이션 시작 또는 Factory 생성 시 비밀값 자체를 노출하지 않는
설정 오류를 반환한다.

### 단계 D — OpenAI와 Gemini 실제 adapter

`openai_provider.py`:

- `openai` 공식 비동기 클라이언트 사용
- 가능한 경우 JSON schema/structured output 사용
- SDK 응답을 `LLMResponse`로 변환
- 인증 실패, rate limit, timeout, 빈 응답을 공통 오류로 변환

`gemini_provider.py`:

- `google-genai` 공식 비동기 API 사용
- JSON MIME type과 response schema 사용
- safety block, 빈 candidate, 비정상 finish reason 처리
- token usage와 model 정보를 공통 응답으로 변환

두 adapter 모두 Provider 간 자동 전환을 하지 않는다. 일시적인 네트워크
오류만 제한적으로 재시도하며, 인증 실패·잘못된 요청·응답 검증 실패는
재시도하지 않는다. 재시도 횟수와 backoff는 고정 상한을 둔다.

### 단계 E — Agent와 MCP 연결

호출 흐름은 다음으로 고정한다.

```text
Agent Service
  → LLMProvider.generate()
  → 구조화 output 검증
  → Backend proposal 검증
  → MCP proposal 제출
  → 규칙 엔진이 최종 상태 변경
```

Router가 Provider별 SDK나 HTTP payload를 직접 만들지 않도록 한다. Provider
timeout이나 장애가 발생해도 게임 상태를 부분 변경하지 않으며, Agent 정책에
따라 안전한 기본 행동·재시도·`PAUSED` 중 하나를 선택한다. 이 fallback은
Provider factory가 아니라 Agent orchestration 계층에 둔다.

## 5. 보안·비용·관측성 기준

- API key와 Authorization header를 로그·예외·응답에 기록하지 않는다.
- 사용자 입력과 게임 context는 길이 제한, 허용 필드 projection, escape 정책을 거친다.
- LLM에는 해당 Agent에 허용된 공개/비공개 context만 전달한다.
- 모델 출력은 신뢰하지 않고 JSON schema, UUID, action allowlist, state version을 검증한다.
- prompt 원문과 raw model response는 기본 저장하지 않는다.
- `provider`, `model`, latency, token 수, 오류 코드만 관측 데이터로 남긴다.
- 비용 계산은 설정된 모델 단가와 token usage를 사용하며, 설정값이 없으면
  원격 호출을 허용하지 않는 정책을 유지한다.
- Provider 호출은 idempotency 또는 agent run 식별자와 함께 추적한다.

## 6. 테스트 계획

실제 OpenAI·Gemini API는 회귀 테스트에서 호출하지 않는다. SDK와 HTTP 응답은
mock/fake로 재현한다.

필수 테스트 파일 후보는 `backend/tests/test_llm_provider.py`,
`backend/tests/test_llm_provider_config.py`, `backend/tests/test_llm_provider_contract.py`다.

검증 항목:

1. Factory가 네 가지 Provider를 올바르게 선택한다.
2. Dummy가 외부 호출 없이 기존 `PING` scaffold 계약을 유지한다.
3. Local의 URL 조합, model, timeout, JSON body가 올바르다.
4. OpenAI/Gemini 정상 응답이 공통 `LLMResponse`로 변환된다.
5. 잘못된 JSON, 누락 필드, 허용되지 않은 action, 잘못된 UUID,
   불일치한 `source_state_version`이 거부된다.
6. timeout, 인증 오류, rate limit, 빈 응답, safety block이 공통 오류로 매핑된다.
7. 재시도는 일시적 오류에만 제한 횟수로 실행된다.
8. 선택된 원격 Provider의 key/model 누락이 거부되고 비밀값은 오류에 나타나지 않는다.
9. prompt·API key·raw response가 로그에 남지 않는다.
10. Provider 장애가 게임 상태 변경이나 MCP 제출으로 이어지지 않는다.

완료 직전에 다음 명령을 실행한다.

```bash
uv run pytest
uv run ruff check .
uv run python -m compileall -q backend frontend_user frontend_admin mcp_server
```

## 7. 문서·운영 설정 갱신

구현 완료 전에 다음을 함께 수정한다.

- `.env.example`: 예약 문구를 실제 Provider 설정 안내로 변경
- `README.md`: 새 디렉터리, Provider 선택, 실행 예시, 테스트 정책 추가
- `backend/README.md`: Backend Provider 설정과 장애 정책 추가
- `docs/scaffold/AI_MAFIA_MIN_CONNECTION_PLAN.md`: scaffold의 Dummy/Local 범위와
  이후 OpenAI/Gemini 확장 관계 명시
- `docs/AI_MAFIA_MVP_FINAL_PLAN.md`: 실제 Provider adapter의 책임과 비밀·비용 경계 반영

## 8. 완료 조건

- 실행 코드와 문서에서 구현 경로가 `backend/app/llm_provider/`로 일치한다.
- `LLM_PROVIDER=dummy`로 외부 key 없이 전체 회귀 테스트가 통과한다.
- Local, OpenAI, Gemini가 동일한 공통 계약과 구조화 출력 검증을 사용한다.
- 원격 Provider별 설정 누락·timeout·인증·응답 오류 테스트가 통과한다.
- Provider는 게임 상태를 직접 바꾸지 않고 proposal만 반환한다.
- 비밀정보, prompt 원문, 비공개 게임 정보가 diff·로그·응답에 노출되지 않는다.
- README와 관련 계획 문서가 현재 구현과 일치한다.
- 커밋·push는 사용자 명시 승인을 받은 경우에만 수행한다.

## 9. 계획 구체성 검증 결과

이 계획은 2026-09-02 현재 저장소를 기준으로 다음 항목을 대조해 작성했다.

| 검증 항목 | 결과 |
|---|---|
| 현재 LLM 구현 위치 | `backend/app/llm_provider/`의 공통 계약·Dummy·Local·OpenAI·Gemini 구현 확인 |
| 현재 실행 코드 import | `backend/app/routers/scaffold_game_router.py`가 `backend.app.llm_provider`를 사용하며 구 경로 import는 제거됨 |
| Provider 선택 설정 | `backend/app/core/config.py`가 네 가지 값을 허용하지만 원격 key/model은 아직 미연결 |
| 예시 환경 변수 | `.env.example`에 Local/OpenAI/Gemini와 timeout·비용 항목이 존재 |
| SDK 의존성 | `pyproject.toml`에 `openai`, `google-genai`, `httpx`가 선언됨 |
| 기존 테스트 위치 | `backend/tests/`가 통합 pytest 대상이며 Provider 전용 테스트는 아직 없음 |
| 문서 연결 | `README.md`에 이 계획 문서 링크와 현재/목표 경로를 반영함 |
| 링크·공백 검사 | README 내부 상대 링크와 `git diff --check` 통과 |

따라서 이 문서는 파일별 구현 위치, 설정 이름, Provider 선택값, 공통 입출력,
오류·보안 경계, 테스트 항목과 완료 명령을 지정하고 있어 구현 착수에 필요한
수준으로 구체적이다. 단, 단계 E에 들어가기 전 `AI_MAFIA_GAME_RULES.md`의
실제 proposal action·필드 목록을 확정해야 한다. 현재 scaffold의 `PING` 계약을
먼저 유지한 뒤 실제 action을 추가하는 방식으로 범위를 통제한다.
