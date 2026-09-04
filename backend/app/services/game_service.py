"""B5 공개 게임 API의 유스케이스와 테스트용 저장소.

현재 B5에서는 HTTP 계약과 규칙 엔진 연결을 먼저 닫는다. 저장소를 생성자에
주입하는 구조를 사용해 외부 DB가 없는 계약 테스트도 가능하게 했고, 다음
단계에서 같은 메서드 계약을 PostgreSQL repository로 교체할 수 있다. 게임
규칙의 최종 판단은 항상 ``GameEngine``에 위임한다.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from backend.app.agent.game_engine import GameEngine, RuleViolation
from backend.app.agent.rng import DeterministicRng
from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import TransactionManager, lock_idempotency
from backend.app.models.enums import GamePhase, GameStatus, NightActionType, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState
from backend.app.repositories.agent_repository import PostgresAgentRepository
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.repositories.game_repository import GameStateKeyring, PostgresGameRepository
from backend.app.repositories.outbox_repository import PostgresOutboxRepository
from backend.app.repositories.player_repository import (
    PlayerInsert,
    PostgresPlayerRepository,
    ScenarioFactInsert,
)
from backend.app.repositories.receipt_repository import PostgresReceiptRepository
from backend.app.repositories.scenario_repository import PostgresScenarioRepository
from backend.app.repositories.user_repository import PostgresUserRepository
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import CreateGameRequest

INTRO_MESSAGE = (
    "사건이 발생한 뒤, 현장에 있던 사람들은 범인을 찾기 위해 서로를 추궁하기 시작했습니다. "
    "그러나 범인은 자신의 정체가 드러나는 것을 막기 위해 밤마다 다른 플레이어를 제거하려 합니다."
)


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "BLACKOUT_STUDIO",
        "title": "정전된 방송국",
        "background": "생방송 준비 중 정전된 방송국에서 PD가 사망했다.",
        "victim": "생방송 PD",
        "locations": ["스튜디오", "조정실", "분장실", "대기실", "장비실"],
    },
    {
        "scenario_id": "SNOWBOUND_LODGE",
        "title": "눈 내리는 산장",
        "background": "폭설로 고립된 산장에서 관리인이 약병 사건으로 사망했다.",
        "victim": "산장 관리인",
        "locations": ["거실", "주방", "복도", "관리인 방", "창고"],
    },
    {
        "scenario_id": "CLOSING_MUSEUM",
        "title": "폐관 직전의 박물관",
        "background": "폐관 직전 박물관에서 전시 담당자가 사망했다.",
        "victim": "전시 담당자",
        "locations": ["중앙 전시장", "보안실", "안내 데스크", "복원실", "직원 휴게실"],
    },
    {
        "scenario_id": "LAST_BANQUET_GUEST",
        "title": "호텔 만찬의 마지막 손님",
        "background": "비공개 호텔 만찬 도중 주최자가 사망했다.",
        "victim": "만찬 주최자",
        "locations": ["연회장", "주방", "로비", "복도", "VIP룸"],
    },
    {
        "scenario_id": "STOPPED_NIGHT_TRAIN",
        "title": "멈춰 선 야간열차",
        "background": "열차가 터널에 멈춘 사이 승무원이 사망했다.",
        "victim": "열차 승무원",
        "locations": ["승무원실", "객차", "식당칸", "연결 통로", "화물칸"],
    },
)


def _create_game_result(state: GameState) -> dict[str, Any]:
    """게임 생성과 replay가 공유할 최소 불변 응답을 만든다.

    snapshot 전체나 seed는 receipt에 넣지 않는다. 같은 Idempotency-Key 재시도는
    이 작은 결과만 재사용하고 실제 화면 상태는 snapshot URL에서 다시 읽는다.
    """

    return {
        "game_id": str(state.game_id),
        "status": state.status.value,
        "phase": state.phase.value,
        "round": state.round,
        "state_version": state.state_version,
        "snapshot_url": f"/api/v1/games/{state.game_id}",
    }


class UserWriteService(Protocol):
    """최초 쓰기에서만 사용자 행을 준비하는 최소 계약."""

    def ensure_user(self, user_id: UUID) -> object: ...


@dataclass
class CanonicalGameRecord:
    """API가 사용할 현재 규칙 상태와 공개 sync 기록."""

    state: GameState
    scenario: dict[str, Any]
    human_player_id: UUID
    owner_user_id: UUID
    alibi: str
    observation: str
    front_sequence: int = 0
    operations: list[dict[str, Any]] = field(default_factory=list)
    public_events: list[dict[str, Any]] = field(default_factory=list)
    eliminated: dict[UUID, tuple[str, int]] = field(default_factory=dict)


class InMemoryGameRepository:
    """계약 테스트와 로컬 학습용으로 사용하는 교체 가능한 저장소.

    실제 서비스에서는 이 인터페이스를 PostgreSQL transaction repository로
    교체한다. router와 service는 내부 dict에 직접 접근하지 않는다.
    """

    def __init__(self) -> None:
        self.games: dict[UUID, CanonicalGameRecord] = {}
        self.game_receipts: dict[tuple[UUID, UUID], tuple[str, dict[str, Any]]] = {}
        self.feedback: dict[UUID, dict[str, Any]] = {}
        self.feedback_game_keys: set[tuple[UUID, UUID]] = set()


class PostgresGameCreationService:
    """새 게임에 필요한 모든 DB 행을 하나의 transaction으로 만드는 서비스.

    이 클래스는 아직 공개 router의 기본 구현을 바꾸지 않는다. 생성된 게임을 DB에서
    snapshot으로 복원하는 read adapter가 연결되기 전까지는 메모리 API와 섞이면 안 되기
    때문이다. 단, 이 클래스의 create는 실제 전환 때 그대로 사용할 완전한 원자 단위다.
    """

    ROUTE_SCOPE = "POST /api/v1/games"
    AGENT_CONFIG_VERSION = "agent-config-v1"

    def __init__(
        self,
        *,
        transactions: TransactionManager,
        keyring: GameStateKeyring,
        users: PostgresUserRepository | None = None,
        games: PostgresGameRepository | None = None,
        scenarios: PostgresScenarioRepository | None = None,
        players: PostgresPlayerRepository | None = None,
        agents: PostgresAgentRepository | None = None,
        events: PostgresEventRepository | None = None,
        outbox: PostgresOutboxRepository | None = None,
        receipts: PostgresReceiptRepository | None = None,
    ) -> None:
        """각 테이블 저장소를 주입해 테스트가 실제 DB 없이도 흐르게 한다."""

        self._transactions = transactions
        self._keyring = keyring
        self._users = users or PostgresUserRepository("")
        self._games = games or PostgresGameRepository()
        self._scenarios = scenarios or PostgresScenarioRepository()
        self._players = players or PostgresPlayerRepository()
        self._agents = agents or PostgresAgentRepository()
        self._events = events or PostgresEventRepository(self._games)
        self._outbox = outbox or PostgresOutboxRepository()
        self._receipts = receipts or PostgresReceiptRepository()

    def create(
        self,
        owner_user_id: UUID,
        payload: CreateGameRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """사용자부터 receipt까지 모두 성공했을 때만 새 게임을 확정한다."""

        request_hash = _request_hash(payload.model_dump(mode="json"))
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    # 같은 key 재전송과 같은 사용자의 동시 게임 생성을 각각 직렬화한다.
                    lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                    lock_idempotency(cursor, "GAME_CREATE", owner_user_id)
                    replay = self._find_replay(
                        cursor,
                        owner_user_id=owner_user_id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                    )
                    if replay is not None:
                        return replay, True

                    self._users.ensure_user_in_transaction(cursor, owner_user_id)
                    state, scenario, player_rows, fact_rows = self._build_initial_game(
                        cursor,
                        owner_user_id=owner_user_id,
                        payload=payload,
                    )
                    encrypted_seed = self._keyring.encrypt_seed(state.seed)
                    self._games.insert_initial_game(
                        cursor,
                        state=state,
                        owner_user_id=owner_user_id,
                        scenario_version=payload.scenario_version,
                        scenario_id=str(scenario["id"]),
                        scenario_content_hash=str(scenario["content_hash"]),
                        encrypted_seed=encrypted_seed,
                        agent_config_version=self.AGENT_CONFIG_VERSION,
                    )
                    self._players.insert_players(cursor, game_id=state.game_id, players=player_rows)
                    self._players.insert_facts(cursor, game_id=state.game_id, facts=fact_rows)
                    event = self._events.append(
                        cursor,
                        game_id=state.game_id,
                        state_version=state.state_version,
                        event_type="GAME_CREATED",
                        audience="PUBLIC",
                        payload={
                            "game_id": str(state.game_id),
                            "status": state.status.value,
                            "phase": state.phase.value,
                            "state_version": state.state_version,
                        },
                    )
                    self._outbox.enqueue(cursor, UUID(str(event["id"])))
                    result = _create_game_result(state)
                    self._receipts.insert(
                        cursor,
                        principal_type="USER",
                        principal_id=owner_user_id,
                        idempotency_key=idempotency_key,
                        route_scope=self.ROUTE_SCOPE,
                        game_id=state.game_id,
                        request_hash=request_hash,
                        result_state_version=state.state_version,
                        http_status=201,
                        result_body=result,
                    )
                    return result, False
        except ApiError:
            raise
        except Exception as exc:
            # DB/키 파일 오류 원문에는 접속 정보나 경로가 포함될 수 있다. 공개 API에는
            # 고정 메시지만 반환하고, transaction context가 모든 중간 INSERT를 rollback한다.
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="게임 저장소를 사용할 수 없습니다.",
                retryable=True,
            ) from exc

    def _find_replay(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        idempotency_key: UUID,
        request_hash: str,
    ) -> dict[str, Any] | None:
        """동일 idempotency key의 불변 결과만 재사용한다."""

        previous = self._receipts.find(
            cursor,
            principal_type="USER",
            principal_id=owner_user_id,
            idempotency_key=idempotency_key,
        )
        if previous is None:
            return None
        if (
            previous["request_hash"] != request_hash
            or previous["route_scope"] != self.ROUTE_SCOPE
        ):
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_KEY_REUSED",
                message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
            )
        result_body = previous["result_body"]
        if not isinstance(result_body, dict):
            raise RuntimeError("Stored game creation receipt is invalid")
        return copy.deepcopy(result_body)

    def _build_initial_game(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        payload: CreateGameRequest,
    ) -> tuple[GameState, Mapping[str, Any], list[PlayerInsert], list[ScenarioFactInsert]]:
        """seed로 시나리오·역할·persona·개인 단서를 확정해 DB 입력으로 바꾼다."""

        human_player_id = uuid4()
        state = GameEngine.new_game(
            [(human_player_id, PlayerKind.HUMAN)]
            + [(uuid4(), PlayerKind.AI) for _ in range(payload.player_count - 1)],
            game_id=uuid4(),
        )
        for player in state.players:
            player.display_name = f"플레이어 {player.seat}"

        candidates = self._scenarios.list_active(
            cursor,
            scenario_version=payload.scenario_version,
        )
        last_scenario_id = self._scenarios.last_created_scenario_id(
            cursor,
            owner_user_id=owner_user_id,
            scenario_version=payload.scenario_version,
        )
        eligible = [item for item in candidates if item["id"] != last_scenario_id]
        if not eligible:
            eligible = candidates
        if not eligible:
            raise RuntimeError("No active scenario is available")
        rng = DeterministicRng(state.seed)
        scenario = rng.choice(eligible, "scenario-selection")

        personas = self._agents.list_active_personas(
            cursor,
            version=self.AGENT_CONFIG_VERSION,
        )
        if not personas:
            raise RuntimeError("No active persona is available")
        ordered_personas = rng.shuffle(personas, "persona-assignment")
        templates = self._scenarios.list_active_templates(cursor, scenario_id=str(scenario["id"]))
        alibis = [item for item in templates if item["template_kind"] == "ALIBI"]
        observations = [item for item in templates if item["template_kind"] == "OBSERVATION"]
        if len(alibis) < payload.player_count or len(observations) < payload.player_count:
            raise RuntimeError("Scenario templates are insufficient")
        selected_alibis = rng.shuffle(alibis, "alibi-template")[: payload.player_count]
        selected_observations = rng.shuffle(observations, "observation-template")[: payload.player_count]

        player_rows: list[PlayerInsert] = []
        fact_rows: list[ScenarioFactInsert] = []
        for index, player in enumerate(state.players):
            persona_id = None
            if player.kind is PlayerKind.AI:
                persona_id = str(ordered_personas[(player.seat - 2) % len(ordered_personas)]["id"])
            player_rows.append(
                PlayerInsert(
                    player_id=player.player_id,
                    user_id=owner_user_id if player.kind is PlayerKind.HUMAN else None,
                    kind=player.kind.value,
                    seat=player.seat,
                    display_name=player.display_name,
                    role=player.role.value,
                    faction=player.faction.value,
                    persona_id=persona_id,
                )
            )
            fact_rows.append(
                self._fact_from_template(
                    player_id=player.player_id,
                    fact_kind="ALIBI",
                    template=selected_alibis[index],
                    seat=player.seat,
                    subject_player_id=None,
                )
            )
            observation_template = selected_observations[index]
            subject_player_id = None
            if observation_template["subject_mode"] == "SEAT":
                subject_candidates = [
                    candidate.player_id
                    for candidate in state.players
                    if candidate.player_id != player.player_id
                ]
                subject_player_id = rng.choice(
                    subject_candidates,
                    f"observation-subject:{player.player_id}",
                )
            fact_rows.append(
                self._fact_from_template(
                    player_id=player.player_id,
                    fact_kind="OBSERVATION",
                    template=observation_template,
                    seat=player.seat,
                    subject_player_id=subject_player_id,
                )
            )
        return state, scenario, player_rows, fact_rows

    @staticmethod
    def _fact_from_template(
        *,
        player_id: UUID,
        fact_kind: str,
        template: Mapping[str, Any],
        seat: int,
        subject_player_id: UUID | None,
    ) -> ScenarioFactInsert:
        """정적 문장에는 좌석만 넣고 역할·진영은 절대 template에 넣지 않는다."""

        rendered_text = str(template["text_template"]).replace("{{seat}}", str(seat))
        return ScenarioFactInsert(
            fact_id=uuid4(),
            player_id=player_id,
            fact_kind=fact_kind,
            template_id=UUID(str(template["id"])),
            rendered_text=rendered_text,
            subject_player_id=subject_player_id,
        )


class CanonicalGameService:
    """게임 생성부터 command·sync·feedback까지의 공개 API 흐름을 조정한다."""

    def __init__(
        self,
        repository: InMemoryGameRepository | None = None,
        *,
        user_service: UserWriteService | None = None,
    ) -> None:
        self.repository = repository or InMemoryGameRepository()
        self.user_service = user_service

    def create(
        self,
        owner_user_id: UUID,
        payload: CreateGameRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """사용자·게임을 만들고 ROLE_REVEAL 시작 정보를 반환한다."""

        request_hash = _request_hash(payload.model_dump(mode="json"))
        receipt_key = (owner_user_id, idempotency_key)
        previous = self.repository.game_receipts.get(receipt_key)
        if previous is not None:
            old_hash, old_result = previous
            if old_hash != request_hash:
                raise ApiError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
                )
            return copy.deepcopy(old_result), True

        # games.owner_user_id는 users.id를 참조한다. 따라서 게임을 만들기 전에
        # 사용자 UUID를 먼저 준비해야 이후 PostgreSQL 게임 INSERT가 FK 오류 없이
        # 동작한다. 같은 UUID를 여러 번 보내도 users 행은 하나만 유지된다.
        self._ensure_write_user(owner_user_id)

        scenario = self._next_scenario(owner_user_id)
        human_id = uuid4()
        players = [(human_id, PlayerKind.HUMAN)] + [
            (uuid4(), PlayerKind.AI) for _ in range(payload.player_count - 1)
        ]
        state = GameEngine.new_game(players, game_id=uuid4())
        for player in state.players:
            player.display_name = f"플레이어 {player.seat}"
        record = CanonicalGameRecord(
            state=state,
            scenario=copy.deepcopy(scenario),
            human_player_id=human_id,
            owner_user_id=owner_user_id,
            alibi=f"좌석 1은 {scenario['locations'][0]}에서 상황을 확인하고 있었다.",
            observation=f"좌석 1은 {scenario['locations'][1]} 방향으로 이동하는 사람을 봤다.",
        )
        self.repository.games[state.game_id] = record
        result = {
            "game_id": str(state.game_id),
            "status": state.status.value,
            "phase": state.phase.value,
            "round": state.round,
            "state_version": state.state_version,
            "snapshot_url": f"/api/v1/games/{state.game_id}",
        }
        self.repository.game_receipts[receipt_key] = (request_hash, copy.deepcopy(result))
        return result, False

    def list_games(
        self,
        owner_user_id: UUID,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """현재 사용자 소유 게임만 최신 변경 순서로 반환한다."""

        records = [
            record
            for record in self.repository.games.values()
            if record.owner_user_id == owner_user_id
            and (status is None or record.state.status.value == status)
        ]
        records.sort(key=lambda item: item.state.updated_at, reverse=True)
        return [self._list_item(record) for record in records[:limit]]

    def snapshot(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """소유자에게만 공개 snapshot과 인간 본인 정보를 반환한다."""

        record = self._owned(owner_user_id, game_id)
        return self._snapshot(record)

    def command(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """version·소유권을 확인하고 엔진 command를 한 번만 적용한다."""

        record = self._owned(owner_user_id, game_id)
        request_hash = _request_hash(payload.model_dump(mode="json"))
        receipt_key = (owner_user_id, idempotency_key)
        previous = self.repository.game_receipts.get(receipt_key)
        if previous is not None:
            old_hash, old_result = previous
            if old_hash != request_hash:
                raise ApiError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
                )
            return copy.deepcopy(old_result), True

        state = record.state
        accepted_version = state.state_version
        if payload.expected_state_version != accepted_version:
            raise ApiError(
                status_code=409,
                code="STALE_STATE_VERSION",
                message="게임 상태가 변경되었습니다. 최신 상태를 다시 확인하세요.",
                details={"current_state_version": accepted_version},
            )
        self._validate_command(record, payload)
        before_alive = {player.player_id: player.alive for player in state.players}
        try:
            self._apply_engine_command(record, payload)
        except RuleViolation as exc:
            raise self._rule_error(exc) from exc
        self._record_eliminations(record, before_alive)
        if state.state_version != accepted_version:
            self._append_sync_batch(record, payload.type, accepted_version)
        result = {
            "command_id": str(idempotency_key),
            "command_type": payload.type,
            "accepted_state_version": accepted_version,
            "result_state_version": state.state_version,
            "sync_url": f"/api/v1/games/{game_id}/sync",
        }
        self.repository.game_receipts[receipt_key] = (request_hash, copy.deepcopy(result))
        return result, False

    def sync(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        *,
        after_state_version: int,
        after_sequence: int,
    ) -> dict[str, Any]:
        """완전한 operation batch만 반환하고 필요하면 snapshot으로 대체한다."""

        record = self._owned(owner_user_id, game_id)
        state = record.state
        if after_state_version > state.state_version or after_sequence > record.front_sequence:
            return {
                "game_id": str(game_id),
                "mode": "SNAPSHOT",
                "from_state_version": after_state_version,
                "state_version": state.state_version,
                "last_sequence": record.front_sequence,
                "operations": [],
                "snapshot": self._snapshot(record),
            }
        operations = [
            copy.deepcopy(batch)
            for batch in record.operations
            if batch["front_sequence"] > after_sequence
        ]
        return {
            "game_id": str(game_id),
            "mode": "DELTA",
            "from_state_version": after_state_version,
            "state_version": state.state_version if operations else after_state_version,
            "last_sequence": record.front_sequence if operations else after_sequence,
            "operations": operations,
            "snapshot": None,
        }

    def feedback(
        self,
        owner_user_id: UUID,
        payload: FeedbackRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """feedback를 게임 상태와 분리해 한 번만 저장한다."""

        request_hash = _request_hash(payload.model_dump(mode="json"))
        receipt_key = (owner_user_id, idempotency_key)
        previous = self.repository.game_receipts.get(receipt_key)
        if previous is not None:
            old_hash, old_result = previous
            if old_hash != request_hash:
                raise ApiError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
                )
            return copy.deepcopy(old_result), True

        # GENERAL feedback은 연결된 game이 없어도 최초 쓰기가 될 수 있다. 이 경우에도
        # feedback.user_id FK가 안전하게 연결되도록 사용자 행부터 멱등 생성한다.
        self._ensure_write_user(owner_user_id)
        if payload.feedback_type == "GAME":
            assert payload.game_id is not None
            record = self._owned(owner_user_id, payload.game_id)
            if record.state.status is not GameStatus.COMPLETED:
                raise ApiError(
                    status_code=409,
                    code="FEEDBACK_GAME_NOT_COMPLETED",
                    message="종료된 게임에만 게임별 의견을 남길 수 있습니다.",
                )
            unique_key = (owner_user_id, payload.game_id)
            if unique_key in self.repository.feedback_game_keys:
                raise ApiError(
                    status_code=409,
                    code="FEEDBACK_ALREADY_SUBMITTED",
                    message="이 게임에는 이미 게임별 의견을 남겼습니다.",
                )
            self.repository.feedback_game_keys.add(unique_key)
        feedback_id = uuid4()
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        result = {
            "feedback_id": str(feedback_id),
            "feedback_type": payload.feedback_type,
            "created_at": created_at,
        }
        self.repository.feedback[feedback_id] = {
            **result,
            "user_id": str(owner_user_id),
            "game_id": str(payload.game_id) if payload.game_id else None,
            "rating": payload.rating,
            "comment": payload.comment,
            "tags": payload.tags,
        }
        self.repository.game_receipts[receipt_key] = (request_hash, copy.deepcopy(result))
        return result, False

    def _ensure_write_user(self, user_id: UUID) -> None:
        """최초 쓰기에 필요한 사용자 행을 준비하고 DB 오류는 안전하게 감춘다.

        조회 요청에서는 이 함수를 호출하지 않는다. 따라서 임의 UUID로 목록이나 게임을
        조회하는 것만으로 users 행이 생성되지 않는다. 실제 DB 오류 원문에는 접속 정보가
        포함될 수 있으므로 공개 API에는 고정 오류만 반환한다.
        """

        if self.user_service is None:
            # 외부 DB를 사용하지 않는 순수 계약 테스트에서는 user service를 생략할 수
            # 있다. 운영 조립 코드는 항상 PostgreSQL user service를 전달한다.
            return
        try:
            self.user_service.ensure_user(user_id)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="사용자 저장소를 사용할 수 없습니다.",
                retryable=True,
            ) from exc

    def _next_scenario(self, owner_user_id: UUID) -> dict[str, Any]:
        """같은 사용자의 직전 scenario를 우선 피한다."""

        used = [
            record.scenario["scenario_id"]
            for record in self.repository.games.values()
            if record.owner_user_id == owner_user_id
        ]
        for scenario in SCENARIOS:
            if scenario["scenario_id"] not in used:
                return copy.deepcopy(scenario)
        return copy.deepcopy(SCENARIOS[len(used) % len(SCENARIOS)])

    def _owned(self, owner_user_id: UUID, game_id: UUID) -> CanonicalGameRecord:
        """존재하지 않는 게임과 타인 게임을 같은 404로 숨긴다."""

        record = self.repository.games.get(game_id)
        if record is None or record.owner_user_id != owner_user_id:
            raise ApiError(
                status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다."
            )
        return record

    def _validate_command(self, record: CanonicalGameRecord, payload: GameCommandRequest) -> None:
        """문법을 넘어 현재 phase·인간 역할·생존 상태를 확인한다."""

        state = record.state
        if state.status is GameStatus.COMPLETED or state.status is GameStatus.FAILED:
            raise ApiError(
                status_code=409,
                code="ACTION_NOT_ALLOWED",
                message="종료된 게임은 변경할 수 없습니다.",
            )
        human = state.player_by_id[record.human_player_id]
        if (
            payload.type in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}
            and not human.alive
        ):
            raise ApiError(
                status_code=409,
                code="PLAYER_DEAD",
                message="사망한 플레이어는 이 행동을 할 수 없습니다.",
            )
        if (
            payload.type in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}
            and payload.window_id is None
        ):
            raise ApiError(
                status_code=422,
                code="INVALID_REQUEST",
                message="현재 행동에는 window_id가 필요합니다.",
            )
        if payload.type in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
            current_window = self._action_window(record, self._legal_actions(record))
            if current_window is None or str(payload.window_id) != current_window["window_id"]:
                raise ApiError(
                    status_code=409,
                    code="WINDOW_CLOSED",
                    message="현재 행동 window가 더 이상 유효하지 않습니다.",
                )
        if payload.type in {"SPEAK", "PASS"} and (
            state.phase is not GamePhase.DAY_DISCUSSION
            or record.human_player_id in state.speech_actors
        ):
            raise ApiError(
                status_code=409, code="ACTION_NOT_ALLOWED", message="현재 발언 차례가 아닙니다."
            )
        if payload.type == "SPEAK" and payload.message is None:
            raise ApiError(
                status_code=422, code="INVALID_REQUEST", message="SPEAK에는 message가 필요합니다."
            )
        if payload.type == "PASS" and payload.message is not None:
            raise ApiError(
                status_code=422,
                code="INVALID_REQUEST",
                message="PASS에는 message를 보낼 수 없습니다.",
            )
        if payload.type == "SUBMIT_NIGHT_ACTION":
            if state.phase is not GamePhase.NIGHT_ACTION or human.role is PlayerRole.CITIZEN:
                raise ApiError(
                    status_code=409,
                    code="ACTION_NOT_ALLOWED",
                    message="현재 밤 행동을 할 수 없습니다.",
                )
            if record.human_player_id in state.night_actions:
                raise ApiError(
                    status_code=409,
                    code="ACTION_ALREADY_SUBMITTED",
                    message="이미 밤 행동을 제출했습니다.",
                )
            if payload.target_player_id is None:
                raise ApiError(
                    status_code=422, code="INVALID_REQUEST", message="대상을 선택해야 합니다."
                )
        if payload.type == "SUBMIT_VOTE":
            if state.phase not in {
                GamePhase.DAY_VOTE,
                GamePhase.REVOTE,
                GamePhase.FINAL_ACCUSATION,
            }:
                raise ApiError(
                    status_code=409, code="INVALID_PHASE", message="현재 투표 단계가 아닙니다."
                )
            if record.human_player_id in state.votes or payload.target_player_id is None:
                raise ApiError(
                    status_code=409 if record.human_player_id in state.votes else 422,
                    code="ACTION_ALREADY_SUBMITTED"
                    if record.human_player_id in state.votes
                    else "INVALID_REQUEST",
                    message="투표를 제출할 수 없습니다.",
                )
        if payload.type == "RESUME" and state.status is not GameStatus.SAVED:
            raise ApiError(
                status_code=409,
                code="ACTION_NOT_ALLOWED",
                message="저장된 게임만 재개할 수 있습니다.",
            )
        if payload.type == "FAST_FORWARD" and human.alive:
            raise ApiError(
                status_code=409,
                code="ACTION_NOT_ALLOWED",
                message="인간 플레이어가 살아 있어 빠른 진행을 할 수 없습니다.",
            )
        if payload.type == "SAVE_AND_EXIT" and state.status is not GameStatus.IN_PROGRESS:
            raise ApiError(
                status_code=409,
                code="ACTION_NOT_ALLOWED",
                message="진행 중인 게임만 저장할 수 있습니다.",
            )

    def _apply_engine_command(
        self, record: CanonicalGameRecord, payload: GameCommandRequest
    ) -> None:
        """공개 command를 순수 엔진 호출로 변환하고 AI 차례는 fallback 처리한다."""

        state = record.state
        engine = GameEngine()
        if payload.type == "BEGIN_GAME":
            engine.begin_game(state)
        elif payload.type == "SPEAK":
            engine.speak(state, record.human_player_id, payload.message or "")
            self._auto_pass_ai_speakers(record)
            self._auto_resolve_citizen_night(record)
        elif payload.type == "PASS":
            engine.pass_turn(state, record.human_player_id)
            self._auto_pass_ai_speakers(record)
            self._auto_resolve_citizen_night(record)
        elif payload.type == "SUBMIT_NIGHT_ACTION":
            role_action = {
                PlayerRole.MAFIA: NightActionType.ATTACK,
                PlayerRole.DETECTIVE: NightActionType.INVESTIGATE,
                PlayerRole.DOCTOR: NightActionType.PROTECT,
            }[state.player_by_id[record.human_player_id].role]
            engine.submit_night_action(
                state, record.human_player_id, role_action, payload.target_player_id
            )  # type: ignore[arg-type]
            engine.resolve_night(state, force=True)
            self._auto_pass_ai_speakers(record)
        elif payload.type == "SUBMIT_VOTE":
            if state.phase is GamePhase.FINAL_ACCUSATION:
                engine.submit_final_accusation(
                    state, record.human_player_id, payload.target_player_id
                )  # type: ignore[arg-type]
            else:
                engine.submit_vote(state, record.human_player_id, payload.target_player_id)  # type: ignore[arg-type]
                engine.resolve_vote(state, force=True)
                self._auto_resolve_citizen_night(record)
        elif payload.type == "SAVE_AND_EXIT":
            remaining = (
                30_000
                if state.phase
                in {
                    GamePhase.NIGHT_ACTION,
                    GamePhase.DAY_VOTE,
                    GamePhase.REVOTE,
                    GamePhase.FINAL_ACCUSATION,
                }
                else 0
            )
            engine.save(state, remaining)
        elif payload.type == "RESUME":
            engine.resume(state)
        elif payload.type == "FAST_FORWARD":
            engine.fast_forward(state)

    def _auto_pass_ai_speakers(self, record: CanonicalGameRecord) -> None:
        """대화에서는 AI가 규칙 fallback PASS를 제출해 다음 인간 입력을 연다."""

        state = record.state
        engine = GameEngine()
        if state.phase is not GamePhase.DAY_DISCUSSION:
            return
        for player in state.alive_players:
            if player.kind is PlayerKind.AI and player.player_id not in state.speech_actors:
                engine.pass_turn(state, player.player_id)

    def _auto_resolve_citizen_night(self, record: CanonicalGameRecord) -> None:
        """인간이 시민이면 밤 행동을 기다리지 않고 규칙 자동 처리한다."""

        state = record.state
        human = state.player_by_id[record.human_player_id]
        if (
            state.phase is GamePhase.NIGHT_ACTION
            and human.alive
            and human.role is PlayerRole.CITIZEN
        ):
            GameEngine().resolve_night(state, force=True)
            self._auto_pass_ai_speakers(record)

    def _record_eliminations(
        self, record: CanonicalGameRecord, before_alive: dict[UUID, bool]
    ) -> None:
        """엔진이 바꾼 생존 상태를 공개 snapshot의 탈락 field로 옮긴다."""

        state = record.state
        for player in state.players:
            if before_alive.get(player.player_id, True) and not player.alive:
                record.eliminated[player.player_id] = (state.phase.value, max(state.round, 1))

    def _append_sync_batch(
        self, record: CanonicalGameRecord, command_type: str, accepted_version: int
    ) -> None:
        """한 client-visible command를 하나의 완전한 Front batch로 만든다."""

        record.front_sequence += 1
        sequence = record.front_sequence
        state = record.state
        state_payload = {
            "status": state.status.value,
            "phase": state.phase.value,
            "round": state.round,
            "day_number": state.day_number,
            "state_version": state.state_version,
            "fast_forward_enabled": not state.human_alive,
        }
        event_type, event_data = _event_for_command(record, command_type)
        operations = [
            {
                "schema_version": 1,
                "front_sequence": sequence,
                "operation_index": 0,
                "state_version": state.state_version,
                "type": "SET_GAME_STATE",
                "payload": state_payload,
            }
        ]
        if event_type is not None:
            event = {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "data": event_data,
            }
            record.public_events.append(event)
            operations.append(
                {
                    "schema_version": 1,
                    "front_sequence": sequence,
                    "operation_index": 1,
                    "state_version": state.state_version,
                    "type": "APPEND_PUBLIC_EVENT",
                    "payload": event,
                }
            )
        record.operations.append({"front_sequence": sequence, "operations": operations})

    def _snapshot(self, record: CanonicalGameRecord) -> dict[str, Any]:
        """Front 정본의 public·human private 경계를 지킨다."""

        state = record.state
        players = []
        for player in sorted(state.players, key=lambda item: item.seat):
            eliminated = record.eliminated.get(player.player_id)
            revealed = (
                player.role.value
                if state.status is GameStatus.COMPLETED
                or (
                    not player.alive
                    and eliminated
                    and eliminated[0] in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
                )
                else None
            )
            players.append(
                {
                    "player_id": str(player.player_id),
                    "seat": player.seat,
                    "display_name": player.display_name,
                    "kind": player.kind.value,
                    "alive": player.alive,
                    "revealed_role": revealed,
                    "eliminated_phase": eliminated[0] if eliminated else None,
                    "eliminated_round": eliminated[1] if eliminated else None,
                }
            )
        human = state.player_by_id[record.human_player_id]
        legal = self._legal_actions(record)
        return {
            "game": {
                "game_id": str(state.game_id),
                "status": state.status.value,
                "phase": state.phase.value,
                "round": state.round,
                "day_number": state.day_number,
                "state_version": state.state_version,
                "last_sequence": record.front_sequence,
                "ruleset_version": "mystery-v1",
                "scenario_version": "scenario-v1",
                "player_count": len(state.players),
                "mafia_count": sum(player.role is PlayerRole.MAFIA for player in state.players),
                "fast_forward_enabled": not state.human_alive,
                "updated_at": state.updated_at.isoformat(),
            },
            "scenario": copy.deepcopy(record.scenario),
            "players": players,
            "me": {
                "player_id": str(record.human_player_id),
                "role": human.role.value,
                "alive": human.alive,
                "spectator": not human.alive,
                "alibi": record.alibi,
                "observation": record.observation,
                "private_events": [],
            },
            "action_window": self._action_window(record, legal),
            "legal_actions": legal,
            "public_events": copy.deepcopy(record.public_events),
            "result": self._result(state),
        }

    def _list_item(self, record: CanonicalGameRecord) -> dict[str, Any]:
        state = record.state
        return {
            "game_id": str(state.game_id),
            "status": state.status.value,
            "phase": state.phase.value,
            "round": state.round,
            "day_number": state.day_number,
            "state_version": state.state_version,
            "scenario_title": record.scenario["title"],
            "player_count": len(state.players),
            "human_alive": state.human_alive,
            "winner": state.winner.value if state.winner else None,
            "can_resume": state.status is GameStatus.SAVED,
            "updated_at": state.updated_at.isoformat(),
        }

    def _legal_actions(self, record: CanonicalGameRecord) -> list[str]:
        state = record.state
        human = state.player_by_id[record.human_player_id]
        if state.status is GameStatus.SAVED:
            return ["RESUME"]
        if state.status is not GameStatus.IN_PROGRESS or not human.alive:
            return (
                ["FAST_FORWARD", "SAVE_AND_EXIT"]
                if not human.alive and state.status is GameStatus.IN_PROGRESS
                else []
            )
        if state.phase is GamePhase.ROLE_REVEAL:
            return ["BEGIN_GAME", "SAVE_AND_EXIT"]
        if (
            state.phase is GamePhase.DAY_DISCUSSION
            and record.human_player_id not in state.speech_actors
        ):
            return ["SPEAK", "PASS", "SAVE_AND_EXIT"]
        if (
            state.phase is GamePhase.NIGHT_ACTION
            and human.role is not PlayerRole.CITIZEN
            and record.human_player_id not in state.night_actions
        ):
            return ["SUBMIT_NIGHT_ACTION", "SAVE_AND_EXIT"]
        if (
            state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}
            and record.human_player_id not in state.votes
        ):
            return ["SUBMIT_VOTE", "SAVE_AND_EXIT"]
        return ["SAVE_AND_EXIT"]

    def _action_window(
        self, record: CanonicalGameRecord, legal: list[str]
    ) -> dict[str, Any] | None:
        state = record.state
        kind = {
            GamePhase.DAY_DISCUSSION: "SPEECH",
            GamePhase.NIGHT_ACTION: "NIGHT",
            GamePhase.DAY_VOTE: "VOTE",
            GamePhase.REVOTE: "REVOTE",
            GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
        }.get(state.phase)
        if kind is None or state.status is GameStatus.COMPLETED:
            return None
        timed = kind != "SPEECH"
        return {
            "window_id": str(uuid5_for_window(state.game_id, state.state_version)),
            "kind": kind,
            "cycle": 1,
            "paused": state.status is GameStatus.SAVED,
            "opened_state_version": state.state_version,
            "server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "deadline_at": None
            if not timed or state.status is GameStatus.SAVED
            else (datetime.now(UTC) + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
            "remaining_ms": 30_000 if timed and state.status is GameStatus.IN_PROGRESS else None,
            "turn_player_id": str(record.human_player_id) if kind == "SPEECH" else None,
            "has_submitted": not any(
                action in legal
                for action in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}
            ),
            "legal_actions": legal if state.status is GameStatus.IN_PROGRESS else [],
            "valid_targets": [
                {"player_id": str(player.player_id), "display_name": player.display_name}
                for player in state.alive_players
                if kind != "NIGHT"
                or state.player_by_id[record.human_player_id].role is PlayerRole.DOCTOR
                or player.player_id != record.human_player_id
            ]
            if kind != "SPEECH"
            else [],
        }

    @staticmethod
    def _result(state: GameState) -> dict[str, Any] | None:
        if state.status is not GameStatus.COMPLETED:
            return None
        return {
            "winner": state.winner.value if state.winner else None,
            "win_reason": state.win_reason.value if state.win_reason else None,
            "finished_at": state.updated_at.isoformat(),
            "players": [
                {
                    "player_id": str(player.player_id),
                    "display_name": player.display_name,
                    "role": player.role.value,
                    "alive": player.alive,
                }
                for player in sorted(state.players, key=lambda item: item.seat)
            ],
        }

    @staticmethod
    def _rule_error(error: RuleViolation) -> ApiError:
        """엔진 내부 코드를 공개 API 오류 코드로 변환한다."""

        code_map = {
            "INVALID_PHASE": "INVALID_PHASE",
            "PLAYER_DEAD": "PLAYER_DEAD",
            "TARGET_DEAD": "TARGET_INVALID",
            "SELF_TARGET_INVALID": "TARGET_INVALID",
            "TARGET_INVALID": "TARGET_INVALID",
            "DUPLICATE_ACTION": "ACTION_ALREADY_SUBMITTED",
            "ROLE_ACTION_NOT_ALLOWED": "ACTION_NOT_ALLOWED",
            "ROLE_ACTION_INVALID": "ACTION_NOT_ALLOWED",
            "SPEECH_LENGTH_INVALID": "INVALID_REQUEST",
            "WINDOW_NOT_READY": "WINDOW_NOT_READY",
        }
        code = code_map.get(str(error), "ACTION_NOT_ALLOWED")
        return ApiError(
            status_code=409 if code != "INVALID_REQUEST" else 422,
            code=code,
            message="현재 게임 상태에서 허용되지 않는 행동입니다.",
        )


def _request_hash(value: dict[str, Any]) -> str:
    """receipt 비교용 요청 지문을 안정적으로 계산한다."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def uuid5_for_window(game_id: UUID, state_version: int) -> UUID:
    """window row가 아직 없는 B5 계약 저장소의 결정적 표시용 ID다."""

    from uuid import NAMESPACE_URL, uuid5

    return uuid5(NAMESPACE_URL, f"mafia-window:{game_id}:{state_version}")


