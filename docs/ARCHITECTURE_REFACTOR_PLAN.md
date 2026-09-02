# Team4 구조 개편 및 서버 연결 구현 계획서

## 0. 구현 상태 (2026-09-01)

이 계획에 정의한 구조 개편과 현재 단계 서버 연결을 적용했다.

- 기존 `frontend` 추적 파일을 `frontend_user`로 이동하고 얇은 `app.py`와
  `app_pages/login_page.py` 경계를 구성했다.
- FastAPI Backend의 health·identity router, schema, service, repository,
  PostgreSQL·migration·HMAC infrastructure 경계를 구성했다.
- Frontend의 PostgreSQL 직접 호출을 제거하고 `core/api_client.py`의 서명된
  `POST /api/v1/identity/provision` 호출로 교체했다.
- `frontend_admin`은 관리자 기능 없이 독립 실행 가능한 준비 화면만 추가했다.
- `mcp_server/tour`, `mcp_server/weather`에는 실제 Tool이나 외부 호출 없이 예약
  package와 계층별 책임 문서만 추가했다.
- migration 소유권과 실행 경로를 `backend/migrations/` 및
  `backend.app.infrastructure.migrations`로 변경했다.
- 실제 `.env`, `secrets.toml`, OAuth client JSON은 자동 이동하거나 내용 확인을
  하지 않았다. 새 `frontend_user` 설정은 예시와 루트 README에 별도로 안내한다.
- 저장소 작업 규칙 파일명은 `AGENT.MD`에서 `AGENTS.MD`로 변경했으며 루트
  README의 링크와 구조 표에도 같은 이름을 반영했다.

LLM Agent, MCP Tool, 관리자 업무, Redis nonce 저장은 계속 후속 범위다. 현재
`request_id`는 trace 상관관계에만 사용하고 재전송 방어는 timestamp 만료를 기준으로
한다.

## 1. 문서 목적

이 문서는 현재 프로젝트의 동작을 유지하면서 루트 아래에 `backend`,
`frontend_user`, `frontend_admin`, `mcp_server`를 독립 실행 단위로 배치하고,
향후 LLM Agent와 MCP를 연결할 수 있는 기본 아키텍처를 마련하기 위한 계획서다.

이번 작업의 목적은 새로운 사용자 기능이나 MCP Tool을 추가하는 것이 아니다.
현재 구현된 Google OIDC 로그인, 사용자 계정 연결, PostgreSQL 저장, 로그인 UI를
보존한 상태에서 파일 책임과 서버 간 연결 경계만 정리한다.

## 2. 현재 구현 범위

현재 프로젝트에서 보존해야 할 기능은 다음과 같다.

- Streamlit 기반 Google OIDC 로그인·로그아웃
- OIDC 설정 누락·placeholder·안전하지 않은 URL 검증
- Google `sub` 기반 외부 계정 식별
- 첫 로그인 시 PostgreSQL 사용자 및 OAuth identity 생성
- 재로그인 시 프로필과 최근 로그인 시각 갱신
- 비활성 사용자 차단
- 프로필 값 HTML escaping 및 HTTPS 아바타 제한
- PostgreSQL migration 실행
- 로그인·프로필 표시 UI

현재 LLM Agent, MCP Tool, 관리자 업무 화면, 대화 기능, Redis 캐시·Pub/Sub는
구현되어 있지 않다. 따라서 이번 구조 개편에서는 해당 기능을 실제로 추가하지
않고 향후 연결 지점만 만든다.

## 3. 구조 개편 원칙

### 3.1 독립 실행 단위

- `backend`는 FastAPI API 서버로 독립 실행한다.
- `frontend_user`와 `frontend_admin`은 각각 독립 Streamlit 앱으로 실행한다.
- `mcp_server/tour`, `mcp_server/weather`는 각각 독립 프로세스로 실행할 수 있게 한다.
- Frontend는 DB, Redis, MCP 서버를 직접 호출하지 않는다.
- MCP 서버끼리는 서로의 내부 Python 모듈을 import하지 않는다.

### 3.2 이번 단계의 보수적 범위

