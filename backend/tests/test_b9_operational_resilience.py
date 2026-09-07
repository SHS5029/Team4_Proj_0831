"""B9 규칙 harness와 외부 장애의 fallback·재시도 경계를 검증한다."""

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.agent.orchestrator import AgentJobSpec, AgentOrchestrator
from backend.app.infrastructure.redis.lock import RedisGameLock
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.game_engine.engine import GameEngine
from backend.app.models.enums import GamePhase, GameStatus, PlayerRole
from backend.app.repositories.agent_repository import AgentReservation, CapabilityGrant
from backend.app.services.outbox_service import PostgresOutboxPublisher
from backend.tests.simulations.heuristic_game import (
    _pass_discussion,
    _players,
    _resolve_heuristic_night,
    _resolve_heuristic_vote,
    _signature,
)


@pytest.mark.parametrize("player_count", [6, 7, 8, 9])
def test_b9_night_harness_submits_every_living_role_actor(player_count: int) -> None:
    """마피아 두 명 구성에서도 모두 첫 제출 기회를 가진 뒤 밤을 해소한다."""

    seed = f"b9-full-night:{player_count}"
    state = GameEngine.new_game(_players(player_count, seed), seed=seed)
    engine = GameEngine()
    engine.begin_game(state)
    _pass_discussion(engine, state)
    assert state.phase is GamePhase.NIGHT_ACTION
    assert state.round == 1
    expected = {
        player.player_id for player in state.alive_players
        if player.role in {PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR}
    }

    _resolve_heuristic_night(engine, state)

    submitted = [op.actor_id for op in state.operations if op.command == "SUBMIT_NIGHT_ACTION"]
    assert len(submitted) == len(expected)
    assert set(submitted) == expected
    assert state.phase is not GamePhase.NIGHT_ACTION


@pytest.mark.parametrize("player_count", [6, 8])
def test_b9_revote_harness_keeps_candidates_and_submitted_vote_on_resume(player_count: int) -> None:
    """동률 replay와 메모리 저장·재개 뒤에도 후보와 첫 제출이 변하지 않는다.

    이 테스트의 복원은 엔진 상태 복사이며 PostgreSQL snapshot 복구를 대신하지 않는다.
    """

    seed = f"b9-revote-resume:{player_count}"
    state = GameEngine.new_game(_players(player_count, seed), seed=seed)
    state.phase = GamePhase.DAY_VOTE
    state.round = 1
    initial = deepcopy(state)
    engine = GameEngine()
    candidates = {player.player_id for player in state.players[:2]}
    for index, actor in enumerate(state.alive_players):
        engine.submit_vote(state, actor.player_id, state.players[1 - index % 2].player_id)
    engine.resolve_vote(state)
    assert state.phase is GamePhase.REVOTE
    assert state.revote_candidates == candidates
    replayed = GameEngine.replay(initial, state.operations)
    assert replayed.revote_candidates == candidates
    assert replayed.phase is GamePhase.REVOTE

    actor, target = state.players[:2]
    engine.submit_vote(state, actor.player_id, target.player_id)
    submitted = dict(state.votes)
    engine.save(state, remaining_ms=12_000)
    restored = deepcopy(state)
    now = datetime(2026, 9, 7, tzinfo=UTC)
    engine.resume(restored, now=now)
    assert restored.deadline_at == now + timedelta(seconds=12)
    assert restored.revote_candidates == candidates
    assert restored.votes == submitted
    operation_start = len(restored.operations) - 3

    _resolve_heuristic_vote(engine, restored)

    votes = [op for op in restored.operations[operation_start:] if op.command == "SUBMIT_VOTE"]
    assert len(votes) == player_count
    assert len({op.actor_id for op in votes}) == player_count
    assert all(op.target_id in candidates and op.target_id != op.actor_id for op in votes)
    assert next(op.target_id for op in votes if op.actor_id == actor.player_id) == target.player_id


@pytest.mark.parametrize("player_count", [6, 7, 8, 9])
def test_b9_final_harness_uses_every_vote_and_replays_result(player_count: int) -> None:
    """최종 결과는 전원 유효 표의 최다 득표 후보이며 같은 기록을 replay해도 같다."""

    seed = f"b9-final-votes:{player_count}"
    state = GameEngine.new_game(_players(player_count, seed), seed=seed)
    state.phase = GamePhase.FINAL_ACCUSATION
    state.round = 5
    initial = deepcopy(state)

    _resolve_heuristic_vote(GameEngine(), state)

    assert state.status is GameStatus.COMPLETED
    assert set(state.votes) == {player.player_id for player in state.alive_players}
    assert all(vote.actor_id != vote.target_id for vote in state.votes.values())
    counts = Counter(vote.target_id for vote in state.votes.values())
    assert counts[state.final_accusation_target] == max(counts.values())
    target = state.player_by_id[state.final_accusation_target]
    assert state.winner.value == ("CITIZEN" if target.role is PlayerRole.MAFIA else "MAFIA")
    assert _signature(GameEngine.replay(initial, state.operations)) == _signature(state)


class BrokenRedis:
    """Redis 연결 장애를 재현하는 최소 대역."""

    def set(self, *args, **kwargs):
        raise ConnectionError("synthetic redis outage")


def test_b9_redis_lock_failure_does_not_claim_lock() -> None:
    """Redis 장애 때 성공한 lock처럼 진행하지 않는지 확인한다."""

    with pytest.raises(ConnectionError):
        RedisGameLock(BrokenRedis()).acquire(str(uuid4()))


class RollbackConnection:
    """DB 예외가 발생하면 transaction context가 rollback되는 대역."""

    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


