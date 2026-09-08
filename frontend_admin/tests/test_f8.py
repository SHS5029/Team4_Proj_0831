import json
import shutil
import subprocess
from pathlib import Path

import pytest

from frontend_admin.core.api_client import AdminApiClient, AdminApiError
from frontend_admin.core.models import reject_private_fields

ADMIN_ID = "83d40f36-e835-4a1d-88db-e59b6920b739"


def test_admin_client_uses_uuid_header_for_read_only_metrics() -> None:
    captured = {}

    def transport(request, timeout):
        captured["request"] = request
        return 200, b'{"data":{"games_created":1}}'

    AdminApiClient(user_id=ADMIN_ID, transport=transport).metrics()
    assert captured["request"].headers["X-user-id"] == ADMIN_ID


def test_admin_403_is_fail_closed() -> None:
    def transport(request, timeout):
        return 403, b'{"error":{"code":"ADMIN_ACCESS_DENIED"}}'

    with pytest.raises(AdminApiError) as error:
        AdminApiClient(user_id=ADMIN_ID, transport=transport).metrics()
    assert error.value.code == "ADMIN_ACCESS_DENIED"


def test_admin_timeout_is_scoped_to_speech_analytics() -> None:
    """분석 GET 전후에도 일반 GET과 질문 POST의 5초 제한이 유지되어야 한다."""

    captured = []

    def transport(request, timeout):
        captured.append((request.get_method(), timeout))
        return 200, b'{"data":{}}'

    client = AdminApiClient(user_id=ADMIN_ID, transport=transport)
    client.metrics()
    client.speech_analytics()
    client.metrics()
    client.games()
    client.game_detail(ADMIN_ID)
    client.role_win_rates()
    client.persona_win_rates()
    client.feedback()
    client.audit_logs()
    client.insights_query("최근 운영 지표를 알려 주세요")

    assert captured == [("GET", 5.0), ("GET", 30.0)] + [("GET", 5.0)] * 7 + [("POST", 5.0)]


@pytest.mark.parametrize("failure", ["timeout", "forbidden"])
def test_admin_speech_analytics_failure_is_closed_without_retry(failure) -> None:
    """분석 시간 초과와 권한 거부는 재시도나 부분 응답 반환 없이 기존 오류로 닫는다."""

    captured = []

    def transport(request, timeout):
        captured.append((request.get_method(), timeout))
        if failure == "timeout":
            raise TimeoutError("합성 분석 요청 시간 초과")
        return 403, b'{"error":{"code":"ADMIN_ACCESS_DENIED"},"data":{"topics":[]}}'

    client = AdminApiClient(user_id=ADMIN_ID, transport=transport)
    with pytest.raises(AdminApiError) as error:
        client.speech_analytics()

    expected = (503, "DEPENDENCY_UNAVAILABLE") if failure == "timeout" else (403, "ADMIN_ACCESS_DENIED")
    assert (error.value.status_code, error.value.code) == expected
    assert captured == [("GET", 30.0)]


def test_live_dashboard_revoked_access_returns_to_identity_flow(monkeypatch) -> None:
    """주기 조회의 403도 권한 표시를 지우고 UUID bridge가 있는 전체 화면으로 복귀한다."""

    from unittest.mock import Mock

    from frontend_admin import app

    state = {app.ADMIN_ACCESS_SESSION_KEY: True}
    ui = Mock(session_state=state)
    ui.rerun.side_effect = RuntimeError("인증 화면 재실행")
    monkeypatch.setattr(app, "st", ui)
    client = Mock()
    client.metrics.side_effect = AdminApiError(403, "ADMIN_ACCESS_DENIED")
    dashboard = Mock()
    monkeypatch.setattr(app, "render_dashboard", dashboard)

    with pytest.raises(RuntimeError, match="인증 화면 재실행"):
        app._render_live_dashboard.__wrapped__(client)

    assert state[app.ADMIN_ACCESS_SESSION_KEY] is False
    ui.rerun.assert_called_once_with(scope="app")
    dashboard.assert_not_called()


