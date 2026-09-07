"""중앙 AI 진행 worker의 게임 간 격리와 순차 처리 테스트."""

from uuid import uuid4

from backend.app.services.game.ai_progress_worker import AiProgressWorker


class _Runtime:
    def __init__(self, failing_game_id, turns):
        self.calls = []
        self.failing_game_id = failing_game_id
        self.turns = turns

    def list_ai_speech_turns(self):
        return self.turns

    def agent_pass(self, owner_id, game_id, player_id, *, expected_state_version, window_id):
        self.calls.append((owner_id, game_id, player_id, expected_state_version, window_id))
        if game_id == self.failing_game_id:
            raise RuntimeError("synthetic failure")


def test_worker_processes_independent_games_when_one_turn_fails(monkeypatch):
    """한 게임의 AI 오류가 다른 게임의 진행을 중단시키지 않는지 확인한다."""

    failing_game_id = uuid4()
    succeeding_game_id = uuid4()
    turns = [
        {
            "owner_user_id": uuid4(),
            "game_id": failing_game_id,
            "turn_player_id": uuid4(),
            "state_version": 4,
            "window_id": uuid4(),
        },
        {
            "owner_user_id": uuid4(),
            "game_id": succeeding_game_id,
            "turn_player_id": uuid4(),
            "state_version": 9,
            "window_id": uuid4(),
        },
    ]
    runtime = _Runtime(failing_game_id, turns)
    worker = AiProgressWorker(runtime)

    assert worker.progress_once() == 1
    assert runtime.calls[0][1] == failing_game_id
    assert runtime.calls[1][1] == succeeding_game_id
