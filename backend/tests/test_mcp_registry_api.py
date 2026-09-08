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
        self.public_history_cache_calls = []
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

    def cache_public_history(self, record, *, through_sequence, events) -> bool:
        """공개 projection과 snapshot 상한을 기록하고 cache 미설정의 False를 반환한다.

        운영 읽기 서비스처럼 cache 저장 여부는 context 반환 성공과 독립적이다.
        전달 자료를 복사해 응답 변경이 cache 호출 검증에 영향을 주지 않게 한다.
        """

        self.public_history_cache_calls.append({
            "game_id": str(record.state.game_id),
            "state_version": record.state.state_version,
            "through_sequence": through_sequence,
            "front_sequence": record.front_sequence,
            "events": deepcopy(events),
        })
        return False

    def list_snapshot_private_events(self, cursor, **kwargs):
        return deepcopy(self.private_rows)

    def list_player_facts(self, cursor, *, game_id, player_id):
        self.fact_calls.append((game_id, player_id))
        return deepcopy(self.facts[player_id])

    def list_active_personas(self, cursor, **kwargs):
        return deepcopy(self.personas)


def _reader():
    return ReaderFixture()


def _special_role_reader():
    """능력 보유자의 소유권·첫 밤 경계를 검사할 합성 저장 행을 만든다."""

    reader = _reader()
    reader.game["mode"] = "CUSTOM_ROLE"
    reader.players[0].update(
        role="CITIZEN", faction="CITIZEN", custom_role_name="직업 기록관",
        custom_role_catalog_version="custom-role-v1",
        custom_ability_ids=["intel.special_roles.v1"],
    )
    reader.players[-1]["role"] = "MAFIA"
    return reader


def _special_roles(reader, **params):
    """운영 route가 저장 snapshot에서 직접 최소 응답을 만드는지 확인한다."""

    runtime = FakeMcpRuntime()
    runtime._read = reader
    application = create_app(enable_background_worker=False)
    application.state.game_runtime = runtime
    return TestClient(application).get(
        "/internal/mcp/special-roles",
        params={"game_id": GAME_ID, "user_id": USER_ID, **params},
    )


def test_special_roles_returns_only_special_roster_after_first_night():
    reader = _special_role_reader()
    reader.players[2].update(alive=False, eliminated_phase="NIGHT_ACTION", eliminated_round=1)
    before = deepcopy((reader.game, reader.players))
    response = _special_roles(reader)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "game_id": GAME_ID, "player_id": str(reader.players[0]["id"]),
        "ability_id": "intel.special_roles.v1", "state_version": 7,
        "roles": [
            {"player_id": str(row["id"]), "display_name": row["display_name"],
             "role": row["role"], "alive": row["alive"]}
            for row in reader.players[1:3]
        ],
    }
    assert reader.connection.read_only is True
    assert reader.fact_calls == []
    assert (reader.game, reader.players) == before
    assert _special_roles(reader).json() == response.json()


@pytest.mark.parametrize("phase,round_number,day_number,expected", [
    ("ROLE_REVEAL", 0, 1, 409), ("DAY_DISCUSSION", 0, 1, 409),
    ("NIGHT_ACTION", 1, 1, 409), ("DAY_DISCUSSION", 1, 2, 200),
    ("NIGHT_ACTION", 2, 2, 200),
])
def test_special_roles_unlocks_only_when_first_night_has_finished(
    phase, round_number, day_number, expected,
):
    reader = _special_role_reader()
    reader.game.update(phase=phase, round=round_number, day_number=day_number)
    response = _special_roles(reader)
    assert response.status_code == expected
    if expected != 200:
        assert response.json()["error"]["code"] == "ABILITY_NOT_AVAILABLE"


