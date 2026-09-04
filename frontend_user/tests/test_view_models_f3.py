from frontend_user.core.view_models import own_private_view, public_players


def test_public_players_excludes_private_fields() -> None:
    snapshot = {
        "players": [{
            "player_id": "player-1", "seat": 1, "display_name": "플레이어 1",
            "kind": "AI", "alive": True, "revealed_role": None,
            "alibi": "비공개 알리바이", "observation": "비공개 관찰", "attack": "private",
        }],
    }
    player = public_players(snapshot)[0]
    assert player["display_name"] == "플레이어 1"
    assert "alibi" not in player
    assert "observation" not in player
    assert "attack" not in player


def test_only_me_projection_is_available_to_private_panel() -> None:
    snapshot = {"me": {
        "player_id": "human-1", "role": "DETECTIVE", "alive": True,
        "alibi": "내 알리바이", "observation": "내 관찰",
        "private_events": [], "other_player_role": "MAFIA",
    }}
    me = own_private_view(snapshot)
    assert me["role"] == "DETECTIVE"
    assert "other_player_role" not in me