- Backend 최종 구조에는 `backend/app/db`와 `backend/app/auth` 디렉터리를 두지 않는다.
- 기존 기능은 `models`, `repositories`, `services`, `infrastructure`로 파일을
  이동해 보존한다.
- 기존 import 경로가 많은 경우에만 짧은 호환 shim을 두고, 전체 테스트가 통과한
  뒤 shim을 제거한다.
- `mcp_server`는 구조만 만들고 실제 외부 API, 벡터 검색, MCP Tool은 추가하지 않는다.
- `agent`, `llm`, `mcp client`는 인터페이스와 조립 위치만 마련하며 실제 호출은
  비활성 상태로 둔다.

### 3.3 의존성 방향

```text
Frontend
    ↓ HTTP
Backend Router
    ↓
Backend Schema → Service → Repository / Models
                                  ↓
                              PostgreSQL

향후 Agent 경로:
Backend Agent Service → LLM Adapter → MCP Client → 독립 MCP Server
```

Router는 요청·응답과 의존성 조립만 담당한다. 업무 흐름은 Service에 두고,
외부 기술 연결은 `infrastructure` 또는 MCP 서버의 `integrations`에 둔다.

### 3.4 이번 단계의 인증 전달 결정

현재 사용자 화면의 Streamlit native OIDC 동작을 유지하기 위해 OIDC 로그인 자체는
`frontend_user`에 남긴다. Frontend가 Backend에 identity를 전달할 때는 단순한
`user_id`나 임의의 JSON만 보내지 않고, 서버 간 공유 비밀로 HMAC 서명한 요청을
사용한다.

```text
Streamlit st.user
    ↓ claim 정규화
frontend_user/auth/identity.py
    ↓ timestamp + HMAC signature
POST /api/v1/identity/provision
    ↓ 서명·시간·payload 검증
Backend identity_service
    ↓
user_repository.upsert_identity()
```

HMAC secret은 브라우저에 전달하지 않고 Streamlit 서버 secrets와 Backend 환경
변수에만 둔다. Timestamp 허용 오차와 request id 또는 nonce를 사용해 재전송을
제한한다. Backend는 서명 검증 후에도 provider, subject, email, email_verified를
도메인 모델 규칙으로 다시 검증한다.

Backend가 OIDC callback과 브라우저 세션을 직접 소유하는 전환은 이번 계획에
포함하지 않는다. 이는 현재 로그인 동작을 바꾸는 별도 작업으로 취급한다.

## 4. 목표 디렉터리 구조

