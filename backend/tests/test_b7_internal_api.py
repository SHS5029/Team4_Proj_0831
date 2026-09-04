"""B7 내부 Engine API·nonce·SSE 계약을 확인하는 focused test."""

import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.infrastructure.security.internal_request import (
    calculate_engine_signature,
    create_bootstrap_token,
)
from backend.app.main import create_app
from backend.app.repositories.agent_repository import CapabilityRecord
from backend.app.repositories.nonce_repository import InMemoryNonceRepository
from backend.app.routers.scaffold_mcp_router import InternalApiDependencies
from backend.app.services.internal_engine_service import InternalEngineService
from backend.app.services.sync_service import (
    build_sync_response,
    encode_sse_batch,
)

SECRET = "engine-secret-for-tests-that-is-long-enough-123456"  # noqa: S105
MCP_SECRET = "mcp-secret-for-tests-that-is-long-enough-123456"  # noqa: S105
GAME_ID = uuid4()
PLAYER_ID = uuid4()
WINDOW_ID = uuid4()
JOB_ID = uuid4()
CAPABILITY = "opaque-capability-for-b7-tests"
NOW = datetime.now(UTC)


class FakeContextProvider:
    """실제 게임 DB 없이 capability와 projection 연결만 확인한다."""

    def get_context(self, record, scope):
        return {
            "context_version": 1,
            "game_id": str(record.game_id),
            "subject_type": record.subject_type,
            "subject_id": str(record.subject_player_id),
            "phase": record.phase,
            "state_version": record.state_version,
            "window_id": str(record.window_id),
            "scope": scope,
            "data": {},
        }


class FakeProposalHandler:
    """B5 command service 자리를 대신하는 안전한 fake 반영기."""

    def submit(self, *, record, proposal_id, request, proposal):
        return {
            "proposal_id": str(proposal_id),
            "status": "ACCEPTED",
            "result_state_version": record.state_version + 1,
        }


def make_record(*, allowed_tools=("propose_speech",)) -> CapabilityRecord:
    """현재 RESERVED agent job에 묶인 capability record를 만든다."""

    import hashlib

    return CapabilityRecord(
        token_hash=hashlib.sha256(CAPABILITY.encode()).hexdigest(),
        job_id=JOB_ID,
        game_id=GAME_ID,
        subject_type="AI_PLAYER",
        subject_player_id=PLAYER_ID,
        phase="DAY_DISCUSSION",
        state_version=12,
        window_id=WINDOW_ID,
        allowed_resources=("mafia://session/public",),
        allowed_tools=allowed_tools,
        expires_at=NOW + timedelta(seconds=100),
        revoked_at=None,
        job_status="RESERVED",
        job_lease_expires_at=NOW + timedelta(seconds=15),
    )


class FakeCapabilityRepository:
    """token hash 조회만 제공하는 B7용 fake repository."""

    def __init__(self, record):
        self.record = record

    def find_capability(self, token_hash):
        return self.record if token_hash == self.record.token_hash else None


def make_client():
    """내부 service 의존성을 주입한 테스트용 FastAPI client를 만든다."""

    settings = Settings(
        database_url="postgresql://test:synthetic@localhost/Team4_Proj",
        engine_internal_api_secret=SECRET,
        mcp_server_auth_secret=MCP_SECRET,
    )
    service = InternalEngineService(
        settings=settings,
        nonce_repository=InMemoryNonceRepository(),
        capability_repository=FakeCapabilityRepository(make_record()),
        context_provider=FakeContextProvider(),
        proposal_handler=FakeProposalHandler(),
        clock=lambda: NOW,
    )
    return TestClient(
        create_app(
            settings=settings,
            internal_dependencies=InternalApiDependencies(service=service),
        )
    )


def signed_headers(method: str, path: str, *, query: str = "", body: bytes = b"") -> dict[str, str]:
    """정본 canonical HMAC header를 만든다."""

    timestamp = str(int(time.time()))
    nonce = str(uuid4())
    signature = calculate_engine_signature(
        secret=SECRET.encode(),
        method=method,
        path=path,
        query=query,
        body=body,
        timestamp=timestamp,
        nonce=nonce,
    )
    return {
        "X-Engine-Timestamp": timestamp,
        "X-Engine-Nonce": nonce,
        "X-Engine-Signature": signature,
        "X-Agent-Capability": CAPABILITY,
    }


