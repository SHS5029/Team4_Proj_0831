"""외부 의존성 상태를 노출하지 않는 Backend 생존 확인 endpoint."""

from fastapi import APIRouter

from backend.app.schemas.common_schema import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """프로세스가 HTTP 요청을 처리할 수 있음을 고정 응답으로 알린다."""

    return HealthResponse()
