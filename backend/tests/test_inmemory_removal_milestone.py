"""PostgreSQL 단일 runtime 경계를 검증한다."""

from pathlib import Path

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services.game.postgres_runtime import PostgresGameRuntime


def test_application_runtime_is_postgres() -> None:
    """앱은 항상 PostgreSQL runtime을 사용한다."""

    application = create_app(
        settings=Settings(
            database_url="postgresql://synthetic:test@127.0.0.1:5432/synthetic",
            redis_url="redis://127.0.0.1:6379/0",
        ),
        enable_background_worker=False,
    )

    assert isinstance(application.state.game_runtime, PostgresGameRuntime)

    main_source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    factory_source = (
        Path(__file__).parents[1] / "app" / "services" / "game" / "runtime_factory.py"
    ).read_text(encoding="utf-8")
    assert "canonical_repository" not in main_source
    assert "build_test_runtime" not in factory_source


def test_postgres_read_service_does_not_construct_inmemory_presenter() -> None:
    """PostgreSQL snapshot 조회가 InMemory service를 우회 presenter로 만들지 않는지 확인한다."""

    source = (
        Path(__file__).parents[1] / "app" / "services" / "game" / "game_read_service.py"
    ).read_text(encoding="utf-8")

    assert "CanonicalGameService" not in source
    assert "InMemoryGameRepository" not in source
    assert "return build_snapshot(record)" in source
