# AI 마피아 계약 문서 인덱스

기존 통합 문서는 독립 개발 시 책임 경계를 흐리므로 상세 계약을 아래 두 문서로
분리했다. 이 파일에는 계약을 재정의하지 않고 읽기 순서와 공통 결정만 둔다.

1. [Backend REST·SSE 계약](AI_MAFIA_BACKEND_API_CONTRACT.md): Frontend↔Backend의 HTTP 진입점, 헤더, schema, 오류, operation, 이벤트 스트림, 관리자 API.
   기계 판독용 [OpenAPI 3.1 원본](AI_MAFIA_BACKEND_OPENAPI.yaml)도 함께 제공한다.
2. [게임 MCP 계약](AI_MAFIA_MCP_API_CONTRACT.md): Backend↔MCP의 내부 HMAC·session과 Agent가 사용하는 게임 Resource·Tool.
3. [DB·Redis 설계](AI_MAFIA_DATA_REDIS_DESIGN.md): 영속 원본·캐시·복구 경계.
4. [Frontend 화면 설계](AI_MAFIA_FRONTEND_SPEC.md): 화면별 상태, 호출 시점, 렌더링 규칙.
5. [게임 규칙·로직](AI_MAFIA_GAME_RULES.md): phase 상태 머신과 상태별 판정·API 이벤트.
6. [연결 뼈대 우선 구현 계획](scaffold/AI_MAFIA_SCAFFOLD_PLAN.md): 참고 프로젝트를 활용한 독립 실행·REST·MCP smoke 구현 순서.
   세부 문서는 파일별 구현, schema, 실행 절차, 테스트 계획으로 연결된다.

충돌 우선순위는 `Backend API schema > 게임 규칙 > DB projection > 화면 표현`이다.
인증은 아직 MVP 범위 밖이며 `X-User-Id`는 개발용 식별자일 뿐이다. 게임 MCP는
`mcp_server/mcp_1`에만 구현하고 `mcp_2`와 다른 도메인은 이번 범위에서 비워 둔다.