def test_agent_context_accepts_valid_hmac_and_rejects_nonce_replay():
    """서명된 첫 요청은 통과하고 같은 Engine nonce 재사용은 거부한다."""

    client = make_client()
    headers = signed_headers("GET", "/internal/v1/agent-context", query="scope=public")
    first = client.get("/internal/v1/agent-context?scope=public", headers=headers)
    second = client.get("/internal/v1/agent-context?scope=public", headers=headers)
    assert first.status_code == 200
    assert first.json()["scope"] == "public"
    assert second.status_code == 403
    assert second.json()["error"]["code"] == "CAPABILITY_DENIED"


def test_invalid_hmac_is_rejected_before_handler():
    """서명이 틀리면 DB capability 조회까지 진행하지 않는다."""

    client = make_client()
    headers = signed_headers("GET", "/internal/v1/agent-context", query="scope=public")
    headers["X-Engine-Signature"] = "invalid"
    response = client.get("/internal/v1/agent-context?scope=public", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_INTERNAL_SIGNATURE"


def test_bootstrap_token_is_consumed_once():
    """bootstrap nonce와 capability binding을 모두 확인하고 한 번만 소비한다."""

    client = make_client()
    import hashlib

    issued_at = int(time.time())
    token = create_bootstrap_token(
        secret=MCP_SECRET.encode(),
        claims={
            "token_type": "MCP_BOOTSTRAP",
            "agent_job_id": str(JOB_ID),
            "game_id": str(GAME_ID),
            "subject_type": "AI_PLAYER",
            "subject_id": str(PLAYER_ID),
            "capability_hash": hashlib.sha256(CAPABILITY.encode()).hexdigest(),
            "iat": issued_at,
            "exp": issued_at + 60,
            "nonce": str(uuid4()),
        },
    )
    body = json.dumps({"bootstrap_token": token}, separators=(",", ":")).encode()
    bootstrap_headers = {
        **signed_headers("POST", "/internal/v1/mcp-bootstrap/consume", body=body),
        "Content-Type": "application/json",
    }
    first = client.post(
        "/internal/v1/mcp-bootstrap/consume",
        content=body,
        headers=bootstrap_headers,
    )
    # 같은 bootstrap token을 새 HTTP nonce로 보내도 bootstrap nonce에서 막힌다.
    second_headers = {
        **signed_headers("POST", "/internal/v1/mcp-bootstrap/consume", body=body),
        "Content-Type": "application/json",
    }
    second = client.post(
        "/internal/v1/mcp-bootstrap/consume",
        content=body,
        headers=second_headers,
    )
    assert first.status_code == 200
    assert first.json() == {"status": "CONSUMED"}
    assert second.status_code == 403


def test_agent_proposal_is_rechecked_against_capability():
    """agent·game·window·version이 capability와 맞을 때만 handler에 전달한다."""

    client = make_client()
    proposal_id = uuid4()
    payload = {
        "proposal_id": str(proposal_id),
        "game_id": str(GAME_ID),
        "agent_id": str(PLAYER_ID),
        "window_id": str(WINDOW_ID),
        "expected_state_version": 12,
        "proposal": {
            "type": "SPEAK",
            "message": "공개된 사실을 다시 확인하겠습니다.",
            "target_player_id": None,
            "public_rationale": "공개 정보만 사용",
        },
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    proposal_headers = {
        **signed_headers("POST", "/internal/v1/agent-proposals", body=body),
        "Content-Type": "application/json",
    }
    response = client.post(
        "/internal/v1/agent-proposals",
        content=body,
        headers=proposal_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"


def test_sync_and_sse_never_emit_incomplete_operation_batch():
    """operation index가 빠진 batch는 delta에 넣지 않는다."""

    event_id = uuid4()
    rows = [
        {
            "id": event_id,
            "front_sequence": 1,
            "operation_index": 0,
            "operation_type": "PLAYER_SPOKE",
            "state_version": 13,
            "payload": {"message": "공개 발언"},
        },
        {
            "id": uuid4(),
            "front_sequence": 2,
            "operation_index": 1,
            "operation_type": "BROKEN_BATCH",
            "state_version": 14,
            "payload": {},
        },
    ]
    response = build_sync_response(
        after_front_sequence=0,
        rows=rows,
        snapshot={"state_version": 14},
    )
    assert response["mode"] == "SNAPSHOT"
    assert response["operations"] == []
    complete = build_sync_response(
        after_front_sequence=0,
        rows=rows[:1],
        snapshot={"state_version": 13},
    )
    assert complete["mode"] == "DELTA"
    assert "event: operations" in encode_sse_batch(complete["operations"][0])
