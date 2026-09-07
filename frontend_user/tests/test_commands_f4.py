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


def test_target_uuid_is_forwarded_for_backend_validation() -> None:
    # Front snapshot의 valid_targets는 stale될 수 있으므로 Backend가 최종 검증한다.
    window = {
        "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
        "paused": False,
        "has_submitted": False,
        "legal_actions": ["SUBMIT_VOTE"],
        "remaining_ms": 30000,
        "valid_targets": [{"player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08", "display_name": "플레이어 2"}],
    }
    snapshot = _snapshot(legal_actions=["SUBMIT_VOTE"], message_window=window)
    command = build_command(snapshot=snapshot, command_type="SUBMIT_VOTE", target_player_id="e15f18b6-ea20-477e-9d99-8a22dc6048f5")
    assert command["target_player_id"] == "e15f18b6-ea20-477e-9d99-8a22dc6048f5"


def test_stale_window_is_forwarded_for_backend_validation() -> None:
    window = _snapshot()["action_window"] | {"remaining_ms": 0}
    command = build_command(snapshot=_snapshot(message_window=window), command_type="SPEAK", message="발언")
    assert command["type"] == "SPEAK"


@pytest.mark.parametrize("command_type", ["SAVE_AND_EXIT", "RESUME", "FAST_FORWARD"])
def test_lifecycle_commands_do_not_send_window_id(command_type: str) -> None:
    """window과 무관한 lifecycle command가 불필요한 필드를 보내지 않는지 확인한다."""

    snapshot = _snapshot(legal_actions=[command_type])
    command = build_command(snapshot=snapshot, command_type=command_type)
    assert command == {"type": command_type, "expected_state_version": 12}