@pytest.mark.parametrize("change,expected,code", [
    ("unowned", 404, "GAME_NOT_FOUND"),
    ("standard", 403, "ABILITY_NOT_ALLOWED"),
    ("unowned_ability", 403, "ABILITY_NOT_ALLOWED"),
    ("dead", 409, "ABILITY_NOT_AVAILABLE"),
    ("saved", 409, "ABILITY_NOT_AVAILABLE"),
    ("completed", 409, "ABILITY_NOT_AVAILABLE"),
    ("failed", 409, "ABILITY_NOT_AVAILABLE"),
    ("foreign_human", 403, "ABILITY_NOT_ALLOWED"),
    ("ai", 403, "ABILITY_NOT_ALLOWED"),
])
def test_special_roles_fails_closed_without_private_output(change, expected, code):
    reader = _special_role_reader()
    params = {}
    if change == "unowned":
        params["user_id"] = str(UUID(int=999))
    elif change == "standard":
        reader.game["mode"] = "STANDARD"
        for key in ("custom_role_name", "custom_role_catalog_version", "custom_ability_ids"):
            reader.players[0][key] = None
    elif change == "unowned_ability":
        reader.players[0]["custom_ability_ids"] = ["night.protect.v1"]
    elif change == "dead":
        reader.players[0].update(alive=False, eliminated_phase="NIGHT_ACTION", eliminated_round=1)
    elif change in {"saved", "completed", "failed"}:
        reader.game["status"] = change.upper()
    elif change == "foreign_human":
        reader.players[0]["user_id"] = UUID(int=999)
    elif change == "ai":
        reader.players[0]["kind"] = "AI"
    response = _special_roles(reader, **params)
    assert response.status_code == expected
    assert response.json()["error"]["code"] == code
    assert "roles" not in response.json()
    assert "DETECTIVE" not in response.text
    assert "DOCTOR" not in response.text
    assert reader.fact_calls == []


def test_special_roles_rejects_arbitrary_actor_query():
    response = _special_roles(_special_role_reader(), player_id=str(ACTOR_ID))
    assert response.status_code == 422


@pytest.mark.parametrize("action,player_id", [("VOTE", str(ACTOR_ID)), ("PASS", None),
                                               ("NIGHT_ACTION", None)])
def test_triple_vote_mcp_input_rejects_ai_and_unrelated_actions(action, player_id):
    response = _client().post("/internal/mcp/actions", json={
        "action": action, "player_id": player_id, "user_id": USER_ID, "game_id": GAME_ID,
        "window_id": WINDOW_ID, "expected_state_version": 7,
        "idempotency_key": str(UUID(int=90)), "target_player_id": str(OTHER_ID),
        "ability_id": "vote.triple.v1",
    })
    assert response.status_code == 422


def test_triple_vote_mcp_forwards_fixed_ability_to_human_command():
    from unittest.mock import MagicMock

    client = _client()
    command = MagicMock(return_value=({"command_type": "SUBMIT_VOTE"}, False))
    client.app.state.game_runtime.command = command
    response = client.post("/internal/mcp/actions", json={
        "action": "VOTE", "user_id": USER_ID, "game_id": GAME_ID,
        "window_id": WINDOW_ID, "expected_state_version": 7,
        "idempotency_key": str(UUID(int=90)), "target_player_id": str(OTHER_ID),
        "ability_id": "vote.triple.v1",
    })
    assert response.status_code == 200
    args = command.call_args.args
    assert args[:2] == (UUID(USER_ID), UUID(GAME_ID))
    assert args[2].type == "SUBMIT_VOTE"
    assert args[2].ability_id == "vote.triple.v1"
    assert args[2].target_player_id == OTHER_ID


@pytest.mark.parametrize("command,ability", [
    ("PASS", "vote.triple.v1"), ("SAVE_AND_EXIT", "vote.triple.v1"),
    ("SUBMIT_NIGHT_ACTION", "vote.triple.v1"), ("SUBMIT_VOTE", "night.protect.v1"),
])
def test_custom_ability_cannot_be_ignored_by_an_unrelated_command(command, ability):
    from pydantic import ValidationError

    from backend.app.schemas.command_schema import GameCommandRequest

    with pytest.raises(ValidationError):
        GameCommandRequest(type=command, expected_state_version=7, ability_id=ability)


