"""bootstrap 검증·replay 예약·Engine consume을 순서대로 조합한다."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import anyio

from mafia_game.core.audit import AuditError, AuditOperation, AuditRecorder, AuditStatus
from mafia_game.core.security.errors import (
    AuthRequired,
    BootstrapDenied,
    EngineConsumeDenied,
    ReplayDetected,
)
from mafia_game.ports.engine_bootstrap import EngineBootstrapPort
from mafia_game.schemas.bootstrap import (
    BootstrapClaims,
    BootstrapTokenVerifier,
    ConsumeBinding,
    ConsumeContractError,
    parse_consume_response,
)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """claim과 Engine issuance가 같은 consume 판정에서 결합된 결과다."""

    claims: BootstrapClaims
    issuance: ConsumeBinding


class InMemoryReplayLedger:
    """동시 initialize에서도 한 nonce만 Engine consume으로 보내는 process-local 원장이다."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._nonces: dict[str, int] = {}
        self._lock = anyio.Lock()
        self._clock = clock

    async def reserve(self, nonce: str, expires_at: int) -> None:
        """호출 전에 nonce를 소모하고 만료된 원장 항목만 정리한다."""

        async with self._lock:
            now = self._clock()
            self._nonces = {
                stored_nonce: expiry
                for stored_nonce, expiry in self._nonces.items()
                if expiry > now
            }
            if nonce in self._nonces:
                raise ReplayDetected
            self._nonces[nonce] = expires_at


class BootstrapService:
    """Engine 응답이 늦게 도착해도 만료된 bootstrap으로 session을 열지 않는다."""

    def __init__(
        self,
        verifier: BootstrapTokenVerifier,
        engine: EngineBootstrapPort,
        replay_ledger: InMemoryReplayLedger,
        *,
        audit: AuditRecorder | None = None,
    ) -> None:
        self._verifier = verifier
        self._engine = engine
        self._replay_ledger = replay_ledger
        self._audit = audit or AuditRecorder()

    def verify(self, token: str, capability: str) -> BootstrapClaims:
        """후속 owner 요청도 같은 canonical 검증기를 사용한다."""

        return self._verifier.verify(token, capability)

    async def consume(self, token: str, capability: str) -> BootstrapResult:
        """consume 전후에 만료를 검증하고 성공이 불명확하면 session을 만들지 않는다."""

        span = self._audit.start(AuditOperation.BOOTSTRAP_CONSUME)
        try:
            result = await self._consume(token, capability)
        except anyio.get_cancelled_exc_class():
            span.finish(AuditStatus.CANCELLED, error_class=AuditError.CANCELLED)
            raise
        except (AuthRequired, BootstrapDenied, ReplayDetected, EngineConsumeDenied):
            span.finish(AuditStatus.REJECTED, error_class=AuditError.BOOTSTRAP_DENIED)
            raise
        except Exception:
            span.finish(AuditStatus.FAILED, error_class=AuditError.INTERNAL_ERROR)
            raise
        span.finish(AuditStatus.SUCCEEDED)
        return result

    async def _consume(self, token: str, capability: str) -> BootstrapResult:
        """로그 record에 자격값을 넘기지 않고 기존 검증·consume 순서를 유지한다."""

        claims = self._verifier.verify(token, capability)
        await self._replay_ledger.reserve(claims.nonce, claims.exp)
        raw_response = await self._engine.consume(token, capability)
        try:
            issuance = parse_consume_response(raw_response, claims.subject_type)
        except ConsumeContractError as error:
            raise EngineConsumeDenied from error
        verified_claims = self._verifier.verify(token, capability)
        return BootstrapResult(verified_claims, issuance)
