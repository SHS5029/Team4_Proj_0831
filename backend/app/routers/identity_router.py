"""레거시 identity 모듈 자리만 유지하는 호환 파일.

B1 정본에서는 OIDC identity/provision API를 사용하지 않는다. 기존 import
경로가 갑자기 깨지지 않도록 파일은 남겨 두지만, 등록할 라우트는 없다.
사용자 식별은 공개 요청의 ``X-User-Id(UUID v4)``로 처리한다.
"""

from fastapi import APIRouter

router = APIRouter()
