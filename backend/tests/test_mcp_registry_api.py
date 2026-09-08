"""WU-SCC-03 최소 FastMCP Backend endpoint 계약 테스트."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.repositories.game_repository import GameStateKeyring


from backend.app.main import create_app


USER_ID = "00000000-0000-4000-8000-000000000002"
GAME_ID = "00000000-0000-4000-8000-000000000001"
WINDOW_ID = "00000000-0000-4000-8000-000000000003"


class FakeMcpRuntime:
    """MCP endpoint의 HTTP 계약만 검증하기 위한 게임 runtime 대역이다."""

    def __init__(self):
        self._read = _reader()
        self._agent_repository = self._read._agents

    def snapshot(self, user_id, game_id):
        """실제 게임 규칙 없이 요청된 식별자를 context에 반영한다."""

        return {"game": {"game_id": str(game_id)}, "me": {"player_id": str(user_id)}}

    def command(self, user_id, game_id, payload, idempotency_key):
        """Backend command 위임 인자를 확인할 수 있는 synthetic 결과를 반환한다."""

        return (
            {
                "type": payload.type,
                "user_id": str(user_id),
                "game_id": str(game_id),
                "idempotency_key": str(idempotency_key),
            },
            False,
        )


def _client() -> TestClient:
    """실제 게임 runtime과 분리된 MCP endpoint 테스트 앱을 만든다."""

    application = create_app(enable_background_worker=False)
    application.state.game_runtime = FakeMcpRuntime()
    return TestClient(application)


def test_mcp_context_prompt_and_action_endpoints_use_game_contract() -> None:
    """세 endpoint가 실제 runtime 위임에 필요한 입력을 전달하는지 확인한다."""

    client = _client()

    context = client.get(f"/internal/mcp/context?game_id={GAME_ID}&user_id={USER_ID}")
    assert context.status_code == 200
    assert context.json()["scope"] == "public"
    assert context.json()["data"]["game"]["game_id"] == GAME_ID
    assert "me" not in context.json()["data"]

    prompt = client.get("/internal/mcp/prompts/agent_instruction")
    assert prompt.status_code == 200
    assert "게임 context" in prompt.json()["prompt"]

    action = client.post(
        "/internal/mcp/actions",
        json={
            "action": "PASS",
            "user_id": USER_ID,
            "game_id": GAME_ID,
            "expected_state_version": 2,
            "window_id": WINDOW_ID,
            "idempotency_key": "00000000-0000-4000-8000-000000000004",
        },
    )
    assert action.status_code == 200
    assert action.json()["accepted"] is True
    assert action.json()["result"]["type"] == "PASS"


def test_minimal_mcp_action_rejects_unknown_fields_with_common_error_envelope() -> None:
    """MCP가 추가 필드를 몰래 전달하지 못하고 Backend 검증 오류를 반환하는지 확인한다."""

    response = _client().post(
        "/internal/mcp/actions",
        json={"action": "PASS", "unexpected": "not-allowed"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "detail" not in response.json()["error"]


def test_minimal_mcp_unknown_prompt_returns_common_error_envelope() -> None:
    """등록되지 않은 Prompt가 framework 기본 detail 형식으로 노출되지 않는지 확인한다."""

    response = _client().get("/internal/mcp/prompts/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROMPT_NOT_FOUND"
    assert "detail" not in response.json()


NOW = datetime.now(UTC)
ACTOR_ID = UUID(int=12)
OTHER_ID = UUID(int=13)
PARAMETERS = dict.fromkeys((
    "sociability", "assertiveness", "suspicion", "deception", "risk_tolerance",
    "memory_recall", "reasoning_skill", "emotionality", "cooperativeness", "verbosity",
), 0.5)


class ReaderFixture:
    """원격 DB 없이 실제 row 복원과 audience 검증까지 실행하는 저장소 대역이다."""

    def __init__(self):
        self._keyring = GameStateKeyring.legacy_plaintext()
        seed = self._keyring.encrypt_seed(b"synthetic-actor-seed")
        self.game = {
            "id": UUID(GAME_ID), "owner_user_id": UUID(USER_ID), "status": "IN_PROGRESS",
            "phase": "DAY_DISCUSSION", "round": 1, "day_number": 2, "state_version": 7,
            "next_front_sequence": 4, "next_event_sequence": 5,
            "player_count": 6, "mafia_count": 1, "scenario_version": "scenario-v1",
            "ruleset_version": "mystery-v1", "scenario_id": "SYNTHETIC",
            "agent_config_version": "test-v1", "scenario_title": "테스트 사건",
            "scenario_background": "합성 배경", "scenario_victim": "합성 피해자",
            "scenario_locations": ["거실", "서재", "정원", "주방"],
            "seed_ciphertext": seed.ciphertext, "seed_nonce": seed.nonce,
            "seed_key_id": seed.key_id, "winner": None, "win_reason": None,
            "fast_forward_enabled": False, "updated_at": NOW,
        }
        self.players = [{
            "id": UUID(int=11 + i), "game_id": UUID(GAME_ID), "seat": i + 1,
            "kind": "HUMAN" if i == 0 else "AI", "user_id": UUID(USER_ID) if i == 0 else None,
            "display_name": f"좌석 {i + 1}", "role": role, "alive": True,
            "persona_id": f"preset-{i}", "eliminated_phase": None, "eliminated_round": None,
        } for i, role in enumerate(["MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN", "CITIZEN", "CITIZEN"])]
        self.window = {
            "id": UUID(WINDOW_ID), "game_id": UUID(GAME_ID), "phase": "DAY_DISCUSSION",
            "window_kind": "SPEECH", "round": 1, "cycle": 2, "status": "OPEN",
            "turn_player_id": ACTOR_ID, "opened_state_version": 5, "deadline_at": None,
        }
        self.public_rows = []
        self.private_rows = []
        self.submissions = []
        self.fact_calls = []
        self.personas = [{
            "id": f"preset-{i}", "version": "test-v1", "display_name": f"성향 {i}",
            "speech_style": "차분하게 말한다.", "backstory": f"합성 배경 {i}",
            "parameters": dict(PARAMETERS),
        } for i in range(1, 6)]
        self.facts = {p["id"]: [
            {"fact_kind": "ALIBI", "rendered_text": f"  좌석 {p['seat']}은 서재에 있었다.  "},
            {"fact_kind": "OBSERVATION", "rendered_text": f"좌석 {p['seat']}은 열린 문을 보았다."},
        ] for p in self.players}
        self._transactions = self
        self._games = self
        self._players = self
        self._events = self
        self._actions = self
        self._agents = self
        self.connection = SimpleNamespace(cursor=self.cursor)

    @contextmanager
    def transaction(self):
        yield self.connection

    @contextmanager
    def cursor(self, **kwargs):
        yield self

    def get_owned_game(self, cursor, *, owner_user_id, game_id):
        return deepcopy(self.game) if self.game is not None and self.game["owner_user_id"] == owner_user_id and self.game["id"] == game_id else None

    def list_players(self, cursor, **kwargs):
        return deepcopy(self.players)

    def active_window(self, cursor, **kwargs):
        return deepcopy(self.window)

    def list_discussion_submissions(self, cursor, **kwargs):
        return deepcopy(self.submissions)

    def list_window_action_submissions(self, cursor, **kwargs):
        return deepcopy(self.submissions)

    def list_snapshot_public_events(self, cursor, **kwargs):
        return deepcopy(self.public_rows)

    def list_snapshot_private_events(self, cursor, **kwargs):
        return deepcopy(self.private_rows)

    def list_player_facts(self, cursor, *, game_id, player_id):
        self.fact_calls.append((game_id, player_id))
        return deepcopy(self.facts[player_id])

    def list_active_personas(self, cursor, **kwargs):
        return deepcopy(self.personas)


def _reader():
    return ReaderFixture()


def _context(reader, scope="public", actor=ACTOR_ID, **changes):
    """공개 HTTP route를 통과시켜 actor 선택과 공통 오류 응답까지 확인한다."""

    runtime = FakeMcpRuntime()
    runtime._read = reader
    runtime._agent_repository = reader._agents
    application = create_app(enable_background_worker=False)
    application.state.game_runtime = runtime
    params = {"game_id": GAME_ID, "user_id": USER_ID, "scope": scope, **changes}
    if actor is not None:
        params["player_id"] = str(actor)
    return TestClient(application).get("/internal/mcp/context", params=params)


def test_actor_context_keeps_subject_facts_and_persona_separate():
    reader = _reader()
    first = _context(reader, "me").json()
    other = _context(reader, "me", OTHER_ID).json()
    assert first["data"]["role"] == "DETECTIVE"
    assert first["data"]["alibi"] == "좌석 2은 서재에 있었다."
    assert other["data"]["role"] == "DOCTOR"
    assert reader.fact_calls == [(UUID(GAME_ID), ACTOR_ID), (UUID(GAME_ID), OTHER_ID)]
    assert _context(reader, "persona").json()["data"]["persona_id"] == "preset-1"
    assert _context(reader, "persona", OTHER_ID).json()["data"]["persona_id"] == "preset-2"
    assert first["window_id"] == WINDOW_ID
    assert first["state_version"] == 7


@pytest.mark.parametrize("actor,scope", [
    (None, "me"), (None, "turn"), (None, "persona"), (None, "gm-guide"),
    (ACTOR_ID, "gm-guide"), (ACTOR_ID, "unknown"), (UUID(int=11), "public"),
    (UUID(int=987), "me"),
])
def test_actor_context_denies_invalid_actor_scope(actor, scope):
    response = _context(_reader(), scope, actor)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CAPABILITY_DENIED"


@pytest.mark.parametrize("changes", [{"game_id": str(UUID(int=987))}, {"user_id": str(UUID(int=987))}])
def test_actor_context_hides_other_owner_or_game(changes):
    assert _context(_reader(), **changes).status_code == 404


def test_actor_context_rejects_cross_game_player_row():
    reader = _reader()
    reader.players[1]["game_id"] = UUID(int=987)
    assert _context(reader, "me").status_code == 403


@pytest.mark.parametrize("change", [
    {"status": "PAUSED"}, {"status": "RESOLVED"}, {"phase": "NIGHT_ACTION"},
    {"game_id": UUID(int=987)}, {"opened_state_version": 8}, {"round": 2},
])
def test_actor_context_rejects_stale_window(change):
    reader = _reader()
    reader.window.update(change)
    assert _context(reader).status_code == 409


def test_actor_context_missing_window_and_private_data_fail_closed():
    reader = _reader()
    reader.window = None
    assert _context(reader).status_code == 409
    reader = _reader()
    reader.facts[ACTOR_ID] = []
    assert _context(reader, "me").status_code == 403
    reader.personas = []
    assert _context(reader, "persona").status_code == 403


def test_actor_turn_uses_actual_window_cycle_version_and_speaker():
    reader = _reader()
    turn = _context(reader, "turn").json()["data"]
    assert turn["window_id"] == WINDOW_ID
    assert turn["cycle"] == 2
    assert turn["opened_state_version"] == 5
    assert turn["allowed_tools"] == ["propose_speech", "propose_pass"]
    assert turn["valid_targets"] == []
    assert _context(reader, "turn", OTHER_ID).status_code == 403


def test_actor_public_is_independent_of_hidden_roles_facts_persona_and_extras():
    reader = _reader()
    first = _context(reader).json()["data"]
    reader.players[2]["role"] = "MAFIA"
    reader.facts[OTHER_ID] = []
    reader.personas[1]["backstory"] = "다른 AI의 비공개 자료"
    second = _context(reader, actor=OTHER_ID).json()["data"]
    assert first == second
    assert set(first) == {"game", "scenario", "players", "public_events"}
    assert first["game"]["mafia_count"] == 1
    assert first["game"]["last_sequence"] == 3
    assert _context(reader, actor=None).json()["subject_type"] == "GM"
    assert _context(reader, actor=None).json()["subject_id"] == GAME_ID
    assert reader.fact_calls == []


@pytest.mark.parametrize("role,self_allowed", [("DETECTIVE", False), ("MAFIA", False), ("DOCTOR", True)])
def test_night_turn_targets_follow_only_own_role(role, self_allowed):
    reader = _reader()
    reader.game["phase"] = "NIGHT_ACTION"
    reader.window.update(phase="NIGHT_ACTION", window_kind="NIGHT", cycle=1,
                         turn_player_id=None, deadline_at=NOW + timedelta(hours=1))
    reader.players[1]["role"] = role
    data = _context(reader, "turn").json()["data"]
    targets = {target["player_id"] for target in data["valid_targets"]}
    assert (str(ACTOR_ID) in targets) == self_allowed
    assert data["allowed_tools"] == ["propose_night_action"]
    reader.window["deadline_at"] = NOW - timedelta(seconds=1)
    assert _context(reader, "turn").status_code == 409


def _event_row(sequence=1, *, audience="PUBLIC", player_id=None,
               event_type="PLAYER_PASSED", payload=None, operation="APPEND_PUBLIC_EVENT"):
    """audience와 cursor의 손상 조건을 개별 변경할 수 있는 합성 원장 행이다."""

    return {
        "id": UUID(int=100 + sequence), "game_id": UUID(GAME_ID), "sequence": sequence,
        "front_sequence": 3, "operation_index": sequence - 1, "state_version": 7,
        "audience": audience, "audience_player_id": player_id, "schema_version": 1,
        "event_type": event_type, "operation_type": operation,
        "payload": payload if payload is not None else {"player_id": str(ACTOR_ID)},
        "created_at": NOW,
    }


def test_actor_private_events_recheck_game_audience_bounds_and_remove_extra_fields():
    reader = _reader()
    own = _event_row(audience="PLAYER", player_id=ACTOR_ID, event_type="INVESTIGATION_RESULT",
                     operation=None, payload={"round": 1, "target_player_id": str(OTHER_ID), "is_mafia": False,
                                              "raw_response": "합성 비공개 원문"})
    reader.private_rows = [
        {**own, "audience_player_id": OTHER_ID},
        {**own, "game_id": UUID(int=987)},
        {**own, "state_version": 8}, {**own, "sequence": 5},
        {**own, "audience": "PUBLIC"}, own, own,
    ]
    first = _context(reader, "me").json()["data"]
    assert first["private_events"] == [{
        "event_id": str(own["id"]), "event_type": "INVESTIGATION_RESULT",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "data": {"round": 1, "target_player_id": str(OTHER_ID), "is_mafia": False},
    }]
    reader.private_rows[0]["payload"] = {"round": 1, "target_player_id": str(ACTOR_ID), "is_mafia": True}
    assert _context(reader, "me").json()["data"] == first
    assert reader.connection.read_only is True
    from psycopg import IsolationLevel
    assert reader.connection.isolation_level is IsolationLevel.REPEATABLE_READ


def test_public_context_strips_unapproved_event_payload_and_reveals_only_executed_roles():
    reader = _reader()
    reader.public_rows = [
        _event_row(payload={"player_id": str(ACTOR_ID), "role": "DETECTIVE"}),
        _event_row(2, event_type="ACTION_RESOLVED", payload={"target_player_id": str(OTHER_ID)}),
    ]
    reader.players[2].update(alive=False, eliminated_phase="NIGHT_ACTION", eliminated_round=1)
    reader.players[3].update(alive=False, eliminated_phase="DAY_VOTE", eliminated_round=1)
    data = _context(reader).json()["data"]
    assert data["public_events"][0]["data"] == {"player_id": str(ACTOR_ID)}
    assert len(data["public_events"]) == 1
    assert data["players"][2]["revealed_role"] is None
    assert data["players"][3]["revealed_role"] == "CITIZEN"
    assert data["players"][2]["eliminated_round"] == 1


@pytest.mark.parametrize("change", [
    {"parameters": {**PARAMETERS, "hidden": 0.5}},
    {"parameters": {**PARAMETERS, "reasoning_skill": 1.1}},
    {"parameters": {**PARAMETERS, "reasoning_skill": -0.1}},
    {"parameters": {**PARAMETERS, "reasoning_skill": float("inf")}},
    {"parameters": {**PARAMETERS, "reasoning_skill": True}},
    {"parameters": {**PARAMETERS, "suspicion": float("nan")}},
    {"parameters": {**PARAMETERS, "verbosity": True}},
    {"speech_style": ""},
])
def test_persona_rejects_unapproved_parameters_and_missing_content(change):
    reader = _reader()
    reader.personas[0].update(change)
    assert _context(reader, "persona").status_code == 403


@pytest.mark.parametrize("reasoning_skill", [0.5, 0.6, 0.7, 0.75, 0.8])
def test_persona_preserves_legacy_and_distinct_reasoning_values(reasoning_skill):
    """기존 게임의 0.5와 새 성향을 허용하되 타인의 배정값과 원문을 바꾸지 않는다."""

    reader = _reader()
    reader.personas[0]["parameters"] = {**PARAMETERS, "reasoning_skill": reasoning_skill}
    original = deepcopy(reader.personas)

    response = _context(reader, "persona")

    assert response.status_code == 200
    assert response.json()["data"]["parameters"] == {**PARAMETERS, "reasoning_skill": reasoning_skill}
    assert _context(reader, "persona", OTHER_ID).json()["data"]["parameters"] == PARAMETERS
    assert reader.personas == original


@pytest.mark.parametrize("phase,kind,action", [
    ("NIGHT_ACTION", "NIGHT", "INVESTIGATE"), ("DAY_VOTE", "VOTE", "VOTE"),
    ("FINAL_ACCUSATION", "FINAL_VOTE", "VOTE"), ("DAY_DISCUSSION", "SPEECH", "PASS"),
])
def test_turn_denies_already_submitted_actor(phase, kind, action):
    reader = _reader()
    reader.game["phase"] = phase
    reader.window.update(phase=phase, window_kind=kind, cycle=1,
                         turn_player_id=ACTOR_ID if kind == "SPEECH" else None,
                         deadline_at=None if kind == "SPEECH" else NOW + timedelta(hours=1))
    reader.submissions = [{"actor_player_id": ACTOR_ID, "action_type": action, "target_player_id": OTHER_ID}]
    assert _context(reader, "turn").status_code == 403


def test_revote_turn_uses_persisted_tied_candidates_and_fails_when_missing():
    reader = _reader()
    reader.game["phase"] = "REVOTE"
    reader.window.update(phase="REVOTE", window_kind="REVOTE", cycle=1,
                         turn_player_id=None, deadline_at=NOW + timedelta(hours=1))
    resolution = {"game_id": UUID(GAME_ID), "resolved_state_version": 5, "resolution_type": "VOTE", "result_payload": {
        "schema_version": 1, "phase": "DAY_VOTE", "round": 1,
        "needs_revote": True, "tied": True, "tied_candidates": [str(ACTOR_ID), str(OTHER_ID)],
        "ballots": [{"actor_player_id": str(ACTOR_ID), "target_player_id": str(OTHER_ID), "is_auto": False},
                    {"actor_player_id": str(OTHER_ID), "target_player_id": str(ACTOR_ID), "is_auto": False}], "counts": [{"target_player_id": str(ACTOR_ID), "vote_count": 1}, {"target_player_id": str(OTHER_ID), "vote_count": 1}],
        "eliminated_player_id": None, "final_target_player_id": None,
    }}
    reader.list_resolutions = lambda *a, **k: [resolution]
    data = _context(reader, "turn").json()["data"]
    assert data["valid_targets"] == [{"player_id": str(OTHER_ID), "display_name": "좌석 3"}]
    reader.list_resolutions = lambda *a, **k: []
    assert _context(reader, "turn").status_code == 403


def _sync(reader, rows, *, after_version=6, after_sequence=2):
    """실제 sync service를 fake repository와 snapshot presenter로 실행한다."""

    from backend.app.services.game.event_sync_service import read_sync

    reader.list_front_events = lambda *a, **k: deepcopy(rows)
    reader.snapshot = lambda *a: {"game": {"state_version": 8, "last_sequence": 4}, "public_events": []}
    return read_sync(reader, UUID(USER_ID), UUID(GAME_ID), after_state_version=after_version, after_sequence=after_sequence)


def test_sync_wraps_human_private_event_and_preserves_front_sequence():
    """공개·개인 operation이 F5에서 수용되도록 원장의 schema와 index를 보존한다."""

    reader = _reader()
    reader.players[0]["role"] = "DETECTIVE"
    result = _sync(reader, [
        _event_row(),
        _event_row(2, audience="PLAYER", player_id=UUID(int=11), event_type="INVESTIGATION_RESULT",
                   operation="APPEND_PRIVATE_EVENT", payload={"round": 1, "target_player_id": str(OTHER_ID), "is_mafia": False}),
    ])
    assert result["mode"] == "DELTA"
    assert result["last_sequence"] == 3
    assert result["operations"][0]["front_sequence"] == 3
    operations = result["operations"][0]["operations"]
    assert [operation["schema_version"] for operation in operations] == [1, 1]
    assert [operation["operation_index"] for operation in operations] == [0, 1]
    assert all(set(operation) == {"schema_version", "operation_index", "type", "payload"} for operation in operations)
    private = result["operations"][0]["operations"][1]
    assert private["operation_index"] == 1
    assert set(private["payload"]) == {"event_id", "event_type", "created_at", "data"}
    assert private["payload"]["data"]["is_mafia"] is False


@pytest.mark.parametrize("change", [
    {"event_type": "ACTION_RESOLVED", "payload": {"target_player_id": str(OTHER_ID)}},
    {"event_type": "UNKNOWN"}, {"schema_version": 2},
    {"payload": {"player_id": str(ACTOR_ID), "role": "DETECTIVE"}},
    {"audience": "PLAYER", "audience_player_id": ACTOR_ID, "operation_type": "APPEND_PRIVATE_EVENT"},
    {"game_id": UUID(int=987)}, {"operation_index": 1}, {"front_sequence": 4},
    {"state_version": 8}, {"operation_type": "SET_RESULT", "payload": {"secret": "합성 비공개 자료"}},
])
def test_sync_unsafe_or_partial_batch_uses_current_snapshot_without_raw_payload(change):
    result = _sync(_reader(), [{**_event_row(), **change}])
    assert result["mode"] == "SNAPSHOT"
    assert result["operations"] == []
    assert result["state_version"] == result["snapshot"]["game"]["state_version"] == 8
    assert result["last_sequence"] == result["snapshot"]["game"]["last_sequence"] == 4


def test_sync_unchanged_cursor_stays_put():
    result = _sync(_reader(), [], after_version=7, after_sequence=3)
    assert result["mode"] == "DELTA"
    assert result["operations"] == []
    assert result["state_version"] == 7
    assert result["last_sequence"] == 3


def test_sse_sets_front_sequence_as_event_id():
    """stream 첫 frame의 id가 내부 event sequence가 아닌 Front cursor인지 확인한다."""

    import asyncio
    from backend.app.routers.game_router import events

    async def run():
        async def connected():
            return False
        runtime = SimpleNamespace(sync=lambda *a, **k: {
            "mode": "DELTA", "operations": [{"front_sequence": 3}], "state_version": 7, "last_sequence": 3,
        })
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(game_runtime=runtime)), is_disconnected=connected)
        response = await events(request, UUID(GAME_ID), x_user_id=USER_ID, last_event_id=2)
        frame = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        assert frame.startswith("id: 3\nevent: game_sync\n")
    asyncio.run(run())



@pytest.mark.parametrize("event_type,payload", [
    ("NIGHT_RESOLVED", {"round": 1, "killed_player_id": None}),
    ("VOTE_RESOLVED", {"round": 1}),
    ("PLAYER_EXECUTED", {"player_id": str(OTHER_ID), "revealed_role": "DOCTOR"}),
    ("GAME_ENDED", {"winner": "CITIZEN", "win_reason": "ALL_MAFIA_ELIMINATED"}),
])
def test_sync_resolution_requires_snapshot_for_players_and_result(event_type, payload):
    """공개 해소 문장만 적용하고 생존자와 종료 결과를 갱신하지 않는 delta를 막는다."""

    result = _sync(_reader(), [_event_row(event_type=event_type, payload=payload)])
    assert result["mode"] == "SNAPSHOT"
    assert result["operations"] == []


def test_sync_empty_window_hint_requires_human_snapshot():
    """writer의 빈 legal_actions hint가 인간의 실제 차례를 덮어쓰지 않게 한다."""

    payload = {
        "window_id": WINDOW_ID, "kind": "SPEECH", "cycle": 1, "paused": False,
        "opened_state_version": 7, "server_time": NOW.isoformat(), "deadline_at": None,
        "remaining_ms": None, "turn_player_id": str(ACTOR_ID), "has_submitted": False,
        "legal_actions": [], "valid_targets": [],
    }
    result = _sync(_reader(), [_event_row(event_type="TURN_OPENED", operation="SET_ACTION_WINDOW", payload=payload)])
    assert result["mode"] == "SNAPSHOT"


def test_sync_page_limit_does_not_publish_a_truncated_final_batch():
    """index가 연속인 LIMIT 경계도 마지막 operation 누락 여부를 추측하지 않는다."""

    result = _sync(_reader(), [_event_row(index) for index in range(1, 501)])
    assert result["mode"] == "SNAPSHOT"
    assert result["operations"] == []


def test_context_serialization_drops_extra_event_fields_and_duplicates():
    """projection을 직접 재사용해도 event 추가 field·중복 ID가 scope에 들어가지 않는다."""

    from backend.app.agent.projections import build_context
    from backend.app.services.game.game_read_service import initial_record_from_rows

    reader = _reader()
    record = initial_record_from_rows(keyring=reader._keyring, game=reader.game, player_rows=reader.players)
    event = {"event_id": str(UUID(int=101)), "event_type": "PLAYER_PASSED", "created_at": NOW.isoformat(),
             "data": {"player_id": str(ACTOR_ID), "role": "DETECTIVE"}, "private": "합성 비공개 자료"}
    context = build_context(record.state, subject_type="AI_PLAYER", subject_id=ACTOR_ID, scope="public",
                            window_id=UUID(WINDOW_ID), scenario={**record.scenario, "hidden_role": "MAFIA"}, public_events=[event, event])
    assert len(context["data"]["public_events"]) == 1
    assert set(context["data"]["public_events"][0]) == {"event_id", "event_type", "created_at", "data"}
    assert context["data"]["public_events"][0]["data"] == {"player_id": str(ACTOR_ID)}
    assert "hidden_role" not in context["data"]["scenario"]



@pytest.mark.parametrize("role", ["CITIZEN", "DOCTOR", "MAFIA"])
def test_private_investigation_requires_recipients_detective_role(role):
    reader = _reader()
    reader.players[1]["role"] = role
    reader.private_rows = [_event_row(audience="PLAYER", player_id=ACTOR_ID, operation=None,
                                      event_type="INVESTIGATION_RESULT", payload={"round": 1, "target_player_id": str(OTHER_ID), "is_mafia": False})]
    assert _context(reader, "me").json()["data"]["private_events"] == []


def test_actor_turn_rejects_first_day_extra_cycle():
    reader = _reader()
    reader.game["day_number"] = 1
    assert _context(reader, "turn").status_code == 409



@pytest.mark.parametrize("candidate_ids", [None, (), (UUID(int=987),), (OTHER_ID, OTHER_ID), (ACTOR_ID,)])
def test_turn_projection_rejects_missing_or_invalid_service_candidates(candidate_ids):
    """서비스 후보가 없거나 잘못돼도 projection이 엔진 후보를 임의 계산하지 않는다."""

    from backend.app.agent.projections import build_context
    from backend.app.services.game.game_read_service import initial_record_from_rows

    reader = _reader()
    reader.game["phase"] = "DAY_VOTE"
    reader.window.update(phase="DAY_VOTE", window_kind="VOTE", turn_player_id=None,
                         deadline_at=NOW + timedelta(hours=1))
    record = initial_record_from_rows(keyring=reader._keyring, game=reader.game, player_rows=reader.players)
    with pytest.raises(PermissionError, match="CAPABILITY_DENIED"):
        build_context(record.state, subject_type="AI_PLAYER", subject_id=ACTOR_ID, scope="turn",
                      window_id=UUID(WINDOW_ID), window=reader.window, now=NOW, valid_target_ids=candidate_ids)


def test_turn_projection_preserves_service_candidate_subset_and_public_fields():
    """서비스가 좁힌 후보를 전체 생존자로 넓히거나 비공개 role을 반환하지 않는다."""

    from backend.app.agent.projections import build_context
    from backend.app.services.game.game_read_service import initial_record_from_rows

    reader = _reader()
    reader.game["phase"] = "DAY_VOTE"
    reader.window.update(phase="DAY_VOTE", window_kind="VOTE", turn_player_id=None,
                         deadline_at=NOW + timedelta(hours=1))
    record = initial_record_from_rows(keyring=reader._keyring, game=reader.game, player_rows=reader.players)
    context = build_context(record.state, subject_type="AI_PLAYER", subject_id=ACTOR_ID, scope="turn",
                            window_id=UUID(WINDOW_ID), window=reader.window, now=NOW, valid_target_ids=(OTHER_ID,))
    assert context["data"]["valid_targets"] == [{"player_id": str(OTHER_ID), "display_name": "좌석 3"}]
