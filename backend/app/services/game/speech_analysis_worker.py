"""게임 진행 worker와 자원을 분리한 공개 발언 분석 polling 실행기다."""

from __future__ import annotations

import asyncio
import logging
import math
from functools import partial

from backend.app.llm_provider.speech_analysis_provider import SpeechAnalysisError

logger = logging.getLogger(__name__)


class SpeechAnalysisWorker:
    """선점된 단계만 호출하고 모든 동기 저장 작업을 thread에서 짧게 끝낸다."""

    def __init__(self, repository, provider, settings) -> None:
        self.repository = repository
        self.provider = provider
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._active: set[asyncio.Task] = set()
        self._db_tasks: set[asyncio.Task] = set()

    def start(self) -> None:
        """같은 앱의 중복 시작은 무시하고 독립 event loop 작업 하나만 생성한다."""

        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="speech-analysis-worker")

    async def stop(self) -> None:
        """새 선점을 막고 모델 timeout까지 유예한 뒤 연결과 thread 결과를 정리한다."""

        self._stopping.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._task), self.settings.speech_analysis_timeout_seconds + 2
                )
            except TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        # to_thread 취소는 실제 DB thread를 멈추지 못하므로 이미 시작한 transaction의
        # 종료를 확인한다. 결과 저장은 repository의 lease fencing이 최종 판정한다.
        if self._db_tasks:
            await asyncio.gather(*self._db_tasks, return_exceptions=True)
        await self.provider.close()

    async def _db(self, method, **kwargs):
        """호출 취소 시에도 실행 중 transaction의 추적을 잃지 않도록 shield한다."""

        task = asyncio.create_task(asyncio.to_thread(partial(method, **kwargs)))
        self._db_tasks.add(task)
        task.add_done_callback(self._db_done)
        return await asyncio.shield(task)

    def _db_done(self, task: asyncio.Task) -> None:
        """호출자 취소 후 thread 예외도 수거하여 비밀값 포함 traceback을 방지한다."""

        self._db_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _run(self) -> None:
        """탐색 실패를 다음 주기로 격리하며 원문·SDK 예외를 로그에 넣지 않는다."""

        try:
            while not self._stopping.is_set():
                try:
                    await self.run_once()
                except Exception:
                    logger.warning("SPEECH_ANALYSIS_CYCLE_FAILED")
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), self.settings.speech_analysis_poll_seconds
                    )
                except TimeoutError:
                    pass
        finally:
            for task in self._active:
                task.cancel()
            await asyncio.gather(*self._active, return_exceptions=True)
            self._active.clear()

    async def run_once(self) -> int:
        """원문 등록 후 저장소가 허용한 투표 준비 경계의 단계만 실행한다.

        discover 자체는 모델을 호출하지 않는다. 첫날·토론 중·저장·종료 상태와
        오래된 PENDING의 차단은 모든 worker가 공유하는 claim_next SQL에 맡긴다.
        선점 전 빈 슬롯을 확보하여 대기열에서 lease가 만료되지 않게 한다.
        """

        if self._stopping.is_set():
            return 0
        await self._db(
            self.repository.discover,
            analysis_version=self.settings.effective_speech_analysis_version,
            embedding_model=self.settings.speech_analysis_embedding_model,
            dimensions=self.settings.speech_analysis_dimensions,
            claims_model=self.settings.speech_analysis_claims_model,
            limit=self.settings.speech_analysis_batch_size,
        )
        claimed = 0
        try:
            while (
                claimed < self.settings.speech_analysis_batch_size and not self._stopping.is_set()
            ):
                if len(self._active) >= self.settings.speech_analysis_concurrency:
                    done, _ = await asyncio.wait(self._active, return_when=asyncio.FIRST_COMPLETED)
                    await asyncio.gather(*done, return_exceptions=True)
                    self._active.difference_update(done)
                if self._stopping.is_set():
                    break
                job = await self._db(
                    self.repository.claim_next,
                    analysis_version=self.settings.effective_speech_analysis_version,
                    lease_seconds=math.ceil(self.settings.speech_analysis_timeout_seconds) + 30,
                    max_attempts=self.settings.speech_analysis_max_attempts,
                )
                if job is None or self._stopping.is_set():
                    break
                self._active.add(asyncio.create_task(self._process(job)))
                claimed += 1
            await asyncio.gather(*self._active)
        finally:
            for task in self._active:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._active, return_exceptions=True)
            self._active.clear()
        return claimed

    async def _process(self, job: dict) -> None:
        """단계 성공은 별개로 저장하고 stale lease 결과는 재저장하거나 재시도하지 않는다."""

        try:
            async with asyncio.timeout(self.settings.speech_analysis_timeout_seconds):
                if job["stage"] == "EMBEDDING":
                    result = await self.provider.embed(job["message"])
                elif job["stage"] == "CLAIMS":
                    result = await self.provider.extract_claims(job["message"], job["players"])
                else:
                    raise SpeechAnalysisError("INVALID_INPUT")
        except TimeoutError:
            await self._fail(job, "TIMEOUT")
            return
        except SpeechAnalysisError as error:
            await self._fail(job, error.code)
            return
        except Exception:
            await self._fail(job, "PROVIDER_ERROR")
            return
        try:
            method = (
                self.repository.complete_embedding
                if job["stage"] == "EMBEDDING"
                else self.repository.complete_claims
            )
            value_key = "embedding" if job["stage"] == "EMBEDDING" else "claims"
            await self._db(
                method, job_id=job["job_id"], lease_token=job["lease_token"], **{value_key: result}
            )
        except Exception:
            # 저장 성공 여부가 불명확한 연결 오류는 lease 만료 뒤 DB 상태로 판정한다.
            # 여기서 fail을 덮어쓰면 이미 성공한 임베딩을 다시 과금할 수 있다.
            logger.warning("SPEECH_ANALYSIS_SAVE_FAILED")

    async def _fail(self, job: dict, code: str) -> None:
        """repository가 단계별 시도 수 상한과 stale token을 최종 검증한다."""

        try:
            await self._db(
                self.repository.fail,
                job_id=job["job_id"],
                lease_token=job["lease_token"],
                stage=job["stage"],
                failure_code=code,
                retry_seconds=max(1, math.ceil(self.settings.speech_analysis_poll_seconds)),
            )
        except Exception:
            logger.warning("SPEECH_ANALYSIS_FAILURE_SAVE_FAILED")
