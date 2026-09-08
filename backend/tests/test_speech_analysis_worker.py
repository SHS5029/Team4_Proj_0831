"""분석 단계 격리·lease 반환·동시성·lifespan을 fake만으로 검증한다."""

import asyncio
import importlib
import threading
from collections import deque
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from backend.app.core.config import Settings
from backend.app.llm_provider.speech_analysis_provider import SpeechAnalysisError
from backend.app.services.game.speech_analysis_worker import SpeechAnalysisWorker


def settings(**changes):
    return Settings(database_url="postgresql://test@localhost/synthetic", **changes)


def job(stage="EMBEDDING"):
    return {
        "job_id": uuid4(),
        "lease_token": uuid4(),
        "stage": stage,
        "message": "공개 발언",
        "players": [],
    }


class Repository:
    """stage 전이와 토큰 소유 검사는 동기 fake에 두고 모델 호출과 분리한다."""

    def __init__(self, jobs=()):
        self.jobs = deque(jobs)
        self.calls = []
        self.saved = []
        self.failures = []
        self.accept_lease = True
        self.requeue_claims = False
        self.retry_claims = False
        self.threads = set()

    def discover(self, **kwargs):
        self.threads.add(threading.get_ident())
        self.calls.append(("discover", kwargs))
        return len(self.jobs)

    def claim_next(self, **kwargs):
        self.threads.add(threading.get_ident())
        self.calls.append(("claim", kwargs))
        return self.jobs.popleft() if self.jobs else None

    def complete_embedding(self, **kwargs):
        self.threads.add(threading.get_ident())
        self.calls.append(("embedding", kwargs))
        if self.accept_lease:
            self.saved.append(("embedding", kwargs))
            if self.requeue_claims:
                self.jobs.append(job("CLAIMS"))
        return self.accept_lease

    def complete_claims(self, **kwargs):
        self.threads.add(threading.get_ident())
        self.calls.append(("claims", kwargs))
        if self.accept_lease:
            self.saved.append(("claims", kwargs))
        return self.accept_lease

    def fail(self, **kwargs):
        self.threads.add(threading.get_ident())
        self.failures.append(kwargs)
        if self.retry_claims and kwargs["stage"] == "CLAIMS":
            self.jobs.append(job("CLAIMS"))
        return self.accept_lease