```text
Team4_Proj_0831/
├── backend/                         # 외부 HTTP 요청을 받는 FastAPI 서버
│   ├── app/
│   │   ├── main.py                  # FastAPI 생성, middleware·router 등록
│   │   ├── routers/                 # HTTP endpoint와 요청 흐름 진입점
│   │   │   ├── health_router.py
│   │   │   └── identity_router.py
│   │   ├── schemas/                 # API 요청·응답 DTO와 validation
│   │   │   ├── identity_schema.py
│   │   │   ├── user_schema.py
│   │   │   └── common_schema.py
│   │   ├── services/                # 사용자 연결 등 애플리케이션 유스케이스
│   │   │   └── identity_service.py
│   │   ├── models/                  # 외부 identity·내부 사용자 도메인 모델
│   │   │   └── identity.py
│   │   ├── repositories/            # 영속성 인터페이스와 PostgreSQL 구현
│   │   │   └── user_repository.py
│   │   ├── agent/                   # 향후 LLM Agent 실행 오케스트레이션
│   │   │   ├── orchestrator.py
│   │   │   └── policies.py
│   │   ├── mcp/                     # 향후 MCP Client·Tool routing 경계
│   │   │   ├── client.py
│   │   │   ├── registry.py
│   │   │   └── tool_router.py
│   │   ├── llm_provider/           # LLM Provider 공통 계약과 실제 adapter
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── dummy.py
│   │   │   ├── local.py
│   │   │   ├── openai_provider.py
│   │   │   └── gemini_provider.py
│   │   ├── infrastructure/         # 외부 기술 구현과 실행 환경 연결
│   │   │   ├── postgres.py          # PostgreSQL 연결 조립
│   │   │   ├── migrations.py        # migration 실행
│   │   │   ├── redis/               # Redis client·key·Pub/Sub
│   │   │   └── security/            # Frontend–Backend HMAC 검증
│   │   ├── core/                   # 오류·응답·설정·로깅 공통 기능
│   │   │   ├── config.py
│   │   │   ├── errors.py
│   │   │   ├── responses.py
│   │   │   └── logging.py
│   ├── migrations/                 # Backend가 소유하는 PostgreSQL schema 변경 이력
│   │   └── 001_create_oauth_schema.sql
│   ├── tests/
│   ├── requirements.txt
│   └── README.md
│
├── frontend_user/                  # 일반 사용자용 Streamlit 서버
│   ├── app.py                      # Streamlit 실행 진입점·공통 레이아웃
│   ├── app_pages/                  # 사용자 화면 단위
│   │   └── login_page.py
│   ├── auth/                       # 현재 Streamlit OIDC claim·상태 처리
│   │   ├── configuration.py
│   │   ├── identity.py
│   │   └── persistence.py
│   ├── components/                 # HTML·CSS·화면 표현 컴포넌트
│   │   └── ui.py
│   ├── core/                       # Backend API client·Frontend session
│   │   ├── api_client.py
│   │   └── session.py
│   ├── .streamlit/
│   ├── requirements.txt
│   └── README.md
│
├── frontend_admin/                 # 관리자용 독립 Streamlit 서버
│   ├── app.py                      # 관리자 앱 실행 진입점
│   ├── app_pages/                  # 관리자 화면 단위
│   │   └── README.md
│   ├── components/                 # 관리자 전용 화면 컴포넌트
│   ├── core/                       # Backend API client·관리자 세션
│   │   ├── api_client.py
│   │   └── auth.py
│   ├── requirements.txt
│   └── README.md
│
├── mcp_server/                     # 독립 배포 가능한 MCP 서버 모음
│   ├── tour/                       # 여행지·숙박 MCP 서버 단위
│   │   ├── __init__.py             # Python package 공개 진입점
│   │   ├── README.md               # 서버 책임·향후 Tool 계획
│   │   ├── api/                    # MCP 프로토콜 공개 계층
│   │   │   ├── tools/              # LLM이 호출할 Tool 등록
│   │   │   ├── resources/          # 읽기 전용 MCP Resource 등록
│   │   │   └── prompts/            # 재사용 MCP Prompt 등록
│   │   ├── domain/                 # 외부 기술과 무관한 업무 개념·규칙
│   │   ├── schemas/                # MCP 입출력·외부 응답 데이터 계약
│   │   ├── services/               # 검색·추천 등 MCP 유스케이스
│   │   ├── ports/                  # Service가 요구하는 외부 연동 Protocol
│   │   ├── integrations/           # DB·embedding·Redis 등의 구체 구현
│   │   │   ├── database/
│   │   │   ├── embedding/
│   │   │   └── redis/
│   │   └── core/                   # 해당 MCP 서버 내부 공통 기능
│   └── weather/                    # 날씨 MCP 서버 단위, tour와 독립 실행
│       └── 동일한 계층 구조
│
├── tests/                          # 서버 간 통합·브라우저 수준 검증
│   ├── integration/
│   └── e2e/
└── README.md
```

`backend/app/auth`와 `backend/app/db`는 목표 구조에 포함하지 않는다. 기존 인증
도메인 모델은 `models/identity.py`, 사용자 저장소는 `repositories/`로 옮기며,
환경 설정은 `core/`가 담당하고, migration 파일은 Backend 소유의
`backend/migrations/`에 둔다. migration 실행 코드는
`backend/app/infrastructure/migrations.py`가 해당 디렉터리를 읽어 처리한다.

### 4.2 MCP `domain/`을 별도로 두는 이유

`mcp_server/tour/domain/`과 `mcp_server/weather/domain/`은 MCP protocol,
FastMCP decorator, PostgreSQL client, 외부 날씨 API 같은 기술 요소를 모르는
순수한 업무 규칙 영역이다. 예를 들어 여행 검색 조건의 의미, 가격 필터 규칙,
위치 표현, 추천 결과의 도메인 모델이 이곳에 들어간다.

