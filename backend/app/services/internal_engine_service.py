"""B7 내부 Engine API의 nonce·capability·projection 경계를 조정한다."""

from __future__ import annotations

import hashlib
import hmac
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.infrastructure.security.internal_request import (
    InternalRequestAuth,
    decode_bootstrap_token,
)
from backend.app.llm_provider.schemas import NormalizedAgentProposal, normalize_agent_proposal
from backend.app.repositories.agent_repository import CapabilityRecord
from backend.app.repositories.nonce_repository import NonceRepository
from backend.app.schemas.internal_schema import AgentProposalRequest


class CapabilityRepository(Protocol):
    """현재 capability를 token hash로 조회하는 최소 계약."""

    def find_capability(self, token_hash: str) -> CapabilityRecord | None: ...


class ContextProvider(Protocol):
    """현재 authoritative 상태에서 scope projection을 제공하는 계약."""

    def get_context(self, record: CapabilityRecord, scope: str) -> dict[str, Any]: ...


class ProposalHandler(Protocol):
    """B5 command service가 연결할 Agent 행동 반영 계약."""

    def submit(
        self,
        *,
        record: CapabilityRecord,
        proposal_id: UUID,
        request: AgentProposalRequest,
        proposal: NormalizedAgentProposal,
    ) -> dict[str, Any]: ...


class InternalApiRejected(ApiError):
    """내부 API에서 capability 상세를 노출하지 않는 공통 거부 오류."""


def _capability_denied() -> InternalApiRejected:
    """만료·주체 불일치·현재 상태 불일치를 같은 외부 오류로 합친다."""

    return InternalApiRejected(
        status_code=403,
        code="CAPABILITY_DENIED",
        message="현재 작업 권한으로 처리할 수 없습니다.",
    )


