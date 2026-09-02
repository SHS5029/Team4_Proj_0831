# Mafia Game Context MCP Server

AI 마피아 게임의 에이전트에게 허용된 게임 컨텍스트(Resource)와 행동 제안
(Tool)을 제공할 MCP 서버 패키지입니다. 제품·소유권은
[공통 마스터플랜](../../docs/개발상세플랜/AI_MAFIA_MASTER_PLAN.md), wire 계약은
[API 명세서](../../docs/개발상세플랜/AI_MAFIA_API_SPEC.md)를 따릅니다.

현재 단계에는 서버 실행 파일, MCP Tool, Backend 연동 코드가 없는 예약
구조입니다. MCP 섹터 담당자는 이 패키지 구현과 별도로 PostgreSQL·Redis 실행
환경의 구축·기동·migration 실행·health 확인을 담당합니다.

## 책임 경계

- 이 서버는 게임 상태의 최종 판정자가 아닙니다. 모든 행동 제안은 Backend
  내부 Engine API로 전달되고 Backend 게임 엔진이 최종 검증·반영합니다.
- DB, Redis에 직접 접근하지 않으며 Backend의 내부 HTTP API만 호출합니다.
- 세션은 `subject_type`과 `subject_id`를 고정합니다. AI player는 `public`, `me`,
  `turn`, `persona` 중 capability가 허용한 정보만 받고 다른 에이전트를 선택할 수
  없습니다. GM은 `public`과 `gm-guide`만 받으며 `me`와 행동 Tool을 사용할 수 없습니다.

PostgreSQL·Redis 운영은 **담당자의 인프라 역할**이며 MCP 서버 runtime의 책임이
아닙니다. DB schema·migration SQL·repository와 Redis client·key·TTL·lock 계약은
Backend가 작성하고, MCP 담당자는 이를 수정하지 않은 채 실제 환경에서 실행·검증해
비밀값 없는 결과만 공유합니다.

의존 방향은 `api → services → ports ← integrations`입니다. `domain`에는
MCP·HTTP 구현을 모르는 순수 게임 개념만 두고, `schemas`는 공개 입출력 계약만
검증합니다. 다른 MCP 서버의 내부 모듈은 import하지 않습니다.
