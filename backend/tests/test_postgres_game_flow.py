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
            assert sync_data["game_id"] == game_id
            assert sync_data["state_version"] == resumed_data["game"]["state_version"]
            assert sync_data["last_sequence"] == resumed_data["game"]["last_sequence"]
            if sync_data["mode"] == "DELTA":
                assert sync_data["snapshot"] is None
                assert sync_data["operations"]
                assert sync_data["operations"][0]["operations"]
                assert sync_data["operations"][-1]["state_version"] == sync_data["state_version"]
                assert sync_data["operations"][-1]["front_sequence"] == sync_data["last_sequence"]
            else:
                # 검증할 수 없는 과거 batch는 현재 snapshot으로 복구하되 내용도 대조한다.
                assert sync_data["mode"] == "SNAPSHOT"
                assert sync_data["operations"] == []
                synchronized = sync_data["snapshot"]
                for key in ("game", "scenario", "players", "me", "public_events", "result"):
                    assert synchronized[key] == resumed_data[key]
                assert synchronized["action_window"]["window_id"] == resumed_data["action_window"]["window_id"]
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


def test_postgres_fast_forward_persists_selection_before_worker_progress() -> None:
    """빠른 진행은 선택만 저장하며 worker가 꺼진 동안 phase와 결과는 유지된다."""

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
            before_forward = current.json()["data"]
            current_version = before_forward["game"]["state_version"]
            assert before_forward["me"]["spectator"] is True
            assert before_forward["game"]["fast_forward_enabled"] is False
            assert "FAST_FORWARD" in before_forward["legal_actions"]
            forwarded = client.post(
                f"/api/v1/games/{game_id}/commands",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"type": "FAST_FORWARD", "expected_state_version": current_version},
            )
            assert forwarded.status_code == 200, forwarded.text
            selected = client.get(f"/api/v1/games/{game_id}", headers=headers)
            assert selected.status_code == 200, selected.text
            selected_data = selected.json()["data"]
            assert selected_data["game"]["status"] == "IN_PROGRESS"
            assert selected_data["game"]["phase"] == before_forward["game"]["phase"]
            assert selected_data["game"]["round"] == before_forward["game"]["round"]
            assert selected_data["game"]["state_version"] == current_version + 1
            assert selected_data["game"]["fast_forward_enabled"] is True
            assert selected_data["players"] == before_forward["players"]
            assert selected_data["result"] is None
            assert "FAST_FORWARD" not in selected_data["legal_actions"]
            assert "SAVE_AND_EXIT" in selected_data["legal_actions"]
            assert selected_data["action_window"]["window_id"] == before_forward["action_window"]["window_id"]
            assert selected_data["action_window"]["deadline_at"] == before_forward["action_window"]["deadline_at"]
            with psycopg.connect(settings.effective_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT fast_forward_enabled FROM public.games WHERE id = %s", (game_id,))
                    assert cursor.fetchone() == (True,)
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


def test_postgres_user_activity_changes_only_on_successful_user_commands() -> None:
    """실제 DB에서 조회·재전송·AI 처리와 성공한 인간 command의 보존 시각을 구분한다."""

    settings = get_settings()
    user_id = uuid4()
    test_run_id = uuid4().hex

    def activity_time(game_id):
        """합성 게임 한 건의 DB 시각만 읽으며 저장된 사용자 내용은 출력하지 않는다."""

        with psycopg.connect(settings.effective_database_url) as connection:
            return connection.execute(
                "SELECT last_user_action_at FROM public.games WHERE id = %s",
                (game_id,),
            ).fetchone()[0]

    try:
        application = create_app(settings=settings, enable_background_worker=False)
        with TestClient(application) as client:
            headers = {"X-User-Id": str(user_id), "X-Test-Run-Id": test_run_id}
            created = client.post(
                "/api/v1/games", headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"player_count": 6, "ruleset_version": "mystery-v1",
                      "scenario_version": "scenario-v1"},
            )
            assert created.status_code == 201
            game_id = created.json()["data"]["game_id"]
            initial = activity_time(game_id)
            path = f"/api/v1/games/{game_id}"
            assert client.get(path, headers=headers).status_code == 200
            assert client.get("/api/v1/games", headers=headers).status_code == 200
            assert activity_time(game_id) == initial

            begin_headers = {**headers, "Idempotency-Key": str(uuid4())}
            begin_body = {"type": "BEGIN_GAME", "expected_state_version": 1}
            begun = client.post(path + "/commands", headers=begin_headers, json=begin_body)
            assert begun.status_code == 200
            begun_at = activity_time(game_id)
            assert begun_at > initial
            replay = client.post(path + "/commands", headers=begin_headers, json=begin_body)
            assert replay.status_code == 200 and replay.json()["meta"]["replayed"]
            assert activity_time(game_id) == begun_at

            snapshot = client.get(path, headers=headers).json()["data"]
            window = snapshot["action_window"]
            # Provider를 부르지 않고 검증된 AI PASS 저장 경로만 실행한다.
            application.state.game_runtime.agent_pass(
                user_id, UUID(game_id), UUID(window["turn_player_id"]),
                expected_state_version=snapshot["game"]["state_version"],
                window_id=UUID(window["window_id"]),
            )
            assert activity_time(game_id) == begun_at
            rejected = client.post(
                path + "/commands", headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"type": "BEGIN_GAME", "expected_state_version": 1},
            )
            assert rejected.status_code == 409
            assert activity_time(game_id) == begun_at

            previous = begun_at
            for command, status in (("SAVE_AND_EXIT", "SAVED"), ("RESUME", "IN_PROGRESS")):
                snapshot = client.get(path, headers=headers).json()["data"]
                response = client.post(
                    path + "/commands", headers={**headers, "Idempotency-Key": str(uuid4())},
                    json={"type": command,
                          "expected_state_version": 1 if command == "SAVE_AND_EXIT" else snapshot["game"]["state_version"]},
                )
                assert response.status_code == 200
                current = activity_time(game_id)
                assert current > previous
                assert client.get(path, headers=headers).json()["data"]["game"]["status"] == status
                previous = current
    finally:
        _cleanup_postgres_test_data(settings, user_id=user_id)
        _cleanup_redis_test_namespace(settings, test_run_id=test_run_id)


