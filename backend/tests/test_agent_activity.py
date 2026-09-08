"""실제 DB·Provider 없이 진행 로그의 격리·순서·commit 경계를 검증한다."""

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.agent.activity import AgentActivity
from backend.app.agent.orchestrator import AgentRunResult
from backend.app.llm_provider.schemas import NormalizedAgentProposal
from backend.app.services.game.postgres_runtime import PostgresGameRuntime
from backend.app.services.game.ai_progress_worker import AiProgressWorker, _log_worker_error


def collector(**kwargs):
    """테스트별 독립 logger로 전역 설정과 실제 로그 파일에 영향을 주지 않는다."""

    stream = io.StringIO()
    logger = logging.Logger("synthetic-progress")
    logger.addHandler(logging.StreamHandler(stream))
    return AgentActivity(logger=logger, **kwargs), stream


def record(activity, owner, game, actor, **kwargs):
    """공개 발언의 승인된 메타데이터만 사용하는 synthetic 입력이다."""

    return activity.record(owner_user_id=owner, game_id=game, player_id=actor,
                           phase="DAY_DISCUSSION", state_version=2, stage="DECIDED", **kwargs)


def test_threaded_sequence_order_and_bounded_owner_history():
    activity, stream = collector(max_games=2)
    owner, game, actor = uuid4(), uuid4(), uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: record(activity, owner, game, actor, action="PASS"), range(100)))
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [row["sequence"] for row in rows] == list(range(1, 101))
    history = activity.recent(owner, game)
    assert len(history) == 50 and history[0]["sequence"] == 51
    assert all(row["created_at"].endswith("Z") for row in history)
    assert activity.recent(uuid4(), game) == []
    assert activity.recent(owner, uuid4()) == []
    history[0]["summary"] = "수정된 복사본"
    assert activity.recent(owner, game)[0]["summary"] != "수정된 복사본"
    record(activity, owner, uuid4(), actor)
    record(activity, owner, uuid4(), actor)
    assert activity.recent(owner, game) == []
    assert collector()[0].run_id != activity.run_id


def test_private_activity_masks_actor_action_and_dummy_is_explicit():
    activity, stream = collector()
    owner, game, actor = uuid4(), uuid4(), uuid4()
    for phase in ("NIGHT_ACTION", "DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"):
        activity.record(owner_user_id=owner, game_id=game, player_id=actor, phase=phase,
                        state_version=2, stage="DECIDED", action="NIGHT_ACTION")
    assert str(actor) not in stream.getvalue()
    assert activity.recent(owner, game) == []
    row = record(activity, owner, game, actor, action="PASS", dummy=True)
    assert "더미" in row["summary"] and len(row["summary"]) <= 200
    assert set(row) == {"sequence", "run_id", "created_at", "player_id", "phase", "state_version", "stage", "action", "summary", "decision_source", "reason_code", "decision_basis"}
    with pytest.raises(ValueError):
        activity.record(stage="synthetic secret")
    with pytest.raises(TypeError):
        activity.record(stage="DECIDED", target_player_id=actor)


def test_logger_failure_does_not_interrupt_record_or_worker_leak(monkeypatch):
    class BrokenLogger:
        def info(self, message):
            raise OSError("synthetic secret")
    activity = AgentActivity(logger=BrokenLogger())
    owner, game, actor = uuid4(), uuid4(), uuid4()
    record(activity, owner, game, actor)
    assert len(activity.recent(owner, game)) == 1
    activity, stream = collector()
    monkeypatch.setattr("backend.app.services.game.ai_progress_worker.agent_activity", activity)
    _log_worker_error("secret-stage", RuntimeError("synthetic secret token role target"))
    assert "secret" not in stream.getvalue()
    assert "WORKER_FAILED" in stream.getvalue()


def runtime_fixture():
    runtime = object.__new__(PostgresGameRuntime)
    activity, stream = collector()
    runtime._activity = activity
    runtime._mutation_lock = RLock()
    game = {"phase": "DAY_DISCUSSION", "state_version": 2, "status": "IN_PROGRESS"}
    runtime._read = SimpleNamespace(snapshot=lambda *args: {"game": dict(game)})
    return runtime, game, stream


