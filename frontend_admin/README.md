# 관리자 Frontend

일반 사용자 앱과 분리된 read-only Streamlit 관리자 앱입니다. Backend의
`GET /api/v1/admin/metrics` 200 응답을 받은 경우에만 dashboard와 목록을 표시합니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 entrypoint가 저장소 루트를 Python import 경로에 등록하므로, 위 명령을
저장소 루트에서 실행하면 `frontend_admin` 패키지 절대 import가 정상적으로
해석됩니다.

## 관리자 진입과 식별자 복구

1. 운영자가 Backend의 `ADMIN_USER_IDS`에 미리 등록한 UUID v4를 준비합니다.
2. `http://127.0.0.1:8502`의 `관리자 식별자`에서 UUID를 입력하고 `입력값 확인`을 누릅니다.
3. 확인 창에서 `확인하고 적용`을 누르면 관리자 origin의 local storage
   `ai_mafia_admin_user_id_v1`에 저장합니다. 저장 응답 확인 후 해당 UUID를
   `X-User-Id`로 보내 Backend 권한을 다시 확인합니다.

UUID는 비밀번호나 강한 인증 수단이 아닙니다. 이 앱은 UUID를 자동 생성하거나
Backend allowlist에 자동 등록하지 않으며 loopback 또는 사설망에서만 사용합니다.
사용자 앱 `:8501`의 식별자는 별도 origin이므로 공유되지 않습니다.

접근이 거부되어도 같은 입력 경로에서 UUID를 교체할 수 있습니다. 잘못된 입력은
기존 저장값을 바꾸지 않습니다. 저장소가 차단되면 데이터 표시를 멈추며 브라우저
설정을 확인하고 `식별자 다시 확인`으로 재시도할 수 있습니다. Backend 연결 오류는
식별자를 삭제하지 않으며 `접근 다시 확인`으로 재시도합니다.

## 게임 조회

- `게임 상태`와 `게임 단계`는 Backend가 지원하는 `status`·`phase` 필터이며,
  선택한 조건의 최근 20개 게임을 표시합니다.
- `상세 보기` 또는 `게임 ID로 상세 열기`는 관리자 상세 API를 호출합니다.
  `game_id`는 목록 검색 필터로 보내지 않습니다.
- 선택한 상세는 주소의 `?game_id=<UUID>`에 보존되어 새로고침해도 복원됩니다.
  UUID 교체 확인 또는 `상세 닫기`는 상세 선택을 지웁니다.
- 주소에는 관리자 UUID를 넣지 않으며 상세 진입도 Backend 권한 확인을 거칩니다.

## focused 검증

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 frontend_admin/.venv/bin/python -m pytest \
  -c pyproject.toml frontend_admin/tests/test_f8.py -q
```

fake HTTP, Streamlit AppTest, Node.js 저장소 mock으로 UUID 입력·저장 응답·접근 거부,
목록 필터, 상세 주소 복원과 비공개 필드 차단을 검증합니다. 실제 Backend·DB·유료
API에는 연결하지 않습니다. Node.js가 없으면 JS bridge 검증 한 건은 건너뜁니다.

## 팀 전달 사항

- Backend는 `X-User-Id`가 `ADMIN_USER_IDS` allowlist에 없거나 allowlist가 비어 있으면
  `403 ADMIN_ACCESS_DENIED`를 반환해야 합니다.
- 진행 중 게임 상세에는 role, 개인 사실, 개별 행동·투표, seed와 Agent private context를
  반환하지 않습니다. Front는 해당 field를 `***`로 마스킹하지 않고 거부합니다.
- 관리자 앱은 PostgreSQL·Redis·MCP에 직접 연결하지 않으며 모든 기능은 read-only입니다.