@dataclass(frozen=True, slots=True)
class InternalEngineService:
    """내부 route가 보안·projection·행동 handler를 같은 순서로 호출하게 한다."""

    settings: Settings
    nonce_repository: NonceRepository
    capability_repository: CapabilityRepository
    context_provider: ContextProvider | None = None
    proposal_handler: ProposalHandler | None = None
    clock: Any = lambda: datetime.now(UTC)

    def consume_engine_nonce(self, auth: InternalRequestAuth) -> None:
        """HMAC 검증 후 PostgreSQL nonce 원장에 먼저 기록한다."""

        now = self.clock()
        accepted = self.nonce_repository.consume(
            scope="ENGINE_HMAC",
            nonce=auth.nonce,
            request_hash=auth.request_hash,
            expires_at=now + timedelta(seconds=120),
        )
        if not accepted:
            raise _capability_denied()

    def consume_bootstrap(
        self,
        *,
        auth: InternalRequestAuth,
        bootstrap_token: str,
    ) -> dict[str, str]:
        """token claim·capability·예약 job·bootstrap nonce를 한 번에 확인한다."""

        try:
            secret = self.settings.validated_mcp_server_auth_secret
            claims = decode_bootstrap_token(secret=secret, token=bootstrap_token)
        except (RuntimeError, ValueError) as exc:
            raise _capability_denied() from exc
        if not hmac.compare_digest(
            self._capability_hash(auth.capability), str(claims["capability_hash"])
        ):
            raise _capability_denied()
        record = self._active_capability(auth.capability)
        self._validate_claim(record, claims)
        accepted = self.nonce_repository.consume(
            scope="MCP_BOOTSTRAP",
            nonce=UUID(str(claims["nonce"])),
            request_hash=hashlib.sha256(bootstrap_token.encode("utf-8")).hexdigest(),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
        )
        if not accepted:
            raise _capability_denied()
        return {"status": "CONSUMED"}

    def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """capability가 허용한 scope만 projection provider에서 읽는다."""

        record = self._active_capability(capability)
        resource = f"mafia://session/{scope}"
        if resource not in record.allowed_resources:
            raise _capability_denied()
        if scope not in {"public", "me", "turn", "persona", "gm-guide"}:
            raise _capability_denied()
        if record.subject_type == "GM" and scope not in {"public", "gm-guide"}:
            raise _capability_denied()
        if record.subject_type == "AI_PLAYER" and scope == "gm-guide":
            raise _capability_denied()
        if self.context_provider is None:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="게임 상태를 조회할 수 없습니다.",
                retryable=True,
            )
        result = self.context_provider.get_context(record, scope)
        if inspect.isawaitable(result):
            raise RuntimeError("비동기 context provider는 async adapter에서 호출해야 합니다.")
        self._validate_context_identity(result, record, scope)
        return result

    def submit_proposal(
        self,
        *,
        capability: str,
        request: AgentProposalRequest,
    ) -> dict[str, Any]:
        """proposal 형식과 capability binding을 확인한 뒤 command handler에 위임한다."""

        record = self._active_capability(capability)
        if (
            record.subject_type != "AI_PLAYER"
            or record.subject_player_id != request.agent_id
            or record.game_id != request.game_id
            or record.window_id != request.window_id
            or record.state_version != request.expected_state_version
        ):
            raise _capability_denied()
        try:
            proposal = normalize_agent_proposal(request.proposal)
        except Exception as exc:
            raise _capability_denied() from exc
        expected_tool = {
            "SPEAK": "propose_speech",
            "PASS": "propose_pass",
            "NIGHT_ACTION": "propose_night_action",
            "VOTE": "propose_vote",
        }[proposal.type]
        if expected_tool not in record.allowed_tools:
            raise _capability_denied()
        if self.proposal_handler is None:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="게임 행동 처리기가 준비되지 않았습니다.",
                retryable=True,
            )
        result = self.proposal_handler.submit(
            record=record,
            proposal_id=request.proposal_id,
            request=request,
            proposal=proposal,
        )
        if inspect.isawaitable(result):
            raise RuntimeError("비동기 proposal handler는 async adapter에서 호출해야 합니다.")
        return result

    def _active_capability(self, raw_capability: str) -> CapabilityRecord:
        """raw token은 hash로만 조회하고 만료·폐기·lease를 다시 확인한다."""

        if not raw_capability or len(raw_capability) > 512:
            raise _capability_denied()
        token_hash = self._capability_hash(raw_capability)
        record = self.capability_repository.find_capability(token_hash)
        now = self.clock()
        if (
            record is None
            or not hmac.compare_digest(record.token_hash, token_hash)
            or record.revoked_at is not None
            or record.expires_at <= now
            or record.job_status != "RESERVED"
            or record.job_lease_expires_at is None
            or record.job_lease_expires_at <= now
        ):
            raise _capability_denied()
        return record

    @staticmethod
    def _capability_hash(raw_capability: str) -> str:
        """opaque capability를 ASCII로만 받아 동일한 hash 규칙을 적용한다."""

        try:
            encoded = raw_capability.encode("ascii")
        except UnicodeEncodeError as exc:
            raise _capability_denied() from exc
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_claim(record: CapabilityRecord, claims: dict[str, Any]) -> None:
        """bootstrap claim의 job·subject가 DB capability와 정확히 같은지 확인한다."""

        if record.job_id is None:
            raise _capability_denied()
        if (
            str(record.job_id) != str(claims["agent_job_id"])
            or str(record.game_id) != str(claims["game_id"])
            or record.subject_type != claims["subject_type"]
            or str(record.subject_player_id or record.game_id) != str(claims["subject_id"])
            or record.token_hash != claims["capability_hash"]
        ):
            raise _capability_denied()

    @staticmethod
    def _validate_context_identity(
        result: dict[str, Any], record: CapabilityRecord, scope: str
    ) -> None:
        """provider가 다른 agent의 context를 실수로 반환하지 않았는지 확인한다."""

        if not isinstance(result, dict):
            raise _capability_denied()
        for key, expected in {
            "context_version": 1,
            "game_id": str(record.game_id),
            "subject_type": record.subject_type,
            "subject_id": str(record.subject_player_id or record.game_id),
            "phase": record.phase,
            "state_version": record.state_version,
            "window_id": str(record.window_id),
            "scope": scope,
        }.items():
            if result.get(key) != expected:
                raise _capability_denied()