이 계층을 `api/`나 `integrations/` 안에 섞지 않으면 다음 변경이 서로 영향을
주지 않는다.

- MCP transport를 Streamable HTTP에서 다른 transport로 변경
- PostgreSQL을 다른 검색 저장소로 교체
- 외부 날씨 Provider를 추가하거나 교체
- 동일한 검색 규칙을 REST API나 배치 작업에서 재사용

`domain/`은 DB repository나 MCP Tool 등록 파일이 아니다. `api/tools`는 공개
입력과 MCP 응답을 담당하고, `services`는 유스케이스를 조합하며, `ports`는
외부 연동 계약을 정의한다. 이번 단계에는 실제 업무 규칙이 없으므로
`domain/`은 역할을 표시하는 예약 디렉터리로만 생성한다.

### 4.1 기존 파일 이동표

| 기존 경로 | 목표 경로 | 처리 방법 |
|---|---|---|
| `frontend/app.py` | `frontend_user/app_pages/login_page.py` | 로그인 화면의 `main()`을 이동 |
| `frontend/ui.py` | `frontend_user/components/ui.py` | UI 생성 함수와 CSS 이동 |
| `frontend/auth/configuration.py` | `frontend_user/auth/configuration.py` | 기능 변경 없이 이동 |
| `frontend/auth/identity.py` | `frontend_user/auth/identity.py` | 새 Backend 모델 import로 수정 |
| `frontend/auth/authorization.py` | `frontend_user/auth/authorization.py` | 기능 변경 없이 이동 |
| `frontend/auth/persistence.py` | `frontend_user/auth/persistence.py` | DB 직접 호출을 API Client 호출로 교체 |
| `frontend/auth/providers.py` | `frontend_user/auth/providers.py` | 기능 변경 없이 이동 |
| `backend/app/auth/models.py` | `backend/app/models/identity.py` | `ExternalIdentity`, `UserRecord` 이동 |
| `backend/app/db/users.py` | `backend/app/repositories/user_repository.py` | SQL·트랜잭션 동작 유지 |
| `backend/app/db/migrate.py` | `backend/app/infrastructure/migrations.py` | 대상 migration 경로만 수정 |
| `backend/app/core/config.py` | `backend/app/core/config.py` | 유지, DB 설정 사용처만 수정 |
| `migrations/001_create_oauth_schema.sql` | `backend/migrations/001_create_oauth_schema.sql` | 파일 이동 후 실행기 경로 수정 |

`frontend_user/app.py`는 페이지 자동 탐색에 의존하지 않고
`app_pages.login_page.main()`을 호출하는 얇은 실행 진입점으로 만든다. 따라서
Streamlit 기본 `pages/` 디렉터리 명명 규칙을 사용하지 않아도 `app_pages` 구조를
안정적으로 유지할 수 있다.

기존 `backend/app/auth`와 `backend/app/db` import를 직접 참조하는 코드가 있으면
먼저 새 경로로 수정하고, 테스트가 통과할 때까지 필요한 파일에만 호환 import를
둔다. 호환 shim은 최종 목표 구조가 아니며 제거 대상이다.

## 5. 디렉터리별 책임

### 5.1 Backend

| 디렉터리 | 책임 |
|---|---|
| `routers/` | HTTP 경로 등록, 요청 수신, 응답 반환 |
| `schemas/` | API 요청·응답 형식과 validation |
| `services/` | identity provision 등 업무 흐름 조정 |
| `models/` | 외부 identity와 내부 사용자 도메인 모델 |
| `repositories/` | PostgreSQL 저장소 구현 |
| `agent/` | 향후 LLM Agent 실행 위치 |
| `mcp/` | 향후 MCP Client·Tool registry 위치 |
| `llm_provider/` | Provider 공통 계약과 Dummy·Local·OpenAI·Gemini adapter |
| `infrastructure/redis/` | 향후 Redis 연결·키·Pub/Sub 위치 |
| `infrastructure/security/` | Frontend–Backend 내부 HMAC 검증 |
| `core/` | 공통 설정, 오류, 응답, 로깅 |

