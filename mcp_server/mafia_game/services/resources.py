"""Resource read의 Engine 1회 호출과 단일 응답 검증을 조합한다."""

from __future__ import annotations

import json

import anyio

from mafia_game.core.audit import AuditError, AuditOperation, AuditRecorder, AuditStatus
from mafia_game.core.security.errors import (
    CapabilityDenied,
    DependencyUnavailable,
    UpstreamContractViolation,
)
from mafia_game.domain.session import SessionBinding
from mafia_game.ports.engine_context import EngineContextPort
from mafia_game.schemas.context import ContextContractError, decode_and_validate_context


class ResourceService:
    """context를 캐시하지 않고 매 허용 read를 새 Engine GET 하나로 처리한다."""

    def __init__(
        self, engine: EngineContextPort, *, audit: AuditRecorder | None = None
    ) -> None:
        self._engine = engine
        self._audit = audit or AuditRecorder()

    async def read(self, binding: SessionBinding, scope: str) -> str:
        """raw JSON을 요청 지역 변수에서만 검증·직렬화하고 retained reference를 두지 않는다."""

        span = self._audit.start(AuditOperation.ENGINE_CONTEXT)
        try:
            result = await self._read_validated(binding, scope)
        except anyio.get_cancelled_exc_class():
            span.finish(AuditStatus.CANCELLED, error_class=AuditError.CANCELLED)
            raise
        except CapabilityDenied:
            span.finish(AuditStatus.REJECTED, error_class=AuditError.CAPABILITY_DENIED)
            raise
        except DependencyUnavailable:
            span.finish(AuditStatus.FAILED, error_class=AuditError.DEPENDENCY_UNAVAILABLE)
            raise
        except UpstreamContractViolation:
            span.finish(AuditStatus.FAILED, error_class=AuditError.UPSTREAM_CONTRACT_VIOLATION)
            raise
        except Exception:
            span.finish(AuditStatus.FAILED, error_class=AuditError.INTERNAL_ERROR)
            raise
        span.finish(AuditStatus.SUCCEEDED)
        return result

    async def _read_validated(self, binding: SessionBinding, scope: str) -> str:
        """HTTP 200뿐 아니라 전체 schema와 직렬화까지 통과해야 조회 성공으로 확정한다."""

        raw = await self._engine.get_context(scope, binding.capability)
        try:
            payload = decode_and_validate_context(
                raw,
                game_id=binding.claims.game_id,
                subject_type=binding.claims.subject_type,
                subject_id=binding.claims.subject_id,
                phase=binding.issuance.phase,
                state_version=binding.issuance.state_version,
                window_id=binding.issuance.window_id,
                scope=scope,
            )
            return json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (ContextContractError, TypeError, ValueError) as error:
            raise UpstreamContractViolation from error