def provider():
    return SimpleNamespace(
        embed=AsyncMock(return_value=[1.0] * 1536),
        extract_claims=AsyncMock(return_value=[]),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_partial_success_never_reembeds_and_db_runs_outside_event_loop():
    repo, fake = Repository([job()]), provider()
    repo.requeue_claims = repo.retry_claims = True
    fake.extract_claims.side_effect = [SpeechAnalysisError("PROVIDER_ERROR"), []]
    worker = SpeechAnalysisWorker(repo, fake, settings(speech_analysis_concurrency=1))
    await worker.run_once()
    assert fake.embed.await_count == 1
    assert fake.extract_claims.await_count == 2
    assert [kind for kind, _ in repo.saved] == ["embedding", "claims"]
    assert len(repo.failures) == 1
    assert threading.get_ident() not in repo.threads
    assert all(call[1]["lease_seconds"] > 30 for call in repo.calls if call[0] == "claim")


@pytest.mark.asyncio
async def test_failed_embedding_does_not_block_independent_claim_job():
    repo, fake = Repository([job(), job("CLAIMS")]), provider()
    fake.embed.side_effect = SpeechAnalysisError("PROVIDER_ERROR")
    await SpeechAnalysisWorker(repo, fake, settings()).run_once()
    assert [kind for kind, _ in repo.saved] == ["claims"]
    assert repo.failures[0]["stage"] == "EMBEDDING"


@pytest.mark.asyncio
async def test_stale_lease_result_is_not_retried_or_written():
    work = job()
    repo, fake = Repository([work]), provider()
    repo.accept_lease = False
    await SpeechAnalysisWorker(repo, fake, settings()).run_once()
    assert not repo.saved and not repo.failures
    completion = next(kwargs for name, kwargs in repo.calls if name == "embedding")
    assert completion["job_id"] == work["job_id"]
    assert completion["lease_token"] == work["lease_token"]
    assert fake.embed.await_count == 1


@pytest.mark.asyncio
async def test_concurrency_limit_is_applied_before_claiming():
    repo, fake = Repository([job() for _ in range(8)]), provider()
    active = peak = 0

    async def embed(message):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        assert len([call for call in repo.calls if call[0] == "claim"]) - len(repo.saved) <= 2
        active -= 1
        return [1.0] * 1536

    fake.embed.side_effect = embed
    worker = SpeechAnalysisWorker(
        repo, fake, settings(speech_analysis_concurrency=2, speech_analysis_batch_size=5)
    )
    assert await worker.run_once() == 5
    assert peak == 2 and len(repo.saved) == 5
    assert len(repo.jobs) == 3


@pytest.mark.asyncio
async def test_timeout_fails_only_the_active_stage():
    repo, fake = Repository([job()]), provider()

    async def blocked(message):
        await asyncio.Event().wait()

    fake.embed.side_effect = blocked
    await SpeechAnalysisWorker(repo, fake, settings(speech_analysis_timeout_seconds=0.1)).run_once()
    assert repo.failures[0]["failure_code"] == "TIMEOUT"
    assert not repo.saved


@pytest.mark.asyncio
async def test_stop_wakes_poll_and_is_idempotent_start():
    repo, fake = Repository(), provider()
    worker = SpeechAnalysisWorker(repo, fake, settings(speech_analysis_poll_seconds=60))
    worker.start()
    first = worker._task
    worker.start()
    assert worker._task is first
    await asyncio.sleep(0.01)
    await asyncio.wait_for(worker.stop(), 0.5)
    assert not worker._active and not worker._db_tasks
    fake.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_drains_inflight_model_and_stops_new_claims():
    repo, fake = Repository([job(), job()]), provider()
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(message):
        entered.set()
        await release.wait()
        return [1.0] * 1536

    fake.embed.side_effect = blocked
    worker = SpeechAnalysisWorker(repo, fake, settings(speech_analysis_concurrency=1))
    worker.start()
    await entered.wait()
    stopping = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(stopping, 1)
    assert fake.embed.await_count == 1
    assert len(repo.saved) == 1 and len(repo.jobs) == 1
    assert not worker._active and not worker._db_tasks


@pytest.mark.asyncio
async def test_cancellation_does_not_mark_interrupted_work_successful():
    repo, fake = Repository([job()]), provider()
    entered = asyncio.Event()

    async def blocked(message):
        entered.set()
        await asyncio.Event().wait()

    fake.embed.side_effect = blocked
    worker = SpeechAnalysisWorker(repo, fake, settings())
    task = asyncio.create_task(worker.run_once())
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not repo.saved and not repo.failures
    assert not worker._active


@pytest.mark.asyncio
async def test_ambiguous_database_save_failure_does_not_reset_success(caplog):
    repo, fake = Repository([job()]), provider()
    repo.complete_embedding = Mock(side_effect=RuntimeError("SYNTHETIC_SECRET"))
    await SpeechAnalysisWorker(repo, fake, settings()).run_once()
    assert not repo.failures
    assert "SPEECH_ANALYSIS_SAVE_FAILED" in caplog.text
    assert "SYNTHETIC_SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_restart_rediscovers_jobs_with_same_version():
    repo, fake = Repository([job()]), provider()
    original = SpeechAnalysisWorker(repo, fake, settings())
    await original.run_once()
    restarted = SpeechAnalysisWorker(repo, fake, settings())
    await restarted.run_once()
    assert fake.embed.await_count == 1
    versions = [args["analysis_version"] for name, args in repo.calls if name == "discover"]
    assert len(versions) == 2 and versions[0] == versions[1]


@pytest.mark.asyncio
async def test_lifespan_is_per_app_and_background_flag_disables_both(monkeypatch):
    base = settings()
    monkeypatch.setattr("backend.app.core.config.get_settings", lambda: base)
    main = importlib.import_module("backend.app.main")
    runtimes = []

    def build(settings):
        runtime = SimpleNamespace(
            start_background_worker=Mock(), stop_background_worker=AsyncMock()
        )
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(main, "build_postgres_runtime", build)
    workers = []

    def build_worker(*args):
        worker = SimpleNamespace(start=Mock(), stop=AsyncMock())
        workers.append(worker)
        return worker

    monkeypatch.setattr(
        "backend.app.services.game.speech_analysis_worker.SpeechAnalysisWorker", build_worker
    )
    monkeypatch.setattr(
        "backend.app.llm_provider.speech_analysis_provider.SpeechAnalysisProvider",
        lambda *args: provider(),
    )
    enabled = replace(base, speech_analysis_enabled=True, openai_api_key="synthetic-placeholder")
    app_a = main.create_app(settings=enabled)
    app_b = main.create_app(settings=enabled)
    disabled = main.create_app(settings=enabled, enable_background_worker=False)
    default = main.create_app(settings=base)
    async with app_a.router.lifespan_context(app_a), app_b.router.lifespan_context(app_b):
        assert app_a.state.speech_analysis_worker is not app_b.state.speech_analysis_worker
        assert len(workers) == 2
        async with (
            disabled.router.lifespan_context(disabled),
            default.router.lifespan_context(default),
        ):
            assert disabled.state.speech_analysis_worker is None
            assert default.state.speech_analysis_worker is None
            assert len(workers) == 2
    for worker in workers:
        worker.start.assert_called_once()
        worker.stop.assert_awaited_once()
    runtimes[2].start_background_worker.assert_not_called()
    runtimes[2].stop_background_worker.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_db_call_is_drained_without_unhandled_exception():
    worker = SpeechAnalysisWorker(Repository(), provider(), settings())
    entered, release = threading.Event(), threading.Event()
    unexpected = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda *args: unexpected.append(args))

    def db_call():
        entered.set()
        release.wait(timeout=2)
        raise RuntimeError("SYNTHETIC_SECRET_DATABASE_ERROR")

    try:
        task = asyncio.create_task(worker._db(db_call))
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        release.set()
        await worker.stop()
        assert not worker._db_tasks
        assert not unexpected
    finally:
        release.set()
        loop.set_exception_handler(previous)


