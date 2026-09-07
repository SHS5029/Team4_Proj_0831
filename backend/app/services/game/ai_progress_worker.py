"""게임별 프로세스 없이 Backend가 AI 차례를 회복·진행하는 중앙 worker."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any
from uuid import UUID


logger = logging.getLogger(__name__)


class AiProgressWorker:
    """열린 AI speech window를 주기적으로 찾아 한 번씩 처리한다."""

    def __init__(self, runtime: Any, *, interval: float = 1.0) -> None:
        """실행 runtime만 주입하고 DB 연결·저장소를 직접 소유하지 않는다."""

        self._runtime = runtime
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def start(self) -> None:
        """FastAPI event loop에서 단일 worker task를 시작한다."""

        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="ai-progress-worker")

    async def stop(self) -> None:
        """서버 종료 시 다음 polling을 기다리지 않고 worker를 종료한다."""

        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        """동기 psycopg 작업은 thread로 보내 API event loop를 점유하지 않는다."""

        while not self._stopping:
            try:
                await asyncio.to_thread(self.progress_once)
            except Exception as error:
                # 다음 주기에 다시 조회한다. 개별 게임 실패가 worker 전체를 끝내면
                # 재시작 전까지 다른 게임의 AI 진행도 멈추므로 오류를 격리한다.
                _log_worker_error("worker_cycle", error)
            await asyncio.sleep(self._interval)

    def progress_once(self) -> int:
        """현재 열린 AI speech 차례를 처리한 게임 수를 반환한다."""

        progressed = 0
        if hasattr(self._runtime, "list_expired_night_windows") and hasattr(self._runtime, "auto_resolve_expired_night"):
            try:
                expired_windows = self._runtime.list_expired_night_windows()
            except Exception as error:
                _log_worker_error("expired_night_lookup", error)
                expired_windows = []
            for window in expired_windows:
                try:
                    self._runtime.auto_resolve_expired_night(
                        UUID(str(window["owner_user_id"])),
                        UUID(str(window["game_id"])),
                    )
                    progressed += 1
                except Exception as error:
                    _log_worker_error("expired_night_processing", error)
                    continue

        try:
            turns = self._runtime.list_ai_speech_turns()
        except Exception as error:
            _log_worker_error("speech_turn_lookup", error)
            return 0
        logger.debug("AI worker speech turn lookup completed: count=%d", len(turns))
        for turn in turns:
            try:
                owner_id = UUID(str(turn["owner_user_id"]))
                game_id = UUID(str(turn["game_id"]))
                player_id = UUID(str(turn["turn_player_id"]))
                if hasattr(self._runtime, "run_agent_turn"):
                    try:
                        # progress_once는 asyncio.to_thread에서 실행되므로 이 thread 안에서
                        # Agent의 비동기 MCP·LLM 호출을 독립 event loop로 완료한다.
                        asyncio.run(self._runtime.run_agent_turn(owner_id, game_id, player_id))
                    except Exception as error:
                        # 외부 의존성 장애가 게임 진행을 막지 않도록 현재 window의
                        # 기존 규칙 fallback(PASS)을 같은 fencing 값으로 적용한다.
                        _log_worker_error("speech_agent_execution", error)
                        self._runtime.agent_pass(
                            owner_id,
                            game_id,
                            player_id,
                            expected_state_version=int(turn["state_version"]),
                            window_id=UUID(str(turn["window_id"])),
                        )
                else:
                    self._runtime.agent_pass(
                        owner_id,
                        game_id,
                        player_id,
                        expected_state_version=int(turn["state_version"]),
                        window_id=UUID(str(turn["window_id"])),
                    )
            except Exception as error:
                _log_worker_error("speech_turn_processing", error)
                continue
            progressed += 1
        if hasattr(self._runtime, "list_ai_night_turns") and hasattr(self._runtime, "run_agent_night_turn"):
            try:
                night_turns = self._runtime.list_ai_night_turns()
            except Exception as error:
                _log_worker_error("night_turn_lookup", error)
                night_turns = []
            grouped: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
            for turn in night_turns:
                key = (UUID(str(turn["game_id"])), UUID(str(turn["window_id"])))
                grouped.setdefault(key, []).append(turn)
            for (game_id, _window_id), game_turns in grouped.items():
                try:
                    owner_id = UUID(str(game_turns[0]["owner_user_id"]))
                    asyncio.run(self._runtime.run_agent_night_turn(owner_id, game_id, game_turns))
                except Exception as error:
                    _log_worker_error("night_turn_processing", error)
                    continue
                progressed += 1
        if hasattr(self._runtime, "list_ai_vote_turns") and hasattr(self._runtime, "run_agent_vote_turn"):
            try:
                vote_turns = self._runtime.list_ai_vote_turns()
            except Exception as error:
                _log_worker_error("vote_turn_lookup", error)
                vote_turns = []
            grouped: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
            for turn in vote_turns:
                key = (UUID(str(turn["game_id"])), UUID(str(turn["window_id"])))
                grouped.setdefault(key, []).append(turn)
            for (game_id, _window_id), game_turns in grouped.items():
                try:
                    owner_id = UUID(str(game_turns[0]["owner_user_id"]))
                    asyncio.run(self._runtime.run_agent_vote_turn(owner_id, game_id, game_turns))
                except Exception as error:
                    _log_worker_error("vote_turn_processing", error)
                    continue
                progressed += 1
        return progressed


def _log_worker_error(stage: str, error: Exception) -> None:
    """worker 장애의 단계와 예외 종류만 기록하고 민감한 원문은 남기지 않는다."""

    frames = traceback.extract_tb(error.__traceback__)
    location = "unknown"
    if frames:
        frame = frames[-1]
        filename = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
        location = f"{filename}:{frame.lineno}:{frame.name}"
    logger.warning(
        "AI worker operation failed: stage=%s error_class=%s location=%s detail=%s",
        stage,
        type(error).__name__,
        location,
        _safe_error_detail(error),
    )


def _safe_error_detail(error: Exception) -> str:
    """원인 식별에 필요한 짧은 예외 문구만 남긴다.

    외부 응답이나 게임 context가 예외 문자열에 섞이는 구현을 고려해 길이를
    제한하고 줄바꿈을 제거한다. 토큰·payload 원문을 로그로 확장하지 않는다.
    """

    detail = " ".join(str(error).split())
    return detail[:240] if detail else "<empty>"
