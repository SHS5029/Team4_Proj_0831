"""Provision Streamlit OIDC secrets from a downloaded Google web client.

The command intentionally never prints client credentials.  It writes the
generated secrets file atomically with owner-only permissions.
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
DEFAULT_OUTPUT_PATH = Path("frontend/.streamlit/secrets.toml")


@dataclass(frozen=True, slots=True)
class WebClientConfig:
    client_id: str
    client_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("Google web client credentials are incomplete")


def load_web_client(path: Path) -> WebClientConfig:
    """Read only the two credentials required by Streamlit OIDC."""

    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Google web client JSON could not be read") from exc

    web = payload.get("web") if isinstance(payload, dict) else None
    if not isinstance(web, dict):
        raise ValueError("Google OAuth client JSON must contain a web client")

    client_id = web.get("client_id")
    client_secret = web.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise ValueError("Google web client credentials are incomplete")

    return WebClientConfig(client_id=client_id.strip(), client_secret=client_secret.strip())


def _validate_redirect_uri(redirect_uri: str) -> str:
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
    # JSON basic strings use escaping compatible with TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def render_streamlit_secrets(
    config: WebClientConfig,
    *,
    redirect_uri: str,
) -> str:
    """Render the minimal native Streamlit OIDC configuration."""

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
    """Create an owner-readable secrets file without exposing its contents."""

    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {output_path}")

    config = load_web_client(source_path)
    rendered = render_streamlit_secrets(config, redirect_uri=redirect_uri)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
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
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, output_path)
        os.chmod(output_path, 0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Streamlit Google OIDC without printing credentials."
    )
    parser.add_argument("--client-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    write_streamlit_secrets(
        args.client_json,
        args.output,
        redirect_uri=args.redirect_uri,
        overwrite=args.overwrite,
    )
    print(f"Configured Streamlit Google OIDC at {args.output}")


if __name__ == "__main__":
    main()
