"""실제 모델·Backend 호출 없이 보조 조회와 투표 화면의 분리 경계를 검증한다."""

import json
from copy import deepcopy
from unittest.mock import patch
from urllib.error import URLError

import pytest
from streamlit.testing.v1 import AppTest

from frontend_user.components import vote_insights
from frontend_user.core.api_client import ApiClient, ApiUnavailableError

GAME = "00000000-0000-4000-8000-000000000201"
WINDOW = "00000000-0000-4000-8000-000000000202"
PLAYER = "00000000-0000-4000-8000-000000000203"
USER = "00000000-0000-4000-8000-000000000204"


def payload(status="READY"):
    """HTML처럼 보이는 공개 원문도 텍스트로만 표시되는 합성 응답을 만든다."""

    evidence = {"event_id": "synthetic-event", "player_id": PLAYER,
                "message": "<script>alert('원문')</script>",
                "created_at": "2026-09-07T00:00:00Z", "sequence": 3}
    return {"data": {"game_id": GAME, "window_id": WINDOW, "scope": "current_discussion",
                     "status": status, "cutoff_sequence": 4, "analysis_version": "v1",
                     "revision": "r1", "generated_at": "2026-09-07T00:00:01Z",
                     "coverage": {"total": 2, "embedding_ready": 2, "claims_ready": 1, "failed": 1},
                     "similar_claims": [{"player_ids": [PLAYER], "target_player_id": PLAYER,
                                         "claim": f"주장 {i}", "evidence": [evidence]} for i in range(5)],
                     "suspicion_ranking": [{"target_player_id": PLAYER, "rank": i + 1,
                                            "accuser_count": 1, "speech_count": 2,
                                            "evidence": [evidence]} for i in range(5)],
                     "candidate_evidence": [{"target_player_id": PLAYER, "suspicion": [evidence],
                                             "defense": [], "questions": []}]}}


def snapshot(phase="DAY_VOTE"):
    return {"game": {"game_id": GAME, "phase": phase, "status": "IN_PROGRESS"},
            "action_window": {"window_id": WINDOW},
            "players": [{"player_id": PLAYER, "display_name": "합성 AI"}]}


class FakeClient:
    """scope를 반영하며 응답 교체·오류 주입·호출 횟수를 관찰하는 로컬 fake다."""

    user_id = USER

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else payload()
        self.error = error
        self.calls = []

    def get_vote_insights(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        response = deepcopy(self.response)
        response["data"]["scope"] = kwargs["scope"]
        return response


def app_body(client, current):
    import streamlit as st
    from frontend_user.components import vote_insights

    current = st.session_state.setdefault("test.snapshot", current)
    st.session_state.setdefault("form.vote_target." + current["game"]["game_id"] + "."
                                + current["action_window"]["window_id"],
                                "00000000-0000-4000-8000-000000000203")
    st.session_state.setdefault("game.command_pending", {"status": "IN_FLIGHT"})
    st.session_state.setdefault("game.action_clock", {"remaining_ms": 25000})
    vote_insights.render(client=client, game_id=current["game"]["game_id"], snapshot=current)


@pytest.mark.parametrize("status,expected", [("READY", 1), ("UNAVAILABLE", 1), ("PENDING", 2), ("PARTIAL", 2)])
def test_only_processing_responses_refresh_on_existing_rerun(status, expected):
    client = FakeClient(payload(status))
    app = AppTest.from_function(app_body, args=(client, snapshot())).run().run()
    assert not app.exception
    assert len(client.calls) == expected
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}
    assert app.session_state["game.action_clock"] == {"remaining_ms": 25000}
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER


@pytest.mark.parametrize("phase", ["DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"])
def test_plain_text_evidence_names_and_three_summary_limit(phase):
    app = AppTest.from_function(app_body, args=(FakeClient(), snapshot(phase))).run()
    assert not app.exception
    texts = [entry.value for entry in app.text]
    assert "주장 2" in texts and "주장 3" not in texts
    assert any("합성 AI" in value for value in texts)
    assert any("event ID: synthetic-event" == value for value in texts)
    assert "<script>alert('원문')</script>" in texts
    assert any("실패 1개" in value for value in texts)
    assert any("사실 판정이 아닙니다" in entry.value for entry in app.caption)
    assert not app.markdown


def test_scope_change_does_not_reuse_other_scope_or_change_vote():
    client = FakeClient()
    app = AppTest.from_function(app_body, args=(client, snapshot())).run()
    app.radio[0].set_value("game").run()
    assert not app.exception
    assert [call["scope"] for call in client.calls] == ["current_discussion", "game"]
    assert any("게임 누적 · AI 발언" in entry.value for entry in app.text)
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER


