"""루트 ``.env``를 읽어 검증된 애플리케이션 설정을 만드는 모듈.

``DATABASE_URL``은 사용자명, 비밀번호, 호스트, 포트와 연결 옵션의 원본이다.
다만 URL에 들어 있던 데이터베이스 경로는 그대로 신뢰하지 않고 프로젝트의
``database_name``으로 교체한다. 기본값이 ``Team4_Proj``이므로 공유 개발용
URL이 다른 데이터베이스를 가리키더라도 이 프로젝트가 실수로 그 DB를 쓰지
않는다. URL을 문자열 치환하지 않고 표준 URL 파서로 분해·재조립해 인코딩된
자격 증명을 손상시키거나 비밀값을 디코딩하는 일을 피한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

# 이 파일에서 세 단계 위가 저장소 루트다. 기본 .env와 migrations 위치를
# 호출한 현재 작업 디렉터리와 무관하게 안정적으로 찾기 위해 절대 경로를 쓴다.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# SQLite/MySQL URL이나 오타 난 스킴이 psycopg까지 전달되지 않도록 허용 목록을
# 명시한다. 두 값은 PostgreSQL에서 통용되는 URI 스킴 표기다.
POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})


@dataclass(frozen=True, slots=True)
class Settings:
    """인증 영속성 계층이 사용하는 검증 완료 설정.

    ``database_url``은 비밀번호를 포함할 수 있으므로 데이터 클래스 ``repr``에서
    제외한다. ``database_name``은 원본 URL의 경로 대신 사용할 대상 DB이며,
    별도 설정이 없으면 반드시 ``Team4_Proj``를 사용한다.
    """

    database_url: str = field(repr=False)
    database_name: str = "Team4_Proj"
    app_env: str = "development"

    def __post_init__(self) -> None:
        """불변 설정이 만들어지는 시점에 URL과 DB 이름을 한 번 검증한다.

        잘못된 설정을 연결 시점까지 미루지 않아 애플리케이션 시작 단계에서
        원인을 확인할 수 있다. 검증 오류에는 URL 원문을 포함하지 않으므로
        사용자명이나 비밀번호가 로그로 유출되지 않는다.
        """

        raw_url = self.database_url.strip()
        if not raw_url:
            raise ValueError("DATABASE_URL must contain a PostgreSQL connection URL")

        try:
            # ``parsed.port`` 접근 자체가 범위를 벗어난 포트 등에 ValueError를
            # 낼 수 있어 URL 분해와 함께 같은 안전한 오류로 변환한다.
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("DATABASE_URL is not a valid PostgreSQL URL") from exc

        if parsed.scheme.lower() not in POSTGRES_SCHEMES:
            raise ValueError("DATABASE_URL must use the postgres or postgresql scheme")
        if not parsed.hostname:
            raise ValueError("DATABASE_URL must include a PostgreSQL host")
        if port is not None and not 1 <= port <= 65_535:
            raise ValueError("DATABASE_URL contains an invalid PostgreSQL port")
        if not self.database_name.strip():
            raise ValueError("DATABASE_NAME must not be empty")
        if any(character in self.database_name for character in ("/", "\x00")):
            raise ValueError("DATABASE_NAME contains an invalid character")

        # frozen 데이터 클래스이므로 검증한 정규화 값은 object.__setattr__로
        # 한 번만 저장한다. 이후 요청 처리 중 설정이 바뀌지 않는다.
        object.__setattr__(self, "database_url", raw_url)
        object.__setattr__(self, "database_name", self.database_name.strip())

    @property
    def effective_database_url(self) -> str:
        """연결 정보는 유지하고 DB 경로만 대상 ``database_name``으로 바꾼다.

        ``urlsplit``과 ``urlunsplit``을 사용하므로 인코딩된 사용자명/비밀번호,
        호스트, 포트, 쿼리 연결 옵션과 fragment를 원형대로 보존한다. DB 이름은
        URL path에 안전하게 들어가도록 percent-encoding한다. 자격 증명을 직접
        디코딩하거나 URL 전체를 출력하지 않는다.
        """

        parsed = urlsplit(self.database_url)
        # 원본 URL이 /agent_db처럼 다른 경로를 갖더라도 폐기하고, 검증된
        # 프로젝트 DB 이름으로 단일 path를 새로 만든다.
        database_path = f"/{quote(self.database_name, safe='')}"
        return urlunsplit(
            (parsed.scheme, parsed.netloc, database_path, parsed.query, parsed.fragment)
        )

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Settings:
        """환경 변수 우선순위를 지키면서 ``.env``에서 설정을 불러온다.

        운영 환경이 주입한 값을 ``.env``가 덮어쓰지 않도록 ``override=False``를
        사용한다. 파일을 따로 지정하지 않으면 저장소 루트의 ``.env``를 읽고,
        ``DATABASE_NAME``이 없을 때 ``Team4_Proj``를 기본 대상으로 강제한다.
        """

        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            database_name=os.getenv("DATABASE_NAME", "Team4_Proj"),
            app_env=os.getenv("APP_ENV", "development"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 동안 재사용할 하나의 불변 설정 인스턴스를 반환한다.

    요청마다 ``.env``를 다시 읽어 중간에 연결 대상이 달라지는 일을 막고,
    모든 저장소 인스턴스가 동일한 ``Team4_Proj`` 대상 URL을 사용하게 한다.
    """

    return Settings.from_env()
