"""기존 PostgreSQL을 사용하는 최소 게임 흐름 smoke test."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient

from backend.app.core.config import Settings, get_settings
from backend.app.main import create_app


def test_postgres_create_begin_and_sync_with_test_run_id() -> None:
    """기존 DB의 seed 데이터를 사용해 생성·조회·시작·sync를 실제로 왕복한다."""

    settings: Settings = get_settings()
    test_run_id = uuid4().hex
    user_id = uuid4()
    create_key = uuid4()
    begin_key = uuid4()
    game_id = None
    redis_client = None
    try:
        application = create_app(settings=settings, enable_background_worker=False)
        with TestClient(application) as client:
            headers = {
                "X-User-Id": str(user_id),
                "Idempotency-Key": str(create_key),
                "X-Test-Run-Id": test_run_id,
            }
            created = client.post(
                "/api/v1/games",
                headers=headers,
                json={
                    "player_count": 6,
                    "ruleset_version": "mystery-v1",
                    "scenario_version": "scenario-v1",
                },
            )
            assert created.status_code == 201, created.text
            game_id = created.json()["data"]["game_id"]

            listed = client.get("/api/v1/games", headers={"X-User-Id": str(user_id)})
            assert listed.status_code == 200, listed.text
            assert any(item["game_id"] == game_id for item in listed.json()["data"]["items"])

            snapshot = client.get(
                f"/api/v1/games/{game_id}", headers={"X-User-Id": str(user_id)}
            )
            assert snapshot.status_code == 200, snapshot.text
            assert snapshot.json()["data"]["game"]["state_version"] == 1

            begun = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={
                    "X-User-Id": str(user_id),
                    "Idempotency-Key": str(begin_key),
                    "X-Test-Run-Id": test_run_id,
                },
                json={"type": "BEGIN_GAME", "expected_state_version": 1},
            )
            assert begun.status_code == 200, begun.text
            assert begun.json()["data"]["result_state_version"] == 2

            with psycopg.connect(settings.effective_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, turn_player_id, opened_state_version
                        FROM public.action_windows
                        WHERE game_id = %s AND status = 'OPEN'
                        """,
                        (game_id,),
                    )
                    human_window_id, _human_player_id, opened_version = cursor.fetchone()

            human_pass = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={"X-User-Id": str(user_id), "Idempotency-Key": str(uuid4())},
                json={
                    "type": "PASS",
                    "expected_state_version": opened_version,
                    "window_id": str(human_window_id),
                },
            )
            assert human_pass.status_code == 200, human_pass.text
            assert human_pass.json()["data"]["result_state_version"] > opened_version

            resumed_snapshot = client.get(
                f"/api/v1/games/{game_id}", headers={"X-User-Id": str(user_id)}
            )
            assert resumed_snapshot.status_code == 200, resumed_snapshot.text
            resumed_data = resumed_snapshot.json()["data"]
            assert resumed_data["game"]["phase"] == "DAY_DISCUSSION"
            assert resumed_data["game"]["state_version"] > opened_version
            assert resumed_data["action_window"] is not None
            assert resumed_data["action_window"]["window_id"]

            synced = client.get(
                f"/api/v1/games/{game_id}/sync?after_state_version=0&after_sequence=0",
                headers={"X-User-Id": str(user_id)},
            )
            assert synced.status_code == 200, synced.text
            sync_data = synced.json()["data"]
            assert sync_data["mode"] == "DELTA"
            assert sync_data["operations"]
            assert sync_data["operations"][0]["operations"]
    finally:
        _cleanup_postgres_test_data(settings, user_id=user_id)
        _cleanup_redis_test_namespace(settings, test_run_id=test_run_id)


def test_postgres_action_flow_keeps_ai_window_after_human_submission() -> None:
    """인간 제출이 AI 처리를 기다리지 않고 열린 window를 유지하는지 확인한다."""

    settings: Settings = get_settings()
    test_run_id = uuid4().hex
    user_id = uuid4()
    game_id = None
    try:
        application = create_app(settings=settings, enable_background_worker=False)
        with TestClient(application) as client:
            common_headers = {"X-User-Id": str(user_id), "X-Test-Run-Id": test_run_id}
            created = client.post(
                "/api/v1/games",
                headers={**common_headers, "Idempotency-Key": str(uuid4())},
                json={
                    "player_count": 6,
                    "ruleset_version": "mystery-v1",
                    "scenario_version": "scenario-v1",
                },
            )
            assert created.status_code == 201, created.text
            game_id = created.json()["data"]["game_id"]
            begun = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**common_headers, "Idempotency-Key": str(uuid4())},
                json={"type": "BEGIN_GAME", "expected_state_version": 1},
            )
            assert begun.status_code == 200, begun.text

            snapshot = client.get(f"/api/v1/games/{game_id}", headers=common_headers)
            assert snapshot.status_code == 200, snapshot.text
            data = snapshot.json()["data"]

            passed = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**common_headers, "Idempotency-Key": str(uuid4())},
                json={
                    "type": "PASS",
                    "expected_state_version": data["game"]["state_version"],
                    "window_id": data["action_window"]["window_id"],
                },
            )
            assert passed.status_code == 200, passed.text

            snapshot = client.get(f"/api/v1/games/{game_id}", headers=common_headers)
            assert snapshot.status_code == 200, snapshot.text
            data = snapshot.json()["data"]
            assert data["game"]["phase"] == "DAY_DISCUSSION"
            assert data["action_window"] is not None
            assert data["action_window"]["window_id"]
    finally:
        _cleanup_postgres_test_data(settings, user_id=user_id)
        _cleanup_redis_test_namespace(settings, test_run_id=test_run_id)