def test_b9_db_failure_rolls_back_transaction() -> None:
    """DB 작업 중 오류가 나면 일부 상태를 commit하지 않는지 확인한다."""

    connection = RollbackConnection()
    manager = TransactionManager("postgresql://synthetic", connection_factory=lambda _: connection)
    with pytest.raises(RuntimeError):
        with manager.transaction():
            raise RuntimeError("synthetic database outage")
    assert connection.rolled_back
    assert not connection.committed


class FakeTransaction:
    """publisher가 여는 transaction context를 재현한다."""

    def __init__(self, cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.cursor_value


class FakeCursorContext:
    """cursor context가 필요한 publisher 경계를 제공한다."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeTransactionManager:
    """호출마다 같은 synthetic cursor를 반환한다."""

    def __init__(self):
        self.cursor_value = FakeCursorContext()

    def transaction(self):
        return FakeTransaction(self.cursor_value)


class FakeOutbox:
    """Redis publish 실패 후 failed 상태 기록을 확인하는 대역."""

    def __init__(self):
        self.failed: list[tuple[int, str]] = []

    def claim_available(self, cursor, limit=50):
        return [{"id": 7, "game_event_id": EVENT_ID}]

    def mark_failed(self, cursor, outbox_id, error_code):
        self.failed.append((outbox_id, error_code))


class FakeEvents:
    """commit된 공개 event pointer만 publisher에 제공한다."""

    def get_by_id(self, cursor, event_id):
        return {"id": event_id, "game_id": GAME_ID, "front_sequence": 1}


class BrokenStream:
    """fan-out만 실패시키고 DB event는 건드리지 않는다."""

    def publish_batch(self, *args, **kwargs):
        raise ConnectionError("synthetic redis publish outage")


GAME_ID = uuid4()
EVENT_ID = uuid4()


def test_b9_outbox_records_redis_failure_for_retry() -> None:
    """Redis publish 실패가 event 삭제가 아닌 재처리 상태로 남는지 확인한다."""

    outbox = FakeOutbox()
    publisher = PostgresOutboxPublisher(
        FakeTransactionManager(),
        BrokenStream(),
        outbox_repository=outbox,
        event_repository=FakeEvents(),
    )
    assert publisher.publish_once() == 0
    assert outbox.failed == [(7, "REDIS_PUBLISH_FAILED")]


class FakeAgentRepository:
    """LLM·MCP 실패 뒤 job terminal 기록을 확인하는 대역."""

    def __init__(self):
        self.completed: list[str] = []
        self.revoked = False

    def reserve_job(self, **kwargs):
        now = kwargs["now"]
        return AgentReservation(
            job_id=uuid4(),
            game_id=kwargs["game_id"],
            player_id=kwargs["player_id"],
            window_id=kwargs["window_id"],
            job_kind=kwargs["job_kind"],
            state_version=kwargs["state_version"],
            lease_token=uuid4(),
            lease_expires_at=now + timedelta(seconds=15),
        )

    def issue_capability(self, reservation, **kwargs):
        return CapabilityGrant(
            "synthetic-capability", "a" * 64, kwargs["now"] + timedelta(seconds=15)
        )

    def complete_job(self, reservation, *, status, **kwargs):
        self.completed.append(status)
        return True

    def revoke_capability(self, *args, **kwargs):
        self.revoked = True


class BrokenContext:
    """MCP context 조회 장애를 재현한다."""

    async def get_context(self, **kwargs):
        raise ConnectionError("synthetic mcp outage")

    async def close(self):
        return None


class HealthyContext:
    """Provider timeout만 분리해서 확인할 수 있는 MCP 대역."""

    async def get_context(self, **kwargs):
        return {"data": {"valid_targets": []}}

    async def close(self):
        return None


class BrokenProvider:
    """MCP를 통과한 뒤 Provider 장애를 재현할 때 사용할 대역."""

    async def generate(self, request):
        raise TimeoutError("synthetic provider timeout")


@pytest.mark.asyncio
async def test_b9_mcp_failure_uses_fallback_and_completes_job() -> None:
    """MCP 조회 실패를 외부 오류로 전파하지 않고 fallback terminal로 남긴다."""

    repository = FakeAgentRepository()
    orchestrator = AgentOrchestrator(
        repository,
        BrokenProvider(),
        BrokenContext(),
        clock=lambda: datetime.now(UTC),
    )
    result = await orchestrator.run(
        AgentJobSpec(
            game_id=GAME_ID,
            player_id=uuid4(),
            window_id=uuid4(),
            job_kind="SPEECH",
            phase="DAY_DISCUSSION",
            state_version=1,
        )
    )
    assert result.status == "FALLBACK"
    assert result.proposal is not None
    assert result.proposal.type == "PASS"
    assert repository.completed == ["FALLBACK"]
    assert repository.revoked


@pytest.mark.asyncio
async def test_b9_provider_timeout_uses_fallback_and_completes_job() -> None:
    """LLM timeout도 자동 provider 전환 없이 규칙 fallback으로 끝낸다."""

    repository = FakeAgentRepository()
    orchestrator = AgentOrchestrator(
        repository,
        BrokenProvider(),
        HealthyContext(),
        clock=lambda: datetime.now(UTC),
    )
    result = await orchestrator.run(
        AgentJobSpec(
            game_id=GAME_ID,
            player_id=uuid4(),
            window_id=uuid4(),
            job_kind="SPEECH",
            phase="DAY_DISCUSSION",
            state_version=1,
        )
    )
    assert result.status == "FALLBACK"
    assert result.failure_code == "PROVIDER_TIMEOUT"
    assert result.proposal is not None
    assert result.proposal.type == "PASS"
    assert repository.completed == ["FALLBACK"]
    assert repository.revoked