def test_mutation_postcommit_phase_order_and_rollback():
    runtime, game, stream = runtime_fixture()
    owner, game_id = uuid4(), uuid4()

    def commit():
        assert stream.getvalue() == ""
        game.update(phase="ENDED", state_version=3, status="COMPLETED")
        return {"result_state_version": 3}, False

    assert runtime._mutation(owner, game_id, commit) == ({"result_state_version": 3}, False)
    assert [json.loads(line)["stage"] for line in stream.getvalue().splitlines()] == ["COMMAND_APPLIED", "PHASE_CHANGED", "COMPLETED"]
    stream.truncate(0)
    stream.seek(0)

    def rollback():
        raise RuntimeError("synthetic rollback")

    with pytest.raises(RuntimeError):
        runtime._mutation(owner, game_id, rollback)
    assert stream.getvalue() == ""
    runtime._mutation(owner, game_id, lambda: ({"result_state_version": 3}, True))
    assert [json.loads(line)["stage"] for line in stream.getvalue().splitlines()] == ["SKIPPED"]


def test_snapshot_ownership_is_checked_before_activity():
    runtime, game, stream = runtime_fixture()
    owner, game_id, actor = uuid4(), uuid4(), uuid4()
    record(runtime._activity, owner, game_id, actor)
    assert len(runtime.snapshot(owner, game_id)["agent_activity"]) == 1

    def deny(*args):
        raise PermissionError("synthetic wrong owner")

    runtime._read.snapshot = deny
    with pytest.raises(PermissionError):
        runtime.snapshot(uuid4(), game_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["DUPLICATE", "STALE"])
async def test_private_batch_stale_result_never_submits_new_action(status):
    runtime, game, stream = runtime_fixture()
    async def result(*args, **kwargs):
        return AgentRunResult(status=status)
    runtime._run_orchestrated_proposal = result
    runtime._actions = SimpleNamespace()
    turns = [{"player_id": uuid4(), "window_id": uuid4(), "state_version": 2}]
    result, replayed = await runtime.run_agent_night_turn(uuid4(), uuid4(), turns)
    assert result == {"status": "DEFERRED"} and replayed
    assert "APPLIED" not in stream.getvalue()


def test_worker_never_retries_failed_agent_with_fresh_pass():
    owner, game, actor, window = uuid4(), uuid4(), uuid4(), uuid4()
    calls = []
    async def fail(*args):
        raise RuntimeError("synthetic failure after possible commit")
    runtime = SimpleNamespace(
        list_ai_speech_turns=lambda: [{"owner_user_id": owner, "game_id": game, "turn_player_id": actor, "window_id": window, "state_version": 2}],
        run_agent_turn=fail, agent_pass=lambda *args, **kwargs: calls.append(args))
    assert AiProgressWorker(runtime).progress_once() == 0
    assert calls == []


def test_worker_vote_expiry_and_fast_forward_advance_after_saved_result():
    owner, game = uuid4(), uuid4()
    calls = []
    runtime = SimpleNamespace(list_ai_speech_turns=lambda: [],
        list_expired_vote_windows=lambda: [{"owner_user_id": owner, "game_id": game}],
        auto_resolve_expired_vote=lambda *args: calls.append(args) or {"result_state_version": 3},
        fast_forward_enabled=lambda *args: True)
    worker = AiProgressWorker(runtime)
    assert worker.progress_once() == 1 and calls == [(owner, game)]
    assert worker._fast_forward_progressed is True


@pytest.fixture
def isolated_logging(tmp_path, monkeypatch):
    """실제 설정 함수를 사용하되 운영 logger와 로그 파일에는 영향을 주지 않는다."""

    from backend.app.core import logging as configuration

    names = ("backend.game_progress", "uvicorn.access", "httpx", "httpcore", "mcp")
    loggers = {name: logging.Logger(name) for name in names}
    original_get_logger = logging.getLogger

    def get_logger(name=None):
        return loggers[name] if name in loggers else original_get_logger(name)

    monkeypatch.setattr(logging, "getLogger", get_logger)
    monkeypatch.setattr(configuration, "__file__", str(tmp_path / "app" / "core" / "logging.py"))
    try:
        yield configuration, loggers
    finally:
        for logger in loggers.values():
            for handler in logger.handlers:
                handler.close()