이번 단계에서는 `agent/`, `mcp/`, `llm_provider/`, `infrastructure/redis/`에 Agent 업무나
외부 호출 코드를 넣지 않는다. 다만 인증 provision API를 위해
`infrastructure/security/`의 HMAC 검증은 구현한다.

### 5.2 Frontend

- `frontend_user`는 현재 로그인 화면을 보존한다.
- `app_pages/login_page.py`는 현재 `frontend/app.py`의 사용자 화면을 이동한 위치다.
- `components/ui.py`는 HTML·CSS 표현을 담당한다.
- `core/api_client.py`는 Backend 호출의 단일 진입점이다.
- `frontend_admin`은 동일한 API Client 패턴을 사용하지만, 이번 작업에서는
  관리자 업무 기능을 추가하지 않는다.

### 5.3 MCP Server

각 MCP 서버는 다음 방향을 지킨다.

```text
api/tools → services → ports → integrations → 외부 API·DB·모델
```

- `server.py`: 서버 생성과 의존성 조립
- `api/tools`: MCP 공개 Tool 등록
- `services`: 도메인 업무 흐름
- `ports`: 외부 구현에 대한 Protocol
- `integrations`: PostgreSQL, Redis, 외부 API, embedding 구현
- `core`: 해당 MCP 서버 내부에서만 사용하는 공통 코드

| MCP 디렉터리 | 맡은 역할 | 두지 않는 것 |
|---|---|---|
| `api/tools/` | LLM이 호출할 MCP Tool 등록, 입력 변환, Service 호출 | DB query, 외부 API 직접 호출 |
| `api/resources/` | 읽기 전용 MCP Resource 등록과 URI 처리 | 상태 변경 업무 |
| `api/prompts/` | 재사용 가능한 MCP Prompt 등록 | 사용자 세션·권한 판단 |
| `domain/` | 여행·날씨 업무 개념, 값 객체, 순수 규칙 | FastMCP, HTTP, PostgreSQL 의존성 |
| `schemas/` | MCP 입력·출력 및 외부 응답 구조 검증 | 업무 흐름 조정 |
| `services/` | 검색·추천·비교 같은 유스케이스 조합 | transport 등록, 환경변수 직접 읽기 |
| `ports/` | Repository·Provider·Embedding 추상 계약 | PostgreSQL·Redis 같은 기술명 구현 |
| `integrations/` | Port의 실제 구현과 외부 시스템 연결 | LLM Tool 공개 등록 |
| `core/` | 서버 내부 timeout, 오류, logging 등 공통 기반 | 다른 MCP 서버와의 공유 코드 |

이번 단계에서는 `tour`와 `weather`를 실제로 실행하거나 Tool을 등록하지 않는다.
향후 기능이 추가될 때 서버별로 독립적인 requirements, 환경 변수, 테스트를
갖도록 한다.

## 6. 서버 간 연결 계획

### 6.1 현재 기능 보존 경로

1. `frontend_user`에서 현재처럼 Streamlit OIDC 로그인 상태를 확인한다.
2. 사용자 입력과 외부 claim은 기존 `frontend_user/auth`에서 정규화한다.
3. `core/api_client.py`가 timestamp, request id, HMAC signature를 포함해 Backend를 호출한다.
4. `identity_router.py`가 schema와 내부 요청 서명을 검증한다.
5. `identity_service.py`가 `repositories/user_repository.py`를 호출한다.
6. DB 저장 성공 여부에 따라 현재와 동일하게 접근을 허용하거나 거부한다.

Frontend가 `user_id`만 보내고 Backend가 그대로 신뢰하는 구조는 사용하지 않는다.
실제 Backend 인증 세션으로 전환하기 전까지 Frontend는 HMAC 서명된 내부 요청만
사용한다. 서명 검증에 실패하거나 timestamp 허용 오차를 벗어나면 저장소를 호출하지
않고 401을 반환한다.

### 6.2 현재 단계 API 계약

