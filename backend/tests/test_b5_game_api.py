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
