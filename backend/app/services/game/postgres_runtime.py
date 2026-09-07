"""PostgreSQL 기반 게임 업무 Service 조합부."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.llm_provider.factory import get_llm_provider
from backend.app.llm_provider.schemas import NormalizedAgentProposal
from backend.app.agent.orchestrator import AgentJobSpec, AgentOrchestrator, AgentRunResult
from backend.app.mcp.client import FastMcpGameContextClient
from backend.app.repositories.action_repository import PostgresActionRepository
from backend.app.repositories.feedback_repository import PostgresFeedbackRepository
from backend.app.repositories.game_repository import GameStateKeyring, PostgresGameRepository
from backend.app.repositories.player_repository import PostgresPlayerRepository
from backend.app.repositories.user_repository import PostgresUserRepository
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.command_service import (
    PostgresActionCommandService,
    PostgresAgentDiscussionService,
    PostgresBeginGameService,
    PostgresDiscussionCommandService,
)
from backend.app.services.game.ai_progress_worker import AiProgressWorker
from backend.app.services.game.creation_service import PostgresGameCreationService
from backend.app.services.game.feedback_service import PostgresFeedbackService
from backend.app.repositories.agent_repository import PostgresAgentRepository
from backend.app.services.game.actor_context import ActorContext
from backend.app.services.game.game_read_service import PostgresGameReadService
from backend.app.services.game.lifecycle_service import (
    PostgresGameResumeService,
    PostgresGameSaveService,
)


class PostgresGameRuntime:
    """테이블 Repository를 게임 업무 Service로 조합하는 실행 계층."""

    def __init__(self, settings: Settings) -> None:
        """설정된 기존 PostgreSQL을 모든 업무 Service가 공유하게 한다."""

        database_url = settings.effective_database_url
        transactions = TransactionManager(database_url)
        self._transactions = transactions
        self._settings = settings
        self._agent_repository = PostgresAgentRepository(transactions)
        self._games = PostgresGameRepository()
        self._actions_repository = PostgresActionRepository()
        self._players = PostgresPlayerRepository()
        keyring = (
            GameStateKeyring.from_settings(settings)
            if settings.game_state_keyring_file and settings.game_state_active_key_id
            else GameStateKeyring.legacy_plaintext()
        )
        users = PostgresUserRepository(database_url)
        common = {"transactions": transactions, "keyring": keyring}
        self._create = PostgresGameCreationService(**common, users=users)
        self._feedback = PostgresFeedbackService(
            transactions=transactions,
            users=users,
            games=self._games,
            feedback=PostgresFeedbackRepository(),
        )
        self._read = PostgresGameReadService(**common)
        self._begin = PostgresBeginGameService(**common)
        self._save = PostgresGameSaveService(**common)
        self._resume = PostgresGameResumeService(**common)
        self._discussion = PostgresDiscussionCommandService(**common)
        self._agent_discussion = PostgresAgentDiscussionService(**common)
        self._actions = PostgresActionCommandService(**common)
        self._ai_worker = AiProgressWorker(self)

    def list_ai_speech_turns(self) -> list[dict[str, Any]]:
        """열린 AI 발언 차례를 조회해 중앙 worker에 전달한다.

        worker가 transaction과 Repository를 직접 소유하면 실행 조합 경계가
        분산되므로, PostgreSQL runtime이 조회 transaction을 관리한다. 이 메서드는
        읽기만 수행하며 실제 AI command 변경 transaction은 agent_pass가 소유한다.
        """

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_ai_speech_turns(cursor)

    def list_ai_night_turns(self) -> list[dict[str, Any]]:
        """모든 required 밤 역할이 AI인 게임의 actor를 조회한다."""

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_ai_night_turns(cursor)

    def list_expired_night_windows(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """deadline이 지난 밤 window를 조회해 자동 해소 worker에 전달한다."""

        current_time = now or datetime.now(UTC)
        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_expired_night_windows(
                    cursor, now=current_time
                )

    def auto_resolve_expired_night(
        self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """인간 포함 무응답 밤 행동을 deadline 기준으로 결정적으로 해소한다."""

        return self._actions.auto_resolve_expired_night(
            owner_user_id, game_id, now=now
        )

    def list_ai_vote_turns(self) -> list[dict[str, Any]]:
        """열린 투표 window에서 아직 처리되지 않은 AI actor를 조회한다."""

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_ai_vote_turns(cursor)

    async def run_agent_night_turn(
        self, owner_user_id: UUID, game_id: UUID, turns: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], bool]:
        """AI별 proposal을 수집한 뒤 밤 batch transaction을 실행한다."""

        actions: list[dict[str, UUID]] = []
        expected_version = int(turns[0]["state_version"])
        window_id = UUID(str(turns[0]["window_id"]))
        for turn in turns:
            player_id = UUID(str(turn["player_id"]))
            run_result = await self._run_orchestrated_proposal(
                owner_user_id, game_id, player_id, window_id, expected_version,
                job_kind="NIGHT_ACTION", phase="NIGHT_ACTION",
            )
            if run_result.status == "DUPLICATE":
                return {"status": "DEFERRED"}, True
            proposal = run_result.proposal
            if proposal is None or proposal.type != "NIGHT_ACTION" or proposal.target_player_id is None:
                proposal = self._fallback_target_proposal(
                    owner_user_id, game_id, player_id, expected_type="NIGHT_ACTION"
                )
            if proposal is None:
                raise ValueError("AI night proposal is not a target action")
            actions.append({"player_id": player_id, "target_player_id": proposal.target_player_id})
        return self._actions.submit_agent_night_actions(
            owner_user_id, game_id, actions, expected_state_version=expected_version,
            window_id=window_id, idempotency_key=uuid4(),
        )

    async def run_agent_vote_turn(
        self, owner_user_id: UUID, game_id: UUID, turns: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], bool]:
        """AI별 투표 proposal을 모아 현재 phase의 VOTE batch를 실행한다."""

        actions: list[dict[str, UUID]] = []
        expected_version = int(turns[0]["state_version"])
        window_id = UUID(str(turns[0]["window_id"]))
        for turn in turns:
            player_id = UUID(str(turn["player_id"]))
            run_result = await self._run_orchestrated_proposal(
                owner_user_id, game_id, player_id, window_id, expected_version,
                job_kind="VOTE", phase=str(turns[0].get("phase", "DAY_VOTE")),
            )
            if run_result.status == "DUPLICATE":
                return {"status": "DEFERRED"}, True
            proposal = run_result.proposal
            if proposal is None or proposal.type != "VOTE" or proposal.target_player_id is None:
                proposal = self._fallback_target_proposal(
                    owner_user_id, game_id, player_id, expected_type="VOTE"
                )
            if proposal is None:
                raise ValueError("AI vote proposal is not a target vote")
            actions.append({"player_id": player_id, "target_player_id": proposal.target_player_id})
        return self._actions.submit_agent_votes(
            owner_user_id, game_id, actions, expected_state_version=expected_version,
            window_id=window_id, idempotency_key=uuid4(),
        )

    async def _run_orchestrated_proposal(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        window_id: UUID,
        state_version: int,
        *,
        job_kind: str,
        phase: str,
    ) -> AgentRunResult:
        """하나의 AI proposal을 reservation·capability 경계 안에서 생성한다."""

        context = FastMcpGameContextClient(self._settings.mcp_server_url, user_id=owner_user_id, game_id=game_id)
        try:
            orchestrator = AgentOrchestrator(
                repository=self._agent_repository,
                provider=get_llm_provider(self._settings),
                context_client=context,
            )
            result = await orchestrator.run(AgentJobSpec(
                game_id=game_id, player_id=player_id, window_id=window_id,
                job_kind=job_kind, phase=phase, state_version=state_version,
            ))
            return result
        finally:
            await context.close()

    def start_background_worker(self) -> None:
        """PostgreSQL runtime에 중앙 AI 진행 task를 연결한다."""

        self._ai_worker.start()

    def _fallback_target_proposal(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        *,
        expected_type: str,
    ) -> NormalizedAgentProposal | None:
        """MCP envelope와 무관하게 DB snapshot의 합법 대상으로 target을 보정한다."""

        snapshot = self.snapshot(owner_user_id, game_id)
        window = snapshot.get("action_window") or {}
        targets = window.get("valid_targets", []) if isinstance(window, dict) else []
        for candidate in targets if isinstance(targets, list) else []:
            if not isinstance(candidate, dict):
                continue
            target = candidate.get("player_id")
            if target is None or str(target) == str(player_id):
                continue
            return NormalizedAgentProposal(
                type=expected_type,
                target_player_id=UUID(str(target)),
            )
        return None

    async def stop_background_worker(self) -> None:
        """앱 종료 시 중앙 AI 진행 task를 정리한다."""

        await self._ai_worker.stop()

    async def run_agent_turn(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
    ) -> dict[str, Any]:
        """FastMCP context와 선택된 LLM으로 AI turn을 실행한다.

        MCP·LLM 호출은 PostgreSQL transaction 밖에서 수행한다. proposal의 상태·권한·
        window 검증과 실제 저장은 FastMCP 뒤의 기존 command service가 담당한다.
        """

        snapshot = self.snapshot(owner_user_id, game_id)
        window = snapshot.get("action_window") or {}
        phase = str(snapshot.get("game", {}).get("phase", "DAY_DISCUSSION"))
        state_version = int(snapshot.get("game", {}).get("state_version", 0))
        context = FastMcpGameContextClient(
            self._settings.mcp_server_url,
            user_id=owner_user_id,
            game_id=game_id,
        )
        try:
            orchestrator = AgentOrchestrator(
                repository=self._agent_repository,
                provider=get_llm_provider(self._settings),
                context_client=context,
            )
            result = await orchestrator.run(
                AgentJobSpec(
                    game_id=game_id,
                    player_id=player_id,
                    window_id=UUID(str(window["window_id"])),
                    job_kind="SPEECH",
                    phase=phase,
                    state_version=state_version,
                )
            )
            proposal = result.proposal
            if proposal is None or proposal.type == "PASS":
                return self.agent_pass(owner_user_id, game_id, player_id, expected_state_version=state_version, window_id=UUID(str(window["window_id"])))
            if proposal.type == "SPEAK" and proposal.message is not None:
                return self.agent_speak(owner_user_id, game_id, player_id, proposal.message, expected_state_version=state_version, window_id=UUID(str(window["window_id"])))
            return self.agent_pass(owner_user_id, game_id, player_id, expected_state_version=state_version, window_id=UUID(str(window["window_id"])))
        finally:
            # Orchestrator도 terminal 처리 뒤 close하지만, 초기화 전 오류까지
            # 포함해 transport 종료를 보장하기 위해 idempotent close를 한 번 더 호출한다.
            await context.close()

    def create(
        self,
        owner_user_id: UUID,
        payload: CreateGameRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """게임 생성 업무를 PostgreSQL transaction으로 실행한다."""

        return self._create.create(owner_user_id, payload, idempotency_key)

    def list_games(
        self,
        owner_user_id: UUID,
        *,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """소유자 게임 목록을 PostgreSQL에서 읽는다."""

        return self._read.list_games(owner_user_id, status=status, limit=limit)

    def snapshot(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """현재 PostgreSQL read adapter가 지원하는 snapshot을 읽는다."""

        return self._read.snapshot(owner_user_id, game_id)

    def command(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """구현된 command Service만 선택하고 미구현 command는 실패시킨다."""

        if payload.type == "BEGIN_GAME":
            return self._begin.begin(owner_user_id, game_id, payload, idempotency_key)
        if payload.type in {"SPEAK", "PASS"}:
            return self._discussion.submit(owner_user_id, game_id, payload, idempotency_key)
        if payload.type in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
            return self._actions.submit(owner_user_id, game_id, payload, idempotency_key)
        if payload.type == "FAST_FORWARD":
            return self._actions.fast_forward(owner_user_id, game_id, payload, idempotency_key)
        if payload.type == "SAVE_AND_EXIT":
            return self._save.save(owner_user_id, game_id, payload, idempotency_key)
        if payload.type == "RESUME":
            return self._resume.resume(owner_user_id, game_id, payload, idempotency_key)
        raise ApiError(
            status_code=501,
            code="GAME_COMMAND_NOT_IMPLEMENTED",
            message="해당 게임 command는 PostgreSQL 업무 계층에 아직 연결되지 않았습니다.",
        )

    def agent_pass(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        *,
        expected_state_version: int,
        window_id: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """운영 Agent Manager 없이 deterministic AI PASS를 저장한다."""

        return self._agent_discussion.submit_pass(
            owner_user_id,
            game_id,
            player_id,
            expected_state_version=expected_state_version,
            window_id=window_id,
        )

    def agent_speak(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        message: str,
        *,
        expected_state_version: int,
        window_id: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """LLM이 만든 발언을 AI player 원장으로 저장한다."""

        return self._agent_discussion.submit_speak(
            owner_user_id, game_id, player_id, message,
            expected_state_version=expected_state_version, window_id=window_id,
        )

    def agent_action(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """AI night·vote proposal을 공통 action transaction으로 전달한다."""

        return self._actions.submit(
            owner_user_id,
            game_id,
            payload,
            idempotency_key,
            actor=ActorContext.agent(owner_user_id=owner_user_id, player_id=player_id),
        )

    def sync(self, owner_user_id: UUID, game_id: UUID, **_: int) -> dict[str, Any]:
        """PostgreSQL game_events를 기준으로 polling sync를 반환한다."""

        return self._read.sync(owner_user_id, game_id, **_)

    def feedback(
        self,
        owner_user_id: UUID,
        payload: FeedbackRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """feedback 요청을 PostgreSQL 업무 서비스로 전달한다."""

        return self._feedback.submit(owner_user_id, payload, idempotency_key)
