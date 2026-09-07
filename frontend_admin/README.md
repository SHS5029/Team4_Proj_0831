# 관리자 Frontend

일반 사용자 앱과 분리된 read-only Streamlit 관리자 앱입니다. 관리자 UUID는
`ai_mafia_admin_user_id_v1` key에 저장하고, Backend의 `GET /api/v1/admin/metrics`
200 응답을 받은 경우에만 운영 분석 화면을 표시합니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

Backend와 관리자 UUID allowlist 없이 화면만 확인하려면 PowerShell에서 개발용
가상 메타데이터 모드를 명시적으로 켭니다. 이 모드는 합성된 운영 지표와 게임
요약만 사용하며 기본값은 꺼져 있습니다.

```powershell
$env:ADMIN_DEMO_MODE = "true"
uv run streamlit run frontend_admin/app.py --server.port 8502
```

실제 운영 데이터를 확인할 때는 `$env:ADMIN_DEMO_MODE = "false"`로 바꾸고,
Backend의 `ADMIN_USER_IDS` allowlist 검증을 사용합니다.

관리자 entrypoint가 저장소 루트를 Python import 경로에 등록하므로, 위 명령을
저장소 루트에서 실행하면 `frontend_admin` 패키지 절대 import가 정상적으로
해석됩니다.

관리자 기능은 Backend의 UUID allowlist로 접근을 검증하며,
사용자 Frontend의 내부 identity 서명을 관리자 권한 증명으로 사용하지 않습니다.
목표 MVP는 [화면 흐름도](../docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md)의 UUID allowlist
기반 read-only 화면이며 loopback 또는 사설망에서만 활성화합니다.

현재 관리자 센터는 중복을 줄인 다음 네 화면으로 구성됩니다.

- **운영 분석**: 전체 사용자·누적 게임·완료율·시민/마피아 승률 KPI, 진영별 도넛, 에이전트 페르소나별 얇은 승률 그래프와 일별 추이
- **사용자 피드백**: 평균 피드백 점수, 종류/평점 필터와 사용자 의견
- **관리자 로그**: 조회 유형별 감사 기록과 요청·대상 식별자
- **운영 에이전트 계획**: RAG 운영 도우미의 자료 경계·검색 방식·근거 답변·도입 순서

네 화면은 같은 관리자용 짙은 퍼플 색상 체계를 사용하며, 차트·KPI·입력창의 글자
대비를 높여 운영자가 한눈에 읽을 수 있게 구성했습니다.

운영 에이전트 계획 탭은 참조 이미지의 계획을 화면으로 정리한 설계 검토용 페이지입니다.
RAG 인덱스·질문 API·외부 LLM 호출·자동 조치는 아직 구현하지 않으며, 상세 내용은
[관리자 운영 에이전트 계획서](../docs/개발상세플랜/AI_MAFIA_ADMIN_AGENT_PLAN.md)를 참고합니다.

실제 모드의 페르소나별 승률, 피드백 목록, 감사 로그와 운영 자료 질문은 API 명세 7.4~7.9와 연결됩니다.
metrics의 users_total·daily_games, persona-win-rates, feedback, audit-logs 응답을 사용합니다.
모든 초기 응답을 검증한 뒤 화면을 표시하며 조회·권한 오류 시 부분 데이터를 숨깁니다.
피드백과 감사 로그는 20건씩 이전·다음으로 조회하고 필터 변경 시 첫 페이지로 돌아갑니다.
감사 이벤트를 조회한 기록은 다음 새로고침 때 보입니다.

운영 에이전트 질문은 승인된 색인 청크를 읽고 답변·근거·신뢰도만 표시합니다. 색인을
사용하려면 DB 담당자가 `backend/migrations/005_create_admin_knowledge_schema.sql`을
실행한 뒤 저장소 루트에서 `backend/index_admin_knowledge.py`를 수동 실행해야 합니다.
연결된 DB에 `pgvector` 확장이 없으면 migration을 적용할 수 없으므로, 먼저 해당 확장을
설치할 수 있는 PostgreSQL 대상인지 확인해야 합니다.

데모 연결 설정에서 공개 테스트 키 `demo_ai_mafia_admin_v1`을 복사하거나 입력한 뒤
**연결 확인**을 누를 수 있습니다. 잘못된 키는 예시 화면을 숨기며 재입력하면 복구됩니다.
이 키는 로컬 가상 클라이언트용으로 실제 관리자 API에 전송되지 않고 인증 권한도 없습니다.
예시 데이터는 사용자 300명, 게임 1,200건(완료 900·저장 180·진행 96·실패 24), 페르소나 5종 집계,
30일 생성 추이, 피드백 240건, 감사 로그 180건입니다. 피드백 종류·평점과 감사 조회 유형을 필터링할 수 있습니다.
피드백과 감사 로그는 20건씩 페이지를 이동하며 마지막 기록까지 조회할 수 있습니다.
시민 540승·마피아 360승을 도넛 차트와 텍스트 비율로 표시합니다. 페르소나별 승률은
종료된 합성 게임의 사람 한 명을 제외한 AI 좌석과 진영 승리 여부로 계산합니다.
기록은 고정된 합성 데이터이며 실제 게임 엔진 시뮬레이션 결과가 아닙니다.
운영 분석 화면은 중복 KPI를 한 번만 표시하고, 진영별 도넛과 얇은 페르소나별 가로 막대,
상세 표를 한 화면에 배치합니다. 관리자 요약 화면에는 최근 게임 목록과 종료 게임 수를
표시하지 않습니다.
데모 모드는 새 서버나 포트를 열지 않으며 게임 예시를 실제 DB에 삽입하지 않습니다.
실제 DB에 합성 운영 자료를 넣어 확인해야 하는 경우에는 Backend 담당자가 검토한 뒤
`backend/seed_admin_demo_data.sql`을 수동 실행합니다. 이 seed는 기존 데이터를 보존하고
게임 30건·게임 참가자 210건·피드백 30건만 idempotent하게 추가하며, 실제 관리자 조회를
나타내는 감사 로그는 임의로 만들지 않습니다. 현재 작업에서는 해당 합성 데이터가 실제 DB에
반영되었고, 최종 집계는 users 89건·games 96건·game_players 680건·feedback 35건입니다.

## 팀 전달 사항

- Backend는 `X-User-Id`가 `ADMIN_USER_IDS` allowlist에 없거나 allowlist가 비어 있으면
  `403 ADMIN_ACCESS_DENIED`를 반환해야 합니다.
- 진행 중 게임 상세에는 role, 개인 사실, 개별 행동·투표, seed와 Agent private context를
  반환하지 않습니다. Front는 해당 field를 `***`로 마스킹하지 않고 거부합니다.
- 관리자 앱은 PostgreSQL·Redis·MCP에 직접 연결하지 않으며 모든 기능은 read-only입니다.
