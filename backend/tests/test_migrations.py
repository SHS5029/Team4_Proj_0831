from pathlib import Path

from backend.app.infrastructure.migrations import MIGRATIONS_DIR


def test_default_migration_path_is_owned_by_backend() -> None:
    backend_root = Path(__file__).resolve().parents[1]

    assert MIGRATIONS_DIR == backend_root / "migrations"
    assert [path.name for path in MIGRATIONS_DIR.glob("*.sql")] == [
        "001_create_oauth_schema.sql",
        "002_create_scaffold_game_schema.sql",
    ]
