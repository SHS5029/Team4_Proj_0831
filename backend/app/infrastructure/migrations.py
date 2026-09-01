"""로컬 ``psql`` 실행 파일 없이 SQL 마이그레이션을 적용하는 실행기.

마이그레이션 파일 자체가 ``BEGIN``/``COMMIT``으로 원자성을 정의하므로 연결은
autocommit 모드로 연다. 실행기는 파일 이름 순서와 대상 DB만 책임지고, 실제
스키마 변경의 트랜잭션 경계와 재실행 안전성은 각 SQL 파일이 명시한다.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from backend.app.core.config import Settings, get_settings

# 호출 위치와 무관하게 Backend가 소유하는 migrations 디렉터리를 찾는다.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_ROOT / "migrations"


def run_migrations(settings: Settings, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """이름순으로 SQL 마이그레이션을 실행하고 완료된 파일명을 반환한다.

    ``settings.effective_database_url``만 사용하므로 ``DATABASE_URL`` 원본의 DB
    경로가 아니라 검증된 프로젝트 DB에 적용된다. 각 파일은 하나의 ``execute``
    호출로 전달되며, 실패하면 예외를 그대로 올려 해당 파일명을 완료 목록에
    넣지 않는다. SQL은 ``IF NOT EXISTS`` 등으로 재실행 가능하게 작성돼 있다.
    """

    # 숫자 접두사를 사용한 파일명이 곧 실행 순서가 되도록 정렬한다.
    migration_paths = sorted(migrations_dir.glob("*.sql"))
    if not migration_paths:
        raise RuntimeError(f"No SQL migrations found in {migrations_dir}")

    applied: list[str] = []
    # SQL 파일 내부의 BEGIN/COMMIT이 실제 최상위 트랜잭션이 되도록 드라이버의
    # 암시적 트랜잭션을 만들지 않는다.
    with psycopg.connect(settings.effective_database_url, autocommit=True) as connection:
        for migration_path in migration_paths:
            # 마이그레이션은 저장소에서 UTF-8 텍스트로 관리한다. SQL 내용이나
            # 연결 URL은 출력하지 않아 스키마 세부와 자격 증명 노출을 줄인다.
            sql = migration_path.read_text(encoding="utf-8")
            with connection.cursor() as cursor:
                cursor.execute(sql)
            # execute가 예외 없이 끝난 파일만 호출자에게 완료로 보고한다.
            applied.append(migration_path.name)
    return applied


def main() -> None:
    """환경 설정으로 전체 마이그레이션을 실행하는 CLI 진입점."""

    settings = get_settings()
    applied = run_migrations(settings)
    # 운영 로그에는 개수, 파일명, 비밀이 아닌 DB 이름만 남긴다. 호스트,
    # 사용자명, 비밀번호 또는 전체 연결 URL은 의도적으로 출력하지 않는다.
    print(f"Applied {len(applied)} migration(s) to {settings.database_name}: {', '.join(applied)}")


if __name__ == "__main__":
    main()
