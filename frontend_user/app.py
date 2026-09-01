"""사용자 로그인 페이지를 호출하는 얇은 Streamlit 실행 진입점."""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit이 파일 경로로 실행할 때도 저장소 루트 패키지를 찾도록 한 번만 추가한다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend_user.app_pages.login_page import main  # noqa: E402, I001


if __name__ == "__main__":
    main()
