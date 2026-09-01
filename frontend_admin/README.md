# 관리자 Frontend

일반 사용자 앱과 분리된 Streamlit 실행 단위입니다. 이번 구조 개편에서는 관리자
인증·권한·업무 API를 구현하지 않으며 준비 상태만 표시합니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 기능은 Backend가 검증하는 별도의 인증·권한 계약이 추가된 뒤 구현해야 하며,
사용자 Frontend의 내부 identity 서명을 관리자 권한 증명으로 사용하지 않습니다.