def test_private_fields_are_rejected_instead_of_masked() -> None:
    with pytest.raises(ValueError, match="ADMIN_PRIVATE_FIELD"):
        reject_private_fields({"status": "IN_PROGRESS", "role": "MAFIA"})


def test_demo_key_and_data_are_isolated(monkeypatch) -> None:
    from frontend_admin.core import api_client

    def deny_network(*args, **kwargs):
        raise AssertionError("데모는 외부 API를 호출하면 안 됩니다.")

    monkeypatch.setattr(api_client, "_send", deny_network)
    with pytest.raises(AdminApiError, match="DEMO_KEY_INVALID"):
        api_client.DemoAdminApiClient(api_key="invalid")
    client = api_client.DemoAdminApiClient(api_key=api_client.DEMO_API_KEY)
    games = []
    cursor = None
    while True:
        page = client.games(cursor=cursor, limit=100)["data"]
        games.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    metrics = client.metrics()["data"]
    assert len(games) == len({g["game_id"] for g in games}) == metrics["games_created"] == 1200
    assert client.games(status="SAVED")["data"]["total"] == metrics["games_saved"] == 180
    assert sum(g["status"] == "COMPLETED" for g in games) == metrics["games_completed"]
    personas = client.persona_win_rates()["data"]["items"]
    assert len(personas) == 5 and all(0 <= row["win_rate"] <= 1 for row in personas)
    assert all("parameters" not in row and "backstory" not in row for row in personas)
    for game in games:
        reject_private_fields(client.game_detail(game["game_id"]))
    preview = client.preview()
    assert sum(row["생성 게임"] for row in preview["daily"]) == 1200
    assert preview["users_total"] == len({g["owner_user_id"] for g in games}) == 300
    assert metrics["wins_by_faction"] == {"CITIZEN": 540, "MAFIA": 360}
    assert sum(metrics["wins_by_faction"].values()) == metrics["games_completed"] == 900
    assert sum(row["참여 수"] for row in preview["jobs"]) == sum(g["player_count"] - 1 for g in games if g["status"] == "COMPLETED")
    preview["feedback"].clear()
    assert len(client.preview()["feedback"]) == 240
    assert len(preview["logs"]) == 180
    for row in preview["jobs"]:
        assert 0 <= row["승리 수"] <= row["참여 수"]
        assert row["승률 (%)"] == round(row["승리 수"] / row["참여 수"] * 100, 1)
    with pytest.raises(AdminApiError, match="GAME_NOT_FOUND"):
        client.game_detail(ADMIN_ID)


def test_demo_ui_connection_failure_and_recovery(monkeypatch) -> None:
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from frontend_admin.core.api_client import DEMO_API_KEY

    monkeypatch.setenv("ADMIN_DEMO_MODE", "true")
    at = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=15).run()
    assert not at.exception
    assert len(at.tabs) == 4
    assert len(at.dataframe) >= 5
    assert any(metric.label == "누적 게임" and metric.value == "1200" for metric in at.metric)
    assert any("마피아 360승 (40.0%)" in item.value for item in at.caption)
    at.text_input[0].set_value("wrong-key")
    at.button[0].click().run()
    assert at.error and not at.metric and not at.exception
    at.text_input[0].set_value(DEMO_API_KEY)
    at.button[0].click().run()
    assert not at.error and not at.exception
    assert at.metric


def test_demo_mode_is_opt_in(monkeypatch) -> None:
    from frontend_admin.core.api_client import is_demo_mode

    monkeypatch.delenv("ADMIN_DEMO_MODE", raising=False)
    assert not is_demo_mode()
    monkeypatch.setenv("ADMIN_DEMO_MODE", "false")
    assert not is_demo_mode()


@pytest.mark.parametrize("cursor", ["ALL:ALL:-1", "ALL:ALL:no", "ALL:ALL:1200", "SAVED:ALL:20"])
def test_demo_rejects_invalid_cursor(cursor) -> None:
    from frontend_admin.core.api_client import DemoAdminApiClient

    with pytest.raises(ValueError):
        DemoAdminApiClient().games(cursor=cursor)