def test_postgres_fast_forward_restores_ended_snapshot() -> None:
    """사망 상태를 테스트 DB에 재현해 FAST_FORWARD와 종료 snapshot을 확인한다."""

    settings: Settings = get_settings()
    test_run_id = uuid4().hex
    user_id = uuid4()
    try:
        application = create_app(settings=settings, enable_background_worker=False)
        with TestClient(application) as client:
            headers = {"X-User-Id": str(user_id), "X-Test-Run-Id": test_run_id}
            created = client.post(
                "/api/v1/games",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"player_count": 6, "ruleset_version": "mystery-v1", "scenario_version": "scenario-v1"},
            )
            assert created.status_code == 201, created.text
            game_id = created.json()["data"]["game_id"]
            begun = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"type": "BEGIN_GAME", "expected_state_version": 1},
            )
            assert begun.status_code == 200, begun.text
            snapshot = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert snapshot.status_code == 200, snapshot.text
            human_id = snapshot.json()["data"]["me"]["player_id"]
            with psycopg.connect(settings.effective_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE public.game_players
                        SET alive = FALSE, eliminated_phase = 'DAY_DISCUSSION', eliminated_round = 1
                        WHERE game_id = %s AND id = %s
                        """,
                        (game_id, human_id),
                    )
            current = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert current.status_code == 200, current.text
            current_version = current.json()["data"]["game"]["state_version"]
            forwarded = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"type": "FAST_FORWARD", "expected_state_version": current_version},
            )
            assert forwarded.status_code == 200, forwarded.text
            ended = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert ended.status_code == 200, ended.text
            ended_data = ended.json()["data"]
            assert ended_data["game"]["status"] == "COMPLETED"
            assert ended_data["game"]["phase"] == "ENDED"
            assert ended_data["result"] is not None
    finally:
        _cleanup_postgres_test_data(settings, user_id=user_id)
        _cleanup_redis_test_namespace(settings, test_run_id=test_run_id)


def test_postgres_save_and_resume_round_trip() -> None:
    """실제 PostgreSQL에서 저장 snapshot과 RESUME 후 상태를 확인한다."""

    settings: Settings = get_settings()
    test_run_id = uuid4().hex
    user_id = uuid4()
    try:
        application = create_app(settings=settings, enable_background_worker=False)
        with TestClient(application) as client:
            headers = {"X-User-Id": str(user_id), "X-Test-Run-Id": test_run_id}
            created = client.post(
                "/api/v1/games",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"player_count": 6, "ruleset_version": "mystery-v1", "scenario_version": "scenario-v1"},
            )
            assert created.status_code == 201, created.text
            game_id = created.json()["data"]["game_id"]
            begun = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"type": "BEGIN_GAME", "expected_state_version": 1},
            )
            assert begun.status_code == 200, begun.text
            before = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert before.status_code == 200, before.text
            before_data = before.json()["data"]
            saved = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={
                    "type": "SAVE_AND_EXIT",
                    "expected_state_version": before_data["game"]["state_version"],
                },
            )
            assert saved.status_code == 200, saved.text
            saved_snapshot = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert saved_snapshot.status_code == 200, saved_snapshot.text
            saved_data = saved_snapshot.json()["data"]
            assert saved_data["game"]["status"] == "SAVED"
            assert saved_data["legal_actions"] == ["RESUME"]

            resumed = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={
                    "type": "RESUME",
                    "expected_state_version": saved_data["game"]["state_version"],
                },
            )
            assert resumed.status_code == 200, resumed.text
            resumed_snapshot = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert resumed_snapshot.status_code == 200, resumed_snapshot.text
            resumed_data = resumed_snapshot.json()["data"]
            assert resumed_data["game"]["status"] == "IN_PROGRESS"
            assert resumed_data["game"]["phase"] == "DAY_DISCUSSION"
            assert resumed_data["action_window"] is not None
    finally:
        _cleanup_postgres_test_data(settings, user_id=user_id)
        _cleanup_redis_test_namespace(settings, test_run_id=test_run_id)


def _cleanup_postgres_test_data(settings: Settings, *, user_id) -> None:
    """테스트가 만든 사용자와 게임만 명시적인 UUID로 정리한다."""

    with psycopg.connect(settings.effective_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM public.games WHERE owner_user_id = %s", (user_id,))
            cursor.execute("DELETE FROM public.users WHERE id = %s", (user_id,))


def _cleanup_redis_test_namespace(settings: Settings, *, test_run_id: str) -> None:
    """현재 실행 ID를 포함한 Redis 테스트 키만 삭제한다."""

    try:
        import redis

        redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
        keys = list(redis_client.scan_iter(match=f"*{test_run_id}*"))
        if keys:
            redis_client.delete(*keys)
    except Exception:
        # Redis가 아직 runtime에 연결되지 않은 환경에서도 DB 정리는 보장한다.
        return