def test_logging_configuration_is_idempotent_and_file_has_rotation(isolated_logging):
    """반복 설정이 필터·출력을 중복시키거나 상세 파일 기록을 선별하지 않는다."""

    configuration, loggers = isolated_logging
    from logging.handlers import RotatingFileHandler

    configuration.configure_logging()
    logger = configuration.progress_logger()
    handlers = list(logger.handlers)
    configuration.configure_logging()
    assert configuration.progress_logger().handlers == handlers
    files = [handler for handler in handlers if isinstance(handler, RotatingFileHandler)]
    terminals = [handler for handler in handlers if not isinstance(handler, RotatingFileHandler)]
    assert len(files) == 1 and files[0].maxBytes == 5 * 1024 * 1024 and files[0].backupCount == 3
    assert len(terminals) == 1
    assert sum(isinstance(item, configuration._ImportantProgressFilter) for item in terminals[0].filters) == 1
    assert not any(isinstance(item, configuration._ImportantProgressFilter)
                   for item in logger.filters + files[0].filters)
    assert sum(isinstance(item, configuration._FailedAccessFilter)
               for item in loggers["uvicorn.access"].filters) == 1
    for name in ("httpx", "httpcore", "mcp"):
        assert loggers[name].getEffectiveLevel() == logging.WARNING


def test_access_status_filter_and_dependency_warnings_are_preserved(isolated_logging):
    """접근 INFO는 실패 상태만 표시하며 상태와 무관한 WARNING 이상은 보존한다."""

    configuration, loggers = isolated_logging
    configuration.configure_logging()
    stream = io.StringIO()
    access = loggers["uvicorn.access"]
    access.setLevel(logging.INFO)
    access.addHandler(logging.StreamHandler(stream))
    statuses = (200, 204, 301, 304, 399, 400, 404, 499, 500, 599, 600, "500", None)
    for status in statuses:
        access.info('%s - "%s %s HTTP/%s" %s', "synthetic-client", "GET", "/synthetic", "1.1", status)
    for level in (logging.WARNING, logging.ERROR, logging.CRITICAL):
        access.log(level, "synthetic access %s", logging.getLevelName(level))
    assert stream.getvalue().splitlines() == [
        f'synthetic-client - "GET /synthetic HTTP/1.1" {status}'
        for status in (400, 404, 499, 500, 599)
    ] + ["synthetic access WARNING", "synthetic access ERROR", "synthetic access CRITICAL"]

    for name in ("httpx", "httpcore", "mcp"):
        stream = io.StringIO()
        loggers[name].addHandler(logging.StreamHandler(stream))
        loggers[name].info("synthetic dependency INFO")
        loggers[name].warning("synthetic dependency WARNING")
        loggers[name].error("synthetic dependency ERROR")
        assert stream.getvalue().splitlines() == ["synthetic dependency WARNING", "synthetic dependency ERROR"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["SUCCEEDED", "FALLBACK", "STALE", "DUPLICATE"])