#### `GET /health`

- 목적: Backend 프로세스 상태 확인
- 응답: `200 {"status": "ok"}`
- 인증: 없음

#### `POST /api/v1/identity/provision`

- 목적: Streamlit에서 검증·정규화한 외부 identity를 내부 사용자와 연결
- 내부 호출 헤더:
  - `X-Internal-Timestamp`: UTC Unix timestamp
  - `X-Internal-Request-Id`: 요청별 UUID
  - `X-Internal-Signature`: `HMAC-SHA256(timestamp.request_id.body)`
- 서명 계산 규칙:

```text
canonical = UTF8(timestamp + "." + request_id + "." + raw_request_body)
signature = hex(HMAC-SHA256(INTERNAL_API_SECRET, canonical))
```

- Backend 허용 시간 오차는 기본 300초로 둔다.
- `request_id`는 UUID 형식을 검증하고 로그의 trace 상관관계에 사용한다.
- Redis가 실제 연결되는 후속 단계에서 `request_id`를 짧은 TTL로 저장해
  재전송을 차단한다. 이번 단계에서는 timestamp 만료가 재전송 방어의 기준이다.
- 요청 schema:

```json
{
  "provider": "google",
  "provider_subject": "opaque-subject",
  "email": "traveler@example.com",
  "email_verified": true,
  "display_name": "여행자",
  "avatar_url": "https://example.com/avatar.png"
}
```

- 성공 응답 `200`:

```json
{
  "user_id": "uuid",
  "email": "traveler@example.com",
  "display_name": "여행자",
  "avatar_url": "https://example.com/avatar.png",
  "is_active": true
}
```

- 오류 계약:
  - `401 INVALID_INTERNAL_SIGNATURE`: HMAC, timestamp, request id 검증 실패
  - `403 INACTIVE_USER`: 비활성 사용자
  - `422 INVALID_IDENTITY`: identity schema 또는 도메인 규칙 위반
  - `503 IDENTITY_PERSISTENCE_UNAVAILABLE`: DB 연결 또는 저장 실패

오류 응답은 `code`, `message`, `details`, `trace_id` 형식으로 통일한다. secret,
OIDC token, 원본 DB URL은 응답과 로그에 포함하지 않는다.

### 6.3 향후 Agent·MCP 연결 경로

```text
frontend_user 또는 frontend_admin
    ↓ POST /api/v1/agent/*
backend/routers/agent_router.py
    ↓
backend/services/agent_service.py
    ↓
backend/agent/orchestrator.py
    ├── llm_provider/factory.py
    └── mcp/client.py
             ↓ Streamable HTTP
       mcp_server/tour 또는 weather
```

LLM은 MCP Tool schema를 선택하는 역할만 수행한다. 실제 Tool 실행, 서버 선택,
권한 확인, 실행 횟수 제한, 결과 기록은 Backend가 담당한다.

### 6.4 DB와 Redis 연결 원칙

- 사용자·OAuth identity의 원본 데이터는 Backend PostgreSQL이 소유한다.
- 향후 Tour 검색 데이터는 `mcp_server/tour`가 읽기 전용으로 접근한다.
- Redis는 세션, 캐시, 실행 상태, Pub/Sub에 사용하고 영구 데이터 저장소로 사용하지 않는다.
- Redis key에는 서비스 prefix를 사용한다. 예: `team4:backend:*`, `team4:tour:*`.
- MCP 서버가 Backend 사용자 테이블을 직접 수정하지 않는다.
- DB migration은 Backend가 소유한다. MCP 전용 schema가 실제로 추가되는 시점에는
  `mcp_server/<server>/migrations/` 또는 별도 MCP 배포 저장소로 분리한다.

### 6.5 MCP 예약 구조 생성 기준

이번 단계에서는 각 MCP 서버에 다음 파일과 디렉터리만 만든다.

```text
mcp_server/tour/
├── __init__.py
├── README.md
├── api/tools/
├── api/resources/
├── api/prompts/
├── domain/
├── schemas/
├── services/
├── ports/
├── integrations/
└── core/
```

