"""명시한 격리 PostgreSQL에서 발언 원장→worker→공개 API 연결을 검증한다."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from backend.app.core.config import Settings
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.main import create_app
from backend.app.repositories.action_repository import ActionWindowInsert, PostgresActionRepository
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.repositories.speech_analysis_repository import PostgresSpeechAnalysisRepository
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.speech_analysis_worker import SpeechAnalysisWorker


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("transition_result", [None, {"result_state_version": 22}])
def test_pre_vote_wait_keeps_expired_discussion_until_analysis_settles(
    monkeypatch, caplog, ready, transition_result,
):
    """분석 대기는 게임 transaction 밖에서 수행하고 준비한 창에만 전환을 적용한다."""

    from unittest.mock import MagicMock
    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    runtime = PostgresGameRuntime.__new__(PostgresGameRuntime)
    runtime._settings = Settings(database_url="postgresql://synthetic@127.0.0.1:1/qa")
    runtime._transactions = MagicMock()
    runtime._discussion = SimpleNamespace()
    runtime._agent_discussion = SimpleNamespace()
    row = {"id": uuid4(), "owner_user_id": uuid4(), "window_id": uuid4(),
           "phase": "DAY_DISCUSSION", "day_number": 2}
    runtime._actions_repository = Mock()
    runtime._actions_repository.expired_discussions.return_value = [row]
    repository = Mock()

    def prepare(**kwargs):
        runtime._transactions.transaction.return_value.__exit__.assert_called_once()
        assert kwargs["game_id"] == row["id"]
        return ready

    repository.prepare_for_vote.side_effect = prepare
    runtime.configure_speech_analysis(repository)
    runtime._mutation = Mock(side_effect=lambda owner, game, call: call())
    caplog.set_level(logging.INFO, logger="backend.app.services.game.postgres_runtime")
    expire = Mock(return_value=transition_result)
    monkeypatch.setattr("backend.app.services.game.discussion_transaction.expire_discussion", expire)
    runtime.expire_discussions()
    repository.prepare_for_vote.assert_called_once()
    assert expire.call_count == int(ready)
    if ready:
        assert expire.call_args.kwargs["expected_window_id"] == row["window_id"]
    applied = [record.message for record in caplog.records
               if "DISCUSSION_TRANSITION_APPLIED" in record.message]
    assert len(applied) == int(ready and transition_result is not None)
    if applied:
        assert f"game_id={row['id']} window_id={row['window_id']}" in applied[0]
        assert f"pid={os.getpid()} analysis=READY" in applied[0]


@pytest.mark.parametrize("mode,error,reason", [
    ("disabled", RuntimeError, None),
    ("first_day", RuntimeError, None),
    ("repository_error", RuntimeError, "PREPARE_ERROR"),
    ("repository_error", psycopg.errors.LockNotAvailable, "DB_LOCK_TIMEOUT"),
    ("repository_error", psycopg.errors.QueryCanceled, "DB_QUERY_CANCELED"),
    ("repository_error", TimeoutError, "DEPENDENCY_TIMEOUT"),
])
def test_pre_vote_gate_does_not_block_first_night_or_analysis_outage(
    monkeypatch, caplog, mode, error, reason,
):
    """첫날·비활성·선택 의존성 장애에서는 투표 준비 호출을 우회하거나 고정 코드로 격리한다."""

    from unittest.mock import MagicMock
    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    runtime = PostgresGameRuntime.__new__(PostgresGameRuntime)
    runtime._settings = Settings(database_url="postgresql://synthetic@127.0.0.1:1/qa")
    runtime._transactions = MagicMock()
    runtime._discussion = SimpleNamespace()
    runtime._agent_discussion = SimpleNamespace()
    runtime._actions_repository = Mock()
    runtime._actions_repository.expired_discussions.return_value = [
        {"id": uuid4(), "owner_user_id": uuid4(), "window_id": uuid4(),
         "phase": "DAY_DISCUSSION", "day_number": 1 if mode == "first_day" else 2}]
    repository = Mock()
    repository.prepare_for_vote.side_effect = error("SYNTHETIC_PRIVATE_ERROR")
    runtime.configure_speech_analysis(None if mode == "disabled" else repository)
    runtime._mutation = Mock(side_effect=lambda owner, game, call: call())
    expire = Mock()
    monkeypatch.setattr("backend.app.services.game.discussion_transaction.expire_discussion", expire)
    runtime.expire_discussions()
    expire.assert_called_once()
    assert repository.prepare_for_vote.call_count == int(mode == "repository_error")
    assert "SYNTHETIC_PRIVATE_ERROR" not in caplog.text
    if mode == "repository_error":
        assert "SPEECH_ANALYSIS_PRE_VOTE_FAILED" in caplog.text
        row = runtime._actions_repository.expired_discussions.return_value[0]
        assert f"game_id={row['id']} window_id={row['window_id']}" in caplog.text
        assert f"pid={os.getpid()} reason_code={reason}" in caplog.text


def test_prepared_discussion_cannot_expire_a_replacement_window():
    """분석 도중 저장·재개로 창이 바뀌면 이전 준비 결과로 새 창을 전환하지 않는다."""

    from unittest.mock import MagicMock
    from backend.app.services.game.discussion_transaction import expire_discussion

    owner, game = uuid4(), uuid4()
    service = MagicMock()
    service._games.lock_game.return_value = {"owner_user_id": owner}
    service._actions.current_window.return_value = {
        "id": uuid4(), "window_kind": "SPEECH", "deadline_at": datetime.now(UTC) - timedelta(seconds=1)}
    assert expire_discussion(service, owner, game, expected_window_id=uuid4()) is None
    service._games.update_game_state.assert_not_called()


def test_failed_discussion_transition_does_not_starve_other_games(caplog):
    """준비가 끝난 한 게임의 전환 실패 뒤에도 다음 게임은 같은 주기에 처리한다."""

    from unittest.mock import MagicMock
    from backend.app.services.game.postgres_runtime import PostgresGameRuntime

    runtime = PostgresGameRuntime.__new__(PostgresGameRuntime)
    runtime._transactions = MagicMock()
    runtime._speech_analysis_repository = None
    runtime._actions_repository = Mock()
    runtime._actions_repository.expired_discussions.return_value = [
        {"id": uuid4(), "owner_user_id": uuid4(), "window_id": uuid4(),
         "phase": "DAY_DISCUSSION", "day_number": 2} for _ in range(2)]
    runtime._mutation = Mock(side_effect=[RuntimeError("SYNTHETIC_PRIVATE_ERROR"), None])
    runtime.expire_discussions()
    assert runtime._mutation.call_count == 2
    assert "DISCUSSION_TRANSITION_FAILED" in caplog.text
    assert "SYNTHETIC_PRIVATE_ERROR" not in caplog.text


@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "FINAL_DISCUSSION"])
@pytest.mark.parametrize("command", ["PASS", "SPEAK"])
def test_last_legacy_speech_waits_in_closed_discussion_before_vote(monkeypatch, phase, command):
    """구형 순차 토론도 마지막 행동을 한 번 저장하고 투표 시간 소진 없이 분석을 기다린다."""

    from unittest.mock import MagicMock
    from backend.app.models.enums import GamePhase, PlayerKind, PlayerRole
    from backend.app.models.game_state import GameState, PlayerState
    from backend.app.schemas.command_schema import GameCommandRequest
    from backend.app.services.game.discussion_transaction import submit_discussion_transaction

    owner, game, window_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    players = [PlayerState(uuid4(), i + 1, PlayerRole.CITIZEN,
                           kind=PlayerKind.HUMAN if i == 0 else PlayerKind.AI) for i in range(6)]
    state = GameState(game, b"synthetic", players, phase=GamePhase(phase), day_number=2,
                      round=2, state_version=10, speech_had_content=True,
                      speech_actors={p.player_id for p in players[1:]})
    service = MagicMock()
    service.wait_for_speech_analysis = True
    service._games.lock_game.return_value = {"id": game, "owner_user_id": owner}
    service._receipts.find.return_value = None
    service._actions.current_window.return_value = {
        "id": window_id, "window_kind": "SPEECH", "status": "OPEN", "phase": phase,
        "turn_player_id": players[0].player_id, "deadline_at": None}
    monkeypatch.setattr("backend.app.services.game.discussion_transaction.restore_locked_game",
                        lambda *args: (state, players[0].player_id))
    payload = GameCommandRequest(type=command, expected_state_version=10, window_id=window_id,
                                 message="합성 공개 발언" if command == "SPEAK" else None)
    result, replayed = submit_discussion_transaction(service, owner, game, payload, uuid4(), now=now)
    following = service._actions.open_window.call_args.args[1]
    assert not replayed and result["result_state_version"] == 11
    assert state.phase.value == phase
    assert following.window_kind == "SPEECH" and following.deadline_at == now
    service._actions.insert_submission.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "start", "stop"])
async def test_analysis_lifecycle_failure_keeps_game_available(monkeypatch, caplog, failure):
    """선택적 분석 초기화·종료 실패가 게임 lifespan을 실패시키거나 원문을 기록하지 않는다."""

    runtime = SimpleNamespace(start_background_worker=Mock(), stop_background_worker=AsyncMock())
    worker = SimpleNamespace(start=Mock(), stop=AsyncMock())
    error = RuntimeError("SYNTHETIC_PRIVATE_ERROR")
    provider = Mock(side_effect=error) if failure == "provider" else Mock()
    if failure == "start":
        worker.start.side_effect = error
    if failure == "stop":
        worker.stop.side_effect = error
    monkeypatch.setattr("backend.app.main.build_postgres_runtime", lambda settings: runtime)
    monkeypatch.setattr("backend.app.llm_provider.speech_analysis_provider.SpeechAnalysisProvider", provider)
    monkeypatch.setattr("backend.app.services.game.speech_analysis_worker.SpeechAnalysisWorker", lambda *args: worker)
    app = create_app(settings=Settings(database_url="postgresql://synthetic@127.0.0.1:1/qa",
                                      speech_analysis_enabled=True, openai_api_key="synthetic-never-sent"))
    async with app.router.lifespan_context(app):
        runtime.start_background_worker.assert_called_once()
        assert app.state.speech_analysis_start_failed is (failure != "stop")
    runtime.stop_background_worker.assert_awaited_once()
    assert "SYNTHETIC_PRIVATE_ERROR" not in caplog.text


@pytest.fixture
def scenario():
    """일반 테스트에서는 건너뛰고 새 QA DB의 자기 UUID 데이터만 생성·정리한다."""

    url = os.getenv("VOTE_INSIGHT_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("VOTE_INSIGHT_TEST_DATABASE_URL로 격리 DB를 명시해야 합니다.")
    address = urlsplit(url)
    if address.hostname not in {"127.0.0.1", "localhost"} or not address.path.startswith(
        "/mafia_vote_insights_qa_"
    ):
        pytest.fail("발언 분석 통합 검증은 loopback 전용 QA DB만 허용합니다.")
    settings = Settings(
        database_url=url, preserve_database_path=True, redis_url="redis://127.0.0.1:1/0",
        llm_provider="dummy", openai_api_key="synthetic-never-sent",
        speech_analysis_enabled=True, speech_analysis_version=uuid4().hex,
        speech_analysis_batch_size=32,
    )
    app = create_app(settings=settings, enable_background_worker=False)
    owner = uuid4()
    created, _ = app.state.game_runtime.create(
        owner, CreateGameRequest(player_count=6, ruleset_version="mystery-v1",
                                 scenario_version="scenario-v1"), uuid4(),
    )
    game_id = UUID(created["game_id"])
    connection = psycopg.connect(url, row_factory=dict_row, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, seat, kind FROM public.game_players WHERE game_id=%s ORDER BY seat", (game_id,))
            players = cursor.fetchall()
            cursor.execute("UPDATE public.games SET status='IN_PROGRESS', phase='DAY_DISCUSSION', round=1, day_number=2, state_version=2 WHERE id=%s", (game_id,))
        value = {"settings": settings, "app": app, "owner": owner, "game_id": game_id,
                 "connection": connection, "players": players, "sequence": 0}
        _open_window(value, "SPEECH", "DAY_DISCUSSION", players[0]["id"])
        yield value
    finally:
        # migration 담당자가 준비한 다른 합성 게임이나 기존 DB에는 접근하지 않는다.
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM public.games WHERE id=%s AND owner_user_id=%s", (game_id, owner))
            cursor.execute("DELETE FROM public.users WHERE id=%s", (owner,))
        connection.close()


def _append(scenario, event_type, payload, *, operation="APPEND_PUBLIC_EVENT", private=False):
    """합성 공개 기록을 실제 event repository로 저장하되 내부 정보는 반환하지 않는다."""

    connection, game_id = scenario["connection"], scenario["game_id"]
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("UPDATE public.games SET next_front_sequence=next_front_sequence+1 WHERE id=%s RETURNING next_front_sequence-1 AS cursor", (game_id,))
        front = cursor.fetchone()["cursor"]
        event = PostgresEventRepository().append(
            cursor, game_id=game_id, state_version=2, event_type=event_type,
            audience="PLAYER" if private else "PUBLIC",
            audience_player_id=scenario["players"][1]["id"] if private else None,
            payload=payload, operation_type=None if private else operation,
            front_sequence=None if private else front, operation_index=None if private else 0,
        )
    scenario["sequence"] = event["sequence"]
    return event


def _open_window(scenario, kind, phase, actor=None):
    """원장의 window 개설 순서만 합성하여 실제 읽기 cutoff 계약을 검증한다."""

    window = uuid4()
    with scenario["connection"].transaction(), scenario["connection"].cursor() as cursor:
        cursor.execute("UPDATE public.action_windows SET status='RESOLVED', resolved_at=clock_timestamp() WHERE game_id=%s AND status IN ('OPEN','PAUSED','RESOLVING')", (scenario["game_id"],))
        cursor.execute("UPDATE public.games SET phase=%s WHERE id=%s", (phase, scenario["game_id"]))
        PostgresActionRepository().open_window(cursor, ActionWindowInsert(
            window_id=window, game_id=scenario["game_id"], window_kind=kind, phase=phase,
            round=1, cycle=1, turn_player_id=actor, opened_state_version=2,
            deadline_at=datetime.now(UTC) + timedelta(minutes=10),
        ))
    scenario["window_id"] = window
    _append(scenario, "TURN_OPENED", {"window_id": str(window), "kind": kind},
            operation="SET_ACTION_WINDOW")
    return window


class FakeAnalysisProvider:
    """실제 네트워크 없이 동일 주장·반대 입장과 한국어 근거 구간을 제공한다."""

    def __init__(self, target):
        self.target = str(target)
        self.calls = 0

    async def embed(self, message):
        self.calls += 1
        return ([1.0, 0.0] if "수상해" in message else [0.0, 1.0]) + [0.0] * 1534

    async def extract_claims(self, message, players):
        assert self.target in {str(player["player_id"]) for player in players}
        return [{"target_player_id": self.target,
                 "stance": "SUSPICION" if "수상해" in message else "DEFENSE",
                 "proposition": message, "evidence_start": 0,
                 "evidence_end": len(message), "quote": message}]


def _process(scenario, provider):
    """기존 공유 원장을 역채움하지 않도록 테스트 게임에만 발견 범위를 제한한다."""

    repository = PostgresSpeechAnalysisRepository(TransactionManager(scenario["settings"].effective_database_url))

    class ScopedRepository:
        def __getattr__(self, name):
            return getattr(repository, name)

        def discover(self, **kwargs):
            return repository.discover(**kwargs, game_id=scenario["game_id"])

    worker = SpeechAnalysisWorker(ScopedRepository(), provider, scenario["settings"])
    for _ in range(4):
        if not asyncio.run(worker.run_once()):
            break
    return repository


def _get(scenario, *, owner=None, window=None, scope="current_discussion"):
    with TestClient(scenario["app"]) as client:
        return client.get(
            f"/api/v1/games/{scenario['game_id']}/vote-insights",
            params={"window_id": str(window or scenario["window_id"]), "scope": scope},
            headers={"X-User-Id": str(owner or scenario["owner"])},
        )


def test_real_pipeline_deduplicates_accusers_and_preserves_public_boundary(scenario):
    """단계별 DB 저장을 거친 실제 API가 반복 의심을 중복 집계하거나 private를 섞지 않는다."""

    ai = [player for player in scenario["players"] if player["kind"] == "AI"]
    target = ai[2]
    message = f"{target['seat']}번의 알리바이가 수상해."
    for actor in (ai[0], ai[0], ai[1]):
        _append(scenario, "PLAYER_SPOKE", {"player_id": str(actor["id"]), "message": message})
    _append(scenario, "PLAYER_SPOKE", {"player_id": str(ai[3]["id"]), "message": f"{target['seat']}번은 마피아가 아니야."})
    human = next(player for player in scenario["players"] if player["kind"] == "HUMAN")
    _append(scenario, "PLAYER_SPOKE", {"player_id": str(human["id"]), "message": message})
    _append(scenario, "PLAYER_SPOKE", {"player_id": str(ai[0]["id"]), "message": "비공개 합성 근거"}, private=True)
    _append(scenario, "PLAYER_SPOKE", {"player_id": str(ai[0]["id"]), "message": "공개 operation이 아닌 합성 근거"}, operation="SET_PRIVATE_STATE")
    _append(scenario, "PLAYER_PASSED", {"player_id": str(ai[1]["id"])})
    provider = FakeAnalysisProvider(target["id"])
    repository = _process(scenario, provider)
    assert provider.calls == 0
    runtime = scenario["app"].state.game_runtime
    runtime.configure_speech_analysis(repository)
    with scenario["connection"].cursor() as cursor:
        cursor.execute("UPDATE public.action_windows SET deadline_at=clock_timestamp()-interval '1 second' WHERE id=%s", (scenario["window_id"],))
    runtime.expire_discussions()
    with scenario["connection"].cursor() as cursor:
        cursor.execute("SELECT phase,state_version FROM public.games WHERE id=%s", (scenario["game_id"],))
        assert cursor.fetchone() == {"phase": "DAY_DISCUSSION", "state_version": 2}
    assert _get(scenario).status_code == 409
    _process(scenario, provider)
    prepared_at = datetime.now(UTC)
    runtime.expire_discussions()
    with scenario["connection"].cursor() as cursor:
        cursor.execute("SELECT id,phase,deadline_at FROM public.action_windows WHERE game_id=%s AND status='OPEN'", (scenario["game_id"],))
        vote = cursor.fetchone()
    assert vote["phase"] == "DAY_VOTE"
    assert vote["deadline_at"] >= prepared_at + timedelta(seconds=29)
    scenario["window_id"] = vote["id"]
    result = _get(scenario)
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["status"] == "READY"
    assert data["coverage"] == {"total": 4, "embedding_ready": 4, "claims_ready": 4, "failed": 0}
    ranked = next(row for row in data["suspicion_ranking"] if row["target_player_id"] == str(target["id"]))
    assert ranked["accuser_count"] == 2 and ranked["speech_count"] == 3
    candidate = next(row for row in data["candidate_evidence"] if row["target_player_id"] == str(target["id"]))
    assert len(candidate["defense"]) == 1
    assert data["similar_claims"]
    assert "비공개 합성 근거" not in result.text and "embedding" not in data
    assert _get(scenario, owner=uuid4()).status_code == 404
    assert _get(scenario, window=uuid4()).status_code == 409
    first_revision = data["revision"]
    _process(scenario, provider)
    assert provider.calls == 4
    assert _get(scenario).json()["data"]["revision"] == first_revision


def test_first_day_waits_for_a_future_vote_without_analysis_calls(scenario):
    """첫날 토론 종료는 밤으로 진행하고 누적 공개 발언은 다음 투표 직전까지 보류한다."""

    ai = next(player for player in scenario["players"] if player["kind"] == "AI")
    _append(scenario, "PLAYER_SPOKE", {"player_id": str(ai["id"]), "message": "합성 첫날 발언"})
    with scenario["connection"].cursor() as cursor:
        cursor.execute("UPDATE public.games SET day_number=1 WHERE id=%s", (scenario["game_id"],))
        cursor.execute("UPDATE public.action_windows SET deadline_at=clock_timestamp()-interval '1 second' WHERE id=%s", (scenario["window_id"],))
    provider = FakeAnalysisProvider(ai["id"])
    repository = _process(scenario, provider)
    runtime = scenario["app"].state.game_runtime
    runtime.configure_speech_analysis(repository)
    runtime.expire_discussions()
    with scenario["connection"].cursor() as cursor:
        cursor.execute("SELECT phase FROM public.games WHERE id=%s", (scenario["game_id"],))
        assert cursor.fetchone()["phase"] == "NIGHT_ACTION"
    _process(scenario, provider)
    assert provider.calls == 0


def test_opening_cutoff_excludes_later_events_and_queries_do_not_write(scenario):
    """잘못 늦게 도착한 발언도 이전 창의 증거로 섞지 않고 읽기가 버전을 바꾸지 않는다."""

    ai = [player for player in scenario["players"] if player["kind"] == "AI"]
    _open_window(scenario, "VOTE", "DAY_VOTE")
    _append(scenario, "PLAYER_SPOKE", {"player_id": str(ai[0]["id"]), "message": "마감 뒤 합성 발언"})
    with scenario["connection"].cursor() as cursor:
        cursor.execute("SELECT state_version,next_event_sequence,next_front_sequence FROM public.games WHERE id=%s", (scenario["game_id"],))
        before = cursor.fetchone()
    result = _get(scenario)
    assert result.status_code == 200
    assert result.json()["data"]["coverage"]["total"] == 0
    assert result.json()["data"]["status"] == "READY"
    with scenario["connection"].cursor() as cursor:
        cursor.execute("SELECT state_version,next_event_sequence,next_front_sequence FROM public.games WHERE id=%s", (scenario["game_id"],))
        assert cursor.fetchone() == before