def test_persona_reasoning_migration_preserves_other_fields_and_is_idempotent() -> None:
    """격리 QA의 임시 테이블에서 추론값·해시만 갱신하고 재실행·version 경계를 검증한다."""

    from pathlib import Path
    from urllib.parse import urlsplit
    import pytest
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    url = get_settings().effective_database_url
    assert urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}
    targets = {
        "CAUTIOUS_ANALYST": 0.8, "OBSERVANT_NOTEKEEPER": 0.8,
        "ACTIVE_DEBATER": 0.75, "COOPERATIVE_MEDIATOR": 0.7,
        "BALANCED_OBSERVER": 0.7, "EMOTIONAL_REACTOR": 0.6,
    }
    sql = (Path(__file__).parents[1] / "migrations/009_update_persona_reasoning_skill.sql").read_text()
    sql = sql.replace("public.agent_personas", "pg_temp.agent_personas")
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
        connection.execute("CREATE TEMP TABLE agent_personas (LIKE public.agent_personas INCLUDING ALL)")
        for name in [*targets, "SYNTHETIC_UNRELATED"]:
            connection.execute(
                "INSERT INTO pg_temp.agent_personas (id, version, display_name, speech_style, "
                "backstory, parameters, active, content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (name, "mystery-v1" if name == "BALANCED_OBSERVER" else "agent-config-v1",
                 "합성 인물", "합성 말투", "합성 배경", Jsonb({"reasoning_skill": 0.5, "suspicion": 0.23}),
                 name != "BALANCED_OBSERVER", "0" * 64),
            )

        def rows():
            """행 원문과 물리 버전을 함께 읽어 불필요한 반복 UPDATE까지 확인한다."""

            return {row["id"]: row for row in connection.execute(
                "SELECT *, xmin::text AS row_version FROM pg_temp.agent_personas ORDER BY id"
            ).fetchall()}

        before = rows()
        connection.execute(
            "ALTER TABLE pg_temp.agent_personas ADD CONSTRAINT synthetic_reject_high "
            "CHECK ((parameters->>'reasoning_skill')::numeric <= 0.7)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(sql)
        connection.execute("ROLLBACK")
        assert rows() == before
        connection.execute("ALTER TABLE pg_temp.agent_personas DROP CONSTRAINT synthetic_reject_high")
        connection.execute(sql)
        after = rows()
        for name, expected in targets.items():
            assert after[name]["parameters"] == {"reasoning_skill": expected, "suspicion": 0.23}
            assert after[name]["content_hash"] != before[name]["content_hash"]
            for field in before[name].keys() - {"parameters", "content_hash", "row_version"}:
                assert after[name][field] == before[name][field]
        assert after["SYNTHETIC_UNRELATED"] == before["SYNTHETIC_UNRELATED"]
        assert connection.execute(
            "SELECT bool_and(content_hash = encode(digest(concat_ws('|', id, version, "
            "display_name, speech_style, backstory, parameters::text), 'sha256'), 'hex')) AS valid "
            "FROM pg_temp.agent_personas WHERE id <> 'SYNTHETIC_UNRELATED'"
        ).fetchone()["valid"]
        connection.execute(sql)
        assert rows() == after

        connection.execute(
            "UPDATE pg_temp.agent_personas SET version = 'future-version', "
            "parameters = '{\"reasoning_skill\":0.5}'::jsonb WHERE id = 'CAUTIOUS_ANALYST'"
        )
        future = rows()["CAUTIOUS_ANALYST"]
        connection.execute(sql)
        assert rows()["CAUTIOUS_ANALYST"] == future


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
