"""인간·AI 공통 actor 계약 테스트."""

from uuid import uuid4

import pytest

from backend.app.services.game.actor_context import ActorContext


def test_human_context_uses_user_principal() -> None:
    """인간 행동은 owner user를 receipt principal로 사용한다."""

    owner, player = uuid4(), uuid4()
    actor = ActorContext.human(owner_user_id=owner, player_id=player)

    assert actor.kind == "HUMAN"
    assert actor.principal_id == owner
    assert actor.principal_type == "USER"
    assert actor.source == "HUMAN"


def test_agent_context_uses_player_principal() -> None:
    """AI 행동은 소유자와 분리된 AI player를 receipt principal로 사용한다."""

    owner, player = uuid4(), uuid4()
    actor = ActorContext.agent(owner_user_id=owner, player_id=player)

    assert actor.kind == "AGENT"
    assert actor.principal_id == player
    assert actor.principal_type == "AGENT"
    assert actor.source == "AGENT"


def test_actor_context_rejects_non_uuid_identity() -> None:
    """외부 문자열이 내부 actor 계약에 직접 주입되지 않도록 차단한다."""

    with pytest.raises(TypeError):
        ActorContext("AGENT", uuid4(), "not-a-uuid", uuid4())  # type: ignore[arg-type]
