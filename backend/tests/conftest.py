"""최신 AnyIO와 Starlette TestClient 사이의 이름 호환을 준비한다."""

import anyio.abc
from anyio.from_thread import BlockingPortal

# Starlette 1.6.0이 아직 예전 경로를 타입 별칭으로 참조한다.
# 경고를 무시하지 않고, AnyIO가 안내하는 정식 경로의 클래스를 같은 이름에
# 연결해 import 시점의 실제 호환 문제를 해결한다.
anyio.abc.BlockingPortal = BlockingPortal