async def test_speech_applied_only_after_tool_or_fallback_success(monkeypatch, status):
    runtime, game, stream = runtime_fixture()
    owner, game_id, actor, window = uuid4(), uuid4(), uuid4(), uuid4()
    runtime._settings = SimpleNamespace(mcp_server_url="http://synthetic.invalid")
    runtime._agent_repository = object()
    runtime._read.snapshot = lambda *args: {"game": dict(game), "action_window": {"window_id": str(window), "turn_player_id": str(actor)}}
    calls = []

    class Context:
        def __init__(self, *args, **kwargs):
            assert kwargs["player_id"] == actor and kwargs["window_id"] == window
        async def close(self):
            pass
        async def submit_action(self, **kwargs):
            assert "APPLIED" not in stream.getvalue()
            calls.append("tool_committed")
            return {"result": {"result_state_version": 3}, "replayed": False}

    class Orchestrator:
        def __init__(self, **kwargs):
            assert kwargs["close_context"] is False
        async def run(self, spec):
            return AgentRunResult(status=status, proposal=NormalizedAgentProposal(type="PASS"))

    def fallback(*args, **kwargs):
        assert "APPLIED" not in stream.getvalue()
        assert kwargs["expected_state_version"] == 2 and kwargs["window_id"] == window
        calls.append("fallback_committed")
        return {"result_state_version": 3}, False

    runtime.agent_pass = fallback
    module = "backend.app.services.game.postgres_runtime"
    monkeypatch.setattr(module + ".FastMcpGameContextClient", Context)
    monkeypatch.setattr(module + ".AgentOrchestrator", Orchestrator)
    monkeypatch.setattr(module + ".get_llm_provider", lambda settings: object())
    await runtime.run_agent_turn(owner, game_id, actor)
    if status in {"STALE", "DUPLICATE"}:
        assert calls == [] and "APPLIED" not in stream.getvalue()
    else:
        assert calls == ["tool_committed" if status == "SUCCEEDED" else "fallback_committed"]
        assert runtime._activity.recent(owner, game_id)[-1]["stage"] == "APPLIED"


@pytest.mark.asyncio
async def test_private_batch_rollback_has_no_applied_activity():
    runtime, game, stream = runtime_fixture()
    actor, target, window = uuid4(), uuid4(), uuid4()
    async def proposal(*args, **kwargs):
        return AgentRunResult(status="SUCCEEDED", proposal=NormalizedAgentProposal(type="NIGHT_ACTION", target_player_id=target))
    def rollback(*args, **kwargs):
        raise RuntimeError("synthetic private target failure")
    runtime._run_orchestrated_proposal = proposal
    runtime._actions = SimpleNamespace(submit_agent_night_actions=rollback)
    turns = [{"player_id": actor, "window_id": window, "state_version": 2}]
    with pytest.raises(RuntimeError):
        await runtime.run_agent_night_turn(uuid4(), uuid4(), turns)
    assert "APPLIED" not in stream.getvalue()
    assert "FAILED" in stream.getvalue()
    assert str(actor) not in stream.getvalue() and str(target) not in stream.getvalue()


@pytest.mark.asyncio
async def test_tool_response_loss_fallback_cannot_apply_to_new_window(monkeypatch):
    runtime, game, stream = runtime_fixture()
    owner, game_id, actor, window = uuid4(), uuid4(), uuid4(), uuid4()
    runtime._settings = SimpleNamespace(mcp_server_url="http://synthetic.invalid")
    runtime._agent_repository = object()
    runtime._read.snapshot = lambda *args: {"game": dict(game), "action_window": {"window_id": str(window), "turn_player_id": str(actor)}}
    seen = []

    class Context:
        def __init__(self, *args, **kwargs):
            pass
        async def close(self):
            pass
        async def submit_action(self, **kwargs):
            game["state_version"] = 3
            raise RuntimeError("synthetic response loss after commit")

    class Orchestrator:
        def __init__(self, **kwargs):
            pass
        async def run(self, spec):
            return AgentRunResult(status="SUCCEEDED", proposal=NormalizedAgentProposal(type="PASS"))

    def fenced_pass(*args, **kwargs):
        seen.append(kwargs)
        assert kwargs["expected_state_version"] != game["state_version"]
        raise RuntimeError("synthetic stale rejection")

    runtime.agent_pass = fenced_pass
    module = "backend.app.services.game.postgres_runtime"
    monkeypatch.setattr(module + ".FastMcpGameContextClient", Context)
    monkeypatch.setattr(module + ".AgentOrchestrator", Orchestrator)
    monkeypatch.setattr(module + ".get_llm_provider", lambda settings: object())
    with pytest.raises(RuntimeError):
        await runtime.run_agent_turn(owner, game_id, actor)
    assert seen == [{"expected_state_version": 2, "window_id": window}]
    stages = [item["stage"] for item in runtime._activity.recent(owner, game_id)]
    assert stages == ["FALLBACK", "FAILED"]


