"""WU-B16 자유 직업의 거부·호환·순수 규칙 계약 테스트."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rules.victory_rules import standard_winner
from backend.app.models.enums import Faction, GamePhase, NightActionType, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, NightAction, PlayerState
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.creation_service import build_initial_game


def _request(**changes):
    body = {
        "player_count": 6,
        "ruleset_version": "mystery-v1",
        "scenario_version": "scenario-v1",
        **changes,
    }
    return CreateGameRequest.model_validate(body)


def test_standard_request_remains_compatible_and_rejects_custom_payload() -> None:
    assert _request().mode == "STANDARD"
    with pytest.raises(ValidationError):
        _request(custom_role={
            "name": "의사", "faction": "CITIZEN",
            "catalog_version": "custom-role-v1",
            "ability_ids": ["night.protect.v1"],
        })


@pytest.mark.parametrize("custom_role", [
    {"name": "x", "faction": "CITIZEN", "catalog_version": "custom-role-v1",
     "ability_ids": ["night.attack.v1"]},
    {"name": "x", "faction": "MAFIA", "catalog_version": "custom-role-v1",
     "ability_ids": ["night.investigate.v1"]},
    {"name": "x", "faction": "CITIZEN", "catalog_version": "custom-role-v1",
     "ability_ids": ["night.protect.v1", "night.protect.v1"]},
    {"name": "x\n지시", "faction": "CITIZEN", "catalog_version": "custom-role-v1",
     "ability_ids": ["night.protect.v1"]},
])
def test_custom_role_fails_closed(custom_role) -> None:
    with pytest.raises(ValidationError):
        _request(mode="CUSTOM_ROLE", custom_role=custom_role)


def test_custom_role_name_is_nfc_and_whitespace_normalized() -> None:
    request = _request(mode="CUSTOM_ROLE", custom_role={
        "name": "  e\u0301\u2003 감식관  ", "faction": "CITIZEN",
        "catalog_version": "custom-role-v1",
        "ability_ids": ["night.investigate.v1"],
    })
    assert request.custom_role.name == "é 감식관"


def test_faction_drives_winner_for_custom_player() -> None:
    players = [
        PlayerState(uuid4(), 1, PlayerRole.CITIZEN, PlayerKind.HUMAN,
                    custom_role_name="잠입자", custom_ability_ids=("night.attack.v1",),
                    custom_faction=Faction.MAFIA),
        PlayerState(uuid4(), 2, PlayerRole.CITIZEN),
    ]
    state = GameState(uuid4(), b"seed", players)
    assert standard_winner(state) == (Faction.MAFIA, standard_winner(state)[1])


def test_multiple_protectors_form_a_target_set_and_investigations_use_faction() -> None:
    attacker = PlayerState(uuid4(), 1, PlayerRole.MAFIA)
    victim = PlayerState(uuid4(), 2, PlayerRole.CITIZEN)
    first = PlayerState(uuid4(), 3, PlayerRole.DOCTOR)
    second = PlayerState(uuid4(), 4, PlayerRole.CITIZEN,
                         custom_ability_ids=("night.protect.v1",), custom_faction=Faction.CITIZEN)
    detective = PlayerState(uuid4(), 5, PlayerRole.DETECTIVE)
    extra = PlayerState(uuid4(), 6, PlayerRole.CITIZEN)
    state = GameState(uuid4(), b"seed", [attacker, victim, first, second, detective, extra],
                      phase=GamePhase.NIGHT_ACTION, round=1, mode="CUSTOM_ROLE")
    state.night_actions = {
        attacker.player_id: NightAction(attacker.player_id, NightActionType.ATTACK, victim.player_id),
        first.player_id: NightAction(first.player_id, NightActionType.PROTECT, extra.player_id),
        second.player_id: NightAction(second.player_id, NightActionType.PROTECT, victim.player_id),
        detective.player_id: NightAction(detective.player_id, NightActionType.INVESTIGATE, attacker.player_id),
    }
    GameEngine().resolve_night(state)
    assert victim.alive is True
    assert state.last_detective_result[detective.player_id] is True


def test_custom_actor_can_choose_nonfirst_saved_ability_once_per_night() -> None:
    actor = PlayerState(
        uuid4(), 1, PlayerRole.CITIZEN, PlayerKind.HUMAN,
        custom_role_name="감식 수호자",
        custom_ability_ids=("night.investigate.v1", "night.protect.v1"),
        custom_faction=Faction.CITIZEN,
    )
    target = PlayerState(uuid4(), 2, PlayerRole.CITIZEN)
    others = [PlayerState(uuid4(), seat, PlayerRole.CITIZEN) for seat in range(3, 7)]
    state = GameState(
        uuid4(), b"seed", [actor, target, *others],
        phase=GamePhase.NIGHT_ACTION, round=1, mode="CUSTOM_ROLE",
    )
    GameEngine().submit_night_action(
        state, actor.player_id, NightActionType.PROTECT, actor.player_id,
    )
    assert state.night_actions[actor.player_id].action_type is NightActionType.PROTECT
    with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
        GameEngine().submit_night_action(
            state, actor.player_id, NightActionType.INVESTIGATE, target.player_id,
        )


def test_custom_human_reserves_faction_slot_and_ai_special_roles() -> None:
    class Scenarios:
        def list_active(self, cursor, *, scenario_version):
            return [{"id": "s", "content_hash": "0" * 64}]

        def last_created_scenario_id(self, cursor, **kwargs):
            return None

        def list_active_templates(self, cursor, *, scenario_id):
            return [
                {"id": uuid4(), "template_kind": kind, "text_template": "단서",
                 "subject_mode": "NONE"}
                for kind in ("ALIBI", "OBSERVATION") for _ in range(6)
            ]

    class Agents:
        def list_active_personas(self, cursor, *, version):
            return [{"id": "p"}]

    service = type("Service", (), {
        "_scenarios": Scenarios(), "_agents": Agents(),
        "AGENT_CONFIG_VERSION": "agent-config-v1",
    })()
    payload = _request(mode="CUSTOM_ROLE", custom_role={
        "name": "밤 기록관", "faction": "MAFIA",
        "catalog_version": "custom-role-v1",
        "ability_ids": ["night.attack.v1", "night.investigate.v1"],
    })
    state, _, rows, _ = build_initial_game(
        service, object(), owner_user_id=uuid4(), payload=payload,
    )
    human = next(player for player in state.players if player.kind is PlayerKind.HUMAN)
    ai_roles = [player.role for player in state.players if player.kind is PlayerKind.AI]
    assert state.mode == "CUSTOM_ROLE"
    assert human.faction is Faction.MAFIA
    assert ai_roles.count(PlayerRole.MAFIA) == 0
    assert ai_roles.count(PlayerRole.DETECTIVE) == 1
    assert ai_roles.count(PlayerRole.DOCTOR) == 1
    human_row = next(row for row in rows if row.kind == "HUMAN")
    assert human_row.custom_role_name == "밤 기록관"


def _custom_service(*, abilities=None, mafia_ai=False):
    """기존 transaction 대역에 HUMAN snapshot만 추가해 실제 저장 경로를 검증한다."""
    from backend.tests.test_b3_infrastructure import _b5_action_service

    service, game, rows, window, now, connection = _b5_action_service(
        roles=["MAFIA", "MAFIA" if mafia_ai else "CITIZEN", "DETECTIVE", "DOCTOR", "CITIZEN", "CITIZEN"],
        deadline_offset=-1,
    )
    game["mode"] = "CUSTOM_ROLE"
    rows[0].update(custom_role_name="감식 잠입자", custom_role_catalog_version="custom-role-v1",
                   custom_ability_ids=abilities or ["night.attack.v1", "night.investigate.v1"], faction="MAFIA")
    return service, game, rows, window, now, connection


@pytest.mark.parametrize("role", [PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR])
def test_custom_game_standard_ai_needs_no_ability_id(role):
    from backend.app.game_engine.rules.night_rules import ability_action, role_action

    actor = PlayerState(uuid4(), 1, role)
    state = GameState(uuid4(), b"seed", [actor], mode="CUSTOM_ROLE")
    assert ability_action(state, actor.player_id, None) is role_action(state, actor.player_id)
    with pytest.raises(RuleViolation):
        ability_action(state, actor.player_id, "night.attack.v1")
    state.mode = "STANDARD"
    with pytest.raises(RuleViolation):
        ability_action(state, actor.player_id, "night.attack.v1")


@pytest.mark.parametrize("ability", ["night.investigate.v1", "night.protect.v1"])
@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("mafia_ai", [False, True])
def test_custom_nonattack_never_creates_second_faction_action(ability, automatic, mafia_ai):
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID

    service, _, rows, _, now, _ = _custom_service(abilities=[ability, "night.attack.v1"], mafia_ai=mafia_ai)
    if not automatic:
        service._actions.list_window_action_submissions.return_value = [{
            "actor_player_id": rows[0]["id"], "target_player_id": rows[4]["id"],
            "action_type": "INVESTIGATE" if "investigate" in ability else "PROTECT",
            "source": "HUMAN", "ability_id": ability,
        }]
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    resolution = service._actions.insert_resolution.call_args.kwargs
    assert (resolution["target_player_id"] is not None) is mafia_ai
    assert resolution["resolution_source"] == ("FACTION_AUTO" if mafia_ai else "SUBMISSIONS")
    stored = [call.args[1] for call in service._actions.insert_submission.call_args_list]
    human = [item for item in stored if item.actor_player_id == rows[0]["id"]]
    assert len(human) == int(automatic)
    if automatic:
        assert human[0].ability_id == ability


@pytest.mark.parametrize("ability", [None, "night.protect.v1", "night.unknown.v1"])
def test_restore_rejects_missing_unowned_or_mismatched_ability(ability):
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions

    service, game, rows, _, _, _ = _custom_service()
    state, _ = restore_locked_game(service, object(), game)
    with pytest.raises(ValueError):
        restore_action_submissions(state, [{"actor_player_id": rows[0]["id"],
            "target_player_id": rows[4]["id"], "action_type": "INVESTIGATE", "ability_id": ability}])


def test_custom_submission_store_and_restore_keep_selected_id():
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions
    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID
    from datetime import timedelta

    service, game, rows, window, now, _ = _custom_service()
    window["deadline_at"] = now + timedelta(seconds=30)
    command = GameCommandRequest(type="SUBMIT_NIGHT_ACTION", expected_state_version=10,
        window_id=window["id"], target_player_id=rows[4]["id"], ability_id="night.investigate.v1")
    service.submit(USER_ID, GAME_ID, command, uuid4(), now=now)
    stored = service._actions.insert_submission.call_args.args[1]
    assert stored.ability_id == "night.investigate.v1"
    state, _ = restore_locked_game(service, object(), game)
    restore_action_submissions(state, [{"actor_player_id": stored.actor_player_id,
        "target_player_id": stored.target_player_id, "action_type": stored.action_type,
        "ability_id": stored.ability_id}])
    assert state.night_actions[stored.actor_player_id].action_type is NightActionType.INVESTIGATE


@pytest.mark.parametrize("change", [
    "standard", "missing_name", "missing_ids", "empty_ids", "duplicate", "unknown",
    "catalog", "faction", "ai", "no_human", "two_humans", "unnormalized",
])
@pytest.mark.parametrize("path", ["locked", "snapshot"])
def test_both_restore_paths_reject_corrupt_custom_rows(change, path):
    from backend.app.services.game.postgres_helpers import restore_locked_game
    from backend.app.services.game.game_read_service import initial_record_from_rows

    service, game, rows, _, _, _ = _custom_service()
    if change == "standard": game["mode"] = "STANDARD"
    elif change == "missing_name": rows[0]["custom_role_name"] = None
    elif change == "missing_ids": rows[0]["custom_ability_ids"] = None
    elif change == "empty_ids": rows[0]["custom_ability_ids"] = []
    elif change == "duplicate": rows[0]["custom_ability_ids"] = ["night.attack.v1"] * 2
    elif change == "unknown": rows[0]["custom_ability_ids"] = ["night.unknown.v1"]
    elif change == "catalog": rows[0]["custom_role_catalog_version"] = "unknown"
    elif change == "faction": rows[0]["faction"] = "CITIZEN"
    elif change == "ai": rows[1]["custom_role_name"] = "오염"
    elif change == "no_human": rows[0]["kind"] = "AI"
    elif change == "two_humans": rows[1].update(rows[0], id=uuid4())
    elif change == "unnormalized": rows[0]["custom_role_name"] = "  이름 "
    with pytest.raises(ValueError):
        if path == "locked": restore_locked_game(service, object(), game)
        else: initial_record_from_rows(keyring=service._keyring, game=game, player_rows=rows)


def test_catalog_and_create_validation_do_not_call_database(monkeypatch):
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    import backend.app.main as main

    runtime = Mock()
    monkeypatch.setattr(main, "build_postgres_runtime", lambda _: runtime)
    client = TestClient(main.create_app(enable_background_worker=False))
    headers = {"X-User-Id": str(uuid4()), "Idempotency-Key": str(uuid4())}
    url = "/api/v1/game-config/custom-role-abilities"
    assert client.get(url).status_code == 400
    assert client.get(url, headers={"X-User-Id": "invalid"}).status_code == 400
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["catalog_version"] == "custom-role-v1"
    assert len(response.json()["data"]["abilities"]) == 5
    body = {"player_count": 6, "ruleset_version": "mystery-v1", "scenario_version": "scenario-v1"}
    response = client.post("/api/v1/games", headers=headers, json={**body, "mode": "CUSTOM_ROLE"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert runtime.mock_calls == []


def test_repository_round_trip_includes_nullable_versioned_ability():
    from unittest.mock import Mock
    from backend.app.repositories.action_repository import PostgresActionRepository, ActionSubmissionInsert

    repository, cursor = PostgresActionRepository(), Mock()
    row = {"ability_id": "night.protect.v1"}
    cursor.fetchone.return_value = row
    submission = ActionSubmissionInsert(uuid4(), uuid4(), uuid4(), "PROTECT", uuid4(),
                                         None, "AUTO", 1, "night.protect.v1")
    assert repository.insert_submission(cursor, submission) == row
    assert cursor.execute.call_args.args[1][-1] == "night.protect.v1"
    cursor.fetchall.return_value = [row]
    assert repository.list_window_action_submissions(cursor, window_id=submission.window_id) == [row]
    assert "ability_id" in cursor.execute.call_args.args[0]


def test_custom_attack_auto_is_saved_with_ability_id():
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID

    service, _, rows, _, now, _ = _custom_service()
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    stored = [call.args[1] for call in service._actions.insert_submission.call_args_list]
    human = next(item for item in stored if item.actor_player_id == rows[0]["id"])
    assert human.action_type == "ATTACK"
    assert human.ability_id == "night.attack.v1"


def test_standard_restore_rejects_ability_but_accepts_legacy_null():
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions
    from backend.tests.test_b3_infrastructure import _b5_action_service, _b5_submission

    service, game, _, _, _, _ = _b5_action_service()
    state, _ = restore_locked_game(service, object(), game)
    row = _b5_submission(0, 1, "INVESTIGATE")
    restore_action_submissions(state, [row])
    row["ability_id"] = "night.investigate.v1"
    with pytest.raises(ValueError):
        restore_action_submissions(state, [row])


def test_migration_010_adds_nullable_closed_action_ability():
    from backend.app.infrastructure.migrations import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "010_add_custom_role.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS ability_id varchar(32);" in sql
    assert "conname = 'action_submissions_ability_id_check'" in sql
    for ability, action in [("attack", "ATTACK"), ("investigate", "INVESTIGATE"), ("protect", "PROTECT")]:
        assert f"ability_id = 'night.{ability}.v1' AND action_type = '{action}'" in sql
    assert "ability_id IS NULL OR" in sql


@pytest.mark.parametrize("ability", ["night.investigate.v1", "night.protect.v1"])
def test_all_submitted_custom_nonattack_resolves_without_deadline(ability):
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions

    service, game, rows, _, _, _ = _custom_service(abilities=["night.attack.v1", ability])
    state, _ = restore_locked_game(service, object(), game)
    submissions = [
        {"actor_player_id": rows[index]["id"], "target_player_id": rows[4]["id"],
         "action_type": action, "source": "HUMAN" if index == 0 else "AGENT",
         "ability_id": ability if index == 0 else None}
        for index, action in [(0, "INVESTIGATE" if "investigate" in ability else "PROTECT"),
                              (2, "INVESTIGATE"), (3, "PROTECT")]
    ]
    restore_action_submissions(state, submissions)
    result = service._resolve(state, "NIGHT_ACTION", 1, submissions, force=False)
    assert result["target"] is None
    assert result["source"] == "SUBMISSIONS"
    assert result["payload"]["killed_player_id"] is None


@pytest.mark.parametrize("changes", [
    {"mode": "unknown"},
    {"mode": "CUSTOM_ROLE"},
    {"mode": "CUSTOM_ROLE", "custom_role": {
        "name": "직업", "faction": "MAFIA", "catalog_version": "custom-role-v2",
        "ability_ids": ["night.attack.v1"]}},
    {"mode": "CUSTOM_ROLE", "custom_role": {
        "name": "직업", "faction": "CITIZEN", "catalog_version": "custom-role-v1",
        "ability_ids": ["night.protect.v1", "night.protect.v1"]}},
])
def test_custom_create_invalid_contract_is_validation_error(changes):
    from backend.app.routers.game_router import _validate_body
    from backend.app.core.errors import ApiError

    with pytest.raises(ApiError) as caught:
        _validate_body(CreateGameRequest, {
            "player_count": 6, "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1", **changes,
        })
    assert caught.value.status_code == 422
    assert caught.value.code == "VALIDATION_ERROR"


def _triple_vote_state(*, phase=GamePhase.DAY_VOTE):
    """표의 방향을 고정해 가중치만으로 최다 득표자가 달라지는 합성 게임이다."""

    roles = [PlayerRole.CITIZEN, PlayerRole.MAFIA, PlayerRole.DETECTIVE,
             PlayerRole.DOCTOR, PlayerRole.CITIZEN, PlayerRole.CITIZEN]
    players = [PlayerState(uuid4(), index + 1, role,
                           PlayerKind.HUMAN if index == 0 else PlayerKind.AI)
               for index, role in enumerate(roles)]
    players[0].custom_role_name = "투표 설계자"
    players[0].custom_role_catalog_version = "custom-role-v1"
    players[0].custom_ability_ids = ("vote.triple.v1",)
    players[0].custom_faction = Faction.CITIZEN
    state = GameState(uuid4(), b"triple-vote", players, phase=phase, round=1,
                      day_number=2, mode="CUSTOM_ROLE")
    if phase is GamePhase.REVOTE:
        state.revote_candidates = {players[4].player_id, players[5].player_id}
    return state


@pytest.mark.parametrize("phase", [GamePhase.DAY_VOTE, GamePhase.REVOTE])
def test_triple_vote_changes_leader_and_preserves_replay(phase):
    """처형·재투표의 사용 표만 3표로 집계하고 같은 operation으로 결과를 재현한다."""

    from copy import deepcopy

    state = _triple_vote_state(phase=phase)
    initial, engine = deepcopy(state), GameEngine()
    targets = [4, 5, 5, 5, 5 if phase is GamePhase.REVOTE else 0, 4]
    if phase is GamePhase.REVOTE:
        targets[1] = 4
    for index, target in enumerate(targets):
        engine.submit_vote(state, state.players[index].player_id, state.players[target].player_id,
                           ability_id="vote.triple.v1" if index == 0 else None)
    assert state.operations[0].ability_id == "vote.triple.v1"
    assert GameEngine.replay(initial, state.operations).votes == state.votes
    assert state.votes[state.players[0].player_id].weight == 3
    assert sum(vote.weight for vote in state.votes.values()) == 8
    engine.resolve_vote(state)
    assert not state.players[4].alive
    assert state.players[5].alive
    replayed = GameEngine.replay(initial, state.operations)
    assert [player.alive for player in replayed.players] == [player.alive for player in state.players]
    assert replayed.phase is state.phase


@pytest.mark.parametrize("change", ["standard", "ai", "unowned", "dead", "night_id", "final"])
def test_triple_vote_rejects_invalid_actor_ability_and_phase_without_mutation(change):
    """보유 ID나 actor를 바꾼 요청은 표와 버전을 바꾸기 전에 거부한다."""

    from copy import deepcopy
    from backend.app.services.game.action_command import PostgresActionCommandService

    state = _triple_vote_state()
    ability = "vote.triple.v1"
    if change == "standard": state.mode = "STANDARD"
    elif change == "ai": state.players[0].kind = PlayerKind.AI
    elif change == "unowned": state.players[0].custom_ability_ids = ("night.protect.v1",)
    elif change == "dead": state.players[0].alive = False
    elif change == "night_id": ability = "night.protect.v1"
    elif change == "final": state.phase = GamePhase.FINAL_ACCUSATION
    before = deepcopy(state)
    with pytest.raises(RuleViolation):
        PostgresActionCommandService._submit_one(
            state, state.players[0].player_id, state.players[4].player_id, ability_id=ability,
        )
    assert state == before


def test_triple_vote_is_opt_in_and_auto_final_votes_stay_single():
    """능력을 보유해도 일반·자동·최종 투표는 능력을 자동 사용하지 않는다."""

    from backend.app.services.game.action_command import PostgresActionCommandService

    state = _triple_vote_state()
    engine = GameEngine()
    engine.submit_vote(state, state.players[0].player_id, state.players[4].player_id)
    assert state.votes[state.players[0].player_id].weight == 1
    with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
        engine.submit_vote(state, state.players[0].player_id, state.players[4].player_id,
                           ability_id="vote.triple.v1")
    state = _triple_vote_state(phase=GamePhase.FINAL_ACCUSATION)
    PostgresActionCommandService._submit_one(state, state.players[0].player_id, state.players[4].player_id)
    assert state.votes[state.players[0].player_id].weight == 1
    state = _triple_vote_state()
    service = object.__new__(PostgresActionCommandService)
    resolution = service._resolve(state, "DAY_VOTE", 1, [], force=True)
    assert all(row.get("ability_id") is None for row in resolution["auto_rows"])
    assert sum(item["vote_count"] for item in resolution["payload"]["counts"]) == 6


def _triple_vote_service(**changes):
    """기존 DB transaction 대역을 사용해 인간 투표 능력 snapshot을 복원한다."""

    from backend.tests.test_b3_infrastructure import _b5_action_service

    service, game, rows, window, now, connection = _b5_action_service(
        **{"phase": "DAY_VOTE", "roles": ["CITIZEN", "MAFIA", "DETECTIVE",
                                           "DOCTOR", "CITIZEN", "CITIZEN"], **changes},
    )
    game["mode"] = "CUSTOM_ROLE"
    rows[0].update(custom_role_name="투표 설계자", custom_role_catalog_version="custom-role-v1",
                   custom_ability_ids=["vote.triple.v1"], faction="CITIZEN")
    return service, game, rows, window, now, connection


def test_triple_vote_transaction_restores_and_retries_without_second_ballot():
    """투표 능력 ID는 원장과 재접속에 남고 재시도는 기존 결과만 돌려준다."""

    from datetime import timedelta
    from backend.app.core.errors import ApiError
    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.app.services.game.postgres_helpers import restore_locked_game, restore_action_submissions
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID

    service, game, rows, window, now, connection = _triple_vote_service()
    command = GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=10,
        window_id=window["id"], target_player_id=rows[4]["id"], ability_id="vote.triple.v1")
    key = uuid4()
    result, replayed = service.submit(USER_ID, GAME_ID, command, key, now=now)
    assert not replayed and connection.committed
    stored = service._actions.insert_submission.call_args.args[1]
    assert stored.ability_id == "vote.triple.v1" and stored.source == "HUMAN"
    submission = {"actor_player_id": stored.actor_player_id, "target_player_id": stored.target_player_id,
                  "action_type": stored.action_type, "source": stored.source, "ability_id": stored.ability_id}
    state, _ = restore_locked_game(service, object(), game)
    restore_action_submissions(state, [submission])
    assert state.votes[rows[0]["id"]].weight == 3
    service._actions.list_window_action_submissions.return_value = [submission]
    with pytest.raises(ApiError) as duplicate:
        service.submit(USER_ID, GAME_ID, command, uuid4(), now=now)
    assert duplicate.value.code == "ACTION_ALREADY_SUBMITTED"
    receipt = service._receipts.insert.call_args.kwargs
    service._receipts.find.return_value = receipt
    service._actions.insert_submission.reset_mock()
    repeated, replayed = service.submit(USER_ID, GAME_ID, command, key, now=now + timedelta(seconds=100))
    assert replayed and repeated == result
    service._actions.insert_submission.assert_not_called()
    with pytest.raises(ApiError) as changed:
        service.submit(USER_ID, GAME_ID, command.model_copy(update={"ability_id": None}), key, now=now)
    assert changed.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(ApiError) as owner:
        service.submit(uuid4(), GAME_ID, command, key, now=now)
    assert owner.value.code == "GAME_NOT_FOUND"


def test_triple_vote_last_submission_commits_weighted_resolution_and_public_counts():
    """마지막 인간 표는 가중 처형·원장·공개 집계를 한 transaction으로 확정한다."""

    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.app.services.game.result_service import resolution_payload
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID, _b5_submission

    submissions = [_b5_submission(actor, target, "VOTE", "AGENT")
                   for actor, target in [(1, 5), (2, 5), (3, 5), (4, 0), (5, 4)]]
    service, _, rows, window, now, connection = _triple_vote_service(submissions=submissions)
    command = GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=10,
        window_id=window["id"], target_player_id=rows[4]["id"], ability_id="vote.triple.v1")
    service.submit(USER_ID, GAME_ID, command, uuid4(), now=now)
    assert connection.committed
    stored = service._actions.insert_resolution.call_args.kwargs
    state = service._games.update_game_state.call_args.kwargs["state"]
    assert stored["target_player_id"] == rows[4]["id"]
    validated = resolution_payload(state, {
        "game_id": GAME_ID, "resolved_state_version": stored["state_version"],
        "resolution_type": stored["resolution_type"], "result_payload": stored["payload"],
    })
    assert sum(item["vote_count"] for item in validated["counts"]) == 8
    events = [call.kwargs for call in service._events.append.call_args_list]
    vote_event = next(event for event in events if event["event_type"] == "VOTE_RESOLVED")
    assert vote_event["audience"] == "PUBLIC"
    assert vote_event["payload"]["counts"] == validated["counts"]
    assert set(vote_event["payload"]) == {"round", "phase", "counts", "tied", "needs_revote"}


@pytest.mark.parametrize("change,expected", [
    ("deadline", "WINDOW_CLOSED"), ("version", "STALE_STATE_VERSION"),
    ("window", "WINDOW_CLOSED"), ("target", "TARGET_INVALID"),
    ("dead", "PLAYER_DEAD"), ("unowned", "ACTION_NOT_ALLOWED"),
    ("saved", "WINDOW_CLOSED"), ("final", "ACTION_NOT_ALLOWED"),
])
def test_triple_vote_transaction_rejects_invalid_boundaries_before_writes(change, expected):
    """능력 사용도 기존 window·마감·잠금·대상 경계를 우회하지 않는다."""

    from backend.app.core.errors import ApiError
    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID

    service, game, rows, window, now, _ = _triple_vote_service(
        phase="FINAL_ACCUSATION" if change == "final" else "DAY_VOTE",
    )
    fields = dict(type="SUBMIT_VOTE", expected_state_version=10, window_id=window["id"],
                  target_player_id=rows[4]["id"], ability_id="vote.triple.v1")
    if change == "deadline": window["deadline_at"] = now
    elif change == "version": fields["expected_state_version"] = 9
    elif change == "window": fields["window_id"] = uuid4()
    elif change == "target": fields["target_player_id"] = rows[0]["id"]
    elif change == "dead": rows[0]["alive"] = False
    elif change == "unowned": rows[0]["custom_ability_ids"] = ["night.protect.v1"]
    elif change == "saved": game["status"] = "SAVED"
    with pytest.raises(ApiError) as error:
        service.submit(USER_ID, GAME_ID, GameCommandRequest(**fields), uuid4(), now=now)
    assert error.value.code == expected
    service._actions.insert_submission.assert_not_called()
    service._games.update_game_state.assert_not_called()
    service._receipts.insert.assert_not_called()


def _triple_vote_resolution(*, weighted=True, tied=False):
    """고정 제출 집합을 실제 복원·해소 경로에 넣어 검증용 확정 원장을 만든다."""

    from backend.app.services.game.action_command import PostgresActionCommandService
    from backend.app.services.game.postgres_helpers import restore_action_submissions

    state = _triple_vote_state()
    targets = [4, 5, 5, 5, 5 if tied else 0, 4]
    rows = [{"actor_player_id": state.players[index].player_id,
             "target_player_id": state.players[target].player_id, "action_type": "VOTE",
             "source": "HUMAN" if index == 0 else "AGENT",
             "ability_id": "vote.triple.v1" if weighted and index == 0 else None}
            for index, target in enumerate(targets)]
    restore_action_submissions(state, rows)
    service = object.__new__(PostgresActionCommandService)
    result = service._resolve(state, "DAY_VOTE", 1, rows, force=False)
    ledger = {"game_id": state.game_id, "resolved_state_version": state.state_version,
              "resolution_type": "VOTE", "result_payload": result["payload"]}
    return state, ledger


@pytest.mark.parametrize("weighted", [False, True])
def test_weighted_resolution_preserves_legacy_ballots_and_exact_counts(weighted):
    """신규 표의 능력 ID만 추가하며 구형 표와 종료 집계 검증을 함께 보존한다."""

    from backend.app.services.game.result_service import resolution_payload

    state, row = _triple_vote_resolution(weighted=weighted)
    payload = resolution_payload(state, row)
    assert sum(item["vote_count"] for item in payload["counts"]) == (8 if weighted else 6)
    assert len(payload["ballots"]) == 6
    assert payload["ballots"][0].get("ability_id") == ("vote.triple.v1" if weighted else None)
    assert all("weight" not in ballot for ballot in payload["ballots"])
    assert all("ability_id" not in ballot for ballot in payload["ballots"][1:])


def test_weighted_tie_restores_exact_revote_candidates():
    """가중 합계의 동률 후보를 확정 원장에서 재접속 후 동일하게 복원한다."""

    from backend.app.services.game.postgres_helpers import restore_revote_candidates

    state, row = _triple_vote_resolution(tied=True)
    assert state.phase is GamePhase.REVOTE
    expected = {state.players[4].player_id, state.players[5].player_id}
    assert state.revote_candidates == expected
    state.revote_candidates.clear()
    restore_revote_candidates(state, [row])
    assert state.revote_candidates == expected


@pytest.mark.parametrize("change", ["auto", "missing", "unknown", "numeric", "other_actor", "counts", "final"])
def test_weighted_resolution_rejects_forged_ability_and_counts(change):
    """자동·미보유 표와 외부 숫자 가중치를 정상 가중 원장으로 해석하지 않는다."""

    from backend.app.services.game.result_service import resolution_payload

    state, row = _triple_vote_resolution()
    payload, ballot = row["result_payload"], row["result_payload"]["ballots"][0]
    if change == "auto": ballot["is_auto"] = True
    elif change == "missing": ballot.pop("ability_id")
    elif change == "unknown": ballot["ability_id"] = "intel.special_roles.v1"
    elif change == "numeric": ballot["weight"] = 3
    elif change == "other_actor":
        ballot.pop("ability_id")
        payload["ballots"][1]["ability_id"] = "vote.triple.v1"
    elif change == "counts": payload["counts"][4]["vote_count"] -= 1
    elif change == "final":
        row["resolution_type"] = "FINAL_VOTE"
        payload["phase"] = "FINAL_ACCUSATION"
    with pytest.raises(ValueError):
        resolution_payload(state, row)


@pytest.mark.parametrize("change", ["auto", "agent_source", "ai", "unowned", "final", "night_id"])
def test_weighted_submission_restore_rejects_invalid_ledger(change):
    """재개 때도 저장된 출처·보유 능력·phase를 다시 검사한다."""

    from backend.app.services.game.postgres_helpers import restore_action_submissions

    state = _triple_vote_state()
    row = {"actor_player_id": state.players[0].player_id, "target_player_id": state.players[4].player_id,
           "action_type": "VOTE", "source": "HUMAN", "ability_id": "vote.triple.v1"}
    if change == "auto": row["source"] = "AUTO"
    elif change == "agent_source": row["source"] = "AGENT"
    elif change == "ai": row["actor_player_id"] = state.players[1].player_id
    elif change == "unowned": state.players[0].custom_ability_ids = ("night.protect.v1",)
    elif change == "final": state.phase = GamePhase.FINAL_ACCUSATION
    elif change == "night_id": row["ability_id"] = "night.protect.v1"
    with pytest.raises(ValueError):
        restore_action_submissions(state, [row])


@pytest.mark.parametrize("ability_ids", [
    ["vote.triple.v1"], ["intel.special_roles.v1"],
    ["vote.triple.v1", "intel.special_roles.v1"],
])
def test_day_only_custom_citizen_never_waits_for_or_submits_night_action(ability_ids):
    """낮·조회 능력만 있으면 밤 UI와 필수 actor에서 빠지고 자동 원장도 만들지 않는다."""

    from backend.app.game_engine.rules.night_rules import required_actors
    from backend.app.services.game.game_read_service import legal_actions, _ability_options
    from backend.app.services.game.models import CanonicalGameRecord
    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID

    request = _request(mode="CUSTOM_ROLE", custom_role={
        "name": "낮 기록관", "faction": "CITIZEN", "catalog_version": "custom-role-v1",
        "ability_ids": ability_ids,
    })
    state = _triple_vote_state(phase=GamePhase.NIGHT_ACTION)
    state.players[0].custom_ability_ids = tuple(request.custom_role.ability_ids)
    assert state.players[0] not in required_actors(state)
    record = CanonicalGameRecord(state, {}, state.players[0].player_id, uuid4(), "", "")
    assert "SUBMIT_NIGHT_ACTION" not in legal_actions(record)
    assert _ability_options(record) == []
    service, _, rows, _, now, _ = _triple_vote_service(phase="NIGHT_ACTION", deadline_offset=-1)
    rows[0]["custom_ability_ids"] = ability_ids
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    stored = [call.args[1] for call in service._actions.insert_submission.call_args_list]
    assert all(item.actor_player_id != rows[0]["id"] for item in stored)
    assert service._games.update_game_state.call_args.kwargs["state"].phase is not GamePhase.NIGHT_ACTION


def test_night_auto_skips_leading_day_and_intel_abilities():
    """저장 순서의 첫 항목이 낮 능력이어도 실제 첫 밤 능력을 자동 선택·기록한다."""

    from backend.tests.test_b3_infrastructure import USER_ID, GAME_ID

    service, _, rows, _, now, _ = _triple_vote_service(phase="NIGHT_ACTION", deadline_offset=-1)
    rows[0]["custom_ability_ids"] = ["vote.triple.v1", "intel.special_roles.v1", "night.protect.v1"]
    service.auto_resolve_expired_night(USER_ID, GAME_ID, now=now)
    stored = [call.args[1] for call in service._actions.insert_submission.call_args_list]
    human = next(item for item in stored if item.actor_player_id == rows[0]["id"])
    assert human.ability_id == "night.protect.v1" and human.action_type == "PROTECT"


def test_migration_011_preserves_existing_rows_and_expands_only_human_vote_ability():
    """후속 migration은 기존 행 갱신 없이 원장 CHECK의 허용 조합만 확장한다."""

    from backend.app.infrastructure.migrations import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "011_add_custom_role_tool_abilities.sql").read_text()
    assert "DROP CONSTRAINT IF EXISTS action_submissions_ability_id_check" in sql
    assert "ability_id = 'vote.triple.v1' AND action_type = 'VOTE' AND source = 'HUMAN'" in sql
    for ability, action in [("attack", "ATTACK"), ("investigate", "INVESTIGATE"), ("protect", "PROTECT")]:
        assert f"ability_id = 'night.{ability}.v1' AND action_type = '{action}'" in sql
    assert "ability_id IS NULL OR" in sql
    assert "UPDATE " not in sql and "DELETE " not in sql


@pytest.mark.parametrize("source", ["HUMAN", "AGENT", "AUTO"])
@pytest.mark.parametrize("action_type", ["VOTE", "ATTACK", "INVESTIGATE", "PROTECT", "PASS", "SPEAK"])
@pytest.mark.parametrize("ability_id", ["vote.triple.v1", "unknown.v1", None])
def test_repository_vote_ability_insert_boundary(source, action_type, ability_id):
    """실제 저장소의 INSERT 경계에서 능력 투표만 인간 VOTE로 제한하고 NULL 원장은 보존한다."""
    from unittest.mock import Mock
    from backend.app.repositories.action_repository import ActionSubmissionInsert, PostgresActionRepository

    target = None if action_type in {"PASS", "SPEAK"} else uuid4()
    message = "합성 발언" if action_type == "SPEAK" else None
    submission = ActionSubmissionInsert(uuid4(), uuid4(), uuid4(), action_type, target,
                                        message, source, 1, ability_id)
    cursor = Mock()
    row = {"ability_id": ability_id, "source": source, "action_type": action_type}
    cursor.fetchone.return_value = row
    allowed = ability_id is None or (
        ability_id == "vote.triple.v1" and source == "HUMAN" and action_type == "VOTE"
    )
    if allowed:
        assert PostgresActionRepository().insert_submission(cursor, submission) == row
        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args.args
        assert "INSERT INTO public.action_submissions" in sql
        assert params == (submission.game_id, submission.window_id, submission.actor_player_id,
                          action_type, target, message, source, 1, ability_id)
    else:
        with pytest.raises(ValueError):
            PostgresActionRepository().insert_submission(cursor, submission)
        cursor.execute.assert_not_called()
        cursor.fetchone.assert_not_called()


@pytest.mark.parametrize("ability_id,action_type", [
    ("night.investigate.v1", NightActionType.INVESTIGATE),
    ("night.protect.v1", NightActionType.PROTECT),
])
def test_custom_night_operation_preserves_selected_ability_in_replay(ability_id, action_type):
    """선택 순서가 다른 복수 능력도 operation과 재생 결과에 동일한 밤 행동으로 남아야 한다."""
    from copy import deepcopy

    state = _triple_vote_state(phase=GamePhase.NIGHT_ACTION)
    actor, target = state.players[0], state.players[4]
    actor.custom_ability_ids = ("night.investigate.v1", "night.protect.v1")
    initial = deepcopy(state)
    GameEngine().submit_night_action(state, actor.player_id, action_type, target.player_id)
    assert state.operations[0].ability_id == ability_id
    replayed = GameEngine.replay(initial, state.operations)
    assert replayed.night_actions == state.night_actions
    assert replayed.operations == state.operations
    assert replayed.state_version == state.state_version


def test_standard_null_night_operation_remains_replayable():
    """능력 ID가 없던 표준 밤 원장은 저장 역할로 행동을 복원한다."""
    from copy import deepcopy
    from backend.app.models.game_state import EngineOperation

    state = _triple_vote_state(phase=GamePhase.NIGHT_ACTION)
    state.mode = "STANDARD"
    actor, target = state.players[2], state.players[4]
    initial = deepcopy(state)
    GameEngine().submit_night_action(state, actor.player_id, NightActionType.INVESTIGATE, target.player_id)
    assert state.operations[0].ability_id is None
    legacy = EngineOperation(command="SUBMIT_NIGHT_ACTION", actor_id=actor.player_id,
                             target_id=target.player_id)
    replayed = GameEngine.replay(initial, [legacy])
    assert replayed.night_actions == state.night_actions
    assert replayed.state_version == state.state_version


def _jsonb_player_rows(ability_ids=()):
    """실제 저장소 검증을 통과하는 합성 6인 입력으로 JSONB 경계만 분리한다."""
    from backend.app.repositories.player_repository import PlayerInsert

    return [
        PlayerInsert(
            player_id=uuid4(), user_id=uuid4() if seat == 1 else None,
            kind="HUMAN" if seat == 1 else "AI", seat=seat,
            display_name=f"합성 참가자 {seat}", role="CITIZEN", faction="CITIZEN",
            persona_id=None if seat == 1 else "synthetic-persona",
            custom_role_name="기록관" if seat == 1 and ability_ids else None,
            custom_role_catalog_version="custom-role-v1" if seat == 1 and ability_ids else None,
            custom_ability_ids=ability_ids if seat == 1 else (),
        )
        for seat in range(1, 7)
    ]


@pytest.mark.parametrize("ability_ids", [
    (), ("night.protect.v1",),
    ("night.investigate.v1", "night.protect.v1"),
    ("vote.triple.v1", "intel.special_roles.v1", "night.protect.v1"),
])
def test_player_repository_ability_snapshot_uses_jsonb_or_sql_null(ability_ids):
    """능력 순서를 JSONB로 보존하고 표준 인간과 모든 AI는 SQL NULL로 전달한다."""
    import json
    from unittest.mock import Mock
    from psycopg.adapt import PyFormat, Transformer
    from psycopg.types.json import Jsonb
    from backend.app.repositories.player_repository import PostgresPlayerRepository

    cursor = Mock()
    PostgresPlayerRepository().insert_players(
        cursor, game_id=uuid4(), players=_jsonb_player_rows(ability_ids),
    )
    assert cursor.execute.call_count == 6
    for index, call in enumerate(cursor.execute.call_args_list):
        sql, params = call.args
        assert "custom_ability_ids" in sql
        snapshot = params[-1]
        if index == 0 and ability_ids:
            assert isinstance(snapshot, Jsonb)
            dumper = Transformer().get_dumper(snapshot, PyFormat.TEXT)
            assert dumper.oid == 3802
            assert json.loads(dumper.dump(snapshot)) == list(ability_ids)
        else:
            assert params[-3:] == (None, None, None)


@pytest.mark.parametrize("invalid", ["count", "seats", "human_identity", "ai_identity"])
def test_player_repository_jsonb_change_preserves_validation(invalid):
    """잘못된 플레이어 묶음은 JSONB 저장 전에 거부하여 부분 INSERT를 막는다."""
    from dataclasses import replace
    from unittest.mock import Mock
    from backend.app.repositories.player_repository import PostgresPlayerRepository

    players = _jsonb_player_rows(("night.protect.v1",))
    if invalid == "count":
        players.pop()
    elif invalid == "seats":
        players[-1] = replace(players[-1], seat=1)
    elif invalid == "human_identity":
        players[0] = replace(players[0], user_id=None)
    else:
        players[-1] = replace(players[-1], persona_id=None)
    cursor = Mock()
    with pytest.raises(ValueError):
        PostgresPlayerRepository().insert_players(cursor, game_id=uuid4(), players=players)
    cursor.execute.assert_not_called()
