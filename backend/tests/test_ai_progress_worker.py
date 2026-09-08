"""중앙 AI 진행 worker의 게임 간 격리와 순차 처리 테스트."""

from uuid import uuid4

import pytest

from backend.app.services.game.ai_progress_worker import AiProgressWorker


class _Runtime:
    def __init__(self, failing_game_id, turns):
        self.calls = []
        self.failing_game_id = failing_game_id
        self.turns = turns

    def list_ai_speech_turns(self):
        return self.turns

    def agent_pass(self, owner_id, game_id, player_id, *, expected_state_version, window_id):
        self.calls.append((owner_id, game_id, player_id, expected_state_version, window_id))
        if game_id == self.failing_game_id:
            raise RuntimeError("synthetic failure")


def test_worker_processes_independent_games_when_one_turn_fails(monkeypatch):
    """한 게임의 AI 오류가 다른 게임의 진행을 중단시키지 않는지 확인한다."""

    failing_game_id = uuid4()
    succeeding_game_id = uuid4()
    turns = [
        {
            "owner_user_id": uuid4(),
            "game_id": failing_game_id,
            "turn_player_id": uuid4(),
            "state_version": 4,
            "window_id": uuid4(),
        },
        {
            "owner_user_id": uuid4(),
            "game_id": succeeding_game_id,
            "turn_player_id": uuid4(),
            "state_version": 9,
            "window_id": uuid4(),
        },
    ]
    runtime = _Runtime(failing_game_id, turns)
    worker = AiProgressWorker(runtime)

    assert worker.progress_once() == 1
    assert runtime.calls[0][1] == failing_game_id
    assert runtime.calls[1][1] == succeeding_game_id


def test_worker_logs_only_allowlisted_error_context(caplog):
    """실패 원인은 구분하되 동적 stage·예외 이름·외부 메시지는 로그에 남기지 않는다."""

    import logging
    from backend.app.core.errors import ApiError
    from backend.app.services.game.ai_progress_worker import _log_worker_error
    from backend.app.game_engine.errors import RuleViolation
    from backend.app.services.game.service_errors import rule_error

    with caplog.at_level(logging.WARNING):
        _log_worker_error("speech_turn_processing", ApiError(
            status_code=409, code="DUPLICATE_ACTION", message="synthetic-private-message",
        ))
        _log_worker_error("speech_turn_processing", rule_error(RuleViolation("DUPLICATE_ACTION")))
        _log_worker_error("synthetic-private-stage", type("SyntheticPrivateError", (Exception,), {})(
            "synthetic-private-message"
        ))
        _log_worker_error("speech_turn_processing", ApiError(
            status_code=500, code="synthetic-private-code", message="synthetic-private-message",
        ))
    assert "reason_code=DUPLICATE_ACTION" in caplog.text
    assert "reason_code=ACTION_ALREADY_SUBMITTED" in caplog.text
    assert "stage=speech_turn_processing" in caplog.text
    assert "reason_code=UNEXPECTED_ERROR" in caplog.text
    assert "stage=worker_cycle" in caplog.text
    assert "synthetic-private" not in caplog.text
    assert "SyntheticPrivateError" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_slow_analysis_preparation_does_not_block_other_vote_deadlines():
    """한 게임의 분석 준비 DB가 대기해도 다른 게임의 투표 마감 조회는 계속한다."""

    import asyncio
    from threading import Event
    from types import SimpleNamespace

    preparing, release, vote_checked = Event(), Event(), Event()

    def prepare():
        preparing.set()
        release.wait(timeout=3)

    def expired_votes():
        if preparing.is_set():
            vote_checked.set()
        return []

    runtime = SimpleNamespace(expire_discussions=prepare,
                              list_expired_vote_windows=expired_votes,
                              list_ai_vote_turns=lambda: [])
    worker = AiProgressWorker(runtime, interval=0.01)
    worker.progress_once = lambda **kwargs: 0
    worker.start()
    try:
        assert await asyncio.to_thread(preparing.wait, 1)
        assert await asyncio.to_thread(vote_checked.wait, 1)
        assert not release.is_set()
    finally:
        release.set()
        await worker.stop()


@pytest.mark.asyncio
async def test_stale_game_cleanup_runs_independently_and_stops_with_worker():
    """정리 sweep은 즉시 시작되고 느린 AI polling을 기다리지 않으며 종료 시 취소된다."""

    import asyncio
    from types import SimpleNamespace

    cleaned = asyncio.Event()

    def cleanup():
        cleaned.set()
        return 1

    runtime = SimpleNamespace(
        cleanup_stale_games=cleanup,
        list_expired_vote_windows=lambda: [],
        list_ai_vote_turns=lambda: [],
        list_ai_speech_turns=lambda: [],
    )
    worker = AiProgressWorker(runtime, interval=60, cleanup_interval=60)
    worker.start()
    cleanup_task = worker._cleanup_task
    try:
        await asyncio.wait_for(cleaned.wait(), timeout=1)
        assert cleanup_task is not None and not cleanup_task.done()
    finally:
        await worker.stop()
    assert cleanup_task.cancelled()
    assert worker._cleanup_task is None
