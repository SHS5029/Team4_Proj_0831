from __future__ import annotations

import json
import os
import stat
import tomllib
from pathlib import Path

import pytest

from scripts.configure_google_oidc import (
    GOOGLE_DISCOVERY_URL,
    WebClientConfig,
    load_web_client,
    render_streamlit_secrets,
    write_streamlit_secrets,
)

SYNTHETIC_CREDENTIAL = "synthetic-client-secret"


def _write_client_json(path: Path, *, client_type: str = "web") -> None:
    path.write_text(
        json.dumps(
            {
                client_type: {
                    "client_id": "synthetic-client.apps.googleusercontent.com",
                    "client_secret": SYNTHETIC_CREDENTIAL,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["https://example.test/oauth2callback"],
                }
            }
        ),
        encoding="utf-8",
    )


def test_load_web_client_requires_a_complete_web_client(tmp_path: Path) -> None:
    client_path = tmp_path / "client.json"
    _write_client_json(client_path)

    config = load_web_client(client_path)

    assert config.client_id.endswith(".apps.googleusercontent.com")
    assert config.client_secret == SYNTHETIC_CREDENTIAL
    assert SYNTHETIC_CREDENTIAL not in repr(config)


@pytest.mark.parametrize(
    "payload",
    [
        {"installed": {"client_id": "id", "client_secret": "secret"}},
        {"web": {"client_id": "", "client_secret": "secret"}},
        {"web": {"client_id": "id", "client_secret": ""}},
    ],
)
def test_load_web_client_rejects_wrong_type_or_missing_credentials(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="(?i)web|client"):
        load_web_client(client_path)


def test_rendered_streamlit_secrets_contains_secure_oidc_configuration() -> None:
    config = WebClientConfig(
        client_id="synthetic-client.apps.googleusercontent.com",
        client_secret=SYNTHETIC_CREDENTIAL,
    )

    rendered = render_streamlit_secrets(
        config,
        redirect_uri="http://localhost:8501/oauth2callback",
    )
    parsed = tomllib.loads(rendered)

    assert parsed["auth"]["redirect_uri"] == "http://localhost:8501/oauth2callback"
    assert len(parsed["auth"]["cookie_secret"]) >= 64
    assert parsed["auth"]["google"]["client_id"] == config.client_id
    assert parsed["auth"]["google"]["client_secret"] == config.client_secret
    assert parsed["auth"]["google"]["server_metadata_url"] == GOOGLE_DISCOVERY_URL


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://example.com/oauth2callback",
        "https://example.com/not-the-callback",
        "https://user:password@example.com/oauth2callback",
        "javascript:alert(1)",
    ],
)
def test_render_rejects_unsafe_redirect_uri(redirect_uri: str) -> None:
    config = WebClientConfig(client_id="id", client_secret=SYNTHETIC_CREDENTIAL)

    with pytest.raises(ValueError, match="(?i)redirect"):
        render_streamlit_secrets(config, redirect_uri=redirect_uri)


def test_writer_creates_private_file_and_refuses_accidental_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "client.json"
    output = tmp_path / ".streamlit" / "secrets.toml"
    _write_client_json(source)

    write_streamlit_secrets(
        source,
        output,
        redirect_uri="https://example.test/oauth2callback",
    )

    parsed = tomllib.loads(output.read_text(encoding="utf-8"))
    assert parsed["auth"]["google"]["client_secret"] == SYNTHETIC_CREDENTIAL
    # Linux/macOS는 POSIX mode로 소유자 전용 권한을 정확히 확인할 수 있다.
    # Windows는 os.chmod(0o600)를 호출해도 stat 결과가 0o666으로 보일 수 있어
    # 같은 숫자를 비교하지 않는다. Windows의 실제 접근 제한은 NTFS ACL 영역이다.
    if os.name != "nt":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600

    with pytest.raises(FileExistsError):
        write_streamlit_secrets(
            source,
            output,
            redirect_uri="https://example.test/oauth2callback",
        )
