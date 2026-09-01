# Weather MCP Server

날씨 조회와 해석 기능을 독립적으로 제공할 MCP 서버의 예약 구조입니다. 현재
단계에는 서버 실행 파일, MCP Tool, 외부 날씨 API, DB, embedding, Redis 연결이
없습니다.

의존 방향은 `api → services → ports ← integrations`입니다. `domain`에는 MCP나
외부 날씨 provider를 모르는 순수 날씨 개념만 두며 Tour 서버 내부 모듈을 import하지
않습니다. 실제 provider와 실행 의존성은 후속 기능 구현 때 이 서버 안에 추가합니다.
