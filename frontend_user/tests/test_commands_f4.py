import pytest

from frontend_user.core.commands import build_command, normalize_message


def _snapshot(*, legal_actions=None, message_window=None):
    return {
        "game": {"state_version": 12},
        "me": {"player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269", "alive": True},
        "legal_actions": legal_actions or ["SPEAK", "PASS"],
        "action_window": message_window or {
            "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
            "paused": False,
            "has_submitted": False,
            "turn_player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
            "legal_actions": ["SPEAK", "PASS"],
            "remaining_ms": None,
            "valid_targets": [],
        },
    }


@pytest.mark.parametrize("length", [0, 201])
def test_message_length_is_rejected(length: int) -> None:
    with pytest.raises(ValueError):
        normalize_message("가" * length)


def test_message_200_chars_is_accepted_after_whitespace_normalization() -> None:
    assert len(normalize_message("가" * 200)) == 200


def test_speak_command_contains_contract_fields() -> None:
    command = build_command(snapshot=_snapshot(), command_type="SPEAK", message="  안녕   하세요 ")
    assert command == {
        "type": "SPEAK",
        "expected_state_version": 12,
        "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
        "message": "안녕 하세요",
    }


def test_target_must_be_in_current_window() -> None:
    # 팀 전달 사항: valid_targets 밖의 UUID는 Backend에서도 동일하게 거부해야 한다.
    window = {
        "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
        "paused": False,
        "has_submitted": False,
        "legal_actions": ["SUBMIT_VOTE"],
        "remaining_ms": 30000,
        "valid_targets": [{"player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08", "display_name": "플레이어 2"}],
    }
    snapshot = _snapshot(legal_actions=["SUBMIT_VOTE"], message_window=window)
    with pytest.raises(ValueError):
        build_command(snapshot=snapshot, command_type="SUBMIT_VOTE", target_player_id="e15f18b6-ea20-477e-9d99-8a22dc6048f5")


def test_expired_window_is_rejected() -> None:
    window = _snapshot()["action_window"] | {"remaining_ms": 0}
    with pytest.raises(ValueError):
        build_command(snapshot=_snapshot(message_window=window), command_type="SPEAK", message="발언")