def test_terminal_selection_preserves_file_order_history_and_quiet_file_failure(
    isolated_logging, tmp_path, capsys, monkeypatch,
):
    """터미널의 중요 기록 선별이 상세 파일·UI 이력·파일 실패 격리를 바꾸지 않는다."""

    from logging.handlers import RotatingFileHandler

    configuration, _ = isolated_logging
    logger = configuration.progress_logger()
    terminal = io.StringIO()
    handler = next(item for item in logger.handlers if isinstance(item, RotatingFileHandler))
    next(item for item in logger.handlers if not isinstance(item, RotatingFileHandler)).setStream(terminal)
    activity = AgentActivity(logger=logger)
    owner, game, actor = uuid4(), uuid4(), uuid4()
    events = [
        ("CREATED", None, "ROLE_REVEAL", True, False),
        ("BEGIN_GAME", None, "DAY_DISCUSSION", True, False),
        ("STARTED", None, "DAY_DISCUSSION", False, True),
        ("CONTEXT_READY", None, "DAY_DISCUSSION", False, True),
        ("DECIDING", None, "DAY_DISCUSSION", False, True),
        ("DECIDED", "SPEAK", "DAY_DISCUSSION", False, True),
        ("APPLIED", "SPEAK", "DAY_DISCUSSION", True, True),
        ("COMMAND_APPLIED", None, "DAY_DISCUSSION", False, False),
        ("APPLIED", "PASS", "DAY_DISCUSSION", False, True),
        ("SKIPPED", None, "DAY_DISCUSSION", False, True),
        ("SAVE_AND_EXIT", None, "DAY_DISCUSSION", True, False),
        ("RESUME", None, "DAY_DISCUSSION", True, False),
        ("PHASE_CHANGED", None, "NIGHT_ACTION", True, False),
        ("APPLIED", "NIGHT_ACTION", "NIGHT_ACTION", False, False),
        ("APPLIED", "SPEAK", "DAY_VOTE", False, False),
        ("FALLBACK", "PASS", "FINAL_DISCUSSION", True, True),
        ("FAILED", "SPEAK", "FINAL_DISCUSSION", True, True),
        ("WORKER_FAILED", None, "FINAL_DISCUSSION", True, False),
        ("APPLIED", "SPEAK", "FINAL_DISCUSSION", True, True),
        ("COMPLETED", None, "ENDED", True, False),
    ]
    emitted, selected, history = [], [], []
    for stage, action, phase, visible, remembered in events:
        row = activity.record(owner_user_id=owner, game_id=game, player_id=actor,
                              phase=phase, state_version=2, stage=stage, action=action)
        entry = {**row, "game_id": str(game)}
        emitted.append(entry)
        if visible:
            selected.append(entry)
        if remembered:
            history.append(row)
    handler.flush()
    file_path = tmp_path / "logs" / "game-progress.log"
    file_rows = [json.loads(line) for line in file_path.read_text(encoding="utf-8").splitlines()]
    assert file_rows == emitted
    assert [row["sequence"] for row in file_rows] == list(range(1, len(events) + 1))
    assert [json.loads(line) for line in terminal.getvalue().splitlines()] == selected
    assert activity.recent(owner, game) == history

    for level, message in (
        (logging.WARNING, json.dumps({"stage": "DECIDING"})),
        (logging.ERROR, "synthetic progress ERROR"),
        (logging.CRITICAL, "synthetic progress CRITICAL"),
    ):
        logger.log(level, message)
    handler.flush()
    assert terminal.getvalue().splitlines()[-3:] == file_path.read_text(encoding="utf-8").splitlines()[-3:]
    assert terminal.getvalue().splitlines()[-3:] == [
        json.dumps({"stage": "DECIDING"}), "synthetic progress ERROR", "synthetic progress CRITICAL"]

    monkeypatch.setattr(logging, "raiseExceptions", True)
    broken = configuration._QuietRotatingFileHandler(tmp_path / "missing" / "log", delay=True)
    logger.addHandler(broken)
    try:
        activity.record(stage="WORKER_FAILED")
    finally:
        logger.removeHandler(broken)
        broken.close()
    assert capsys.readouterr().err == ""