각 디렉터리에는 `__init__.py`를 두고, 역할은 `README.md`에 기록한다.
`server.py`, `__main__.py`, 실제 Tool 등록, 외부 API 호출, PostgreSQL 검색,
embedding, Redis 연결은 향후 기능 구현 단계에서 추가한다.

## 7. 단계별 구현 순서

### 1단계: 현재 상태 고정

- 현재 테스트와 컴파일 결과를 기록한다.
- 실제 `.env`, `secrets.toml`, OAuth client JSON은 이동 대상에 포함하지 않는다.
- 현재 `frontend`, `backend`, `migrations`의 동작을 baseline으로 보존한다.

### 2단계: Frontend 분리

- `frontend`를 `frontend_user`로 이동한다.
- `app.py`, `auth`, UI, Streamlit secrets 예시를 기능 변경 없이 이동한다.
- `app_pages/login_page.py`를 추가하고 기존 로그인 화면을 연결한다.
- `frontend_admin`은 실행 가능한 최소 골격만 만든다.

### 3단계: Backend API 골격 추가

- FastAPI `backend/app/main.py`를 추가한다.
- `health_router.py`, `identity_router.py`, `schemas/`를 추가한다.
- 기존 `backend/app/auth/models.py`의 모델을 `app/models/identity.py`로 이동한다.
- 기존 `backend/app/db/users.py`를 `app/repositories/user_repository.py`로 이동한다.
- 기존 repository의 SQL·트랜잭션 동작은 변경하지 않고 Service에서 호출한다.
- `identity_schema.py`와 HMAC 내부 요청 검증을 추가한다.

### 4단계: Frontend–Backend 연결

- Frontend의 Backend 호출을 `core/api_client.py` 한 곳으로 모은다.
- `POST /api/v1/identity/provision`을 호출하도록 persistence 경계를 교체한다.
- Frontend와 Backend의 HMAC secret은 각각 secrets/env에만 보관한다.
- API 오류 응답과 trace id 처리 경계를 정의한다.
- 기존 로그인 성공·실패·비활성 계정 화면이 동일하게 동작하는지 확인한다.

### 5단계: MCP 예약 구조 추가

- `mcp_server/tour`, `mcp_server/weather`의 계층 디렉터리만 생성한다.
- 서버별 계층 README와 `__init__.py`만 생성한다.
- 실제 Tool, 외부 API, DB 검색, Redis 동작은 구현하지 않는다.
- Backend에는 향후 MCP Client를 둘 위치만 만들고 API에 연결하지 않는다.

### 6단계: 마이그레이션과 검증 정리

- 기존 OAuth migration을 `backend/migrations/`로 이동한다.
- `backend/app/infrastructure/migrations.py`의 기본 migration 경로를 수정한다.
- 경로 변경 후 Backend repository와 migration 실행 테스트를 다시 수행한다.
- import 검색으로 이전 경로 참조를 확인한다.
- 전체 테스트, compileall, lint 결과를 기록한다.

### 7단계: 실패 시 복구

- 구조 개편은 작업 브랜치에서 수행하고 단계별로 커밋한다.
- 각 이동은 `git mv`로 수행해 파일 이력을 보존한다.
- 새 경로 테스트가 통과하기 전에는 기존 호환 shim을 삭제하지 않는다.
- 인증 또는 사용자 저장 테스트가 실패하면 다음 단계로 진행하지 않고 직전
  단계의 경로와 import 상태로 되돌린다.
- 실제 secrets, `.env`, OAuth client JSON은 이동·복구 대상에서 제외한다.

## 8. 실행 명령과 검증 절차

### 8.1 Backend 실행

저장소 루트에서 실행한다. 별도의 루트 `infra/` 디렉터리나 Docker Compose에
의존하지 않는다.

```powershell
python -m uvicorn backend.app.main:app --reload --port 8000
Invoke-RestMethod http://127.0.0.1:8000/health
```

정상 응답은 `{"status":"ok"}`다.

### 8.2 사용자 Frontend 실행

```powershell
python -m streamlit run frontend_user/app.py --server.port 8501
```

기존과 동일하게 `http://localhost:8501`에서 Google 로그인 화면을 확인한다.

