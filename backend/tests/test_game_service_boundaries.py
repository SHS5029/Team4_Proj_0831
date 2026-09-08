"""GameService command와 window 조합 경계를 검증한다."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase, GameStatus
from backend.app.services.game.window_service import validate_action_window


class _State:
    """window 검증이 읽는 진행 상태와 phase를 제공하는 최소 게임 상태 대역."""

    def __init__(self, phase: GamePhase) -> None:
        self.phase = phase
        self.status = GameStatus.IN_PROGRESS


class _Payload:
    """window 검증 입력을 단순화한 command 대역."""

    def __init__(self, window_id: object, target_player_id: object) -> None:
        self.window_id = window_id
        self.target_player_id = target_player_id


def test_action_window_validation_accepts_matching_vote_window() -> None:
    """진행 중 게임에서 phase·종류가 맞고 마감 전인 window는 검증을 통과한다."""

    window_id = uuid4()
    now = datetime(2026, 9, 7, tzinfo=UTC)
    validate_action_window(
        _State(GamePhase.DAY_VOTE),
        {
            "id": window_id,
            "status": "OPEN",
            "window_kind": "VOTE",
            "phase": GamePhase.DAY_VOTE.value,
            "deadline_at": now + timedelta(seconds=30),
        },
        _Payload(window_id, uuid4()),  # type: ignore[arg-type]
        now=now,
    )


def test_action_window_validation_rejects_wrong_window_kind() -> None:
    """ID·phase·마감 조건이 유효해도 window 종류만 다르면 공통 오류를 반환한다."""

    window_id = uuid4()
    now = datetime(2026, 9, 7, tzinfo=UTC)
    with pytest.raises(ApiError) as error:
        validate_action_window(
            _State(GamePhase.DAY_VOTE),
            {
                "id": window_id,
                "status": "OPEN",
                "window_kind": "NIGHT",
                "phase": GamePhase.DAY_VOTE.value,
                "deadline_at": now + timedelta(seconds=30),
            },
            _Payload(window_id, uuid4()),  # type: ignore[arg-type]
            now=now,
        )
    assert error.value.status_code == 409
    assert error.value.code == "WINDOW_CLOSED"


@pytest.fixture
def discussion_ledger():
    """합성 SQLite 원장에 실제 복원 SQL을 실행하며 외부 DB에는 연결하지 않는다.

    PostgreSQL의 JSON 텍스트 추출과 placeholder만 대역으로 맞춘다. 조회 결과를
    미리 정하지 않아 날짜·phase·버전 경계가 빠진 SQL은 실제 과거 행을 반환한다.
    """

    import json
    import sqlite3
    from types import SimpleNamespace
    from backend.app.models.enums import PlayerRole
    from backend.app.models.game_state import GameState, PlayerState
    from backend.app.repositories.action_repository import PostgresActionRepository
    from backend.app.services.game_service import PostgresDiscussionCommandService

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("ATTACH DATABASE ':memory:' AS public")
    db.create_function("->>", 2, lambda value, key: (
        str(json.loads(value)[key]) if json.loads(value).get(key) is not None else None
    ))
    db.executescript("""
        CREATE TABLE public.games (id TEXT, phase TEXT, round INTEGER, day_number INTEGER, state_version INTEGER);
        CREATE TABLE public.game_events (game_id TEXT, state_version INTEGER, sequence INTEGER,
            audience TEXT, operation_type TEXT, payload TEXT);
        CREATE TABLE public.game_players (id TEXT, game_id TEXT, seat INTEGER);
        CREATE TABLE public.action_windows (id TEXT, game_id TEXT, phase TEXT, round INTEGER,
            cycle INTEGER, opened_state_version INTEGER, deadline_at TEXT);
        CREATE TABLE public.action_submissions (id TEXT, game_id TEXT, window_id TEXT,
            actor_player_id TEXT, action_type TEXT, message TEXT, submitted_at INTEGER,
            observed_state_version INTEGER);
    """)
    players = [PlayerState(uuid4(), seat, PlayerRole.CITIZEN) for seat in range(1, 9)]
    state = GameState(uuid4(), b"synthetic", players, phase=GamePhase.DAY_DISCUSSION,
                      round=3, day_number=4, state_version=35)
    game_id = str(state.game_id)
    db.execute("INSERT INTO public.games VALUES (?, ?, ?, ?, ?)",
               (game_id, state.phase.value, state.round, state.day_number, state.state_version))
    db.executemany("INSERT INTO public.game_players VALUES (?, ?, ?)",
                   [(str(player.player_id), game_id, player.seat) for player in players])

    class Cursor:
        """바인딩 자료형만 SQLite에 맞추고 production 조회식을 그대로 실행한다."""

        def execute(self, query, params):
            self.result = db.execute(query.replace("%s", "?"), tuple(
                str(value) if isinstance(value, UUID) else value for value in params
            ))

        def fetchall(self):
            return self.result.fetchall()

    def event(version, day=4, phase="DAY_DISCUSSION"):
        db.execute("INSERT INTO public.game_events VALUES (?, ?, ?, 'PUBLIC', 'SET_GAME_STATE', ?)",
                   (game_id, version, version, json.dumps({"phase": phase, "day_number": day})))

    def submission(version, actor, action="PASS", cycle=1, deadline=None, phase="DAY_DISCUSSION"):
        window_id = str(uuid4())
        db.execute("INSERT INTO public.action_windows VALUES (?, ?, ?, 3, ?, ?, ?)",
                   (window_id, game_id, phase, cycle, version, deadline))
        db.execute("INSERT INTO public.action_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (str(uuid4()), game_id, window_id, str(actor.player_id), action,
                    "합성 발언" if action == "SPEAK" else None, version, version))

    service = object.__new__(PostgresDiscussionCommandService)
    service._actions = PostgresActionRepository()
    fixture = SimpleNamespace(db=db, state=state, players=players, event=event,
                              submission=submission, cursor=Cursor(), service=service)
    yield fixture
    db.close()


def test_legacy_discussion_restoration_excludes_previous_day(discussion_ledger):
    """day3의 round3 원장이 day4의 첫 PASS를 중복으로 거부하던 경로를 재현한다."""

    from backend.app.game_engine.phases.discussion import pass_turn
    ledger = discussion_ledger
    ledger.event(24, day=3)
    for version, actor in enumerate(ledger.players, 24):
        ledger.submission(version, actor)
    ledger.event(32, day=3, phase="DAY_VOTE")
    ledger.event(35)
    ledger.service.hydrate_discussion_state(ledger.cursor, state=ledger.state, window={"cycle": 1})
    assert ledger.state.speech_actors == set()
    pass_turn(ledger.state, ledger.players[0].player_id)
    assert ledger.state.speech_actors == {ledger.players[0].player_id}


@pytest.mark.parametrize("deadline", [None, "2026-09-07T12:00:00Z"])
@pytest.mark.parametrize("cycle", [1, 2])
def test_discussion_restores_all_current_windows_and_keeps_duplicate_guard(discussion_ledger, deadline, cycle):
    """동일 날짜의 여러 window·추가 순환·timed/legacy에서도 정상 중복은 거부한다."""

    from backend.app.game_engine.errors import RuleViolation
    from backend.app.game_engine.phases.discussion import pass_turn
    ledger = discussion_ledger
    ledger.event(24, day=3)
    ledger.submission(24, ledger.players[2], cycle=cycle)
    ledger.event(32)
    ledger.submission(32, ledger.players[0], cycle=cycle, deadline=deadline)
    ledger.event(33)
    ledger.submission(33, ledger.players[1], "SPEAK", cycle=cycle, deadline=deadline)
    ledger.submission(34, ledger.players[3], cycle=3 - cycle)
    ledger.service.hydrate_discussion_state(ledger.cursor, state=ledger.state, window={"cycle": cycle})
    assert ledger.state.speech_actors == {player.player_id for player in ledger.players[:2]}
    assert ledger.state.speech_had_content
    assert ledger.state.speech_question_cycle_used is (cycle == 2)
    with pytest.raises(RuleViolation, match="DUPLICATE_ACTION"):
        pass_turn(ledger.state, ledger.players[0].player_id)


def test_discussion_restoration_requires_current_phase_entry(discussion_ledger):
    """같은 날짜라도 phase 재진입 전 제출과 미래 버전은 현재 순환으로 복원하지 않는다."""

    ledger = discussion_ledger
    ledger.event(24)
    ledger.submission(24, ledger.players[0])
    ledger.event(30, phase="DAY_VOTE")
    ledger.event(32)
    ledger.submission(32, ledger.players[1])
    ledger.submission(36, ledger.players[2])
    ledger.service.hydrate_discussion_state(ledger.cursor, state=ledger.state, window={"cycle": 1})
    assert ledger.state.speech_actors == {ledger.players[1].player_id}


@pytest.mark.parametrize("day,phase", [(1, "DAY_DISCUSSION"), (6, "FINAL_DISCUSSION")])
def test_discussion_restores_first_and_final_day(discussion_ledger, day, phase):
    """첫날과 최종 토론도 날짜와 phase의 확정 이벤트로 복원한다."""

    ledger = discussion_ledger
    ledger.state.day_number = day
    ledger.state.phase = GamePhase(phase)
    ledger.db.execute("UPDATE public.games SET day_number=?, phase=?", (day, phase))
    ledger.event(32, day=day, phase=phase)
    ledger.submission(32, ledger.players[0], phase=phase)
    ledger.service.hydrate_discussion_state(ledger.cursor, state=ledger.state, window={"cycle": 1})
    assert ledger.state.speech_actors == {ledger.players[0].player_id}


def test_discussion_does_not_guess_day_without_entry_evidence(discussion_ledger):
    """날짜 진입 이벤트가 없을 때 round를 날짜로 추정해 과거 원장을 섞지 않는다."""

    ledger = discussion_ledger
    ledger.submission(24, ledger.players[0])
    ledger.service.hydrate_discussion_state(ledger.cursor, state=ledger.state, window={"cycle": 1})
    assert ledger.state.speech_actors == set()


def test_expired_discussion_returns_binding_for_analysis_gate(discussion_ledger):
    """분석 완료 뒤 같은 window인지 재검증할 메타데이터를 실제 조회 결과로 확인한다."""

    ledger = discussion_ledger
    ledger.db.execute("ALTER TABLE public.games ADD COLUMN owner_user_id TEXT")
    ledger.db.execute("ALTER TABLE public.games ADD COLUMN status TEXT DEFAULT 'IN_PROGRESS'")
    ledger.db.execute("ALTER TABLE public.action_windows ADD COLUMN status TEXT DEFAULT 'OPEN'")
    ledger.db.execute("ALTER TABLE public.action_windows ADD COLUMN window_kind TEXT DEFAULT 'SPEECH'")
    owner_id, window_id = str(uuid4()), str(uuid4())
    ledger.db.execute("UPDATE public.games SET owner_user_id=?", (owner_id,))
    ledger.db.execute("""INSERT INTO public.action_windows
        (id, game_id, phase, round, cycle, opened_state_version, deadline_at)
        VALUES (?, ?, 'DAY_DISCUSSION', 3, 1, 35, '2026-09-07T12:00:00Z')""",
        (window_id, str(ledger.state.game_id)))
    result = ledger.service._actions.expired_discussions(ledger.cursor, now="2026-09-07T12:00:01Z")
    assert result == [{"id": str(ledger.state.game_id), "owner_user_id": owner_id,
                       "window_id": window_id, "phase": "DAY_DISCUSSION", "day_number": 4}]