def test_demo_empty_filter_and_final_page() -> None:
    from frontend_admin.core.api_client import DemoAdminApiClient

    client = DemoAdminApiClient()
    assert client.games(status="SAVED", phase="RESULT")["data"] == {
        "items": [], "next_cursor": None, "total": 0,
    }
    page = client.games(status="FAILED", cursor="FAILED:ALL:20")["data"]
    assert len(page["items"]) == 4 and page["next_cursor"] is None


def test_feedback_and_audit_pages_change_on_one_click(monkeypatch):
    """필터를 바꾸면 첫 페이지로 돌아가고 다음 버튼은 한 번 클릭으로 반영된다."""

    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("ADMIN_DEMO_MODE", "true")
    at = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=15).run()
    def frame_with(column):
        return next(frame.value for frame in at.dataframe if column in frame.value.columns)

    first_id = frame_with("피드백 UUID").iloc[0]["피드백 UUID"]
    at.button(key="admin.feedback.next").click().run()
    assert not at.exception and frame_with("피드백 UUID").iloc[0]["피드백 UUID"] != first_id
    at.selectbox(key="admin.feedback.rating").select("5").run()
    assert set(frame_with("피드백 UUID")["평점"]) == {5}
    assert at.button(key="admin.feedback.previous").disabled
    at.selectbox(key="admin.logs.type").select("운영 지표 조회").run()
    assert set(frame_with("조회 유형")["조회 유형"]) == {"운영 지표 조회"}
    at.button(key="admin.logs.next").click().run()
    assert not at.exception and len(frame_with("조회 유형")) == 16
    assert at.button(key="admin.logs.next").disabled
    assert at.button(key="admin.logs.next").disabled


def test_admin_client_extension_urls_are_encoded():
    """신규 API에 UUID 인증만 전달하고 쿼리 특수문자는 URL 인코딩한다."""

    captured = []

    def transport(request, timeout):
        captured.append(request)
        return 200, b'{"data":{"items":[],"next_cursor":null}}'

    client = AdminApiClient(user_id=ADMIN_ID, transport=transport)
    client.role_win_rates(from_date="2026-09-01T00:00:00+09:00")
    client.persona_win_rates(from_date="2026-09-01T00:00:00+09:00")
    client.feedback(feedback_type="GAME", rating=5, cursor=ADMIN_ID, limit=10)
    client.audit_logs(event_type="ADMIN_GET_METRICS", cursor="180")
    client.insights_query(
        "운영 지표에서 반복되는 문제는 무엇인가요?",
        source_types=["FEEDBACK"],
        rating_lte=3,
        top_k=5,
    )
    assert "/role-win-rates?from=" in captured[0].full_url and "%2B09" in captured[0].full_url
    assert "/persona-win-rates?from=" in captured[1].full_url and "%2B09" in captured[1].full_url
    assert "feedback_type=GAME&rating=5" in captured[2].full_url
    assert "/audit-logs?event_type=ADMIN_GET_METRICS&cursor=180" in captured[3].full_url
    assert captured[4].method == "POST"
    assert captured[4].headers["Content-type"] == "application/json"
    assert json.loads(captured[4].data.decode("utf-8"))["filters"]["source_types"] == ["FEEDBACK"]
    assert all(r.headers["X-user-id"] == ADMIN_ID and "X-api-key" not in r.headers for r in captured)


def test_admin_speech_analytics_client_encodes_analysis_scope():
    """발언 분석 조건을 URL에 안전하게 인코딩하고 관리자 UUID만 전달한다."""

    from urllib.parse import parse_qs, urlsplit

    captured = []

    def transport(request, timeout):
        captured.append(request)
        return 200, b'{"data":{"topics":[]}}'

    client = AdminApiClient(user_id=ADMIN_ID, transport=transport)
    client.speech_analytics(
        from_date="2026-09-01T00:00:00+09:00",
        to_date="2026-09-08T00:00:00+09:00",
        game_id="00000000-0000-4000-8000-000000000299",
        persona_id="ACTIVE DEBATER",
        round_number=2,
        analysis_version="claims-ko-v2",
        limit=5,
    )
    query = parse_qs(urlsplit(captured[0].full_url).query)
    assert query == {
        "limit": ["5"],
        "from": ["2026-09-01T00:00:00+09:00"],
        "to": ["2026-09-08T00:00:00+09:00"],
        "game_id": ["00000000-0000-4000-8000-000000000299"],
        "persona_id": ["ACTIVE DEBATER"],
        "round": ["2"],
        "analysis_version": ["claims-ko-v2"],
    }
    assert captured[0].headers["X-user-id"] == ADMIN_ID


