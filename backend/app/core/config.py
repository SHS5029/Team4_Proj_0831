"""루트 ``.env``를 읽어 검증된 애플리케이션 설정을 만드는 모듈.

``TEAM_DATABASE_URL``은 실제 원격 PostgreSQL 연결의 우선 설정이며,
``DATABASE_URL``은 로컬 테스트용 fallback이다. 원격 URL이 선택되면 URL에 포함된
database path를 그대로 사용하고, 로컬 fallback일 때만 ``database_name``으로
경로를 교체한다. URL을 문자열 치환하지 않고 표준 URL 파서로 분해·재조립해
인코딩된 자격 증명을 손상시키거나 비밀값을 디코딩하는 일을 피한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

# 이 파일에서 세 단계 위가 저장소 루트다. 기본 .env 위치를 호출한 현재 작업
# 디렉터리와 무관하게 안정적으로 찾기 위해 절대 경로를 쓴다.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# SQLite/MySQL URL이나 오타 난 스킴이 psycopg까지 전달되지 않도록 허용 목록을
# 명시한다. 두 값은 PostgreSQL에서 통용되는 URI 스킴 표기다.
POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})


@dataclass(frozen=True, slots=True)
class Settings:
    """인증 영속성 계층이 사용하는 검증 완료 설정.

    ``database_url``은 비밀번호를 포함할 수 있으므로 데이터 클래스 ``repr``에서
    제외한다. ``preserve_database_path``가 거짓이면 ``database_name``을 URL 경로로
    사용하고, 원격 ``TEAM_DATABASE_URL``에서 읽은 설정이면 원격 URL의 경로를
    보존한다.
    """

    database_url: str = field(repr=False)
    database_name: str = "Team4_Proj"
    preserve_database_path: bool = False
    app_env: str = "development"
    redis_url: str = field(default="redis://127.0.0.1:6379/0", repr=False)
    mcp_server_url: str = "http://127.0.0.1:8100"
    cors_allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:8501",
        "http://127.0.0.1:8502",
        "http://localhost:8501",
        "http://localhost:8502",
    )
    # 게임 seed와 snapshot 암호화 키는 .env에 직접 넣지 않는다. .env에는
    # 저장소 밖의 keyring 파일 위치와 현재 사용할 key ID만 기록한다.
    game_state_keyring_file: str = field(default="", repr=False)
    game_state_active_key_id: str = ""
    llm_provider: str = "dummy"
    # 관리자 API는 이 목록에 있는 UUID v4만 읽기 권한을 갖는다. 형식 검증은
    # AdminService가 fail-closed로 수행하므로 잘못된 설정이 일부 관리자만
    # 남기는 상태로 시작되지 않는다.
    admin_user_ids: tuple[str, ...] = ()
    local_llm_base_url: str = "http://127.0.0.1:1234/v1"
    local_llm_model: str = "local-model"
    openai_api_key: str = field(default="", repr=False)
    openai_model: str = "gpt-4.1-mini"
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: int = 30
    llm_max_output_tokens: int = 400
    game_max_total_tokens: int = 60_000
    llm_input_cost_per_million_usd: float = 0.0
    llm_output_cost_per_million_usd: float = 0.0

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
        if not self.redis_url.strip():
            raise ValueError("REDIS_URL must not be empty")
        if not self.mcp_server_url.strip():
            raise ValueError("MCP_SERVER_URL must not be empty")
        normalized_origins = tuple(origin.strip().rstrip("/") for origin in self.cors_allowed_origins if origin.strip())
        if not normalized_origins or any(
            urlsplit(origin).scheme not in {"http", "https"} or not urlsplit(origin).netloc
            for origin in normalized_origins
        ):
            raise ValueError("CORS_ALLOWED_ORIGINS must contain absolute origins")
        keyring_file = self.game_state_keyring_file.strip()
        active_key_id = self.game_state_active_key_id.strip()
        # 아직 DB 게임 저장 기능을 사용하지 않는 개발 환경은 두 설정을 모두
        # 비워 둘 수 있다. 단, 하나만 설정하면 암호화가 불완전하므로 시작부터
        # 명확하게 거부한다.
        if bool(keyring_file) != bool(active_key_id):
            raise ValueError(
                "GAME_STATE_KEYRING_FILE and GAME_STATE_ACTIVE_KEY_ID must be set together"
            )
        if len(active_key_id) > 64:
            raise ValueError("GAME_STATE_ACTIVE_KEY_ID must be 64 characters or fewer")
        if self.llm_provider.strip().lower() not in {"dummy", "local", "openai", "gemini"}:
            raise ValueError("LLM_PROVIDER is not supported")
        if not self.local_llm_base_url.strip() or not self.local_llm_model.strip():
            raise ValueError("LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL must not be empty")
        if self.llm_provider == "openai" and (
            not self.openai_api_key.strip() or not self.openai_model.strip()
        ):
            raise ValueError("OPENAI_API_KEY and OPENAI_MODEL are required")
        if self.llm_provider == "gemini" and (
            not self.gemini_api_key.strip() or not self.gemini_model.strip()
        ):
            raise ValueError("GEMINI_API_KEY and GEMINI_MODEL are required")
        if not 1 <= self.llm_timeout_seconds <= 300:
            raise ValueError("LLM_TIMEOUT_SECONDS must be between 1 and 300")
        if not 1 <= self.llm_max_output_tokens <= 16_384:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must be between 1 and 16384")
        if not 1 <= self.game_max_total_tokens <= 1_000_000:
            raise ValueError("GAME_MAX_TOTAL_TOKENS must be between 1 and 1000000")
        if self.llm_input_cost_per_million_usd < 0 or self.llm_output_cost_per_million_usd < 0:
            raise ValueError("LLM token costs must not be negative")

        # frozen 데이터 클래스이므로 검증한 정규화 값은 object.__setattr__로
        # 한 번만 저장한다. 이후 요청 처리 중 설정이 바뀌지 않는다.
        object.__setattr__(self, "database_url", raw_url)
        object.__setattr__(self, "database_name", self.database_name.strip())
        object.__setattr__(self, "redis_url", self.redis_url.strip())
        object.__setattr__(self, "mcp_server_url", self.mcp_server_url.strip().rstrip("/"))
        object.__setattr__(self, "cors_allowed_origins", normalized_origins)
        object.__setattr__(self, "game_state_keyring_file", keyring_file)
        object.__setattr__(self, "game_state_active_key_id", active_key_id)
        object.__setattr__(self, "llm_provider", self.llm_provider.strip().lower())
        object.__setattr__(self, "local_llm_base_url", self.local_llm_base_url.strip().rstrip("/"))
        object.__setattr__(self, "local_llm_model", self.local_llm_model.strip())
        object.__setattr__(self, "openai_api_key", self.openai_api_key.strip())
        object.__setattr__(self, "openai_model", self.openai_model.strip())
        object.__setattr__(self, "gemini_api_key", self.gemini_api_key.strip())
        object.__setattr__(self, "gemini_model", self.gemini_model.strip())

    @property
    def effective_database_url(self) -> str:
        """연결 정보와 필요 시 원격 DB 경로를 보존한 유효 URL을 반환한다.

        ``urlsplit``과 ``urlunsplit``을 사용하므로 인코딩된 사용자명/비밀번호,
        호스트, 포트, 쿼리 연결 옵션과 fragment를 원형대로 보존한다. DB 이름은
        URL path에 안전하게 들어가도록 percent-encoding한다. 자격 증명을 직접
        디코딩하거나 URL 전체를 출력하지 않는다.
        """

        parsed = urlsplit(self.database_url)
        if self.preserve_database_path:
            return self.database_url
        # 로컬 fallback URL이 다른 경로를 갖더라도 검증된 프로젝트 DB 이름으로
        # 단일 path를 새로 만들어 테스트 대상이 흔들리지 않게 한다.
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
        team_database_url = os.getenv("TEAM_DATABASE_URL", "").strip()
        database_url = team_database_url or os.getenv("DATABASE_URL", "")
        if team_database_url:
            # 원격 DSN의 database path는 운영 대상의 일부이므로 DATABASE_NAME이나
            # 로컬 기본값으로 덮어쓰지 않는다. path가 없으면 PostgreSQL이 기본 DB를
            # 선택하게 두지 않고 설정 오류로 즉시 거부한다.
            parsed_team_url = urlsplit(team_database_url)
            remote_database_name = parsed_team_url.path.lstrip("/")
            if not remote_database_name:
                raise ValueError("TEAM_DATABASE_URL must include a database path")
            configured_database_name = remote_database_name
        else:
            configured_database_name = os.getenv("DATABASE_NAME", "Team4_Proj")
        return cls(
            database_url=database_url,
            database_name=configured_database_name,
            preserve_database_path=bool(team_database_url),
            app_env=os.getenv("APP_ENV", "development"),
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            mcp_server_url=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8100"),
            cors_allowed_origins=tuple(
                item.strip()
                for item in os.getenv(
                    "CORS_ALLOWED_ORIGINS",
                    "http://127.0.0.1:8501,http://127.0.0.1:8502,http://localhost:8501,http://localhost:8502",
                ).split(",")
            ),
            game_state_keyring_file=os.getenv("GAME_STATE_KEYRING_FILE", ""),
            game_state_active_key_id=os.getenv("GAME_STATE_ACTIVE_KEY_ID", ""),
            llm_provider=os.getenv("LLM_PROVIDER", "dummy"),
            admin_user_ids=tuple(
                item.strip() for item in os.getenv("ADMIN_USER_IDS", "").split(",")
            ),
            local_llm_base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1"),
            local_llm_model=os.getenv("LOCAL_LLM_MODEL", "local-model"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            llm_timeout_seconds=_read_positive_int(
                os.getenv("LLM_TIMEOUT_SECONDS", "30"), name="LLM_TIMEOUT_SECONDS"
            ),
            llm_max_output_tokens=_read_positive_int(
                os.getenv("LLM_MAX_OUTPUT_TOKENS", "400"), name="LLM_MAX_OUTPUT_TOKENS"
            ),
            game_max_total_tokens=_read_positive_int(
                os.getenv("GAME_MAX_TOTAL_TOKENS", "60000"), name="GAME_MAX_TOTAL_TOKENS"
            ),
            llm_input_cost_per_million_usd=_read_nonnegative_float(
                os.getenv("LLM_INPUT_COST_PER_MILLION_USD", "0"),
                name="LLM_INPUT_COST_PER_MILLION_USD",
            ),
            llm_output_cost_per_million_usd=_read_nonnegative_float(
                os.getenv("LLM_OUTPUT_COST_PER_MILLION_USD", "0"),
                name="LLM_OUTPUT_COST_PER_MILLION_USD",
            ),
        )


def _read_positive_int(value: str, *, name: str) -> int:
    """환경 변수의 양의 정수를 원문 노출 없이 검증해 반환한다."""

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _read_nonnegative_float(value: str, *, name: str) -> float:
    """환경 변수의 음이 아닌 실수를 비밀값 없이 검증해 반환한다."""

    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed < 0:
        raise ValueError(f"{name} must not be negative")
    return parsed


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 동안 재사용할 하나의 불변 설정 인스턴스를 반환한다.

    요청마다 ``.env``를 다시 읽어 중간에 연결 대상이 달라지는 일을 막고,
    모든 저장소 인스턴스가 동일한 ``Team4_Proj`` 대상 URL을 사용하게 한다.
    """

    return Settings.from_env()
