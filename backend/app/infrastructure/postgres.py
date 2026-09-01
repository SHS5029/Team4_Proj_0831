"""검증된 Backend 설정으로 PostgreSQL 사용자 저장소를 조립한다."""

from backend.app.core.config import Settings
from backend.app.repositories.user_repository import PostgresUserRepository


def build_user_repository(settings: Settings) -> PostgresUserRepository:
    """원본 DB URL 대신 대상 DB가 강제된 URL로 저장소를 생성한다."""

    return PostgresUserRepository(settings.effective_database_url)
