"""B5 공개 게임·sync·feedback API의 PostgreSQL 계약 테스트."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app

USER_ID = uuid4()


@pytest.fixture(autouse=True)
def cleanup_test_user() -> None:
    """각 테스트가 만든 UUID 사용자와 종속 행만 PostgreSQL에서 정리한다."""

    yield
    settings: Settings = get_settings()
    with psycopg.connect(settings.effective_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM public.feedback WHERE user_id = %s", (USER_ID,))
            cursor.execute("DELETE FROM public.games WHERE owner_user_id = %s", (USER_ID,))
            cursor.execute("DELETE FROM public.users WHERE id = %s", (USER_ID,))


def _client() -> TestClient:
    """실제 PostgreSQL runtime을 사용하는 FastAPI client를 만든다."""

    return TestClient(create_app(settings=get_settings(), enable_background_worker=False))


def _headers(key: UUID | None = None, user: UUID = USER_ID) -> dict[str, str]:
    """공개 API 공통 header를 만든다."""

    headers = {"X-User-Id": str(user)}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    return headers


def _create(client: TestClient) -> tuple[UUID, dict]:
    """정본 생성 응답과 game id를 반환한다."""

    response = client.post(
        "/api/v1/games",
        headers=_headers(uuid4()),
        json={
            "player_count": 6,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(body["data"]["game_id"]), body


@pytest.mark.parametrize("saved", [False, True])
def test_b5_delete_owned_game_and_cascade_without_touching_other_game(saved) -> None:
    """생성된 합성 게임 하나만 삭제하고 원장 연쇄 삭제·반복 요청·소유권을 확인한다."""

    client = _client()
    game_id, _ = _create(client)
    other_game_id, _ = _create(client)
    version = 1
    if saved:
        response = client.post(
            f"/api/v1/games/{game_id}/commands", headers=_headers(uuid4()),
            json={"type": "SAVE_AND_EXIT", "expected_state_version": version},
        )
        assert response.status_code == 200
        version = response.json()["data"]["result_state_version"]
    path = f"/api/v1/games/{game_id}?expected_state_version={version}"
    assert client.delete(path, headers=_headers(user=uuid4())).status_code == 404
    assert client.delete(f"/api/v1/games/{game_id}", headers=_headers()).status_code == 422
    assert client.delete(path).status_code == 400
    assert client.delete(f"/api/v1/games/{game_id}?expected_state_version={version + 1}", headers=_headers()).status_code == 409
    assert client.get(f"/api/v1/games/{game_id}", headers=_headers()).status_code == 200
    deleted = client.delete(path, headers=_headers())
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"] == {"game_id": str(game_id), "deleted": True}
    assert client.delete(path, headers=_headers()).status_code == 404
    assert client.get(f"/api/v1/games/{game_id}", headers=_headers()).status_code == 404
    assert client.get(f"/api/v1/games/{other_game_id}", headers=_headers()).status_code == 200
    with psycopg.connect(get_settings().effective_database_url) as connection:
        with connection.cursor() as cursor:
            for table in ("game_players", "game_events", "command_receipts", "game_snapshots", "speech_analysis"):
                cursor.execute(psycopg.sql.SQL("SELECT count(*) FROM public.{} WHERE game_id = %s").format(psycopg.sql.Identifier(table)), (game_id,))
                assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM public.users WHERE id = %s", (USER_ID,))
            assert cursor.fetchone()[0] == 1


def test_b5_delete_waits_for_game_lock_and_rejects_updated_version() -> None:
    """다른 transaction이 먼저 진행한 게임을 오래된 화면의 삭제 요청으로 지우지 않는다."""

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch
    from backend.app.core.errors import ApiError

    client = _client()
    game_id, _ = _create(client)
    runtime = client.app.state.game_runtime
    entered = Event()
    original_lock = runtime._games.lock_game

    def observed_lock(cursor, target):
        entered.set()
        return original_lock(cursor, target)

    with ThreadPoolExecutor(max_workers=1) as pool, patch.object(runtime._games, "lock_game", side_effect=observed_lock):
        with psycopg.connect(get_settings().effective_database_url) as connection:
            connection.execute("SELECT id FROM public.games WHERE id = %s FOR UPDATE", (game_id,))
            future = pool.submit(runtime.delete_game, USER_ID, game_id, expected_state_version=1)
            assert entered.wait(2)
            assert not future.done()
            connection.execute("UPDATE public.games SET state_version = 2 WHERE id = %s", (game_id,))
        with pytest.raises(ApiError) as error:
            future.result(timeout=3)
        assert error.value.code == "STALE_STATE_VERSION"
    assert client.get(f"/api/v1/games/{game_id}", headers=_headers()).status_code == 200


def test_b5_delete_failure_rolls_back_game_and_children() -> None:
    """삭제 SQL 뒤 장애를 주입해 게임과 종속 플레이어가 함께 복원되는지 확인한다."""

    from unittest.mock import patch

    client = _client()
    game_id, _ = _create(client)
    repository = client.app.state.game_runtime._games
    original_delete = repository.delete_owned_game

    def fail_after_delete(*args, **kwargs):
        original_delete(*args, **kwargs)
        raise RuntimeError("합성 transaction 장애")

    with patch.object(repository, "delete_owned_game", side_effect=fail_after_delete):
        response = client.delete(f"/api/v1/games/{game_id}?expected_state_version=1", headers=_headers())
    assert response.status_code == 503
    restored = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    assert restored["game"]["state_version"] == 1
    assert len(restored["players"]) == 6


def test_b5_stale_save_preserves_committed_state_and_rejects_late_ai_result() -> None:
    """오래된 화면에서도 확정 발언을 보존해 저장하고 늦은 AI 응답·중복 저장은 반영하지 않는다."""

    from backend.app.core.errors import ApiError

    client = _client()
    game_id, _ = _create(client)
    route = f"/api/v1/games/{game_id}"
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={
        "type": "BEGIN_GAME", "expected_state_version": 1,
    }).status_code == 200
    before = client.get(route, headers=_headers()).json()["data"]
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={
        "type": "SPEAK", "expected_state_version": before["game"]["state_version"],
        "window_id": before["action_window"]["window_id"], "message": "저장 전에 확정된 합성 발언",
    }).status_code == 200
    committed = client.get(route, headers=_headers()).json()["data"]
    version = committed["game"]["state_version"]
    key = uuid4()
    payload = {"type": "SAVE_AND_EXIT", "expected_state_version": 1}
    response = client.post(route + "/commands", headers=_headers(key), json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["accepted_state_version"] == version
    assert response.json()["data"]["result_state_version"] == version + 1
    saved = client.get(route, headers=_headers()).json()["data"]
    assert saved["game"]["status"] == "SAVED"
    assert saved["game"]["phase"] == committed["game"]["phase"]
    assert saved["players"] == committed["players"]
    assert saved["public_events"][:len(committed["public_events"])] == committed["public_events"]
    assert saved["action_window"]["window_id"] == committed["action_window"]["window_id"]
    assert saved["action_window"]["paused"] is True
    assert saved["action_window"]["deadline_at"] is None
    assert 0 <= saved["action_window"]["remaining_ms"] <= committed["action_window"]["remaining_ms"]
    runtime = client.app.state.game_runtime
    with pytest.raises(ApiError):
        runtime._agent_discussion.submit_speak(
            USER_ID, game_id, UUID(committed["action_window"]["turn_player_id"]),
            "저장 뒤 도착한 미확정 합성 응답", expected_state_version=version,
            window_id=UUID(committed["action_window"]["window_id"]),
        )
    replay = client.post(route + "/commands", headers=_headers(key), json=payload)
    assert replay.status_code == 200
    assert replay.json()["meta"]["replayed"] is True
    assert replay.json()["data"] == response.json()["data"]
    replayed = client.get(route, headers=_headers()).json()["data"]
    assert replayed["game"] == saved["game"]
    assert replayed["public_events"] == saved["public_events"]
    assert {key: value for key, value in replayed["action_window"].items() if key != "server_time"} == {
        key: value for key, value in saved["action_window"].items() if key != "server_time"
    }
    conflict = client.post(route + "/commands", headers=_headers(key), json={**payload, "expected_state_version": version})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    stale_resume = client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "RESUME", "expected_state_version": 1})
    assert stale_resume.status_code == 409
    assert stale_resume.json()["error"]["code"] == "STALE_STATE_VERSION"
    resumed = client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "RESUME", "expected_state_version": version + 1})
    assert resumed.status_code == 200
    restored = client.get(route, headers=_headers()).json()["data"]
    assert restored["game"]["phase"] == saved["game"]["phase"]
    assert restored["public_events"][:len(saved["public_events"])] == saved["public_events"]


def test_b5_stale_save_preserves_owner_and_status_validation() -> None:
    """버전 예외가 타인 게임이나 이미 멈춘 게임의 새 저장까지 허용하지 않는지 확인한다."""

    client = _client()
    game_id, _ = _create(client)
    route = f"/api/v1/games/{game_id}"
    payload = {"type": "SAVE_AND_EXIT", "expected_state_version": 99}
    assert client.post(route + "/commands", headers=_headers(uuid4(), user=uuid4()), json=payload).status_code == 404
    assert client.get(route, headers=_headers()).json()["data"]["game"]["state_version"] == 1
    assert client.post(route + "/commands", headers=_headers(uuid4()), json=payload).status_code == 200
    assert client.post(route + "/commands", headers=_headers(uuid4()), json=payload).status_code == 409
    saved = client.get(route, headers=_headers()).json()["data"]
    assert saved["game"]["status"] == "SAVED"
    assert saved["game"]["state_version"] == 2
    assert saved["action_window"] is None


def test_b5_stale_save_uses_version_committed_while_waiting_for_lock() -> None:
    """선행 transaction을 기다린 저장은 잠금 전에 본 버전이 아닌 commit된 버전을 사용한다."""

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch
    from backend.app.schemas.command_schema import GameCommandRequest

    client = _client()
    game_id, _ = _create(client)
    service = client.app.state.game_runtime._save
    entered = Event()
    original_lock = service._games.lock_game

    def observed_lock(cursor, target):
        entered.set()
        return original_lock(cursor, target)

    with ThreadPoolExecutor(max_workers=1) as pool, patch.object(service._games, "lock_game", side_effect=observed_lock):
        with psycopg.connect(get_settings().effective_database_url) as connection:
            connection.execute("SELECT id FROM public.games WHERE id = %s FOR UPDATE", (game_id,))
            future = pool.submit(service.save, USER_ID, game_id, GameCommandRequest(type="SAVE_AND_EXIT", expected_state_version=1), uuid4())
            assert entered.wait(2)
            assert not future.done()
            connection.execute("UPDATE public.games SET state_version = 2 WHERE id = %s", (game_id,))
        result, replayed = future.result(timeout=3)
    assert not replayed
    assert result["accepted_state_version"] == 2
    assert result["result_state_version"] == 3
    assert client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]["game"]["status"] == "SAVED"


def test_b5_create_snapshot_command_and_sync() -> None:
    """생성부터 첫 발언과 delta sync까지의 PostgreSQL 흐름을 검증한다."""

    client = _client()
    game_id, created = _create(client)
    snapshot = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    assert snapshot["game"]["state_version"] == created["data"]["state_version"]
    assert len(snapshot["players"]) == 6

    begin = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(uuid4()),
        json={"type": "BEGIN_GAME", "expected_state_version": 1},
    )
    assert begin.status_code == 200, begin.text

    current = client.get(f"/api/v1/games/{game_id}", headers=_headers()).json()["data"]
    speak = client.post(
        f"/api/v1/games/{game_id}/commands",
        headers=_headers(uuid4()),
        json={
            "type": "SPEAK",
            "expected_state_version": current["game"]["state_version"],
            "window_id": current["action_window"]["window_id"],
            "message": "조정실 근처에 있었습니다.",
        },
    )
    assert speak.status_code == 200, speak.text

    sync = client.get(
        f"/api/v1/games/{game_id}/sync?after_state_version=0&after_sequence=0",
        headers=_headers(),
    )
    assert sync.status_code == 200, sync.text
    synchronized = sync.json()["data"]
    if synchronized["mode"] == "SNAPSHOT":
        assert synchronized["snapshot"]["game"]["state_version"] == speak.json()["data"]["result_state_version"]
        assert any(event["event_type"] == "PLAYER_SPOKE" for event in synchronized["snapshot"]["public_events"])
    else:
        assert synchronized["mode"] == "DELTA" and synchronized["operations"]


def test_b5_owner_and_create_idempotency_boundaries() -> None:
    """타 사용자 접근과 같은 생성 key 재전송을 확인한다."""

    client = _client()
    game_id, _ = _create(client)
    wrong_owner = client.get(f"/api/v1/games/{game_id}", headers=_headers(user=uuid4()))
    assert wrong_owner.status_code == 404

    key = uuid4()
    payload = {
        "player_count": 6,
        "ruleset_version": "mystery-v1",
        "scenario_version": "scenario-v1",
    }
    first = client.post("/api/v1/games", headers=_headers(key), json=payload)
    second = client.post("/api/v1/games", headers=_headers(key), json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["meta"]["replayed"] is True


def test_b5_general_feedback_is_persisted_and_replayed() -> None:
    """일반 feedback을 PostgreSQL에 저장하고 동일 key 재요청을 replay한다."""

    client = _client()
    key = uuid4()
    payload = {
        "feedback_type": "GENERAL",
        "rating": 4,
        "comment": "  흐름이 이해하기 쉬웠습니다. ",
        "tags": ["ux"],
    }
    first = client.post("/api/v1/feedback", headers=_headers(key), json=payload)
    second = client.post("/api/v1/feedback", headers=_headers(key), json=payload)

    assert first.status_code == second.status_code == 201
    assert UUID(first.json()["data"]["feedback_id"])
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["meta"]["replayed"] is True

    with psycopg.connect(get_settings().effective_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rating, comment, tags FROM public.feedback WHERE user_id = %s",
                (USER_ID,),
            )
            row = cursor.fetchone()
    assert row == (4, "흐름이 이해하기 쉬웠습니다.", ["UX"])


def test_b5_feedback_validation_is_kept_at_http_boundary() -> None:
    """허용되지 않은 tag는 DB transaction 전에 422로 거부한다."""

    response = _client().post(
        "/api/v1/feedback",
        headers=_headers(uuid4()),
        json={"feedback_type": "GENERAL", "rating": 4, "tags": ["UNKNOWN"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("human_role", ["DETECTIVE", "DOCTOR", "MAFIA"])
def test_b5_night_ledger_persists_mixed_roles_and_reloads_private_events(human_role: str) -> None:
    """격리된 테스트 게임의 인간 특수 역할과 AI 밤 행동을 실제 원장까지 연결한다."""

    from datetime import UTC, datetime, timedelta
    from psycopg.rows import dict_row
    from backend.app.repositories.action_repository import ActionWindowInsert
    from backend.app.schemas.game_schema import CreateGameRequest
    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    runtime = PostgresGameRuntime(get_settings())
    created, _ = runtime._create.create(USER_ID, CreateGameRequest(player_count=6, ruleset_version="mystery-v1", scenario_version="scenario-v1"), uuid4())
    game_id = UUID(created["game_id"])
    now = datetime.now(UTC)
    window_id = uuid4()
    roles = [human_role, *[role for role in ["DETECTIVE", "DOCTOR", "MAFIA"] if role != human_role], "CITIZEN", "CITIZEN", "CITIZEN"]
    with runtime._transactions.transaction() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            players = runtime._players.list_players(cursor, game_id=game_id)
            for player, role in zip(players, roles, strict=True):
                cursor.execute("UPDATE public.game_players SET role = %s, faction = %s WHERE game_id = %s AND id = %s", (role, "MAFIA" if role == "MAFIA" else "CITIZEN", game_id, player["id"]))
            cursor.execute("UPDATE public.games SET phase = 'NIGHT_ACTION', round = 1, state_version = 2 WHERE id = %s", (game_id,))
            runtime._actions_repository.open_window(cursor, ActionWindowInsert(window_id, game_id, "NIGHT", "NIGHT_ACTION", 1, 1, None, 2, now + timedelta(seconds=20)))
    target = players[4]["id"]
    human, _ = runtime._actions.submit(USER_ID, game_id, GameCommandRequest(type="SUBMIT_NIGHT_ACTION", expected_state_version=2, window_id=window_id, target_player_id=target), uuid4(), now=now)
    submitted = runtime._read.snapshot(USER_ID, game_id)
    assert submitted["action_window"]["has_submitted"] is True
    assert "SUBMIT_NIGHT_ACTION" not in submitted["legal_actions"]
    assert not any(event["event_type"] == "ACTION_RESOLVED" for event in submitted["public_events"])
    turns = runtime.list_ai_night_turns()
    assert {turn["player_id"] for turn in turns if turn["game_id"] == game_id} == {player["id"] for player in players[1:3]}
    result, _ = runtime._actions.submit_agent_night_actions(USER_ID, game_id,
        [{"player_id": player["id"], "target_player_id": target} for player in players[1:3]],
        expected_state_version=human["result_state_version"], window_id=window_id, idempotency_key=uuid4(), now=now)
    snapshot = runtime._read.snapshot(USER_ID, game_id)
    assert snapshot["game"]["state_version"] == result["result_state_version"]
    assert snapshot["game"]["round"] == 1 and snapshot["game"]["day_number"] == 2
    assert snapshot["public_events"][-1]["event_type"] == "NIGHT_RESOLVED"
    assert snapshot["public_events"][-1]["data"] == {"round": 1, "killed_player_id": None}
    assert len(snapshot["me"]["private_events"]) == int(human_role == "DETECTIVE")
    with runtime._transactions.transaction() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            resolutions = runtime._actions_repository.list_resolutions(cursor, game_id=game_id, through_state_version=result["result_state_version"])
            assert len(resolutions) == 1
            assert resolutions[0]["result_payload"]["resolved_attack_target_player_id"] == str(target)
            detective = players[roles.index("DETECTIVE")]["id"]
            private = runtime._read._events.list_snapshot_private_events(cursor, game_id=game_id, player_id=detective,
                through_sequence=999, through_state_version=result["result_state_version"])
            assert len(private) == 1 and private[0]["event_type"] == "INVESTIGATION_RESULT"

    # 마지막 지목 window를 테스트 원본에 준비하고 첫 인간 표 뒤 AI 전원 표를 보존한다.
    final_window = uuid4()
    final_version = result["result_state_version"] + 1
    with runtime._transactions.transaction() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            runtime._actions_repository.cancel_current_window(cursor, game_id=game_id)
            cursor.execute("UPDATE public.games SET phase = 'FINAL_ACCUSATION', round = 5, day_number = 6, state_version = %s WHERE id = %s", (final_version, game_id))
            runtime._actions_repository.open_window(cursor, ActionWindowInsert(final_window, game_id, "FINAL_VOTE", "FINAL_ACCUSATION", 5, 1, None, final_version, now + timedelta(seconds=30)))
    first, _ = runtime._actions.submit(USER_ID, game_id, GameCommandRequest(type="SUBMIT_VOTE", expected_state_version=final_version, window_id=final_window, target_player_id=target), uuid4(), now=now)
    waiting = runtime._read.snapshot(USER_ID, game_id)
    assert waiting["result"] is None and waiting["action_window"]["has_submitted"] is True
    mafia = players[roles.index("MAFIA")]["id"]
    runtime._actions.submit_agent_votes(USER_ID, game_id,
        [{"player_id": player["id"], "target_player_id": target if player["id"] == mafia else mafia} for player in players[1:]],
        expected_state_version=first["result_state_version"], window_id=final_window, idempotency_key=uuid4(), now=now)
    ended = runtime._read.snapshot(USER_ID, game_id)
    assert ended["game"]["status"] == "COMPLETED" and ended["action_window"] is None
    assert ended["result"]["winner"] == "CITIZEN"
    assert len(ended["result"]["nights"]) == 1 and len(ended["result"]["votes"]) == 1
    assert len(ended["result"]["votes"][0]["ballots"]) == 6
    assert ended["result"]["votes"][0]["round"] == 5
    assert ended["public_events"][-1]["event_type"] == "GAME_ENDED"
    assert ended["result"]["public_event_ids"] == [event["event_id"] for event in ended["public_events"]]


def test_free_discussion_seven_messages_deadline_and_idempotency():
    """AI 예약 중 인간 연속 발언·7회 제한·중복 재전송·마감 전이를 실제 원장으로 검증한다."""
    from datetime import UTC, datetime, timedelta
    from backend.app.services.game.discussion_transaction import expire_discussion
    client = _client()
    game_id, _ = _create(client)
    route = f"/api/v1/games/{game_id}"
    response = client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "BEGIN_GAME", "expected_state_version": 1})
    assert response.status_code == 200, response.text
    initial = client.get(route, headers=_headers()).json()["data"]
    deadline = initial["action_window"]["deadline_at"]
    assert deadline is not None
    assert 95_000 < initial["action_window"]["remaining_ms"] <= 105_000
    for number in range(7):
        snapshot = client.get(route, headers=_headers()).json()["data"]
        assert snapshot["game"]["phase"] == "DAY_DISCUSSION"
        assert snapshot["action_window"]["deadline_at"] == deadline
        key = uuid4()
        payload = {"type": "SPEAK", "expected_state_version": snapshot["game"]["state_version"], "window_id": snapshot["action_window"]["window_id"], "message": f"합성 자유 발언 {number}"}
        response = client.post(route + "/commands", headers=_headers(key), json=payload)
        assert response.status_code == 200, response.text
        replay = client.post(route + "/commands", headers=_headers(key), json=payload)
        assert replay.status_code == 200, replay.text
    snapshot = client.get(route, headers=_headers()).json()["data"]
    payload.update(expected_state_version=snapshot["game"]["state_version"], window_id=snapshot["action_window"]["window_id"])
    response = client.post(route + "/commands", headers=_headers(uuid4()), json=payload)
    assert response.status_code == 429, response.text
    runtime = client.app.state.game_runtime
    expiry = datetime.fromisoformat(deadline.replace("Z", "+00:00")) + timedelta(milliseconds=1)
    expire_discussion(runtime._discussion, USER_ID, game_id, now=expiry)
    final = client.get(route, headers=_headers()).json()["data"]
    assert final["game"]["phase"] == "NIGHT_ACTION"
    assert len([e for e in final["public_events"] if e["event_type"] == "PLAYER_SPOKE"]) == 7
    assert not any(e["event_type"] == "PLAYER_PASSED" for e in final["public_events"])


@pytest.mark.parametrize("phase,day,expected", [("DAY_DISCUSSION", 2, "DAY_VOTE"), ("FINAL_DISCUSSION", 6, "FINAL_ACCUSATION")])
def test_free_discussion_repeated_ai_save_resume_and_expiry(phase, day, expected):
    """AI가 여러 번 말해도 토론은 끝나지 않고 저장·재개와 마감 후 단계가 유지된다."""
    from datetime import datetime, timedelta
    from backend.app.services.game.discussion_transaction import expire_discussion
    client = _client()
    game_id, _ = _create(client)
    route = f"/api/v1/games/{game_id}"
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "BEGIN_GAME", "expected_state_version": 1}).status_code == 200
    with psycopg.connect(get_settings().effective_database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE public.games SET phase=%s,day_number=%s,round=%s WHERE id=%s", (phase,day,day-1,game_id))
            cursor.execute("UPDATE public.action_windows SET phase=%s,round=%s WHERE game_id=%s AND status='OPEN'", (phase,day-1,game_id))
    runtime = client.app.state.game_runtime
    seen = []
    for index in range(8):
        snapshot = client.get(route, headers=_headers()).json()["data"]
        window = snapshot["action_window"]
        actor = UUID(window["turn_player_id"])
        seen.append(actor)
        runtime._agent_discussion.submit_speak(USER_ID, game_id, actor, f"합성 AI 의견 {index}", expected_state_version=snapshot["game"]["state_version"], window_id=UUID(window["window_id"]))
    assert len(set(seen)) < len(seen)
    snapshot = client.get(route, headers=_headers()).json()["data"]
    assert snapshot["game"]["phase"] == phase
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "SAVE_AND_EXIT", "expected_state_version": snapshot["game"]["state_version"]}).status_code == 200
    saved = client.get(route, headers=_headers()).json()["data"]
    assert 0 < saved["action_window"]["remaining_ms"] <= 105_000
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "RESUME", "expected_state_version": saved["game"]["state_version"]}).status_code == 200
    resumed = client.get(route, headers=_headers()).json()["data"]
    assert resumed["action_window"]["remaining_ms"] <= saved["action_window"]["remaining_ms"]
    expiry = datetime.fromisoformat(resumed["action_window"]["deadline_at"].replace("Z", "+00:00")) + timedelta(milliseconds=1)
    expire_discussion(runtime._discussion, USER_ID, game_id, now=expiry)
    final = client.get(route, headers=_headers()).json()["data"]
    assert final["game"]["phase"] == expected
    expire_discussion(runtime._discussion, USER_ID, game_id, now=expiry)
    assert client.get(route, headers=_headers()).json()["data"]["game"]["state_version"] == final["game"]["state_version"]


def test_free_discussion_concurrent_eighth_message_is_rejected():
    """같은 버전으로 경쟁한 발언은 하나만 반영하고 재시도로 7회 상한을 넘지 못한다."""
    from concurrent.futures import ThreadPoolExecutor
    client = _client()
    game_id, _ = _create(client)
    route = f"/api/v1/games/{game_id}"
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "BEGIN_GAME", "expected_state_version": 1}).status_code == 200
    for i in range(6):
        snapshot = client.get(route, headers=_headers()).json()["data"]
        assert client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "SPEAK", "message": f"합성 발언 {i}", "expected_state_version": snapshot["game"]["state_version"], "window_id": snapshot["action_window"]["window_id"]}).status_code == 200
    snapshot = client.get(route, headers=_headers()).json()["data"]
    payload = {"type": "SPEAK", "message": "합성 경쟁 발언", "expected_state_version": snapshot["game"]["state_version"], "window_id": snapshot["action_window"]["window_id"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(route + "/commands", headers=_headers(uuid4()), json=payload), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    snapshot = client.get(route, headers=_headers()).json()["data"]
    payload.update(expected_state_version=snapshot["game"]["state_version"], window_id=snapshot["action_window"]["window_id"])
    assert client.post(route + "/commands", headers=_headers(uuid4()), json=payload).status_code == 429


def test_free_discussion_ai_resumes_after_rolling_minute_limit():
    """1분 45초 토론에서 전원 분당 상한 뒤에도 AI 예약이 남아 다음 분 발언을 재개한다."""
    client = _client()
    game_id, _ = _create(client)
    route = f"/api/v1/games/{game_id}"
    assert client.post(route + "/commands", headers=_headers(uuid4()), json={"type": "BEGIN_GAME", "expected_state_version": 1}).status_code == 200
    runtime = client.app.state.game_runtime
    for index in range(35):
        snapshot = client.get(route, headers=_headers()).json()["data"]
        window = snapshot["action_window"]
        runtime._agent_discussion.submit_speak(USER_ID, game_id, UUID(window["turn_player_id"]), f"합성 AI 발언 {index}", expected_state_version=snapshot["game"]["state_version"], window_id=UUID(window["window_id"]))
    assert not any(str(row["game_id"]) == str(game_id) for row in runtime.list_ai_speech_turns())
    with psycopg.connect(get_settings().effective_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE public.action_submissions SET submitted_at=submitted_at-interval '61 seconds' WHERE game_id=%s", (game_id,))
    assert any(str(row["game_id"]) == str(game_id) for row in runtime.list_ai_speech_turns())
