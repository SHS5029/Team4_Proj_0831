"""현재 snapshot의 행동 창을 단계별 입력 화면으로 표현한다."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import streamlit as st

from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError
from frontend_user.core.commands import build_command

ACTION_PANEL_CSS = """
<style>
[class*="st-key-discussion-action-panel"] {
  margin-top: .9rem; padding: .85rem !important; border: 1px solid #8eb6ff !important;
  border-radius: .75rem !important;
  background: linear-gradient(135deg, #f9fbff, #eef4ff) !important;
}
[class*="st-key-discussion-action-panel"] textarea { min-height: 6.2rem; border-color: #afc4e8; }
[class*="st-key-night-action-panel"] {
  min-height: 37rem; padding: 1.15rem !important; border: 1px solid #203a60 !important;
  border-radius: .8rem !important; color: #f3f7ff !important;
  background: linear-gradient(145deg, #101f37, #061328 72%) !important;
  box-shadow: 0 1rem 2.5rem rgba(4, 17, 38, .2);
}
[class*="st-key-night-action-panel"] h2,
[class*="st-key-night-action-panel"] h3,
[class*="st-key-night-action-panel"] p,
[class*="st-key-night-action-panel"] label { color: #f3f7ff !important; }
[class*="st-key-night-action-panel"] [data-testid="stCaptionContainer"] {
  color: #b6c4da !important;
}
[class*="st-key-night-action-panel"] div[role="radiogroup"] {
  display: flex; flex-wrap: wrap; gap: .65rem;
}
[class*="st-key-night-action-panel"] div[role="radiogroup"] > label {
  flex: 1 1 29%; min-width: 8.5rem; margin: 0; padding: 1rem .7rem;
  border: 1px solid #3a5378; border-radius: .7rem; background: #12233d;
}
[class*="st-key-night-action-panel"] div[role="radiogroup"] > label:has(input:checked) {
  border-color: #2f7cff; box-shadow: inset 0 0 0 1px #2f7cff; background: #152c4d;
}
[class*="st-key-vote-action-panel"] {
  min-height: 37rem; padding: 1.1rem !important; border: 1px solid #d2dceb !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-vote-summary"] {
  margin: .75rem 0 1rem; padding: .8rem .9rem !important;
  border: 1px solid #d8e2ef !important; border-radius: .65rem !important;
  background: linear-gradient(135deg, #f9fbff, #f1f5fb) !important;
}
[class*="st-key-vote-action-panel"] div[role="radiogroup"] {
  display: flex; flex-wrap: wrap; gap: .65rem;
}
[class*="st-key-vote-action-panel"] div[role="radiogroup"] > label {
  flex: 1 1 29%; min-width: 8.5rem; margin: 0; padding: 1rem .75rem;
  border: 1px solid #d6dfec; border-radius: .7rem; background: #fff;
}
[class*="st-key-vote-action-panel"] div[role="radiogroup"] > label:has(input:checked) {
  border-color: #2f7cff; box-shadow: inset 0 0 0 1px #2f7cff;
  background: linear-gradient(145deg, #fff, #eef5ff);
}
[class*="st-key-discussion-action-panel"] [data-testid="stButton"] button,
[class*="st-key-night-action-panel"] [data-testid="stButton"] button,
[class*="st-key-vote-action-panel"] [data-testid="stButton"] button {
  min-height: 2.9rem; font-weight: 750;
}
@media (max-width: 768px) {
  [class*="st-key-night-action-panel"] { min-height: auto; }
  [class*="st-key-night-action-panel"] div[role="radiogroup"] > label { flex-basis: 45%; }
  [class*="st-key-vote-action-panel"] { min-height: auto; }
  [class*="st-key-vote-action-panel"] div[role="radiogroup"] > label { flex-basis: 45%; }
}
</style>
"""

DISCUSSION_PHASES = {"DAY_DISCUSSION", "FINAL_DISCUSSION"}
VOTE_PHASES = {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}


def render(*, client: ApiClient, game_id: str, snapshot: dict[str, Any]) -> None:
    """Backend 행동 계약은 유지하고 현재 phase에 맞는 입력만 표시한다."""

    # command POST는 클릭이 발생한 렌더 주기와 분리한다. 이렇게 해야 버튼의
    # 순간적인 중복 이벤트가 네트워크 요청으로 이어지지 않고, 결과가 불명확할 때도
    # 최초 body와 Idempotency-Key를 그대로 재사용할 수 있다.
    st.markdown(ACTION_PANEL_CSS, unsafe_allow_html=True)
    _process_pending(client=client, game_id=game_id, snapshot=snapshot)

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    phase = str(game.get("phase", ""))
    if phase in DISCUSSION_PHASES:
        _render_discussion(game_id=game_id, snapshot=snapshot)
    elif phase == "NIGHT_ACTION":
        _render_night_action(game_id=game_id, snapshot=snapshot)
    elif phase in VOTE_PHASES:
        _render_vote_action(game_id=game_id, snapshot=snapshot)


def _render_discussion(*, game_id: str, snapshot: dict[str, Any]) -> None:
    """내 발언 차례에만 200자 입력과 PASS를 제공하고 나머지는 대기시킨다."""

    window = _window(snapshot)
    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    legal = set(snapshot.get("legal_actions", []))
    my_turn = window.get("turn_player_id") == me.get("player_id")
    pending = _pending_for_window(game_id=game_id, window=window)

    with st.container(key="discussion-action-panel", border=True):
        _render_pending_feedback(pending=pending)
        if not my_turn or not ({"SPEAK", "PASS"} & legal):
            speaker = _current_speaker(snapshot=snapshot, player_id=window.get("turn_player_id"))
            if window.get("has_submitted"):
                st.info("발언이 제출되었습니다. 다음 차례를 기다려 주세요.")
            elif speaker:
                st.info(f"현재 {speaker}님의 발언 차례입니다.")
            else:
                st.info("다른 플레이어의 발언을 기다리고 있습니다.")
            return

        locked = _is_locked(window=window, pending=pending)
        turn_col, guide_col = st.columns([1, 4])
        turn_col.markdown("**내 차례**")
        guide_col.write("공개된 정보를 바탕으로 의견을 말해 주세요.")
        message_key = f"form.message.{window.get('window_id', 'current')}"
        message = st.text_area(
            "발언 내용",
            max_chars=200,
            disabled=locked,
            key=message_key,
            placeholder="이곳에 발언을 입력하세요. (최대 200자)",
        )
        st.caption(f"{len(message)} / 200")
        speak_col, pass_col = st.columns([1.2, 1])
        if speak_col.button(
            "💬 발언하기",
            key="action.SPEAK",
            disabled=locked or "SPEAK" not in legal or not message.strip(),
            use_container_width=True,
            type="primary",
        ):
            _queue_command(
                game_id=game_id, snapshot=snapshot, command_type="SPEAK", message=message
            )
        if pass_col.button(
            "PASS",
            key="action.PASS",
            disabled=locked or "PASS" not in legal,
            use_container_width=True,
        ):
            _queue_command(game_id=game_id, snapshot=snapshot, command_type="PASS")
        st.caption("🔒 제출 후에는 내용을 변경할 수 없습니다.")


def _render_night_action(*, game_id: str, snapshot: dict[str, Any]) -> None:
    """역할은 안내에만 사용하고 Backend가 허용한 밤 대상만 선택지로 제공한다."""

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    window = _window(snapshot)
    pending = _pending_for_window(game_id=game_id, window=window)
    role = str(me.get("role", "CITIZEN"))
    title, guidance, submit_label = {
        "MAFIA": (
            "공격할 플레이어를 선택해 주세요",
            "자신을 제외한 생존자 한 명을 공격할 수 있습니다.",
            "공격 제출",
        ),
        "DETECTIVE": (
            "조사할 플레이어를 선택해 주세요",
            "자신을 제외한 생존자 한 명의 진영을 확인할 수 있습니다.",
            "조사 제출",
        ),
        "DOCTOR": (
            "보호할 플레이어를 선택해 주세요",
            "Backend가 허용한 생존자 한 명을 보호할 수 있습니다.",
            "보호 제출",
        ),
    }.get(role, ("밤이 되었습니다", "모두 조용히 행동을 선택하고 있습니다.", "행동 제출"))

    with st.container(key="night-action-panel", border=True):
        header_col, timer_col = st.columns([2, 1])
        header_col.markdown(f"### 🌙 밤 {game.get('round', 1)} · 행동 선택")
        remaining = _remaining_text(window.get("remaining_ms"))
        timer_col.markdown(f"### ⏱ {remaining}" if remaining else "### ⏱ 대기 중")
        st.divider()
        st.markdown(f"## {title}")
        st.caption(guidance)
        _render_pending_feedback(pending=pending)

        legal = set(snapshot.get("legal_actions", []))
        targets = _valid_targets(window)
        if "SUBMIT_NIGHT_ACTION" not in legal or not targets:
            if window.get("has_submitted") or (pending and pending.get("status") == "SUCCEEDED"):
                st.success("밤 행동을 제출했습니다. 다른 플레이어의 선택을 기다리고 있습니다.")
            elif role == "CITIZEN":
                st.info("시민은 밤에 선택할 행동이 없습니다. 아침이 올 때까지 기다려 주세요.")
            else:
                st.info("다른 플레이어의 행동이 끝나기를 기다리고 있습니다.")
            return

        locked = _is_locked(window=window, pending=pending)
        option_ids = [str(target["player_id"]) for target in targets]
        names = {
            str(target["player_id"]): str(target.get("display_name", "플레이어"))
            for target in targets
        }
        target_id = st.radio(
            "대상 선택",
            option_ids,
            index=None,
            format_func=lambda value: names.get(value, "플레이어"),
            disabled=locked,
            key=f"form.night_target.{window.get('window_id', 'current')}",
        )
        if st.button(
            submit_label,
            key="action.SUBMIT_NIGHT_ACTION",
            disabled=locked or target_id is None,
            use_container_width=True,
            type="primary",
        ):
            _queue_command(
                game_id=game_id,
                snapshot=snapshot,
                command_type="SUBMIT_NIGHT_ACTION",
                target_player_id=target_id,
            )
        st.caption("🔒 첫 제출 후에는 선택을 변경할 수 없습니다.")


def _render_vote_action(*, game_id: str, snapshot: dict[str, Any]) -> None:
    """공개 요약과 함께 Backend가 확정한 투표 후보만 단일 선택으로 제공한다."""

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    window = _window(snapshot)
    pending = _pending_for_window(game_id=game_id, window=window)
    targets = _valid_targets(window)
    phase = str(game.get("phase", "DAY_VOTE"))
    phase_label = {
        "DAY_VOTE": "투표",
        "REVOTE": "재투표",
        "FINAL_ACCUSATION": "최종 지목",
    }.get(phase, "투표")

    with st.container(key="vote-action-panel", border=True):
        title_col, timer_col = st.columns([2, 1])
        title_col.markdown(f"### ☀️ 낮 {game.get('day_number', 1)}일차 · {phase_label}")
        remaining = _remaining_text(window.get("remaining_ms"))
        timer_col.markdown(f"### ⏱ {remaining}" if remaining else "### ⏱ 대기 중")
        _render_vote_summary(snapshot=snapshot, phase_label=phase_label)
        st.divider()
        st.subheader("처형할 플레이어를 선택해 주세요")
        st.caption("Backend가 확정한 생존 후보 중 한 명에게 투표합니다.")
        _render_pending_feedback(pending=pending)
        if "SUBMIT_VOTE" not in set(snapshot.get("legal_actions", [])) or not targets:
            if window.get("has_submitted") or (pending and pending.get("status") == "SUCCEEDED"):
                st.success("투표를 제출했습니다. 집계 결과를 기다리고 있습니다.")
            else:
                st.info("다른 플레이어의 투표를 기다리고 있습니다.")
            return
        locked = _is_locked(window=window, pending=pending)
        options = [str(target["player_id"]) for target in targets]
        names = {
            str(target["player_id"]): str(target.get("display_name", "플레이어"))
            for target in targets
        }
        target_id = st.radio(
            "대상 선택",
            options,
            index=None,
            format_func=lambda value: f"🤖 {names.get(value, '플레이어')}",
            captions=["생존"] * len(options),
            disabled=locked,
            horizontal=True,
            key=f"form.vote_target.{window.get('window_id', 'current')}",
        )
        remaining_ms = window.get("remaining_ms")
        if isinstance(remaining_ms, int) and 0 < remaining_ms <= 15_000:
            st.warning("투표 마감까지 15초 이하 남았습니다.")
        if st.button(
            "투표 제출  →",
            key="action.SUBMIT_VOTE",
            disabled=locked or target_id is None,
            use_container_width=True,
            type="primary",
        ):
            _queue_command(
                game_id=game_id,
                snapshot=snapshot,
                command_type="SUBMIT_VOTE",
                target_player_id=target_id,
            )
        st.caption("🔒 첫 제출 후에는 선택을 변경할 수 없습니다.")


def _render_vote_summary(*, snapshot: dict[str, Any], phase_label: str) -> None:
    """공개 event에서 밤 결과만 찾아 현재 투표 단계와 함께 짧게 요약한다."""

    # 개별 발언·투표 대상은 요약에 다시 노출하지 않는다. 공개가 허용된 밤 확정 결과와
    # 현재 game phase만 사용해 참고용 문장을 만들며, 승패나 처형 결과는 추론하지 않는다.
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    player_names = {
        str(player.get("player_id")): str(player.get("display_name", "플레이어"))
        for player in snapshot.get("players", [])
        if isinstance(player, dict)
    }
    latest_night: str | None = None
    for event in snapshot.get("public_events", []):
        if not isinstance(event, dict) or event.get("event_type") != "NIGHT_RESOLVED":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        round_number = data.get("round", game.get("round", 1))
        killed_id = data.get("killed_player_id")
        killed_name = player_names.get(str(killed_id)) if killed_id else None
        result = f"{killed_name} 사망" if killed_name else "사망자 없음"
        latest_night = f"🌙 밤 {round_number}: {result}"

    with st.container(key="vote-summary", border=True):
        st.markdown("**공개 타임라인 요약**")
        if latest_night:
            st.write(latest_night)
        st.write(f"☀️ 낮 {game.get('day_number', 1)}일차: 토론 종료")
        st.write(f"☀️ 낮 {game.get('day_number', 1)}일차: {phase_label} 진행 중")


def _queue_command(
    *,
    game_id: str,
    snapshot: dict[str, Any],
    command_type: str,
    message: str | None = None,
    target_player_id: str | None = None,
) -> None:
    """검증된 command를 다음 렌더 주기에 전송하도록 session에 고정한다."""

    try:
        command = build_command(
            snapshot=snapshot,
            command_type=command_type,
            message=message,
            target_player_id=target_player_id,
        )
    except ValueError as error:
        st.error(str(error))
        return
    st.session_state["game.command_pending"] = {
        "status": "PENDING_TO_RENDER",
        "game_id": game_id,
        "command": command,
        "idempotency_key": str(uuid4()),
    }
    st.rerun()


def _process_pending(*, client: ApiClient, game_id: str, snapshot: dict[str, Any]) -> None:
    """pending command를 한 번 전송하고 terminal 결과 뒤 snapshot을 교체한다."""

    pending = st.session_state.get("game.command_pending")
    if not isinstance(pending, dict):
        return
    if pending.get("game_id") != game_id:
        st.session_state.pop("game.command_pending", None)
        return
    if pending.get("status") == "PENDING_TO_RENDER":
        pending["status"] = "IN_FLIGHT"
        st.session_state["game.command_pending"] = pending
        st.rerun()
    if pending.get("status") != "IN_FLIGHT":
        return
    try:
        response = client.submit_command(
            game_id=game_id,
            command=pending["command"],
            idempotency_key=pending["idempotency_key"],
        )
        refreshed = client.get_game(game_id)
        st.session_state["game.latest_snapshot"] = refreshed
        st.session_state["game.command_pending"] = {
            **pending,
            "status": "SUCCEEDED",
            "response": response,
        }
    except ApiResponseError as error:
        status = "RETRYABLE_UNKNOWN" if error.status_code >= 500 else "REJECTED"
        st.session_state["game.command_pending"] = {**pending, "status": status, "code": error.code}
    except (ApiUnavailableError, ValueError) as error:
        st.session_state["game.command_pending"] = {
            **pending,
            "status": "RETRYABLE_UNKNOWN",
            "code": getattr(error, "code", "DEPENDENCY_UNAVAILABLE"),
        }
    st.rerun()


def _render_pending_feedback(*, pending: dict[str, Any] | None) -> None:
    """terminal 상태를 숨기지 않고 같은 요청 재확인을 제공한다."""

    if not pending:
        return
    status = pending.get("status")
    if status in {"PENDING_TO_RENDER", "IN_FLIGHT"}:
        st.info("제출 내용을 확인하고 있습니다.")
    elif status == "SUCCEEDED":
        st.success("행동이 제출되었습니다.")
    elif status == "RETRYABLE_UNKNOWN":
        st.warning("제출 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다.")
        if st.button("같은 요청 다시 확인", key="action.retry_pending"):
            st.session_state["game.command_pending"] = {**pending, "status": "PENDING_TO_RENDER"}
            st.rerun()
    elif status == "REJECTED":
        st.error("현재 게임 상태가 바뀌어 요청이 처리되지 않았습니다. 최신 상태를 기다려 주세요.")


def _pending_for_window(*, game_id: str, window: dict[str, Any]) -> dict[str, Any] | None:
    """다른 게임이나 이미 지나간 행동 창의 pending 상태가 새 입력을 잠그지 않게 한다."""

    pending = st.session_state.get("game.command_pending")
    if not isinstance(pending, dict) or pending.get("game_id") != game_id:
        return None
    command = pending.get("command") if isinstance(pending.get("command"), dict) else {}
    command_window = command.get("window_id")
    current_window = window.get("window_id")
    if command_window and current_window and command_window != current_window:
        st.session_state.pop("game.command_pending", None)
        return None
    return pending


def _window(snapshot: dict[str, Any]) -> dict[str, Any]:
    """nullable action_window를 화면에서 다루기 쉬운 빈 mapping으로 변환한다."""

    window = snapshot.get("action_window")
    return window if isinstance(window, dict) else {}


def _valid_targets(window: dict[str, Any]) -> list[dict[str, Any]]:
    """식별자가 있는 Backend valid_targets만 원래 순서대로 반환한다."""

    targets = window.get("valid_targets", [])
    if not isinstance(targets, list):
        return []
    return [target for target in targets if isinstance(target, dict) and target.get("player_id")]


def _is_locked(*, window: dict[str, Any], pending: dict[str, Any] | None) -> bool:
    """일시정지·제출 완료·마감·처리 중 상태에서는 모든 행동 입력을 잠근다."""

    pending_status = pending.get("status") if pending else None
    remaining = window.get("remaining_ms")
    expired = isinstance(remaining, int) and remaining <= 0
    return bool(
        window.get("paused")
        or window.get("has_submitted")
        or expired
        or pending_status in {"PENDING_TO_RENDER", "IN_FLIGHT", "SUCCEEDED", "RETRYABLE_UNKNOWN"}
    )


def _current_speaker(*, snapshot: dict[str, Any], player_id: Any) -> str | None:
    """공개 player 목록에서 현재 발언자의 표시 이름만 찾는다."""

    for player in snapshot.get("players", []):
        if isinstance(player, dict) and player.get("player_id") == player_id:
            return str(player.get("display_name", "플레이어"))
    return None


def _remaining_text(value: Any) -> str | None:
    """Backend remaining_ms를 내림한 분:초 형식으로 표시한다."""

    if not isinstance(value, int):
        return None
    seconds = max(0, value) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
