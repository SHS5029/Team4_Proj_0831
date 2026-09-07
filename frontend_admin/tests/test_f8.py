import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from frontend_admin.core.api_client import AdminApiClient, AdminApiError
from frontend_admin.core.models import reject_private_fields


ADMIN_ID = "83d40f36-e835-4a1d-88db-e59b6920b739"
OTHER_ADMIN_ID = "00000000-0000-4000-8000-000000000102"
GAME_ID = "00000000-0000-4000-8000-000000000201"


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


def test_private_fields_are_rejected_instead_of_masked() -> None:
    with pytest.raises(ValueError, match="ADMIN_PRIVATE_FIELD"):
        reject_private_fields({"status": "IN_PROGRESS", "role": "MAFIA"})


def test_admin_filters_and_game_detail_use_supported_read_only_routes() -> None:
    requests = []

    def transport(request, timeout):
        requests.append(request)
        return 200, b'{"data":{}}'

    client = AdminApiClient(user_id=f" {ADMIN_ID.upper()} ", transport=transport)
    client.games(status="SAVED", phase="DAY_VOTE", cursor="opaque+cursor&next")
    client.game_detail(GAME_ID)
    assert parse_qs(urlsplit(requests[0].full_url).query) == {
        "limit": ["20"], "status": ["SAVED"], "phase": ["DAY_VOTE"],
        "cursor": ["opaque+cursor&next"],
    }
    assert urlsplit(requests[1].full_url).path == f"/api/v1/admin/games/{GAME_ID}"
    assert all(request.get_method() == "GET" for request in requests)
    assert all(request.headers["X-user-id"] == ADMIN_ID for request in requests)


@pytest.mark.parametrize("query", [{"status": "SAVED&limit=100"}, {"phase": "SECRET"}])
def test_unknown_filters_never_reach_transport(query) -> None:
    def transport(request, timeout):
        pytest.fail("잘못된 필터는 HTTP 요청 전에 거부해야 합니다.")

    with pytest.raises(ValueError):
        AdminApiClient(user_id=ADMIN_ID, transport=transport).games(**query)


@pytest.mark.parametrize("value", ["invalid", "00000000-0000-1000-8000-000000000001"])
def test_non_v4_admin_identity_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        AdminApiClient(user_id=value)


def _identity(user_id=ADMIN_ID, *, scope="1", error=None):
    return {"scope_version": scope, "user_id": user_id, "error_code": error}


def test_identity_bridge_waits_for_matching_scope_and_replacement(monkeypatch) -> None:
    from frontend_admin.components import identity_bridge

    response = None
    monkeypatch.setattr(
        identity_bridge, "ADMIN_IDENTITY_COMPONENT",
        lambda **kwargs: SimpleNamespace(identity=response),
    )
    assert identity_bridge.load_identity() == (None, None)
    response = _identity()
    assert identity_bridge.load_identity(scope_version="2") == (None, None)
    response = _identity(scope="2")
    assert identity_bridge.load_identity(
        scope_version="2", replacement=UUID(OTHER_ADMIN_ID),
    ) == (None, "INVALID_BRIDGE_RESPONSE")
    response = _identity(OTHER_ADMIN_ID, scope="2")
    assert identity_bridge.load_identity(
        scope_version="2", replacement=UUID(OTHER_ADMIN_ID),
    ) == (UUID(OTHER_ADMIN_ID), None)
    response = _identity(None, error="STORAGE_BLOCKED")
    assert identity_bridge.load_identity() == (None, "STORAGE_BLOCKED")


def _run_with_identity(tested, identity):
    """AppTest가 자동 지원하지 않는 v2 응답을 실제 widget ID에 주입한다."""

    states = tested._tree.get_widget_states()
    component_id = tested.get("bidi_component")[0].proto.id
    states.widgets.add(id=component_id, json_value=json.dumps({"identity": identity}))
    tested._run(widget_state=states)
    assert not tested.exception


def _admin_app(monkeypatch, *, metrics_status=200, private_detail=False):
    """실제 진입점을 실행하되 모든 HTTP는 synthetic 관리자 응답으로 대체한다."""

    from streamlit.components.v2.component_manager import BidiComponentManager
    from streamlit.components.v2.component_registry import BidiComponentDefinition
    from streamlit.testing.v1 import AppTest

    from frontend_admin.components import identity_bridge

    requests = []

    def transport(request, timeout):
        assert request.get_method() == "GET"
        requests.append(request)
        path = urlsplit(request.full_url).path
        if path.endswith("/metrics"):
            if metrics_status != 200:
                return metrics_status, b'{"error":{"code":"<script>synthetic-error</script>"}}'
            return 200, b'{"data":{"games_created":1,"games_completed":0}}'
        if path == "/api/v1/admin/games":
            payload = {"data": {"items": [{
                "game_id": GAME_ID, "status": "SAVED", "phase": "DAY_VOTE", "player_count": 6,
            }]}}
        else:
            assert path == f"/api/v1/admin/games/{GAME_ID}"
            payload = {"data": {"game_id": GAME_ID, "status": "SAVED"}}
            if private_detail:
                payload["data"]["agent_context"] = "synthetic-private-context"
        return 200, json.dumps(payload).encode()

    monkeypatch.setattr("frontend_admin.core.api_client._send", transport)
    tested = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    # pytest 수집 시 임시 등록된 component를 AppTest runtime에도 동일하게 등록한다.
    tested._bidi_component_manager = BidiComponentManager()
    tested._bidi_component_manager.register(BidiComponentDefinition(
        name="ai_mafia_admin_identity",
        html=(identity_bridge.ASSET_DIR / "index.html").read_text(),
        js=(identity_bridge.ASSET_DIR / "index.js").read_text(),
    ))
    tested.run()
    assert not tested.exception
    assert not requests
    return tested, requests


