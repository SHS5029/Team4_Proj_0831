# 관리자 Frontend

일반 사용자 앱과 분리된 read-only Streamlit 관리자 앱입니다. 관리자 UUID는
`ai_mafia_admin_user_id_v1` key에 저장하고, Backend의 `GET /api/v1/admin/metrics`
200 응답을 받은 경우에만 dashboard와 목록을 표시합니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 entrypoint가 저장소 루트를 Python import 경로에 등록하므로, 위 명령을
저장소 루트에서 실행하면 `frontend_admin` 패키지 절대 import가 정상적으로
해석됩니다.

관리자 기능은 Backend가 검증하는 별도의 인증·권한 계약이 추가된 뒤 구현해야 하며,
사용자 Frontend의 내부 identity 서명을 관리자 권한 증명으로 사용하지 않습니다.
목표 MVP는 [화면 흐름도](../docs/개발상세플랜/AI_MAFIA_SCREEN_FLOW.md)의 UUID allowlist
기반 read-only 화면이며 loopback 또는 사설망에서만 활성화합니다.

## 팀 전달 사항

- Backend는 `X-User-Id`가 `ADMIN_USER_IDS` allowlist에 없거나 allowlist가 비어 있으면
  `403 ADMIN_ACCESS_DENIED`를 반환해야 합니다.
- 진행 중 게임 상세에는 role, 개인 사실, 개별 행동·투표, seed와 Agent private context를
  반환하지 않습니다. Front는 해당 field를 `***`로 마스킹하지 않고 거부합니다.
- 관리자 앱은 PostgreSQL·Redis·MCP에 직접 연결하지 않으며 모든 기능은 read-only입니다.
