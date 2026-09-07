"""Backend bootstrap token의 canonical wire schema와 서명 검증이다."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from mafia_game.core.security.errors import AuthRequired, BootstrapDenied
from mafia_game.schemas.common import (
    GAME_PHASES,
    RESOURCE_SCOPE_ORDER,
    WireContractError,
    canonical_uuid,
    integer,
    require_keys,
    strict_json_object,
)

_TOKEN_PART = re.compile(r"^[A-Za-z0-9_-]+$")
_LOWER_HEX_256 = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_KEYS = {
    "token_type",
    "agent_job_id",
    "game_id",
    "subject_type",
    "subject_id",
    "capability_hash",
    "iat",
    "exp",
    "nonce",
}


@dataclass(frozen=True, slots=True)
class BootstrapClaims:
    """검증을 모두 통과해 한 MCP session에만 고정할 bootstrap claim이다."""

    agent_job_id: str
    game_id: str
    subject_type: str
    subject_id: str
    capability_hash: str
    iat: int
    exp: int
    nonce: str


@dataclass(frozen=True, slots=True)
class ConsumeBinding:
    """Engine이 capability record에서 반환한 immutable issuance metadata다."""

    status: str
    allowed_resource_scopes: tuple[str, ...]
    phase: str
    state_version: int
    window_id: str


class ConsumeContractError(ValueError):
    """consume 원문을 노출하지 않고 5-field 계약 위반만 나타낸다."""


def parse_consume_response(raw: bytes, subject_type: str) -> ConsumeBinding:
    """duplicate·scope 순서·subject binding을 포함한 성공 body 전체를 검증한다."""

    try:
        data = require_keys(
            strict_json_object(raw),
            {"status", "allowed_resource_scopes", "phase", "state_version", "window_id"},
        )
        if data["status"] != "CONSUMED":
            raise WireContractError
        scopes = data["allowed_resource_scopes"]
        if not isinstance(scopes, list) or not scopes:
            raise WireContractError
        allowed = {
            "AI_PLAYER": frozenset({"public", "me", "turn", "persona"}),
            "GM": frozenset({"public", "gm-guide"}),
        }.get(subject_type)
        if allowed is None or any(
            not isinstance(scope, str) or scope not in allowed for scope in scopes
        ):
            raise WireContractError
        expected_order = [scope for scope in RESOURCE_SCOPE_ORDER if scope in scopes]
        if scopes != expected_order:
            raise WireContractError
        phase = data["phase"]
        if not isinstance(phase, str) or phase not in GAME_PHASES:
            raise WireContractError
        state_version = integer(data["state_version"], minimum=1)
        window_id = canonical_uuid(data["window_id"])
    except WireContractError as error:
        raise ConsumeContractError from error
    return ConsumeBinding("CONSUMED", tuple(scopes), phase, state_version, window_id)


def _decode_base64url(value: str, *, auth_error: bool = True) -> bytes:
    """padding 없는 canonical base64url만 받아 표현 중복을 차단한다."""

    error_type = AuthRequired if auth_error else BootstrapDenied
    if (
        not isinstance(value, str)
        or not value
        or "=" in value
        or _TOKEN_PART.fullmatch(value) is None
    ):
        raise error_type
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise error_type from error
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise error_type
    return decoded


def _canonical_uuid(value: Any) -> str:
    """API 식별자는 version을 제한하지 않고 canonical hyphen UUID만 허용한다."""

    if not isinstance(value, str):
        raise BootstrapDenied
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise BootstrapDenied from error
    if str(parsed) != value:
        raise BootstrapDenied
    return value


def _closed_json(payload: bytes) -> dict[str, Any]:
    """중복 key와 비canonical JSON을 거부해 서명 payload 의미를 하나로 고정한다."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BootstrapDenied
            result[key] = value
        return result

    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BootstrapDenied from error
    if not isinstance(data, dict) or set(data) != _CLAIM_KEYS:
        raise BootstrapDenied
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if not hmac.compare_digest(canonical, payload):
        raise BootstrapDenied
    return data


class BootstrapTokenVerifier:
    """서명·폐쇄형 claim·capability binding을 clock leeway 없이 검증한다."""

    def __init__(self, secret: str, *, clock: Callable[[], float] = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("MCP_SERVER_AUTH_SECRET must contain at least 32 characters")
        self._secret = secret.encode("utf-8")
        self._clock = clock

    def verify(self, token: str, capability: str) -> BootstrapClaims:
        """상세 실패 원문을 남기지 않고 검증된 binding만 반환한다."""

        if not isinstance(token, str) or token.count(".") != 1:
            raise AuthRequired
        encoded_payload, encoded_signature = token.split(".")
        payload = _decode_base64url(encoded_payload)
        signature = _decode_base64url(encoded_signature)
        if len(signature) != hashlib.sha256().digest_size:
            raise AuthRequired
        expected = hmac.new(self._secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise BootstrapDenied

        data = _closed_json(payload)
        if data["token_type"] != "MCP_BOOTSTRAP":  # noqa: S105
            raise BootstrapDenied
        agent_job_id = _canonical_uuid(data["agent_job_id"])
        game_id = _canonical_uuid(data["game_id"])
        subject_id = _canonical_uuid(data["subject_id"])
        nonce = _canonical_uuid(data["nonce"])
        subject_type = data["subject_type"]
        if not isinstance(subject_type, str) or subject_type not in {"AI_PLAYER", "GM"}:
            raise BootstrapDenied
        if subject_type == "GM" and subject_id != game_id:
            raise BootstrapDenied

        if not isinstance(capability, str) or not capability:
            raise BootstrapDenied
        capability_hash = data["capability_hash"]
        if (
            not isinstance(capability_hash, str)
            or _LOWER_HEX_256.fullmatch(capability_hash) is None
        ):
            raise BootstrapDenied
        actual_hash = hashlib.sha256(capability.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(capability_hash, actual_hash):
            raise BootstrapDenied

        iat = data["iat"]
        exp = data["exp"]
        if isinstance(iat, bool) or not isinstance(iat, int):
            raise BootstrapDenied
        if isinstance(exp, bool) or not isinstance(exp, int):
            raise BootstrapDenied
        now = self._clock()
        if not (iat <= now < exp and 1 <= exp - iat <= 120):
            raise BootstrapDenied
        return BootstrapClaims(
            agent_job_id=agent_job_id,
            game_id=game_id,
            subject_type=subject_type,
            subject_id=subject_id,
            capability_hash=capability_hash,
            iat=iat,
            exp=exp,
            nonce=nonce,
        )