def test_browser_admin_uuid_requires_explicit_value_and_preserves_storage_on_failure():
    """JS bridge는 UUID 자동 생성 없이 입력·새로고침·차단·손상을 구분해야 한다."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("브라우저 bridge JS 검증에는 Node.js가 필요합니다.")
    source = (Path(__file__).parents[1] / "components/browser_components/identity/index.js").read_text(encoding="utf-8")
    script = r"""
import assert from 'node:assert/strict';
const {default: render} = await import('data:text/javascript;base64,' + Buffer.from(SOURCE).toString('base64'));
const A = '00000000-0000-4000-8000-000000000101';
const B = '00000000-0000-4000-8000-000000000102';
let stored = null;
let blocked = false;
let writes = 0;
globalThis.window = {localStorage: {
  getItem: () => stored,
  setItem: (_key, value) => {
    if (blocked) throw Error('synthetic-storage-block');
    stored = value; writes += 1;
  },
}};
const root = {};
const outputs = [];
function run(data = {}, parentElement = root) {
  render({data: {scope_version: '1', ...data}, parentElement,
    setStateValue: (_key, value) => outputs.push(value)});
  return outputs.at(-1);
}
assert.equal(run().error_code, 'MISSING_UUID');
assert.equal(stored, null);
run();
assert.equal(outputs.length, 1);
assert.equal(run({scope_version: '2', replacement: A}).user_id, A);
assert.equal(writes, 1);
assert.equal(run({}, {}).user_id, A);
blocked = true;
assert.equal(run({scope_version: '3', replacement: B}).error_code, 'STORAGE_BLOCKED');
assert.equal(stored, A);
blocked = false;
assert.equal(run({scope_version: '3', replacement: B}).user_id, B);
stored = 'broken-value';
assert.equal(run({}, {}).error_code, 'INVALID_STORED_UUID');
assert.equal(stored, 'broken-value');
window.localStorage.getItem = () => { throw Error('synthetic-read-block'); };
assert.equal(run().error_code, 'STORAGE_BLOCKED');
console.log('admin identity lifecycle passed');
""".replace("SOURCE", json.dumps(source))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "admin identity lifecycle passed" in result.stdout


def test_admin_backend_url_uses_environment_and_explicit_override(monkeypatch):
    """로컬 별도 포트 설정을 사용하되 호출자가 지정한 주소를 우선한다."""

    monkeypatch.setenv("BACKEND_API_URL", "http://127.0.0.1:18000/")
    assert AdminApiClient(user_id=ADMIN_ID).api_url == "http://127.0.0.1:18000"
    assert AdminApiClient(user_id=ADMIN_ID, api_url="http://127.0.0.1:9000").api_url.endswith(":9000")
    monkeypatch.delenv("BACKEND_API_URL")
    assert AdminApiClient(user_id=ADMIN_ID).api_url == "http://127.0.0.1:8000"


@pytest.mark.parametrize("status", [403, 503])
def test_real_mode_denial_preserves_identity_input(monkeypatch, status):
    """접속·권한 오류에서 운영 데이터는 숨기고 UUID 교체 입력은 유지한다."""

    from uuid import UUID

    from streamlit.testing.v1 import AppTest

    from frontend_admin.components import identity_bridge
    from frontend_admin.core import api_client

    monkeypatch.setenv("ADMIN_DEMO_MODE", "false")
    monkeypatch.setattr(identity_bridge, "load_identity", lambda **kwargs: (UUID(ADMIN_ID), None))
    monkeypatch.setattr(api_client, "_send", lambda *args: (status, b'{"error":{"code":"SYNTHETIC"}}'))
    at = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=15).run()
    assert at.error and not at.exception and not at.tabs
    assert at.text_input(key="admin.identity.input") is not None
    assert at.button(key="admin.access.retry") is not None