@pytest.mark.parametrize("field,value", [("window_id", "old-window"), ("game_id", "other-game")])
def test_stale_response_is_discarded(field, value):
    response = payload()
    response["data"][field] = value
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot())).run()
    assert not app.exception
    assert not app.text
    assert "사용할 수 없어요" in app.info[0].value


def test_stale_scope_is_discarded(monkeypatch):
    monkeypatch.setattr(vote_insights.st, "session_state", {})
    client = FakeClient()
    with patch.object(client, "get_vote_insights", return_value=payload()):
        assert vote_insights._load(client=client, game_id=GAME, window_id=WINDOW, scope="game") is None


@pytest.mark.parametrize("client", [object(), FakeClient(error=ApiUnavailableError(status_code=503, code="SYNTHETIC")),
                                     FakeClient(error=ValueError("synthetic"))])
def test_missing_optional_method_and_failure_leave_game_state_intact(client):
    app = AppTest.from_function(app_body, args=(client, snapshot())).run().run()
    assert not app.exception
    assert "사용할 수 없어요" in app.info[0].value
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}


def test_saved_resume_and_new_window_clear_completed_cache():
    client = FakeClient()
    app = AppTest.from_function(app_body, args=(client, snapshot())).run()
    app.session_state["test.snapshot"]["game"]["status"] = "SAVED"
    app.run()
    assert len(client.calls) == 1
    app.session_state["test.snapshot"]["game"]["status"] = "IN_PROGRESS"
    app.run()
    assert len(client.calls) == 2
    app.session_state["test.snapshot"]["action_window"]["window_id"] = "new-window"
    app.run()
    assert len(client.calls) == 3
    assert not app.text


def test_empty_and_partial_are_distinct():
    response = payload()
    response["data"]["coverage"] = {"total": 0}
    response["data"]["similar_claims"] = []
    response["data"]["suspicion_ranking"] = []
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot())).run()
    assert "발언이 없습니다" in app.info[0].value
    partial = AppTest.from_function(app_body, args=(FakeClient(payload("PARTIAL")), snapshot())).run()
    assert "부분 결과" in partial.info[0].value


def test_api_uses_envelope_encoded_scope_and_short_timeout():
    captured = []

    def transport(request, timeout):
        captured.append((request, timeout))
        return 200, json.dumps(payload()).encode()

    client = ApiClient(user_id=USER, transport=transport)
    assert client.get_vote_insights(game_id=GAME, window_id=WINDOW) == payload()
    request, timeout = captured[0]
    assert request.full_url.endswith(f"/games/{GAME}/vote-insights?window_id={WINDOW}&scope=current_discussion")
    assert request.method == "GET" and request.data is None
    assert request.get_header("X-user-id") == USER
    assert timeout == 0.75
    with pytest.raises(ValueError):
        client.get_vote_insights(game_id=GAME, window_id=WINDOW, scope="other&injected=1")
    with pytest.raises(ValueError):
        client.get_vote_insights(game_id=GAME, window_id="invalid")
    assert len(captured) == 1


def test_api_timeout_isolated_as_safe_error():
    def transport(request, timeout):
        raise URLError("synthetic outage")

    client = ApiClient(user_id=USER, transport=transport)
    with pytest.raises(ApiUnavailableError):
        client.get_vote_insights(game_id=GAME, window_id=WINDOW)


def test_legacy_dynamic_fake_does_not_invent_optional_api(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(vote_insights.st, "session_state", {})
    client = Mock()
    assert vote_insights._load(client=client, game_id=GAME, window_id=WINDOW, scope="game") is None
    assert client.mock_calls == []


def test_nonvote_phase_never_queries():
    client = FakeClient()
    app = AppTest.from_function(app_body, args=(client, snapshot("DAY_DISCUSSION"))).run()
    assert not app.exception
    assert client.calls == []
    assert not app.expander


def test_malformed_optional_response_does_not_break_game():
    response = payload()
    response["data"].update(coverage=[], similar_claims=[None], suspicion_ranking="invalid",
                            candidate_evidence=[None])
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot())).run()
    assert not app.exception
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}


def test_evidence_candidate_control_does_not_submit_or_change_vote():
    other = "00000000-0000-4000-8000-000000000205"
    current = snapshot()
    current["players"].append({"player_id": other, "display_name": "다른 AI"})
    response = payload()
    response["data"]["candidate_evidence"].append({"target_player_id": other, "suspicion": [],
                                                  "defense": [], "questions": []})
    client = FakeClient(response)
    app = AppTest.from_function(app_body, args=(client, current)).run()
    app.selectbox[0].set_value(other).run()
    assert not app.exception
    assert "선택 후보: 다른 AI" in [entry.value for entry in app.text]
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER
    assert len(client.calls) == 1