@pytest.mark.asyncio
async def test_shutdown_timeout_cancels_model_and_leaves_lease_for_recovery():
    repo, fake = Repository([job()]), provider()
    entered = asyncio.Event()

    async def delayed_process(work):
        entered.set()
        await asyncio.Event().wait()

    worker = SpeechAnalysisWorker(repo, fake, settings(speech_analysis_timeout_seconds=0.1))
    worker._process = delayed_process
    worker.start()
    await entered.wait()
    await asyncio.wait_for(worker.stop(), 3)
    assert not repo.saved and not repo.failures
    assert not worker._active
    fake.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'deadline': 1}, {'day': 1}, {'phase': 'NIGHT'},
    {'phase': 'DAY_VOTE', 'window_kind': 'VOTE'}, {'game_status': 'SAVED'},
    {'game_status': 'COMPLETED'},
])
async def test_repository_boundary_prevents_model_calls_for_old_pending(monkeypatch, changes):
    from backend.tests.test_speech_analysis_repository import LeaseTransactions
    from backend.app.repositories.speech_analysis_repository import PostgresSpeechAnalysisRepository

    tx, fake = LeaseTransactions(), provider()
    tx.version = settings().effective_speech_analysis_version
    for name, value in changes.items():
        setattr(tx, name, value)
    repo = PostgresSpeechAnalysisRepository(tx)
    monkeypatch.setattr(repo, 'discover', Mock(return_value=1))
    worker = SpeechAnalysisWorker(repo, fake, settings())
    assert await worker.run_once() == 0
    fake.embed.assert_not_awaited()
    fake.extract_claims.assert_not_awaited()
    repo.discover.assert_called_once()


@pytest.mark.asyncio
async def test_deadline_arrival_processes_both_stages_once(monkeypatch):
    from backend.tests.test_speech_analysis_repository import LeaseTransactions
    from backend.app.repositories.speech_analysis_repository import PostgresSpeechAnalysisRepository

    tx, fake = LeaseTransactions(), provider()
    tx.version = settings().effective_speech_analysis_version
    tx.deadline = 1
    fake.embed.return_value = [1.0, 0.0]
    repo = PostgresSpeechAnalysisRepository(tx)
    monkeypatch.setattr(repo, 'discover', Mock(return_value=1))
    worker = SpeechAnalysisWorker(repo, fake, settings(speech_analysis_concurrency=1))
    assert await worker.run_once() == 0
    tx.now = 1
    assert await worker.run_once() == 2
    assert tx.status == {'EMBEDDING': 'READY', 'CLAIMS': 'READY'}
    assert await worker.run_once() == 0
    fake.embed.assert_awaited_once()
    fake.extract_claims.assert_awaited_once()
