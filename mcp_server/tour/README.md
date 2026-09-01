# Tour MCP Server

여행지·숙박 검색과 추천 기능을 독립적으로 제공할 MCP 서버의 예약 구조입니다.
현재 단계에는 서버 실행 파일, MCP Tool, 외부 API, PostgreSQL 검색, embedding,
Redis 연결이 없습니다.

의존 방향은 `api → services → ports ← integrations`입니다. `domain`에는 MCP,
HTTP, DB 구현을 모르는 순수 여행 규칙만 두고, `schemas`는 공개 입출력과 외부 응답
계약만 검증합니다. 다른 MCP 서버의 내부 모듈은 import하지 않습니다.
