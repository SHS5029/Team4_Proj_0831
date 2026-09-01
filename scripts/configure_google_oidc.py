"""Google 웹 클라이언트 JSON으로 Streamlit OIDC 비밀 설정을 생성한다.

Google Cloud Console에서 내려받은 JSON에는 실제 ``client_secret``이 들어 있으므로
일반 설정 파일처럼 화면이나 로그에 출력해서는 안 된다. 이 모듈은 필요한 값만 메모리에서
읽고, 강한 쿠키 서명 키를 새로 만든 뒤, 결과 파일을 소유자만 읽을 수 있는 권한(0600)으로
원자적으로 교체한다. 중간 파일이 남거나 일부만 기록된 설정을 앱이 읽는 상황도 방지한다.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
DEFAULT_REDIRECT_URI = "http://localhost:8501/oauth2callback"
DEFAULT_OUTPUT_PATH = Path("frontend_user/.streamlit/secrets.toml")


@dataclass(frozen=True, slots=True)
class WebClientConfig:
    """Streamlit OIDC 설정에 필요한 Google 웹 클라이언트 값만 보관한다.

    ``client_secret``은 객체를 디버깅하거나 예외 로그에 출력했을 때 노출되지 않도록
    dataclass의 ``repr``에서 제외한다. 이 객체에는 redirect URI 목록이나 프로젝트 메타데이터
    등 런타임 로그인에 불필요한 원본 JSON 필드는 담지 않는다.
    """

    client_id: str
    client_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        # 공백 문자열도 누락된 자격 증명으로 처리하여 불완전한 설정 파일 생성을 막는다.
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("Google web client credentials are incomplete")


def load_web_client(path: Path) -> WebClientConfig:
    """Google JSON을 검증하고 Streamlit에 필요한 두 자격 증명만 반환한다.

    데스크톱 앱용 ``installed`` 클라이언트와 웹 클라이언트는 redirect 처리 방식이 다르다.
    Streamlit 서버 콜백에는 반드시 ``web`` 유형이 필요하므로 다른 유형은 조기에 거부한다.
    """

    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Google web client JSON could not be read") from exc

    # JSON 최상위가 객체인지 확인한 후에만 web 항목을 조회해 타입 혼동을 방지한다.
    web = payload.get("web") if isinstance(payload, dict) else None
    if not isinstance(web, dict):
        raise ValueError("Google OAuth client JSON must contain a web client")

    client_id = web.get("client_id")
    client_secret = web.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise ValueError("Google web client credentials are incomplete")

    return WebClientConfig(client_id=client_id.strip(), client_secret=client_secret.strip())


def _validate_redirect_uri(redirect_uri: str) -> str:
    """Streamlit 콜백으로 안전하게 사용할 수 있는 정확한 URI만 허용한다.

    운영 주소는 HTTPS만 허용하며 로컬 개발 편의를 위해 ``localhost``에 한해서만 HTTP를
    허용한다. 사용자 정보, 쿼리, fragment를 금지해 자격 증명이 예상 밖의 대상으로 전달될
    여지를 줄이고, Streamlit이 사용하는 고정 콜백 경로도 정확히 검사한다.
    """

    candidate = redirect_uri.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("OIDC redirect URI is invalid") from exc

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("OIDC redirect URI must contain a safe host")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("OIDC redirect URI contains an invalid port")
    if parsed.path != "/oauth2callback" or parsed.query or parsed.fragment:
        raise ValueError("OIDC redirect URI must end with /oauth2callback")
    if parsed.scheme == "https":
        return candidate
    if parsed.scheme == "http" and parsed.hostname == "localhost":
        return candidate
    raise ValueError("OIDC redirect URI must use HTTPS, except on localhost")


def _toml_string(value: str) -> str:
    # JSON 기본 문자열의 이스케이프 규칙은 TOML 기본 문자열과 호환되므로, 따옴표나
    # 제어 문자가 포함되더라도 직접 문자열을 이어 붙이는 것보다 안전하게 직렬화할 수 있다.
    return json.dumps(value, ensure_ascii=False)


def render_streamlit_secrets(
    config: WebClientConfig,
    *,
    redirect_uri: str,
) -> str:
    """Streamlit 네이티브 OIDC가 요구하는 최소 TOML 설정을 메모리에서 생성한다.

    쿠키 서명 키는 OAuth 클라이언트 secret과 목적이 다르므로 재사용하지 않는다. 매번
    암호학적으로 안전한 난수 32바이트를 생성해 세션 쿠키 위조 가능성을 낮춘다.
    """

    validated_redirect_uri = _validate_redirect_uri(redirect_uri)
    cookie_secret = secrets.token_hex(32)
    return "\n".join(
        (
            "[auth]",
            f"redirect_uri = {_toml_string(validated_redirect_uri)}",
            f"cookie_secret = {_toml_string(cookie_secret)}",
            "",
            "[auth.google]",
            f"client_id = {_toml_string(config.client_id)}",
            f"client_secret = {_toml_string(config.client_secret)}",
            f"server_metadata_url = {_toml_string(GOOGLE_DISCOVERY_URL)}",
            "",
        )
    )


def write_streamlit_secrets(
    source_path: Path,
    output_path: Path,
    *,
    redirect_uri: str,
    overwrite: bool = False,
) -> None:
    """자격 증명을 출력하지 않고 소유자 전용 secrets 파일을 원자적으로 만든다.

    기본 동작은 기존 파일을 덮어쓰지 않는다. 운영자가 명시적으로 ``overwrite``를 선택한
    경우에만 교체하며, 같은 디렉터리에 임시 파일을 만든 뒤 ``os.replace``를 사용해 파일
    시스템 관점에서 한 번에 전환한다.
    """

    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {output_path}")

    config = load_web_client(source_path)
    rendered = render_streamlit_secrets(config, redirect_uri=redirect_uri)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        # 대상과 같은 디렉터리를 사용해야 서로 다른 파일 시스템 사이의 이동 문제 없이
        # os.replace가 원자적으로 동작한다. 임시 파일명에는 실제 비밀값을 포함하지 않는다.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".secrets-",
            suffix=".toml.tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(rendered)
            temporary_file.flush()
            # Python 버퍼뿐 아니라 운영체제 버퍼까지 기록해 교체 직후 내용이 유실될 위험을 줄인다.
            os.fsync(temporary_file.fileno())
        # 교체 전후 모두 0600을 적용한다. 프로세스의 umask 설정에 의존하지 않기 위함이다.
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, output_path)
        os.chmod(output_path, 0o600)
    finally:
        # 예외가 발생해도 민감정보가 담긴 임시 파일이 디스크에 남지 않도록 정리한다.
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _parse_args() -> argparse.Namespace:
    """CLI 입력을 파싱한다. 비밀값 자체는 인자로 받지 않고 JSON 경로만 받는다."""

    parser = argparse.ArgumentParser(
        description="Configure Streamlit Google OIDC without printing credentials."
    )
    parser.add_argument("--client-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    """CLI 진입점: 안전한 설정 파일을 생성하고 민감하지 않은 대상 경로만 알린다."""

    args = _parse_args()
    write_streamlit_secrets(
        args.client_json,
        args.output,
        redirect_uri=args.redirect_uri,
        overwrite=args.overwrite,
    )
    # 성공 메시지에는 client id, client secret, 쿠키 secret을 절대 포함하지 않는다.
    print(f"Configured Streamlit Google OIDC at {args.output}")


if __name__ == "__main__":
    main()
