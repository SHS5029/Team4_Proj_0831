"""MCP package 테스트가 동일한 asyncio 실행 경계를 사용하도록 고정한다.

실제 네트워크나 외부 Backend를 사용하지 않고 ASGI transport와 fake Engine만으로
인증·session 계약을 재현하기 위한 공통 pytest 설정이다.
"""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """trio 설치 여부에 흔들리지 않도록 package 테스트 backend를 asyncio로 고정한다."""

    return "asyncio"
