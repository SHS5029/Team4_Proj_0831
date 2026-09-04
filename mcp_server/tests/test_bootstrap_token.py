"""bootstrap token의 폐쇄형·무유예 검증 계약을 고정한다."""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from uuid import uuid4

import pytest

from mafia_game.core.security.errors import BootstrapDenied
from mafia_game.schemas.bootstrap import BootstrapTokenVerifier

NOW = 1_788_352_496
SECRET = "synthetic-mcp-bootstrap-secret-value"


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


CAPABILITY = _encoded(b"synthetic-capability-value-00001")


def make_claims(**changes: object) -> dict[str, object]:
    """정본의 정확한 claim 집합을 만들고 개별 거부 조건만 분리해 바꾼다."""

    game_id = str(uuid4())
    claims: dict[str, object] = {
        "token_type": "MCP_BOOTSTRAP",
        "agent_job_id": str(uuid4()),
        "game_id": game_id,
        "subject_type": "AI_PLAYER",
        "subject_id": str(uuid4()),
        "capability_hash": hashlib.sha256(CAPABILITY.encode()).hexdigest(),
        "iat": NOW,
        "exp": NOW + 120,
        "nonce": "00000000-0000-1000-8000-000000000004",
    }
    claims.update(changes)
    return claims


def sign(claims: dict[str, object], *, secret: str = SECRET) -> str:
    """정렬 key·공백 없는 canonical JSON과 padding 없는 base64url 서명을 만든다."""

    payload = json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    encoded_payload = _encoded(payload)
    signature = hmac.new(secret.encode(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_encoded(signature)}"


def verifier() -> BootstrapTokenVerifier:
    return BootstrapTokenVerifier(SECRET, clock=lambda: NOW)


def test_accepts_exact_canonical_claims_and_capability_hash() -> None:
    claims = make_claims()

    parsed = verifier().verify(sign(claims), CAPABILITY)

    assert parsed.agent_job_id == claims["agent_job_id"]
    assert parsed.subject_type == "AI_PLAYER"
    assert parsed.capability_hash == hashlib.sha256(CAPABILITY.encode()).hexdigest()


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda claims: {**claims, "unexpected": True}, id="unknown-claim"),
        pytest.param(lambda claims: {**claims, "token_type": "OTHER"}, id="token-type"),
        pytest.param(lambda claims: {**claims, "agent_job_id": "not-a-uuid"}, id="job-uuid"),
        pytest.param(lambda claims: {**claims, "subject_type": "ADMIN"}, id="subject-type"),
        pytest.param(lambda claims: {**claims, "capability_hash": "A" * 64}, id="hash-format"),
        pytest.param(lambda claims: {**claims, "iat": NOW + 1}, id="future-iat"),
        pytest.param(lambda claims: {**claims, "exp": NOW}, id="expired-no-leeway"),
        pytest.param(lambda claims: {**claims, "exp": NOW + 121}, id="over-120-seconds"),
    ],
)
def test_rejects_invalid_or_noncanonical_claims(
    mutate: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    with pytest.raises(BootstrapDenied):
        verifier().verify(sign(mutate(make_claims())), CAPABILITY)


def test_rejects_gm_subject_that_is_not_the_game_id() -> None:
    claims = make_claims(subject_type="GM", subject_id=str(uuid4()))

    with pytest.raises(BootstrapDenied):
        verifier().verify(sign(claims), CAPABILITY)


def test_accepts_canonical_non_v4_ids_including_bootstrap_nonce() -> None:
    """bootstrap claim의 모든 ID는 canonical UUID이면 version과 무관하게 허용한다."""

    game_id = "00000000-0000-1000-8000-000000000001"
    job_id = "00000000-0000-5000-8000-000000000002"
    subject_id = "00000000-0000-1000-8000-000000000003"
    claims = make_claims(agent_job_id=job_id, game_id=game_id, subject_id=subject_id)

    parsed = verifier().verify(sign(claims), CAPABILITY)

    assert parsed.agent_job_id == job_id
    assert parsed.game_id == game_id
    assert parsed.subject_id == subject_id
    assert parsed.nonce == "00000000-0000-1000-8000-000000000004"


@pytest.mark.parametrize("capability", ["opaque+capability", "x", "한글 opaque capability"])
def test_accepts_nonempty_opaque_capability_when_claim_hash_matches(capability: str) -> None:
    """MCP는 Backend가 발급한 capability의 내부 encoding이나 길이를 재검증하지 않는다."""

    claims = make_claims(capability_hash=hashlib.sha256(capability.encode()).hexdigest())

    parsed = verifier().verify(sign(claims), capability)

    assert parsed.capability_hash == hashlib.sha256(capability.encode()).hexdigest()


def test_non_string_subject_type_is_fixed_denial() -> None:
    with pytest.raises(BootstrapDenied):
        verifier().verify(sign(make_claims(subject_type=["AI_PLAYER"])), CAPABILITY)


def test_rejects_noncanonical_json_even_when_signature_matches() -> None:
    payload = json.dumps(make_claims(), ensure_ascii=False, sort_keys=False, indent=1).encode()
    encoded_payload = _encoded(payload)
    signature = _encoded(
        hmac.new(SECRET.encode(), encoded_payload.encode(), hashlib.sha256).digest()
    )

    with pytest.raises(BootstrapDenied):
        verifier().verify(f"{encoded_payload}.{signature}", CAPABILITY)


def test_rejects_tampered_signature_and_capability_hash_mismatch() -> None:
    token = sign(make_claims())
    encoded_payload, encoded_signature = token.split(".")
    signature = bytearray(_decode_for_test(encoded_signature))
    signature[0] ^= 1
    tampered = f"{encoded_payload}.{_encoded(bytes(signature))}"

    with pytest.raises(BootstrapDenied):
        verifier().verify(tampered, CAPABILITY)
    with pytest.raises(BootstrapDenied):
        verifier().verify(token, "different-capability")


def _decode_for_test(value: str) -> bytes:
    """서명 byte를 바꿔 base64url 형식은 유지한 변조 fixture를 만든다."""

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
