"""실제 모델·DB 쓰기 없이 공개 보조 조회의 거부 경로와 집계 경계를 검증한다."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import IsolationLevel

from backend.app.core.errors import ApiError
from backend.app.core.responses import api_error_response
from backend.app.repositories.vote_insight_repository import PostgresVoteInsightRepository
from backend.app.routers.game_router import router
from backend.app.services.game.vote_insight_service import VoteInsightService

NOW = datetime(2026, 9, 7, tzinfo=UTC)


@pytest.fixture
def context():
    owner, game, window = uuid4(), uuid4(), uuid4()
    players = [{"id": str(uuid4()), "game_id": str(game), "user_id": str(owner) if i == 0 else None,
                "kind": "HUMAN" if i == 0 else "AI", "alive": True, "seat": i + 1,
                "display_name": name} for i, name in enumerate(("인간", "민수", "영희", "지수", "철수"))]
    source = {"game": {"id": str(game), "owner_user_id": str(owner), "status": "IN_PROGRESS",
                       "phase": "DAY_VOTE", "round": 2},
              "window": {"id": str(window), "game_id": str(game), "status": "OPEN",
                         "phase": "DAY_VOTE", "round": 2, "window_kind": "VOTE",
                         "deadline_at": NOW + timedelta(hours=1)},
              "players": players, "cutoff_sequence": 50, "discussion_segment": "DAY_DISCUSSION:1",
              "speeches": [], "revote": None}
    settings = SimpleNamespace(speech_analysis_enabled=True, effective_speech_analysis_version="synthetic-v1",
                               speech_analysis_embedding_model="synthetic-embedding", speech_analysis_dimensions=3,
                               speech_analysis_claims_model="synthetic-claims")
    return SimpleNamespace(owner=owner, game=game, window=window, source=source, settings=settings)


def speech(c, *, speaker=2, target=1, sequence=10, message=None, stance="SUSPICION", proposition=None):
    """분석 identity와 원문 hash가 정확히 결합된 합성 원장을 만든다."""
    message = message or f"{c.source['players'][target]['display_name']}의 알리바이가 수상해."
    event, player = str(uuid4()), c.source["players"][speaker]["id"]
    row = {"event_id": event, "game_id": str(c.game), "player_id": player,
           "audience": "PUBLIC", "audience_player_id": None, "event_type": "PLAYER_SPOKE",
           "operation_type": "APPEND_PUBLIC_EVENT", "schema_version": 1,
           "message": message, "created_at": NOW, "sequence": sequence,
           "discussion_segment": "DAY_DISCUSSION:1", "source_round": 1,
           "analysis_event_id": event, "analysis_game_id": str(c.game), "analysis_player_id": player,
           "source_sequence": sequence, "analysis_segment": "DAY_DISCUSSION:1", "analysis_round": 1,
           "content_hash": sha256(message.encode()).hexdigest(), "analysis_version": "synthetic-v1",
           "embedding_model": "synthetic-embedding", "dimensions": 3, "claims_model": "synthetic-claims",
           "embedding_status": "READY", "claims_status": "READY", "embedding": [1., 0., 0.],
           "claims": [{"target_player_id": c.source["players"][target]["id"], "stance": stance,
                       "proposition": proposition or message, "quote": message,
                       "evidence_start": 0, "evidence_end": len(message)}]}
    c.source["speeches"].append(row)
    return row


def service(c):
    return VoteInsightService(SimpleNamespace(load=lambda **_: deepcopy(c.source)), c.settings, clock=lambda: NOW)


def read(c, **kwargs):
    return service(c).get(c.owner, c.game, window_id=c.window, **kwargs)


def test_paraphrase_and_public_exact_projection(context):
    c = context
    speech(c)
    speech(c, speaker=3, sequence=11, message="민수의 알리바이 설명이 앞뒤가 맞지 않아.")
    data = read(c)
    assert data["status"] == "READY"
    assert data["coverage"] == dict(total=2, embedding_ready=2, claims_ready=2, failed=0)
    assert len(data["similar_claims"]) == 1
    assert data["similar_claims"][0]["claim"] == "알리바이에 관한 유사한 의심 발언"
    assert data["suspicion_ranking"][0]["accuser_count"] == 2
    assert set(data) == {"game_id", "window_id", "scope", "cutoff_sequence", "analysis_version",
                        "revision", "generated_at", "status", "coverage", "similar_claims",
                        "suspicion_ranking", "candidate_evidence", "conversation_summary"}
    assert set(data["similar_claims"][0]) == {"player_ids", "target_player_id", "claim", "evidence"}
    assert set(data["similar_claims"][0]["evidence"][0]) == {"event_id", "player_id", "message", "created_at", "sequence"}


@pytest.mark.parametrize("mutation", [
    lambda c: c.source["game"].update(owner_user_id=str(uuid4())),
    lambda c: c.source["game"].update(id=str(uuid4())),
])
def test_ownership_disabled_still_rejected(context, mutation):
    context.settings.speech_analysis_enabled = False
    mutation(context)
    with pytest.raises(ApiError) as caught:
        read(context)
    assert caught.value.status_code == 404


@pytest.mark.parametrize("mutation", [
    lambda c: c.source["game"].update(status="SAVED"),
    lambda c: c.source["game"].update(phase="DAY_DISCUSSION"),
    lambda c: c.source["window"].update(id=str(uuid4())),
    lambda c: c.source["window"].update(game_id=str(uuid4())),
    lambda c: c.source["window"].update(status="PAUSED"),
    lambda c: c.source["window"].update(status="RESOLVING"),
    lambda c: c.source["window"].update(deadline_at=NOW),
    lambda c: c.source["window"].update(round=3),
    lambda c: c.source["players"][0].update(alive=False),
])
def test_stale_window_disabled_still_rejected(context, mutation):
    context.settings.speech_analysis_enabled = False
    mutation(context)
    with pytest.raises(ApiError) as caught:
        read(context)
    assert caught.value.code == "VOTE_INSIGHTS_STALE_WINDOW"


def test_empty_disabled_pending_partial_failed(context):
    c = context
    assert read(c)["status"] == "READY"
    row = speech(c)
    row.update(analysis_version=None)
    assert read(c)["status"] == "PENDING"
    speech(c, speaker=3, sequence=11)
    data = read(c)
    assert data["status"] == "PARTIAL"
    assert data["coverage"]["total"] == 2
    c.source["speeches"] = c.source["speeches"][1:]
    c.source["speeches"][0].update(embedding_status="FAILED", claims_status="FAILED")
    assert read(c)["status"] == "UNAVAILABLE"
    c.settings.speech_analysis_enabled = False
    assert read(c)["coverage"] == dict(total=0, embedding_ready=0, claims_ready=0, failed=0)


@pytest.mark.parametrize("field,value", [
    ("analysis_game_id", "foreign"), ("analysis_event_id", "foreign"),
    ("analysis_player_id", "foreign"), ("source_sequence", 100),
    ("analysis_segment", "DAY_DISCUSSION:2"), ("analysis_round", 2),
    ("content_hash", "wrong"), ("embedding_model", "other"), ("claims_model", "other"),
    ("dimensions", 4), ("analysis_version", "other"),
])
def test_mismatched_analysis_is_pending(context, field, value):
    speech(context)[field] = value
    data = read(context)
    assert data["status"] == "PENDING"
    assert data["coverage"]["total"] == 1
    assert data["suspicion_ranking"] == []


@pytest.mark.parametrize("vector", [[0., 0., 0.], [float("nan"), 1., 0.], [float("inf"), 0., 0.],
                                     [True, 0., 0.], [1., 0.], ["1", 0., 0.], None])
def test_invalid_vectors_keep_claims_partial(context, vector):
    speech(context)["embedding"] = vector
    data = read(context)
    assert data["status"] == "PARTIAL"
    assert data["coverage"]["embedding_ready"] == 0
    assert len(data["suspicion_ranking"]) == 1


def test_large_finite_vector_and_low_cosine(context):
    speech(context)["embedding"] = [1e308, 1e308, 0.]
    speech(context, speaker=3, sequence=11)["embedding"] = [-1e308, -1e308, 0.]
    assert read(context)["status"] == "READY"
    assert read(context)["similar_claims"] == []


def test_duplicates_unique_accusers_tied_rank_and_dead_speaker(context):
    c = context
    row = speech(c)
    row["claims"] *= 3
    c.source["speeches"].append(deepcopy(row))
    speech(c, sequence=11)
    speech(c, sequence=12, target=3)
    c.source["players"][2]["alive"] = False
    result = read(c)
    ranking = result["suspicion_ranking"]
    assert [r["rank"] for r in ranking] == [1, 1]
    assert [r["accuser_count"] for r in ranking] == [1, 1]
    assert [r["speech_count"] for r in ranking] == [2, 1]
    assert result["similar_claims"] == []
    assert result["coverage"]["total"] == 3
    assert all(item["target_player_id"] != c.source["players"][2]["id"] for item in result["candidate_evidence"])


@pytest.mark.parametrize("message,stance", [
    ("민수의 역할 주장이 수상해.", "SUSPICION"),
    ("민수의 알리바이는 타당해.", "DEFENSE"),
    ("민수의 알리바이가 수상하다고 영희가 말했어.", "SUSPICION"),
    ("민수의 알리바이가 수상하지 않아.", "SUSPICION"),
    ("민수의 알리바이가 수상해?", "SUSPICION"),
    ('민수는 "알리바이가 수상해"라고 말했다.', "SUSPICION"),
    ("민수의 알리바이 의심을 철회합니다.", "SUSPICION"),
])
def test_opposite_topic_quote_negation_question_not_grouped(context, message, stance):
    speech(context)
    speech(context, speaker=3, sequence=11, message=message, stance=stance)
    assert read(context)["similar_claims"] == []


def test_model_proposition_never_substitutes_source_or_adds_accuser(context):
    speech(context, message="민수는 여기 있었습니다.", proposition="민수의 알리바이가 수상해.")
    assert read(context)["suspicion_ranking"] == []
    context.source["speeches"] = []
    speech(context)
    speech(context, speaker=3, sequence=11, proposition="민수의 역할 주장이 수상해.")
    assert read(context)["similar_claims"] == []


def test_question_defense_buckets_and_limits(context):
    c = context
    for i in range(8):
        speech(c, sequence=i + 1)
    speech(c, sequence=12, message="민수는 어디에 있었나요?", stance="QUESTION")
    speech(c, sequence=13, message="민수는 무고합니다.", stance="DEFENSE")
    data = read(c)
    candidate = data["candidate_evidence"][0]
    assert len(candidate["suspicion"]) == 5
    assert len(candidate["defense"]) == len(candidate["questions"]) == 1
    assert data["suspicion_ranking"][0]["speech_count"] == 8
    assert data["suspicion_ranking"][0]["accuser_count"] == 1


def test_current_scope_keeps_source_round_and_game_scope(context):
    c = context
    speech(c)
    old = speech(c, sequence=5)
    old.update(discussion_segment="DAY_DISCUSSION:0", source_round=0,
               analysis_segment="DAY_DISCUSSION:0", analysis_round=0)
    assert read(c)["coverage"]["total"] == 1
    assert read(c, scope="game")["coverage"]["total"] == 2
    assert c.source["game"]["round"] == 2


def test_cutoff_private_interference_and_repeat_revision(context):
    c = context
    speech(c)
    before = read(c)
    c.source["game"].update(seed="private", role="MAFIA", private_events=["secret"])
    c.source["players"][1].update(role="MAFIA", thoughts="private")
    c.source["speeches"][0].update(private="secret", payload={"thoughts": "secret"})
    speech(c, sequence=50)
    speech(c, sequence=51)
    foreign = speech(c, sequence=12)
    foreign["game_id"] = str(uuid4())
    hidden = speech(c, sequence=13)
    hidden["audience"] = "PLAYER"
    assert read(c) == before
    assert read(c) == read(c)


def test_revote_and_final_candidates(context):
    c = context
    speech(c)
    c.source["game"]["phase"] = "REVOTE"
    c.source["window"].update(phase="REVOTE", window_kind="REVOTE")
    candidates = [p["id"] for p in c.source["players"]][1:3]
    c.source["revote"] = {"counts": [{"target_player_id": p, "vote_count": 2} for p in candidates],
                          "tied_candidates": candidates, "needs_revote": True}
    assert {p["target_player_id"] for p in read(c)["candidate_evidence"]} == set(candidates)
    c.source["revote"]["tied_candidates"] = candidates[:1]
    with pytest.raises(ApiError) as caught:
        read(c)
    assert caught.value.code == "VOTE_INSIGHTS_UNAVAILABLE"
    c.source["game"]["phase"] = "FINAL_ACCUSATION"
    c.source["window"].update(phase="FINAL_ACCUSATION", window_kind="FINAL_VOTE")
    c.source["discussion_segment"] = "FINAL_DISCUSSION:2"
    row = c.source["speeches"][0]
    row.update(discussion_segment="FINAL_DISCUSSION:2", source_round=2,
               analysis_segment="FINAL_DISCUSSION:2", analysis_round=2)
    assert read(c)["coverage"]["total"] == 1


def test_save_resume_unchanged_cutoff(context):
    c = context
    speech(c)
    before = read(c)
    c.source["game"]["status"] = "SAVED"
    with pytest.raises(ApiError):
        read(c)
    c.source["game"]["status"] = "IN_PROGRESS"
    c.source["window"]["deadline_at"] += timedelta(minutes=1)
    speech(c, sequence=51)
    assert read(c) == before


class Cursor:
    """SQL을 기록하고 순서대로 합성 읽기 결과만 전달하는 cursor다."""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params):
        self.statements.append((query, params))
        self.result = next(self.replies)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class Transactions:
    """설정 시점을 확인할 수 있는 읽기 연결 fake다."""
    def __init__(self, cursor):
        self.connection = SimpleNamespace(cursor=lambda **_: cursor, isolation_level=None, read_only=False)

    @contextmanager
    def transaction(self):
        yield self.connection


def test_repository_repeatable_read_original_left_join_cutoff_and_disabled(context):
    c = context
    c.source["window"]["deadline_at"] = datetime.now(UTC) + timedelta(hours=1)
    replies = [c.source["game"], c.source["window"], c.source["players"], {"cutoff_sequence": 50},
               {"discussion_segment": "DAY_DISCUSSION:1"}, []]
    cursor = Cursor(replies)
    transactions = Transactions(cursor)
    result = PostgresVoteInsightRepository(transactions).load(owner_user_id=c.owner, game_id=c.game,
              window_id=c.window, scope="current_discussion", settings=c.settings)
    assert transactions.connection.isolation_level == IsolationLevel.REPEATABLE_READ
    assert transactions.connection.read_only is True
    assert result["cutoff_sequence"] == 50
    queries = " ".join(q for q, _ in cursor.statements)
    assert "min(sequence)" in queries
    assert "LEFT JOIN public.speech_analysis" in queries
    assert not any(word in queries for word in ("UPDATE", "INSERT", "DELETE", "seed", "ballots", "role"))
    c.settings.speech_analysis_enabled = False
    cursor = Cursor(replies[:-1])
    PostgresVoteInsightRepository(Transactions(cursor)).load(owner_user_id=c.owner, game_id=c.game,
              window_id=c.window, scope="current_discussion", settings=c.settings)
    assert all("speech_analysis" not in q for q, _ in cursor.statements)


def test_repository_failure_safe_message(context):
    def fail(**kwargs):
        raise RuntimeError("synthetic-secret-db-provider")
    s = VoteInsightService(SimpleNamespace(load=fail), context.settings)
    with pytest.raises(ApiError) as caught:
        s.get(context.owner, context.game, window_id=context.window)
    assert caught.value.code == "VOTE_INSIGHTS_UNAVAILABLE"
    assert "synthetic-secret" not in caught.value.message


def test_router_injected_service_envelope_and_validation(context):
    c = context
    speech(c)
    app = FastAPI()
    app.state.vote_insight_service = service(c)
    app.include_router(router)
    @app.exception_handler(ApiError)
    async def handler(request, error):
        """앱 운영과 같은 오류 envelope를 합성 앱에도 사용한다."""
        return api_error_response(request, error)
    with TestClient(app) as client:
        url = f"/api/v1/games/{c.game}/vote-insights"
        response = client.get(url, params={"window_id": str(c.window)}, headers={"X-User-Id": str(c.owner)})
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "READY"
        assert client.get(url, params={"window_id": "wrong"}, headers={"X-User-Id": str(c.owner)}).status_code == 422
        assert client.get(url, params={"window_id": str(c.window), "scope": "private"}, headers={"X-User-Id": str(c.owner)}).status_code == 422


def test_proposition_other_target_and_unsupported_topic_hold(context):
    c = context
    speech(c)
    speech(c, speaker=3, sequence=11, proposition="철수의 알리바이가 수상해.")
    assert read(c)["similar_claims"] == []
    c.source["speeches"] = []
    speech(c, message="민수가 수상합니다.")
    speech(c, speaker=3, sequence=11, message="민수를 의심합니다.")
    result = read(c)
    assert result["similar_claims"] == []
    assert result["suspicion_ranking"][0]["accuser_count"] == 2


def test_similar_clusters_do_not_merge_through_intermediate(context):
    c = context
    from math import cos, sin, radians
    for index, degree in enumerate((0, 25, 50)):
        row = speech(c, speaker=index + 2, sequence=index + 1)
        row["embedding"] = [cos(radians(degree)), sin(radians(degree)), 0.]
    cards = read(c)["similar_claims"]
    assert len(cards) == 1
    assert len(cards[0]["player_ids"]) == 2


def test_claim_unknown_field_and_invalid_evidence_pending(context):
    row = speech(context)
    row["claims"][0]["private"] = "not-public"
    assert read(context)["coverage"]["claims_ready"] == 0
    del row["claims"][0]["private"]
    row["claims"][0]["quote"] = "invented"
    assert read(context)["coverage"]["claims_ready"] == 0


def test_similar_evidence_limit_preserves_distinct_speakers(context):
    c = context
    for sequence in range(1, 8):
        speech(c, sequence=sequence)
    speech(c, speaker=3, sequence=9)
    card = read(c)["similar_claims"][0]
    assert len(card["evidence"]) == 5
    assert len({e["player_id"] for e in card["evidence"]}) == 2


@pytest.mark.parametrize("left,right", [
    ("민수의 의사 역할 주장이 수상합니다.", "민수의 시민 역할 주장이 수상합니다."),
    ("민수의 3시 알리바이가 수상합니다.", "민수의 4시 알리바이가 수상합니다."),
    ("민수의 알리바이 시간이 수상합니다.", "민수의 알리바이 장소가 수상합니다."),
])
def test_different_concrete_claims_not_grouped(context, left, right):
    speech(context, message=left)
    speech(context, speaker=3, sequence=11, message=right)
    assert read(context)["similar_claims"] == []


def test_empty_has_no_cards(context):
    result = read(context)
    assert all(result[key] == [] for key in ("similar_claims", "suspicion_ranking", "candidate_evidence"))


@pytest.mark.parametrize("message,accepted", [
    ("2번은 마피아가 아니야.", True), ("2번 플레이어는 마피아가 아닙니다.", True),
    ("2번은 마피아가 아니라고 말했다.", False), ("2번은 마피아가 아니라는 말이 있어.", False),
])
def test_explicit_role_negation_is_defense_not_reported_speech(context, message, accepted):
    speech(context, message=message, stance="DEFENSE")
    result = read(context)
    assert bool(result["candidate_evidence"][0]["defense"]) is accepted
    assert result["suspicion_ranking"] == []


@pytest.mark.parametrize("message", ["2번을 의심하지 않는다.", "2번은 마피아가 아니야."])
def test_negation_cannot_be_promoted_to_suspicion(context, message):
    speech(context, message=message)
    assert read(context)["suspicion_ranking"] == []


@pytest.mark.parametrize("message,accepted", [
    ("2번의 알리바이가 수상해.", True), ("2번 플레이어의 알리바이가 수상해.", True),
    ("12번의 알리바이가 수상해.", False), ("2번과 3번의 알리바이가 수상해.", False),
    ("민수와 4번의 알리바이가 수상해.", False),
])
def test_seat_references_and_boundaries(context, message, accepted):
    speech(context, message=message)
    assert bool(read(context)["suspicion_ranking"]) is accepted


def test_analysis_start_failure_still_validates_ownership_and_window(context):
    c = context
    speech(c)
    s = service(c)
    assert s.get(c.owner, c.game, window_id=c.window, analysis_available=False)["status"] == "UNAVAILABLE"
    with pytest.raises(ApiError) as caught:
        s.get(uuid4(), c.game, window_id=c.window, analysis_available=False)
    assert caught.value.status_code == 404
    with pytest.raises(ApiError) as caught:
        s.get(c.owner, c.game, window_id=uuid4(), analysis_available=False)
    assert caught.value.status_code == 409
    assert c.settings.speech_analysis_enabled is True


def test_name_and_seat_paraphrase_group_with_same_target(context):
    speech(context)
    speech(context, speaker=3, sequence=11, message="2번 플레이어의 알리바이 설명이 앞뒤가 맞지 않아.")
    assert len(read(context)["similar_claims"]) == 1


def test_multi_target_conjunction_cannot_hide_first_target(context):
    speech(context, target=2, message="2번과 3번의 알리바이가 수상해.")
    assert read(context)["suspicion_ranking"] == []


@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "FINAL_DISCUSSION"])
@pytest.mark.parametrize("deadline", [None, NOW, NOW + timedelta(minutes=1)])
def test_live_discussion_summary_includes_human_without_vote_cards(context, phase, deadline):
    """열린 토론과 마감 뒤 분석 준비에서 공개 요약만 제공하고 투표권은 만들지 않는다."""
    c = context
    c.source["game"]["phase"] = phase
    c.source["window"].update(phase=phase, window_kind="SPEECH", deadline_at=deadline)
    c.source["players"][0]["alive"] = False
    c.source["discussion_segment"] = f"{phase}:2"
    row = speech(c, speaker=0, proposition="민수의 알리바이에 대한 의심")
    row.update(discussion_segment=f"{phase}:2", source_round=2,
               analysis_segment=f"{phase}:2", analysis_round=2, embedding_status="PENDING", embedding=None)
    data = read(c)
    assert data["status"] == "PARTIAL"
    assert data["coverage"] == dict(total=1, embedding_ready=0, claims_ready=1, failed=0)
    summary = data["conversation_summary"]
    assert summary["total"] == 1 and summary["omitted"] == 0
    assert summary["items"][0]["summary"] == "민수의 알리바이에 대한 의심"
    assert summary["items"][0]["evidence"][0]["message"] == row["message"]
    assert summary["items"][0]["evidence"][0]["player_id"] == row["player_id"]
    assert all(data[key] == [] for key in ("similar_claims", "candidate_evidence", "suspicion_ranking"))


def test_summary_keeps_latest_twenty_and_reports_all_counts(context):
    """누적 요약의 표시 한도 때문에 원문 집계 수나 시간순이 바뀌지 않게 한다."""
    c = context
    for sequence in range(1, 26):
        row = speech(c, sequence=sequence)
        row["claims"] *= 2
    result = read(c)
    summary = result["conversation_summary"]
    assert summary["total"] == 25 and summary["omitted"] == 5
    assert len(summary["items"]) == 20
    assert [item["evidence"][0]["sequence"] for item in summary["items"]] == list(range(6, 26))
    assert all(item["summary"] == c.source["speeches"][0]["message"] for item in summary["items"])
    assert result["coverage"]["total"] == 25


def test_summary_excludes_unvalidated_empty_and_nonpublic_claims(context):
    """모델 결과를 요약에 노출하기 전에 기존 source·claim 검증을 그대로 적용한다."""
    c = context
    speech(c)["claims"][0]["quote"] = "존재하지 않는 인용"
    speech(c, sequence=11)["claims"] = []
    speech(c, sequence=12)["claims_status"] = "PENDING"
    speech(c, sequence=13)["audience"] = "PLAYER"
    speech(c, sequence=14)["content_hash"] = "wrong"
    speech(c, sequence=15)["claims"][0]["proposition"] = "   "
    assert read(c)["conversation_summary"] == {"items": [], "total": 0, "omitted": 0}
    c.settings.speech_analysis_enabled = False
    assert read(c)["conversation_summary"] == {"items": [], "total": 0, "omitted": 0}


def test_summary_revision_changes_with_completed_claim_and_human_counts(context):
    """인간의 확정 발언과 새 요약은 공개 revision에 반영하고 READY 결과는 재사용한다."""
    c = context
    row = speech(c, speaker=0)
    before = read(c)
    assert before["coverage"]["total"] == 1
    assert before["suspicion_ranking"][0]["accuser_count"] == 1
    row["claims"][0]["proposition"] = "민수의 설명을 의심함"
    assert read(c)["revision"] != before["revision"]


def test_repository_live_cutoff_tracks_public_snapshot_and_stays_read_only(context):
    """공개 sequence 상한만 읽어 private 이벤트 추가가 실시간 응답을 바꾸지 않게 한다."""
    c = context
    c.source["game"]["phase"] = "DAY_DISCUSSION"
    c.source["window"].update(phase="DAY_DISCUSSION", window_kind="SPEECH", deadline_at=NOW)
    cursor = Cursor([c.source["game"], c.source["window"], c.source["players"],
                     {"cutoff_sequence": 51}, []])
    transactions = Transactions(cursor)
    data = PostgresVoteInsightRepository(transactions).load(owner_user_id=c.owner, game_id=c.game,
        window_id=c.window, scope="current_discussion", settings=c.settings)
    assert data["cutoff_sequence"] == 51
    assert data["discussion_segment"] == "DAY_DISCUSSION:2"
    cutoff_query = cursor.statements[3][0]
    assert "max(sequence)" in cutoff_query and "audience='PUBLIC'" in cutoff_query
    assert transactions.connection.read_only is True
    assert transactions.connection.isolation_level == IsolationLevel.REPEATABLE_READ