@pytest.mark.parametrize("change", ["unknown_ability", "unknown_catalog", "foreign_player", "invalid_alive"])
def test_special_roles_rejects_corrupt_storage_without_leaking_roles(change):
    reader = _special_role_reader()
    if change == "unknown_ability":
        reader.players[0]["custom_ability_ids"].append("intel.unknown.v1")
    elif change == "unknown_catalog":
        reader.players[0]["custom_role_catalog_version"] = "unknown"
    elif change == "foreign_player":
        reader.players[2]["game_id"] = UUID(int=999)
    else:
        reader.players[2]["alive"] = "false"
    response = _special_roles(reader)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "DETECTIVE" not in response.text
    assert "DOCTOR" not in response.text


@pytest.mark.asyncio
async def test_custom_tools_cross_real_mcp_adapter_and_backend_routes():
    """MCP 등록·HTTP 직렬화·실제 Backend 검증을 함께 통과시키며 외부 서버는 쓰지 않는다."""

    import json
    from unittest.mock import MagicMock

    import httpx
    from mcp.server.fastmcp.exceptions import ToolError

    from mafia_game.integrations.engine_http import MinimalBackendContextClient
    from mafia_game.main import create_fastmcp_server

    reader = _special_role_reader()
    application = create_app(enable_background_worker=False)
    runtime = FakeMcpRuntime()
    runtime._read = reader
    runtime.command = MagicMock(return_value=({"command_type": "SUBMIT_VOTE"}, False))
    application.state.game_runtime = runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application)) as http:
        server = create_fastmcp_server(MinimalBackendContextClient("http://127.0.0.1:8000", client=http))
        result = await server.call_tool("inspect_special_roles", {"user_id": USER_ID, "game_id": GAME_ID})
        payload = json.loads(result[0][0].text)
        assert [entry["role"] for entry in payload["roles"]] == ["DETECTIVE", "DOCTOR"]
        reader.game.update(day_number=1, phase="NIGHT_ACTION")
        with pytest.raises(ToolError, match="MCP_BACKEND_HTTP_409"):
            await server.call_tool("inspect_special_roles", {"user_id": USER_ID, "game_id": GAME_ID})
        await server.call_tool("manipulate_vote", {
            "user_id": USER_ID, "game_id": GAME_ID, "expected_state_version": 7,
            "window_id": WINDOW_ID, "idempotency_key": str(UUID(int=90)),
            "target_player_id": str(OTHER_ID),
        })
        assert runtime.command.call_args.args[2].ability_id == "vote.triple.v1"


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
    assert reader.public_history_cache_calls == []


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
    assert reader.public_history_cache_calls == [{
        "game_id": GAME_ID, "state_version": 7, "through_sequence": 4,
        "front_sequence": 3, "events": data["public_events"],
    }]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_method,http_method,path,payload", [
    ("snapshot", "GET", f"/api/v1/games/{GAME_ID}", None),
    ("command", "POST", f"/api/v1/games/{GAME_ID}/commands",
     {"type": "BEGIN_GAME", "expected_state_version": 1}),
    ("sync", "GET", f"/api/v1/games/{GAME_ID}/sync?after_state_version=0&after_sequence=0", None),
    ("create", "POST", "/api/v1/games",
     {"player_count": 6, "ruleset_version": "mystery-v1", "scenario_version": "scenario-v1"}),
    ("list_games", "GET", "/api/v1/games", None),
    ("feedback", "POST", "/api/v1/feedback", {"feedback_type": "GENERAL", "rating": 3}),
], ids=["snapshot", "command", "sync", "create", "list", "feedback"])
async def test_public_game_storage_does_not_delay_mcp_context(
    monkeypatch, runtime_method, http_method, path, payload,
):
    """사용자 요청의 저장소 대기 중에도 같은 앱의 MCP 조회가 먼저 완료되어야 한다."""

    import asyncio
    from threading import Event

    import httpx
    from fastapi import FastAPI

    from backend.app.routers.game_router import feedback_router, router as game_router
    from backend.app.routers.mcp_registry_router import router as mcp_router

    entered, release, finished = Event(), Event(), Event()

    def blocked_storage(*args, **kwargs):
        """실제 DB 없이 대기 경계를 만들며 회귀가 있어도 제한 시간 뒤 스레드를 해제한다."""

        entered.set()
        try:
            release.wait(timeout=2)
            if runtime_method == "list_games":
                return []
            result = {"game_id": GAME_ID}
            return (result, False) if runtime_method in {"create", "command", "feedback"} else result
        finally:
            finished.set()

    context = {"scope": "public", "data": {"game": {"game_id": GAME_ID}, "public_events": []}}
    # 이번 검증은 HTTP 동시성 경계만 다룬다. 실제 projection·DB fixture와 분리해
    # 사용자 저장소가 대기하는 동안 내부 MCP 응답을 전달할 수 있는지 확인한다.
    monkeypatch.setattr("backend.app.routers.mcp_registry_router.read_actor_context",
                        lambda *args, **kwargs: context)
    application = FastAPI()
    application.state.game_runtime = SimpleNamespace(
        _read=object(), _agent_repository=object(), **{runtime_method: blocked_storage},
    )
    application.include_router(game_router)
    application.include_router(feedback_router)
    application.include_router(mcp_router)
    headers = {"X-User-Id": USER_ID, "Idempotency-Key": "00000000-0000-4000-8000-000000000004"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                base_url="http://synthetic.invalid") as client:
        slow_request = asyncio.create_task(client.request(http_method, path, headers=headers, json=payload))
        try:
            assert await asyncio.to_thread(entered.wait, 1), "합성 저장소 호출이 시작되지 않았습니다."
            response = await asyncio.wait_for(client.get(
                "/internal/mcp/context", params={"game_id": GAME_ID, "user_id": USER_ID},
            ), timeout=1)
            assert response.status_code == 200 and response.json() == context
            assert not finished.is_set(), "사용자 저장소 대기가 끝날 때까지 MCP 응답이 막혔습니다."
        finally:
            release.set()
            slow_response = await asyncio.wait_for(slow_request, timeout=3)
        assert slow_response.status_code == (201 if runtime_method in {"create", "feedback"} else 200)


