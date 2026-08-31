"""Small migration runner for environments without a local ``psql`` binary."""

from __future__ import annotations

from pathlib import Path

import psycopg

from backend.app.core.config import Settings, get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def run_migrations(settings: Settings, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply ordered, idempotent SQL migrations and return their filenames."""

    migration_paths = sorted(migrations_dir.glob("*.sql"))
    if not migration_paths:
        raise RuntimeError(f"No SQL migrations found in {migrations_dir}")

    applied: list[str] = []
    with psycopg.connect(settings.effective_database_url, autocommit=True) as connection:
        for migration_path in migration_paths:
            sql = migration_path.read_text(encoding="utf-8")
            with connection.cursor() as cursor:
                cursor.execute(sql)
            applied.append(migration_path.name)
    return applied


def main() -> None:
    settings = get_settings()
    applied = run_migrations(settings)
    # Deliberately print no host, username, or connection URL.
    print(f"Applied {len(applied)} migration(s) to {settings.database_name}: {', '.join(applied)}")


if __name__ == "__main__":
    main()

