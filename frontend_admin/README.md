# 관리자 Frontend

일반 사용자 앱과 분리된 read-only Streamlit 관리자 앱입니다. 관리자 UUID는
`ai_mafia_admin_user_id_v1` key에 저장하고, Backend의 `GET /api/v1/admin/metrics`
200 응답을 받은 경우에만 dashboard와 목록을 표시합니다.

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

관리자 기능은 Backend가 검증하는 별도의 인증·권한 계약이 추가된 뒤 구현해야 하며,
사용자 Frontend의 내부 identity 서명을 관리자 권한 증명으로 사용하지 않습니다.
목표 MVP는 [화면 흐름도](../docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md)의 UUID allowlist
기반 read-only 화면이며 loopback 또는 사설망에서만 활성화합니다.

현재 관리자 센터는 다음 세 탭으로 구성됩니다.

- **운영 현황**: 전체 게임·종료 게임·종료율·시민/마피아 승률 KPI와 최근 게임 목록
- **통계 분석**: 시민/마피아 승리 횟수 그래프와 평균 라운드 등 운영 지표
- **피드백 · 로그**: 평균 피드백 점수와 향후 목록·감사 로그 연동 영역

직업별 승률, 피드백 목록, 감사 로그 목록은 현재 Backend 조회 계약에 포함되어 있지
않아 임의의 데이터를 표시하지 않고 준비 상태 안내를 표시합니다.

## 팀 전달 사항

- Backend는 `X-User-Id`가 `ADMIN_USER_IDS` allowlist에 없거나 allowlist가 비어 있으면
  `403 ADMIN_ACCESS_DENIED`를 반환해야 합니다.
- 진행 중 게임 상세에는 role, 개인 사실, 개별 행동·투표, seed와 Agent private context를
  반환하지 않습니다. Front는 해당 field를 `***`로 마스킹하지 않고 거부합니다.
- 관리자 앱은 PostgreSQL·Redis·MCP에 직접 연결하지 않으며 모든 기능은 read-only입니다.
