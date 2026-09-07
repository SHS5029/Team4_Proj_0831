"""PostgreSQL 게임 목록·snapshot 조회와 row 변환을 담당하는 모듈."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.models.enums import Faction, GamePhase, GameStatus, PlayerKind, PlayerRole, WinReason
from backend.app.models.game_state import GameState, PlayerState, Vote
from backend.app.repositories.game_repository import GameStateKeyring
from backend.app.repositories.game_repository import PostgresGameRepository
from backend.app.repositories.player_repository import PostgresPlayerRepository
from backend.app.repositories.action_repository import PostgresActionRepository
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.services.game.models import CanonicalGameRecord
from backend.app.services.game.helpers import window_id as uuid5_for_window
from backend.app.services.game.result_service import build_result


class PostgresGameReadService:
    """DB 원본에서 게임 목록·snapshot·sync를 읽는 facade다."""

    def __init__(
        self,
        *,
        transactions: TransactionManager,
        keyring: GameStateKeyring,
        games: PostgresGameRepository | None = None,
        players: PostgresPlayerRepository | None = None,
        events: PostgresEventRepository | None = None,
        actions: PostgresActionRepository | None = None,
    ) -> None:
        """읽기 업무에 필요한 transaction과 repository를 주입한다."""

        self._transactions = transactions
        self._keyring = keyring
        self._games = games or PostgresGameRepository()
        self._players = players or PostgresPlayerRepository()
        self._events = events or PostgresEventRepository(self._games)
        self._actions = actions or PostgresActionRepository()

    def list_games(self, owner_user_id: UUID, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        """소유자 게임 목록을 반환한다."""

        return list_games(self, owner_user_id, status=status, limit=limit)

    def snapshot(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """소유자 snapshot을 반환한다."""

        return read_snapshot(self, owner_user_id, game_id)

    def sync(self, owner_user_id: UUID, game_id: UUID, *, after_state_version: int, after_sequence: int) -> dict[str, Any]:
        """event 정본에서 sync envelope를 반환한다."""

        from backend.app.services.game.event_sync_service import read_sync

        return read_sync(self, owner_user_id, game_id, after_state_version=after_state_version, after_sequence=after_sequence)

    def _initial_record_from_rows(self, game: Mapping[str, Any], player_rows: list[Mapping[str, Any]], window: Mapping[str, Any] | None = None, submissions: list[Mapping[str, Any]] | None = None) -> CanonicalGameRecord:
        """DB row를 canonical record로 변환한다."""

        return initial_record_from_rows(keyring=self._keyring, game=game, player_rows=player_rows, window=window, submissions=submissions)

    @staticmethod
    def _attach_human_facts(record: CanonicalGameRecord, facts: list[Mapping[str, Any]]) -> None:
        """인간에게 공개할 단서를 record에 결합한다."""

        attach_human_facts(record, facts)

    @staticmethod
    def _list_item(row: Mapping[str, Any]) -> dict[str, Any]:
        """게임 목록 row를 공개 projection으로 변환한다."""

        return list_item(row)


def list_games(reader: Any, owner_user_id: UUID, *, status: str | None, limit: int) -> list[dict[str, Any]]:
    """소유자 게임 목록을 DB에서 읽어 공개 목록 projection으로 변환한다."""

    try:
        with reader._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = reader._games.list_owned_games(
                    cursor,
                    owner_user_id=owner_user_id,
                    status=status,
                    limit=limit,
                )
        return [list_item(row) for row in rows]
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="게임 저장소를 사용할 수 없습니다.",
            retryable=True,
        ) from exc


def read_snapshot(reader: Any, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
    """소유자 검증부터 공개 snapshot 반환까지의 DB 조회 흐름을 실행한다."""

    try:
        with reader._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                game = reader._games.get_owned_game(
                    cursor,
                    owner_user_id=owner_user_id,
                    game_id=game_id,
                )
                if game is None:
                    raise ApiError(
                        status_code=404,
                        code="GAME_NOT_FOUND",
                        message="게임을 찾을 수 없습니다.",
                    )
                player_rows = reader._players.list_players(cursor, game_id=game_id)
                window = reader._actions.active_window(cursor, game_id=game_id)
                submissions = (
                    reader._actions.list_discussion_submissions(
                        cursor,
                        game_id=game_id,
                        phase=str(game["phase"]),
                        round=int(game["round"]),
                        cycle=int(window["cycle"]),
                    )
                    if window is not None
                    and str(game["phase"]) in {GamePhase.DAY_DISCUSSION.value, GamePhase.FINAL_DISCUSSION.value}
                    else []
                )
                vote_submissions = (
                    reader._actions.list_window_vote_submissions(
                        cursor, window_id=UUID(str(window["id"]))
                    )
                    if window is not None
                    and str(game["phase"]) in {
                        GamePhase.DAY_VOTE.value,
                        GamePhase.REVOTE.value,
                    }
                    else []
                )
                record = initial_record_from_rows(
                    keyring=reader._keyring,
                    game=game,
                    player_rows=player_rows,
                    window=window,
                    submissions=submissions,
                )
                record.state.votes = {
                    UUID(str(row["actor_player_id"])): Vote(
                        UUID(str(row["actor_player_id"])),
                        UUID(str(row["target_player_id"])),
                    )
                    for row in vote_submissions
                }
                facts = reader._players.list_player_facts(
                    cursor,
                    game_id=game_id,
                    player_id=record.human_player_id,
                )
        attach_human_facts(record, facts)
        return build_snapshot(record)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="게임 저장소를 사용할 수 없습니다.",
            retryable=True,
        ) from exc


def initial_record_from_rows(
    *,
    keyring: GameStateKeyring,
    game: Mapping[str, Any],
    player_rows: list[Mapping[str, Any]],
    window: Mapping[str, Any] | None = None,
    submissions: list[Mapping[str, Any]] | None = None,
) -> CanonicalGameRecord:
    """DB row를 현재 GameState와 공개 snapshot 원장으로 복원한다."""

    if not isinstance(game["updated_at"], datetime):
        raise RuntimeError("Persisted game timestamp is invalid")
    seed = keyring.decrypt_seed(
        ciphertext=bytes(game["seed_ciphertext"]),
        nonce=bytes(game["seed_nonce"]),
        key_id=str(game["seed_key_id"]),
    )
    players: list[PlayerState] = []
    human_player_id: UUID | None = None
    eliminated: dict[UUID, tuple[str, int]] = {}
    for row in player_rows:
        player_id = UUID(str(row["id"]))
        player = PlayerState(
            player_id=player_id,
            seat=int(row["seat"]),
            role=PlayerRole(str(row["role"])),
            kind=PlayerKind(str(row["kind"])),
            display_name=str(row["display_name"]),
            alive=bool(row["alive"]),
        )
        players.append(player)
        if player.kind is PlayerKind.HUMAN:
            if human_player_id is not None or row["user_id"] is None:
                raise RuntimeError("Persisted human player is invalid")
            human_player_id = player_id
        if not player.alive:
            phase = row["eliminated_phase"]
            round_number = row["eliminated_round"]
            if phase is None or round_number is None:
                raise RuntimeError("Persisted eliminated player is invalid")
            eliminated[player_id] = (str(phase), int(round_number))
    if human_player_id is None or len(players) != int(game["player_count"]):
        raise RuntimeError("Persisted players are incomplete")

    state = GameState(
        game_id=UUID(str(game["id"])),
        seed=seed,
        players=players,
        phase=GamePhase(str(game["phase"])),
        status=GameStatus(str(game["status"])),
        round=int(game["round"]),
        day_number=int(game["day_number"]),
        state_version=int(game["state_version"]),
        updated_at=game["updated_at"],
        winner=Faction(str(game["winner"])) if game["winner"] is not None else None,
        win_reason=WinReason(str(game["win_reason"])) if game["win_reason"] is not None else None,
    )
    if window is not None and state.phase in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        discussion_submissions = submissions or []
        state.speech_actors = {UUID(str(row["actor_player_id"])) for row in discussion_submissions}
        state.speech_had_content = any(row["action_type"] == "SPEAK" for row in discussion_submissions)
        state.speech_question_cycle_used = state.day_number == 1 and int(window["cycle"]) == 2
    locations = game["scenario_locations"]
    if not isinstance(locations, list) or not all(isinstance(item, str) for item in locations):
        raise RuntimeError("Persisted scenario locations are invalid")
    return CanonicalGameRecord(
        state=state,
        scenario={
            "scenario_id": str(game["scenario_id"]),
            "title": str(game["scenario_title"]),
            "background": str(game["scenario_background"]),
            "victim": str(game["scenario_victim"]),
            "locations": list(locations),
        },
        human_player_id=human_player_id,
        owner_user_id=UUID(str(game["owner_user_id"])),
        alibi="",
        observation="",
        front_sequence=max(int(game["next_front_sequence"]) - 1, 0),
        eliminated=eliminated,
        action_window=dict(window) if window is not None else None,
    )


def attach_human_facts(record: CanonicalGameRecord, facts: list[Mapping[str, Any]]) -> None:
    """공개 snapshot에 현재 인간 플레이어의 두 단서만 연결한다."""

    by_kind = {str(fact["fact_kind"]): str(fact["rendered_text"]) for fact in facts}
    if set(by_kind) != {"ALIBI", "OBSERVATION"}:
        raise RuntimeError("Persisted human facts are incomplete")
    record.alibi = by_kind["ALIBI"]
    record.observation = by_kind["OBSERVATION"]


def build_snapshot(record: CanonicalGameRecord) -> dict[str, Any]:
    """PostgreSQL에서 복원한 canonical record를 공개 snapshot으로 투영한다.

    이 함수는 저장소나 InMemory service를 생성하지 않는 순수 projection이다. 공개
    player 정보와 인간 본인의 private facts를 한 곳에서 분리해, read service가
    테스트용 실행 runtime을 presenter로 우회하지 않도록 한다.
    """

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
    legal = legal_actions(record)
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
        "action_window": action_window(record, legal),
        "legal_actions": legal,
        "public_events": copy.deepcopy(record.public_events),
        "result": build_result(state),
    }


def legal_actions(record: CanonicalGameRecord) -> list[str]:
    """현재 상태에서 인간에게 공개할 command 종류를 계산한다."""

    state = record.state
    human = state.player_by_id[record.human_player_id]
    if state.status is GameStatus.SAVED:
        return ["RESUME"]
    if state.status is not GameStatus.IN_PROGRESS or not human.alive:
        return ["FAST_FORWARD", "SAVE_AND_EXIT"] if not human.alive and state.status is GameStatus.IN_PROGRESS else []
    if state.phase is GamePhase.ROLE_REVEAL:
        return ["BEGIN_GAME", "SAVE_AND_EXIT"]
    if state.phase in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION} and record.human_player_id not in state.speech_actors:
        return ["SPEAK", "PASS", "SAVE_AND_EXIT"]
    if state.phase is GamePhase.NIGHT_ACTION and human.role is not PlayerRole.CITIZEN and record.human_player_id not in state.night_actions:
        return ["SUBMIT_NIGHT_ACTION", "SAVE_AND_EXIT"]
    if state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION} and record.human_player_id not in state.votes:
        return ["SUBMIT_VOTE", "SAVE_AND_EXIT"]
    return ["SAVE_AND_EXIT"]


def action_window(record: CanonicalGameRecord, legal: list[str]) -> dict[str, Any] | None:
    """복원된 DB window를 공개 action window projection으로 변환한다."""

    state = record.state
    kind = {
        GamePhase.DAY_DISCUSSION: "SPEECH",
        GamePhase.FINAL_DISCUSSION: "SPEECH",
        GamePhase.NIGHT_ACTION: "NIGHT",
        GamePhase.DAY_VOTE: "VOTE",
        GamePhase.REVOTE: "REVOTE",
        GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
    }.get(state.phase)
    if kind is None or state.status is GameStatus.COMPLETED:
        return None
    persisted = record.action_window
    if persisted is not None:
        timed = kind != "SPEECH"
        now = datetime.now(UTC)
        if timed and state.status is GameStatus.IN_PROGRESS:
            deadline = persisted["deadline_at"]
            if not isinstance(deadline, datetime):
                raise RuntimeError("Active timed action window deadline is invalid")
            remaining_ms = max(int((deadline - now).total_seconds() * 1000), 0)
        elif timed:
            remaining_ms = (
                int(persisted["remaining_ms_on_save"])
                if persisted["remaining_ms_on_save"] is not None
                else None
            )
        else:
            remaining_ms = None
        return {
            "window_id": str(persisted["id"]),
            "kind": kind,
            "cycle": int(persisted["cycle"]),
            "paused": persisted["status"] == "PAUSED" or state.status is GameStatus.SAVED,
            "opened_state_version": int(persisted["opened_state_version"]),
            "server_time": now.isoformat().replace("+00:00", "Z"),
            "deadline_at": None if not timed or state.status is GameStatus.SAVED else (
                persisted["deadline_at"].isoformat().replace("+00:00", "Z")
                if persisted["deadline_at"] is not None else None
            ),
            "remaining_ms": remaining_ms,
            "turn_player_id": str(persisted["turn_player_id"]) if persisted["turn_player_id"] is not None else None,
            "has_submitted": not any(action in legal for action in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}),
            "legal_actions": legal if state.status is GameStatus.IN_PROGRESS else [],
            "valid_targets": _valid_targets(record, kind),
        }
    timed = kind != "SPEECH"
    now = datetime.now(UTC)
    return {
        "window_id": str(uuid5_for_window(state.game_id, state.state_version)),
        "kind": kind,
        "cycle": 1,
        "paused": state.status is GameStatus.SAVED,
        "opened_state_version": state.state_version,
        "server_time": now.isoformat().replace("+00:00", "Z"),
        "deadline_at": None if not timed or state.status is GameStatus.SAVED else (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "remaining_ms": 30_000 if timed and state.status is GameStatus.IN_PROGRESS else None,
        "turn_player_id": str(record.human_player_id) if kind == "SPEECH" else None,
        "has_submitted": not any(action in legal for action in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}),
        "legal_actions": legal if state.status is GameStatus.IN_PROGRESS else [],
        "valid_targets": _valid_targets(record, kind),
    }


def _valid_targets(record: CanonicalGameRecord, kind: str) -> list[dict[str, str]]:
    """현재 공개 window에서 선택 가능한 생존 대상만 반환한다."""

    if kind == "SPEECH":
        return []
    human = record.state.player_by_id[record.human_player_id]
    return [
        {"player_id": str(player.player_id), "display_name": player.display_name}
        for player in record.state.alive_players
        if kind != "NIGHT" or human.role is PlayerRole.DOCTOR or player.player_id != record.human_player_id
    ]


def list_item(row: Mapping[str, Any]) -> dict[str, Any]:
    """게임 목록용 공개 projection을 만든다."""

    updated_at = row["updated_at"]
    if not isinstance(updated_at, datetime):
        raise RuntimeError("Persisted game timestamp is invalid")
    status = GameStatus(str(row["status"]))
    return {
        "game_id": str(row["id"]),
        "status": status.value,
        "phase": str(row["phase"]),
        "round": int(row["round"]),
        "day_number": int(row["day_number"]),
        "state_version": int(row["state_version"]),
        "scenario_title": str(row["scenario_title"]),
        "player_count": int(row["player_count"]),
        "human_alive": bool(row["human_alive"]),
        "winner": str(row["winner"]) if row["winner"] is not None else None,
        "can_resume": status is GameStatus.SAVED,
        "updated_at": updated_at.isoformat(),
    }

__all__ = [
    "PostgresGameReadService",
    "attach_human_facts",
    "action_window",
    "build_snapshot",
    "initial_record_from_rows",
    "legal_actions",
    "list_item",
]