def _public_special_roles(reader, *, game_id=GAME_ID, user_id=USER_ID, params=None, content=None):
    """실제 공개 facade와 권위 조회를 합성 저장소로 연결해 외부 서비스 없이 검증한다."""

    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    runtime = object.__new__(PostgresGameRuntime)
    runtime._read = reader
    application = create_app(enable_background_worker=False)
    application.state.game_runtime = runtime
    return TestClient(application).request(
        "GET", f"/api/v1/games/{game_id}/special-roles",
        headers={} if user_id is None else {"X-User-Id": user_id},
        params=params, content=content,
    )


def test_public_special_roles_envelope_matches_internal_read_only_projection():
    """공개 응답은 같은 최소 정보만 감싸며 쓰기·사건·cache·AI 경로를 호출하지 않는다."""

    from psycopg import IsolationLevel
    from unittest.mock import Mock

    reader = _special_role_reader()
    reader.players[2].update(alive=False, eliminated_phase="NIGHT_ACTION", eliminated_round=1)
    reader.players.reverse()
    before = deepcopy((reader.game, reader.players, reader.public_rows, reader.private_rows, reader.submissions))
    forbidden = Mock(side_effect=AssertionError("조회는 쓰기 또는 다른 projection을 호출하면 안 됩니다."))
    reader.execute = forbidden
    reader._events = reader._actions = reader._agents = reader._conversation_history = forbidden
    response = _public_special_roles(reader)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"data", "meta"}
    assert set(payload["meta"]) == {"request_id", "server_time", "replayed"}
    assert payload["meta"]["replayed"] is False
    assert payload["meta"]["request_id"] == response.headers["x-request-id"]
    assert set(payload["data"]) == {"game_id", "player_id", "ability_id", "state_version", "roles"}
    assert payload["data"] == _special_roles(reader).json()
    assert [row["role"] for row in payload["data"]["roles"]] == ["DETECTIVE", "DOCTOR"]
    assert payload["data"]["roles"][1]["alive"] is False
    assert all(set(row) == {"player_id", "display_name", "role", "alive"} for row in payload["data"]["roles"])
    assert reader.connection.read_only is True
    assert reader.connection.isolation_level is IsolationLevel.REPEATABLE_READ
    assert (reader.game, reader.players, reader.public_rows, reader.private_rows, reader.submissions) == before
    assert reader.fact_calls == []
    assert forbidden.mock_calls == []