def test_fallback_target_uses_ai_actor_scope_and_rejects_changed_window(monkeypatch):
    runtime, game, stream = runtime_fixture()
    owner, game_id, actor, window = uuid4(), uuid4(), uuid4(), uuid4()
    runtime._agent_repository = object()
    received = []
    context = {"state_version": 2, "window_id": str(window), "phase": "NIGHT_ACTION",
               "data": {"valid_targets": [{"player_id": str(actor), "display_name": "합성 의사"}]}}
    def read(reader, **kwargs):
        received.append(kwargs)
        return context
    monkeypatch.setattr("backend.app.services.game.postgres_runtime.read_actor_context", read)
    args = dict(expected_type="NIGHT_ACTION", state_version=2, window_id=window, phase="NIGHT_ACTION")
    assert runtime._fallback_target_proposal(owner, game_id, actor, **args).target_player_id == actor
    assert received[0]["scope"] == "turn" and received[0]["player_id"] == actor
    context["window_id"] = str(uuid4())
    assert runtime._fallback_target_proposal(owner, game_id, actor, **args) is None


@pytest.mark.asyncio
async def test_recovered_speech_rollback_releases_token_and_replays_same_speak(monkeypatch):
    """저장된 SPEAK가 rollback돼도 PASS나 새 Provider 선택으로 바뀌지 않는다."""

    from datetime import UTC, datetime, timedelta
    from backend.app.repositories.agent_repository import AgentReservation
    runtime, game, stream = runtime_fixture()
    owner, game_id, actor, window = uuid4(), uuid4(), uuid4(), uuid4()
    reservation = AgentReservation(uuid4(), game_id, actor, window, "SPEECH", 2, uuid4(), datetime.now(UTC) + timedelta(seconds=15))
    runtime._settings = SimpleNamespace(mcp_server_url="http://synthetic.invalid")
    released = []
    runtime._agent_repository = SimpleNamespace(release_unapplied_job=lambda item: released.append(item))
    runtime._read.snapshot = lambda *args: {"game": dict(game), "action_window": {"window_id": str(window), "turn_player_id": str(actor)}}
    calls = []

    class Context:
        def __init__(self, *args, **kwargs):
            pass
        async def close(self):
            pass
        async def submit_action(self, **kwargs):
            raise AssertionError("복구 결과에는 새 MCP 선택을 요청하지 않습니다.")

    class Orchestrator:
        def __init__(self, **kwargs):
            pass
        async def run(self, spec):
            return AgentRunResult(status="SUCCEEDED", proposal=NormalizedAgentProposal(type="SPEAK", message="저장된 합성 발언"),
                                  reservation=reservation, recovered=True)

    def speak(owner_id, identifier, player, message, **kwargs):
        calls.append((message, kwargs))
        if len(calls) == 1:
            raise RuntimeError("합성 speech rollback")
        return {"result_state_version": 3}, False

    runtime.agent_speak = speak
    runtime.agent_pass = lambda *args, **kwargs: pytest.fail("저장 발언을 PASS로 바꾸면 안 됩니다.")
    module = "backend.app.services.game.postgres_runtime"
    monkeypatch.setattr(module + ".FastMcpGameContextClient", Context)
    monkeypatch.setattr(module + ".AgentOrchestrator", Orchestrator)
    monkeypatch.setattr(module + ".get_llm_provider", lambda settings: object())
    with pytest.raises(RuntimeError):
        await runtime.run_agent_turn(owner, game_id, actor)
    assert released == [reservation] and "APPLIED" not in stream.getvalue()
    await runtime.run_agent_turn(owner, game_id, actor)
    assert calls[0] == calls[1] and released == [reservation]
    assert runtime._activity.recent(owner, game_id)[-1]["stage"] == "APPLIED"


