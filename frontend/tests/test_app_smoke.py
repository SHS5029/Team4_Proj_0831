from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_login_screen_handles_missing_and_ready_oidc_configuration() -> None:
    missing = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    assert not missing.exception
    assert [(button.label, button.disabled) for button in missing.button] == [
        ("Google로 계속하기", True)
    ]
    assert [item.value for item in missing.error] == [
        "Google 로그인 설정이 아직 완료되지 않았어요."
    ]
    assert missing.session_state["application-access-granted"] is False

    ready = AppTest.from_file(str(APP_PATH), default_timeout=10)
    try:
        ready.secrets["auth"] = {
            "redirect_uri": "http://localhost:8501/oauth2callback",
            "cookie_secret": "synthetic-cookie-secret-over-32-characters",
            "google": {
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
                "server_metadata_url": (
                    "https://accounts.google.com/.well-known/openid-configuration"
                ),
            },
        }
        ready.run()

        assert not ready.exception
        assert [(button.label, button.disabled) for button in ready.button] == [
            ("Google로 계속하기", False)
        ]
        assert not ready.error
        assert ready.session_state["application-access-granted"] is False
    finally:
        ready.secrets.clear()