def _event_for_command(
    record: CanonicalGameRecord, command_type: str
) -> tuple[str | None, dict[str, Any]]:
    """정본에서 허용한 공개 event만 생성한다."""

    state = record.state
    if command_type == "BEGIN_GAME":
        return "GAME_BEGAN", {"message": INTRO_MESSAGE}
    if command_type == "SPEAK":
        latest = next(
            (
                operation
                for operation in reversed(state.operations)
                if operation.command == "SPEAK" and operation.actor_id == record.human_player_id
            ),
            None,
        )
        return "PLAYER_SPOKE", {
            "player_id": str(record.human_player_id),
            "message": latest.text if latest else "",
        }
    if command_type == "PASS":
        return "PLAYER_PASSED", {"player_id": str(record.human_player_id)}
    if command_type == "FAST_FORWARD":
        return "FAST_FORWARD_ENABLED", {"enabled": True}
    if command_type in {"SAVE_AND_EXIT", "RESUME"}:
        return "GAME_SAVED" if command_type == "SAVE_AND_EXIT" else "GAME_RESUMED", {
            "phase": state.phase.value,
            "round": state.round,
        }
    if state.status is GameStatus.COMPLETED:
        return "GAME_ENDED", {
            "winner": state.winner.value if state.winner else "CITIZEN",
            "win_reason": state.win_reason.value if state.win_reason else "MAFIA_PARITY",
        }
    return None, {}
