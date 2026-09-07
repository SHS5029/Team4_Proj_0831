"""Agent job 예약부터 Provider 결과 정리까지의 B6 orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from backend.app.llm_provider.base import LLMRequest, LLMResponse
from backend.app.llm_provider.schemas import (
    NormalizedAgentProposal,
    agent_proposal_schema,
    normalize_agent_proposal,
)
from backend.app.mcp.client import AgentContextClient

if TYPE_CHECKING:
    from backend.app.repositories.agent_repository import AgentReservation, CapabilityGrant


class AgentRepository(Protocol):
    """Orchestrator가 필요한 저장소 동작만 표현한다."""

    def reserve_job(self, **kwargs: Any) -> AgentReservation | None: ...

    def issue_capability(self, **kwargs: Any) -> CapabilityGrant: ...

    def complete_job(self, *args: Any, **kwargs: Any) -> bool: ...

    def revoke_capability(self, *args: Any, **kwargs: Any) -> None: ...


class AgentProvider(Protocol):
    """환경에서 선택된 단일 Provider 계약이다. 자동 failover를 하지 않는다."""

    async def generate(self, request: LLMRequest) -> LLMResponse: ...


@dataclass(frozen=True, slots=True)
class AgentJobSpec:
    """한 번의 AI turn에 필요한 DB·권한 식별자."""

    game_id: UUID
    player_id: UUID | None
    window_id: UUID
    job_kind: str
    phase: str
    state_version: int
    subject_type: str = "AI_PLAYER"
    window_deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """외부에 공개하지 않고 command service가 사용할 terminal 결과."""

    status: str
    proposal: NormalizedAgentProposal | None = None
    result_state_version: int | None = None
    failure_code: str | None = None
    fallback_message: str | None = None


class AgentOrchestrator:
    """외부 호출 전후에 fencing과 capability 수명을 관리한다."""

    def __init__(
        self,
        repository: AgentRepository,
        provider: AgentProvider,
        context_client: AgentContextClient,
        *,
        clock: Any | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.context_client = context_client
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def run(self, spec: AgentJobSpec) -> AgentRunResult:
        """예약→context→단일 Provider→검증→완료/fallback 순서를 실행한다."""

        reservation = self.repository.reserve_job(
            game_id=spec.game_id,
            player_id=spec.player_id,
            window_id=spec.window_id,
            job_kind=spec.job_kind,
            state_version=spec.state_version,
            window_deadline=spec.window_deadline,
            now=self.clock(),
        )
        if reservation is None:
            return AgentRunResult(status="DUPLICATE")

        capability = self.repository.issue_capability(
            reservation,
            subject_type=spec.subject_type,
            phase=spec.phase,
            allowed_resources=self._resources(spec.subject_type),
            allowed_tools=self._tools(spec.job_kind, spec.subject_type),
            now=self.clock(),
        )
        result = AgentRunResult(status="FAILED", failure_code="AGENT_FAILED")
        context: dict[str, Any] = {}
        try:
            try:
                context = {}
                # 현재 FastMCP adapter는 scope별 별도 projection이 아니라 하나의
                # canonical snapshot을 반환하므로 같은 snapshot을 네 번 조회하지
                # 않고 한 번만 읽어 Agent 내부 scope에 재사용한다.
                snapshot = await self.context_client.get_context(
                    capability=capability.raw_token,
                    scope="public",
                )
                for scope in self._scopes(spec.subject_type):
                    context[scope] = snapshot
                response = await self.provider.generate(self._request(context))
                try:
                    proposal = normalize_agent_proposal(response.output)
                except Exception:
                    # 구조화 오류는 한 번만 재요청한다. 두 번째도 실패하면 외부
                    # 모델을 반복 호출하지 않고 규칙 fallback으로 종료한다.
                    repair = await self.provider.generate(self._request(context, repair=True))
                    proposal = normalize_agent_proposal(repair.output)
                proposal = self._coerce_target_proposal(spec, proposal, context)
                result = AgentRunResult(status="SUCCEEDED", proposal=proposal)
            except Exception as error:
                result = AgentRunResult(
                    status="FALLBACK",
                    proposal=self._fallback_proposal(spec, context),
                    failure_code=self._failure_code(error),
                    fallback_message=(
                        "게임 진행에 문제가 있어 안내 문구를 표시합니다."
                        if spec.subject_type == "GM"
                        else None
                    ),
                )

            # 외부 호출이 끝난 뒤에만 lease를 확인한다. 늦은 결과를 새 상태에
            # 자동 rebase하지 않고 STALE로 버리는 것이 fencing의 핵심이다.
            if self.clock() >= reservation.lease_expires_at:
                result = AgentRunResult(status="STALE", failure_code="LEASE_EXPIRED")
            proposal_body = result.proposal.model_dump(mode="json") if result.proposal else None
            completed = self.repository.complete_job(
                reservation,
                status=result.status,
                normalized_proposal=proposal_body,
                failure_code=result.failure_code,
                now=self.clock(),
            )
            if not completed:
                return AgentRunResult(status="STALE", failure_code="FENCING_REJECTED")
            return result
        finally:
            # raw capability가 더 이상 사용되지 않도록 terminal 결과 뒤 hash만
            # 폐기 요청에 사용한다. raw token을 DB·log에 넘기지 않는다.
            self.repository.revoke_capability(capability.token_hash, now=self.clock())
            await self.context_client.close()

    @staticmethod
    def _request(context: dict[str, Any], *, repair: bool = False) -> LLMRequest:
        """LLM에 context와 출력 schema만 전달하고 내부 추론을 요구하지 않는다."""

        import json

        instruction = (
            "정해진 JSON proposal만 반환하세요. 내부 추론은 반환하지 마세요."
            if not repair
            else "직전 형식 오류를 고쳐 정해진 JSON proposal만 반환하세요."
        )
        return LLMRequest(
            messages=(
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, sort_keys=True)},
            ),
            response_schema=agent_proposal_schema(),
            max_output_tokens=400,
            timeout_seconds=15,
        )

    @staticmethod
    def _resources(subject_type: str) -> list[str]:
        return [
            "mafia://session/public",
            "mafia://session/gm-guide",
        ] if subject_type == "GM" else [
            "mafia://session/public",
            "mafia://session/me",
            "mafia://session/turn",
            "mafia://session/persona",
        ]

    @staticmethod
    def _tools(job_kind: str, subject_type: str) -> list[str]:
        if subject_type == "GM":
            return []
        return {
            "SPEECH": ["propose_speech", "propose_pass"],
            "NIGHT_ACTION": ["propose_night_action"],
            "VOTE": ["propose_vote"],
        }.get(job_kind, [])

    @staticmethod
    def _scopes(subject_type: str) -> list[str]:
        """주체별 허용 resource만 조회한다."""

        return ["public", "gm-guide"] if subject_type == "GM" else ["public", "me", "turn", "persona"]

    @staticmethod
    def _failure_code(error: Exception) -> str:
        """외부 오류의 class만 운영 결과로 남기고 원문은 버린다."""

        name = type(error).__name__.upper()
        if "TIMEOUT" in name:
            return "PROVIDER_TIMEOUT"
        if "MCP" in name or "CONTEXT" in name:
            return "MCP_UNAVAILABLE"
        if "LLM" in name or "PROPOSAL" in name:
            return "PROPOSAL_INVALID"
        return "AGENT_DEPENDENCY_ERROR"

    @staticmethod
    def _fallback_proposal(
        spec: AgentJobSpec,
        context: dict[str, Any],
    ) -> NormalizedAgentProposal | None:
        """실패한 Agent를 게임 규칙 fallback으로 넘길 canonical 결과를 만든다."""

        if spec.job_kind == "SPEECH":
            return NormalizedAgentProposal(type="PASS")
        if spec.job_kind not in {"NIGHT_ACTION", "VOTE"}:
            return None
        targets = AgentOrchestrator._valid_targets(context)
        target = targets[0].get("player_id") if targets and isinstance(targets[0], dict) else None
        if target is None:
            return None
        proposal_type = "NIGHT_ACTION" if spec.job_kind == "NIGHT_ACTION" else "VOTE"
        return NormalizedAgentProposal(type=proposal_type, target_player_id=target)

    @classmethod
    def _coerce_target_proposal(
        cls,
        spec: AgentJobSpec,
        proposal: NormalizedAgentProposal,
        context: dict[str, Any],
    ) -> NormalizedAgentProposal:
        """대상 행동에서 PASS 응답을 첫 합법 대상 선택으로 보정한다.

        현재 Dummy Provider는 모든 작업에 PASS를 반환할 수 있고, 일부 LLM도
        대상 행동에서 PASS를 선택할 수 있다. 밤 행동과 투표는 게임 규칙상
        PASS가 없으므로 MCP turn context가 제공한 후보만 사용해 결정적으로
        보정한다. 후보가 없으면 원 proposal을 반환해 상위 계층이 안전하게
        실패 처리하도록 한다.
        """

        if spec.job_kind not in {"NIGHT_ACTION", "VOTE"}:
            return proposal
        expected_type = "NIGHT_ACTION" if spec.job_kind == "NIGHT_ACTION" else "VOTE"
        if proposal.type == expected_type and proposal.target_player_id is not None:
            return proposal
        targets = cls._valid_targets(context)
        target = targets[0].get("player_id") if targets and isinstance(targets[0], dict) else None
        if target is None:
            return proposal
        return NormalizedAgentProposal(type=expected_type, target_player_id=target)

    @staticmethod
    def _valid_targets(context: dict[str, Any]) -> list[Any]:
        """Fake envelope와 실제 FastMCP snapshot에서 합법 대상을 통일해 읽는다."""

        nested = context.get("context")
        if isinstance(nested, dict):
            targets = AgentOrchestrator._valid_targets(nested)
            if targets:
                return targets
        turn_context = context.get("turn", context)
        if isinstance(turn_context, dict):
            data = turn_context.get("data", {})
            if isinstance(data, dict) and isinstance(data.get("valid_targets"), list):
                return data["valid_targets"]
            window = turn_context.get("action_window")
            if isinstance(window, dict) and isinstance(window.get("valid_targets"), list):
                return window["valid_targets"]
        window = context.get("action_window")
        if isinstance(window, dict) and isinstance(window.get("valid_targets"), list):
            return window["valid_targets"]
        return []