### 8.3 관리자 Frontend 실행

이번 단계의 관리자 앱은 업무 기능 없이 구조 확인용으로만 실행한다.

```powershell
python -m streamlit run frontend_admin/app.py --server.port 8502
```

### 8.4 Migration 실행

```powershell
python -m backend.app.infrastructure.migrations
```

기존 `DATABASE_URL` 연결 정보와 `DATABASE_NAME=Team4_Proj` 적용 규칙을 유지한다.

이번 구조 개편에서는 루트 `migrations/`와 `infra/`를 만들지 않는다. 로컬
PostgreSQL·Redis 실행은 개발자 환경 또는 별도 운영 인프라에서 준비하고,
서비스별 README에는 필요한 접속 URL과 환경 변수만 문서화한다.

### 8.5 테스트 순서

```powershell
python -m compileall backend frontend_user frontend_admin mcp_server
python -m pytest backend/tests
python -m pytest frontend_user/tests
```

추가해야 할 Backend API 테스트는 다음 경로를 검증한다.

1. 정상 HMAC 요청은 repository를 호출하고 `200`을 반환한다.
2. 서명 불일치 요청은 `401`을 반환하고 repository를 호출하지 않는다.
3. 만료된 timestamp 요청은 `401`을 반환한다.
4. `email_verified=false` 요청은 `422`를 반환한다.
5. 비활성 사용자는 `403`을 반환하고 프로필을 갱신하지 않는다.
6. DB 예외는 `503`과 고정된 오류 형식으로 변환한다.

구조 개편 직전 baseline은 현재 macOS 개발 환경에서 전체 테스트 51개, compileall,
Ruff가 모두 통과했다. 과거 기록의 `.env` 부재와 Windows 파일 권한 관련 3개 실패는
현재 환경에서 재현되지 않았다. 구현 후에는 HMAC 정상·거부 경로와 Frontend API
client 테스트를 추가한 전체 회귀 결과를 완료 보고의 기준으로 사용한다.

구현 완료 후 전체 회귀 테스트는 70개가 통과했고, `compileall`과 Ruff도 통과했다.
FastAPI TestClient가 현재 설치된 Starlette 조합에서 향후 `httpx2` 전환을 안내하는
deprecation warning 1건을 출력하지만 테스트 실패나 런타임 동작 오류는 아니다.

## 9. 완료 기준

- 기존 Google 로그인 화면과 OIDC 설정 오류 처리가 동일하게 동작한다.
- 신규 사용자 생성, 재로그인 갱신, 비활성 사용자 차단이 동일하게 동작한다.
- 기존 PostgreSQL migration과 repository 테스트가 통과한다.
- `POST /api/v1/identity/provision`의 정상·서명 실패·비활성 사용자·DB 실패 경로가
  모두 테스트된다.
- `frontend_user`, `frontend_admin`, `backend`가 서로 독립된 실행 단위를 가진다.
- Frontend가 DB 또는 MCP 서버를 직접 호출하지 않는다.
- `mcp_server/tour`, `mcp_server/weather`가 서로 독립된 패키지 구조를 가진다.
- 실제 LLM 호출이나 MCP Tool 추가 없이 향후 연결 위치가 문서화되어 있다.
- `frontend_user/app.py`가 `app_pages.login_page`를 통해 현재 로그인 화면을 실행한다.
- Backend와 Frontend가 정의된 실행 명령으로 각각 기동된다.
- 실제 비밀정보가 새 디렉터리나 문서에 포함되지 않는다.
- README, 실행 명령, 테스트 경로가 변경된 구조와 일치한다.

## 10. 이번 단계에서 하지 않는 작업

- 새로운 여행지·호텔·날씨 기능 추가
- LLM Provider 또는 Agent Loop 구현
- MCP Tool·Resource·Prompt 구현
- 관리자 대시보드와 관리자 업무 API 구현
- Redis 캐시·세션·Pub/Sub 실제 연결
- OAuth token 저장 또는 Google API 권한 확장
- 데이터베이스 스키마의 업무 기능 확장
- Docker Compose 등 운영 인프라 완성