@pytest.mark.parametrize("change,status,code", [
    ("other_user", 404, "GAME_NOT_FOUND"), ("missing", 404, "GAME_NOT_FOUND"),
    ("standard", 403, "ABILITY_NOT_ALLOWED"), ("unowned_ability", 403, "ABILITY_NOT_ALLOWED"),
    ("foreign_human", 403, "ABILITY_NOT_ALLOWED"), ("ai", 403, "ABILITY_NOT_ALLOWED"),
    ("dead", 409, "ABILITY_NOT_AVAILABLE"), ("day1", 409, "ABILITY_NOT_AVAILABLE"),
    ("SAVED", 409, "ABILITY_NOT_AVAILABLE"), ("COMPLETED", 409, "ABILITY_NOT_AVAILABLE"),
    ("FAILED", 409, "ABILITY_NOT_AVAILABLE"), ("storage", 503, "DEPENDENCY_UNAVAILABLE"),
])
def test_public_special_roles_denials_are_private_and_not_cached(change, status, code):
    """권한·상태·저장소 거부 의미를 유지하고 오류에서 비공개 정보와 원문을 제거한다."""

    reader = _special_role_reader()
    kwargs = {}
    if change == "other_user":
        kwargs["user_id"] = "00000000-0000-4000-8000-000000000999"
    elif change == "missing":
        reader.game = None
    elif change == "standard":
        reader.game["mode"] = "STANDARD"
    elif change == "unowned_ability":
        reader.players[0]["custom_ability_ids"] = ["night.protect.v1"]
    elif change == "foreign_human":
        reader.players[0]["user_id"] = UUID(int=999)
    elif change == "ai":
        reader.players[0]["kind"] = "AI"
    elif change == "dead":
        reader.players[0].update(alive=False, eliminated_phase="NIGHT_ACTION", eliminated_round=1)
    elif change == "day1":
        reader.game["day_number"] = 1
    elif change == "storage":
        from unittest.mock import Mock
        reader.get_owned_game = Mock(side_effect=RuntimeError("synthetic-private-storage-error"))
    else:
        reader.game["status"] = change
    response = _public_special_roles(reader, **kwargs)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == code
    assert all(value not in response.text for value in ("roles", "DETECTIVE", "DOCTOR", "synthetic-private-storage-error"))


@pytest.mark.parametrize("kwargs,status,code", [
    ({"user_id": None}, 400, "MISSING_USER_ID"),
    ({"user_id": "invalid"}, 400, "INVALID_REQUEST"),
    ({"user_id": str(UUID(int=999))}, 400, "INVALID_REQUEST"),
    ({"game_id": "invalid"}, 422, "INVALID_REQUEST"),
    ({"params": {"user_id": USER_ID}}, 422, "INVALID_REQUEST"),
    ({"params": {"player_id": str(ACTOR_ID)}}, 422, "INVALID_REQUEST"),
    ({"params": {"unexpected": ""}}, 422, "INVALID_REQUEST"),
    ({"content": '{"user_id":"synthetic"}'}, 422, "INVALID_REQUEST"),
])
def test_public_special_roles_invalid_input_never_reads_storage(kwargs, status, code):
    """식별자·추가 입력은 저장소 접근 전에 거부하고 validation 응답도 캐시하지 않는다."""

    from unittest.mock import Mock

    reader = _special_role_reader()
    reader._transactions = Mock(side_effect=AssertionError("입력 검증 실패는 DB에 접근하면 안 됩니다."))
    response = _public_special_roles(reader, **kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert reader._transactions.mock_calls == []