def test_applied_retains_fallback_reason_but_next_attempt_resets_it():
    """적용 성공이 장애 PASS를 정상 추론으로 바꿔 표시하지 않게 한다."""

    activity, _ = collector()
    owner, game, actor = uuid4(), uuid4(), uuid4()
    args = dict(owner_user_id=owner, game_id=game, player_id=actor,
                phase="DAY_DISCUSSION", state_version=3)
    activity.record(**args, stage="FALLBACK", action="PASS", reason_code="PROVIDER_INCOMPLETE")
    applied = activity.record(**args, stage="APPLIED", action="PASS")
    assert applied["decision_source"] == "FALLBACK"
    assert applied["reason_code"] == "PROVIDER_INCOMPLETE"
    activity.record(**args, stage="STARTED", decision_source="MODEL")
    activity.record(**args, stage="DECIDED", action="SPEAK", decision_source="MODEL",
                    decision_basis="ASK_FOR_CLARIFICATION")
    applied = activity.record(**args, stage="APPLIED", action="SPEAK")
    assert applied["decision_basis"] == "ASK_FOR_CLARIFICATION"
    assert applied["decision_source"] == "MODEL" and applied["reason_code"] is None


@pytest.mark.parametrize("value", ["synthetic secret", [], {"role": "MAFIA"}])
def test_activity_rejects_untrusted_diagnostic_strings(value):
    """Provider 자유 문자열·비정상 형식이 공개 기록이나 로그에 섞이지 않는다."""

    activity, stream = collector()
    row = record(activity, uuid4(), uuid4(), uuid4(), decision_source=value,
                 reason_code=value, decision_basis=value)
    assert row["decision_source"] is row["reason_code"] is row["decision_basis"] is None
    assert "synthetic secret" not in stream.getvalue() and "MAFIA" not in stream.getvalue()


@pytest.mark.asyncio
async def test_model_speech_reaches_tool_and_activity_with_public_basis(monkeypatch):
    """실제 orchestrator부터 Tool 제출까지 연결해 발언이 PASS로 바뀌지 않음을 검증한다."""

    from datetime import UTC, datetime, timedelta
    from backend.app.repositories.agent_repository import AgentReservation, CapabilityGrant
    from backend.app.llm_provider.base import LLMResponse
    runtime, game, _ = runtime_fixture()
    owner, game_id, actor, window = uuid4(), uuid4(), uuid4(), uuid4()
    runtime._settings = SimpleNamespace(mcp_server_url="http://synthetic.invalid")
    reservation = AgentReservation(uuid4(), game_id, actor, window, "SPEECH", 2, uuid4(), datetime.now(UTC) + timedelta(seconds=15))
    runtime._agent_repository = SimpleNamespace(
        reserve_job=lambda **kw: reservation,
        issue_capability=lambda *a, **kw: CapabilityGrant("synthetic-capability", "a" * 64, reservation.lease_expires_at),
        complete_job=lambda *a, **kw: True, revoke_capability=lambda *a, **kw: None,
    )
    runtime._read.snapshot = lambda *a: {"game": dict(game), "action_window": {"window_id": str(window), "turn_player_id": str(actor)}}
    submitted = []
    class Context:
        def __init__(self, *args, **kwargs):
            pass
        async def close(self):
            pass
        async def get_context(self, **kwargs):
            return {"data": {}}
        async def submit_action(self, **kwargs):
            submitted.append(kwargs["action"])
            return {"result": {"result_state_version": 3}, "replayed": False}
    class Provider:
        async def generate(self, request):
            return LLMResponse(provider="fake", model="fake", output={
                "type": "SPEAK", "message": "사건 당시 어디에 계셨나요?", "public_rationale": "ASK_FOR_CLARIFICATION"})
    def unexpected_pass(*args, **kwargs):
        pytest.fail("정상 발언에 PASS fallback이 실행되었습니다.")
    runtime.agent_pass = unexpected_pass
    module = "backend.app.services.game.postgres_runtime"
    monkeypatch.setattr(module + ".FastMcpGameContextClient", Context)
    monkeypatch.setattr(module + ".get_llm_provider", lambda settings: Provider())
    await runtime.run_agent_turn(owner, game_id, actor)
    assert submitted[0]["type"] == "SPEAK"
    latest = runtime._activity.recent(owner, game_id)[-1]
    assert latest["stage"] == "APPLIED" and latest["action"] == "SPEAK"
    assert latest["decision_basis"] == "ASK_FOR_CLARIFICATION"
    assert latest["decision_source"] == "MODEL"