@pytest.mark.parametrize("status", [403, 503, 201])
def test_admin_denial_or_connection_failure_keeps_recovery_and_hides_data(monkeypatch, status):
    tested, requests = _admin_app(monkeypatch, metrics_status=status)
    _run_with_identity(tested, _identity())
    assert len(requests) == 1
    assert not tested.metric
    assert not tested.json
    assert tested.session_state["admin-access-granted"] is False
    assert tested.text_input(key="admin.identity.input")
    assert tested.button(key="admin.access.retry")
    assert "synthetic-error" not in " ".join(error.value for error in tested.error)


def test_admin_uuid_confirmation_blocks_old_ack_then_uses_new_header(monkeypatch):
    tested, requests = _admin_app(monkeypatch)
    _run_with_identity(tested, _identity())
    component_id = tested.get("bidi_component")[0].proto.id
    tested.text_input(key="admin.identity.input").set_value(f" {OTHER_ADMIN_ID.upper()} ")
    tested.button(key="admin.identity.apply").click()
    _run_with_identity(tested, _identity())
    assert tested.session_state["admin.identity.pending"] == OTHER_ADMIN_ID
    tested.query_params["game_id"] = GAME_ID
    tested.button(key="admin.identity.confirm").click()
    count = len(requests)
    _run_with_identity(tested, _identity())
    assert len(requests) == count
    assert not tested.metric
    assert "game_id" not in tested.query_params
    assert tested.session_state["admin-access-granted"] is False
    assert tested.session_state["admin.identity.write"] == OTHER_ADMIN_ID
    scope = str(tested.session_state["admin.identity.scope"])
    _run_with_identity(tested, _identity(OTHER_ADMIN_ID, scope=scope))
    assert tested.session_state["admin.user_id"] == OTHER_ADMIN_ID
    assert tested.session_state["admin-access-granted"] is True
    assert tested.text_input(key="admin.identity.input").value == ""
    assert tested.get("bidi_component")[0].proto.id == component_id
    assert all(request.headers["X-user-id"] == OTHER_ADMIN_ID for request in requests[count:])


def test_admin_missing_uuid_can_be_entered_without_any_backend_request(monkeypatch):
    tested, requests = _admin_app(monkeypatch)
    missing = _identity(None, error="MISSING_UUID")
    _run_with_identity(tested, missing)
    tested.text_input(key="admin.identity.input").set_value("not-a-uuid")
    tested.button(key="admin.identity.apply").click()
    _run_with_identity(tested, missing)
    assert tested.error
    assert not requests
    tested.text_input(key="admin.identity.input").set_value(ADMIN_ID)
    tested.button(key="admin.identity.apply").click()
    _run_with_identity(tested, missing)
    assert tested.button(key="admin.identity.confirm")
    assert not requests


def test_admin_filters_and_detail_url_survive_rerun(monkeypatch):
    tested, requests = _admin_app(monkeypatch)
    _run_with_identity(tested, _identity())
    tested.selectbox(key="admin.filter.status").set_value("SAVED")
    tested.selectbox(key="admin.filter.phase").set_value("DAY_VOTE")
    _run_with_identity(tested, _identity())
    assert parse_qs(urlsplit(requests[-1].full_url).query) == {
        "limit": ["20"], "status": ["SAVED"], "phase": ["DAY_VOTE"],
    }
    tested.button(key=f"admin.game.{GAME_ID}").click()
    _run_with_identity(tested, _identity())
    assert tested.query_params["game_id"] == [GAME_ID]
    assert requests[-1].full_url.endswith(f"/admin/games/{GAME_ID}")
    assert tested.json
    _run_with_identity(tested, _identity())
    assert tested.json
    assert requests[-1].full_url.endswith(f"/admin/games/{GAME_ID}")


@pytest.mark.parametrize("game_id", [GAME_ID, "<script>bad-game-id</script>"])
def test_admin_deep_link_rejects_private_data_and_invalid_path(monkeypatch, game_id):
    tested, requests = _admin_app(monkeypatch, private_detail=True)
    tested.query_params["game_id"] = game_id
    _run_with_identity(tested, _identity())
    assert not tested.json
    assert tested.error
    assert "synthetic-private-context" not in " ".join(error.value for error in tested.error)
    if game_id != GAME_ID:
        assert len(requests) == 2


def test_browser_admin_uuid_requires_explicit_value_and_preserves_storage_on_failure():
    """JS bridge는 UUID 자동 생성 없이 입력·새로고침·차단·손상을 구분해야 한다."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("브라우저 bridge JS 검증에는 Node.js가 필요합니다.")
    source = (Path(__file__).parents[1] / "components/browser_components/identity/index.js").read_text()
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
