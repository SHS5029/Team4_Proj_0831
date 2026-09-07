"""현재 snapshot의 행동 창을 단계별 입력 화면으로 표현한다."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError
from frontend_user.core.commands import build_command

ASSET_DIR = Path(__file__).with_name("browser_components") / "action_attention"
ACTION_ATTENTION_COMPONENT = st.components.v2.component(
    name="ai_mafia_action_attention",
    html=(ASSET_DIR / "index.html").read_text(encoding="utf-8"),
    js=(ASSET_DIR / "index.js").read_text(encoding="utf-8"),
)

ACTION_PANEL_CSS = """
<style>
[class*="st-key-discussion-action-panel"] {
  margin-top: .9rem; padding: .95rem !important; border: 1px solid #8eb6ff !important;
  border-radius: .75rem !important;
  background: linear-gradient(135deg, #f9fbff, #eef4ff) !important;
  box-shadow: 0 .7rem 1.8rem rgba(20, 42, 81, .10);
}
[class*="st-key-discussion-action-panel"] textarea {
  min-height: 7.3rem; border-color: #8eb6ff; background: #fff !important;
}
[class*="st-key-night-action-panel"] {
  padding: 1.15rem !important; border: 1px solid #203a60 !important;
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
  padding: 1.1rem !important; border: 1px solid #d2dceb !important;
  border-radius: .8rem !important; color: #000 !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
/* 투표의 밝은 카드에서는 테마와 선택·잠금 상태에 관계없이 문구를 검게 표시한다.
   제출 버튼의 흰색 글자를 덮지 않도록 읽기 영역과 후보 선택 영역에만 적용한다. */
.st-key-vote-action-panel :is(h2, h3, h4, [data-testid="stCaptionContainer"],
  [data-testid="stWidgetLabel"], [data-testid="stRadio"], [data-testid="stText"],
  .st-key-vote-summary [data-testid="stMarkdownContainer"]),
.st-key-vote-action-panel :is(h2, h3, h4, [data-testid="stCaptionContainer"],
  [data-testid="stWidgetLabel"], [data-testid="stRadio"], [data-testid="stText"],
  .st-key-vote-summary [data-testid="stMarkdownContainer"]) * {
  color: #000 !important;
  -webkit-text-fill-color: #000 !important;
  opacity: 1 !important;
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
[class*="st-key-current-action-status"] {
  position: fixed; left: 50%; bottom: max(.75rem, env(safe-area-inset-bottom));
  z-index: 1000; width: min(calc(100vw - 2rem), 760px); transform: translateX(-50%);
  padding: .7rem .9rem !important; border: 1px solid #79a8ff !important;
  border-radius: .75rem !important; color: #10203b !important; background: #f8fbff !important;
  box-shadow: 0 .8rem 2rem rgba(7, 20, 38, .2);
}
.current-action-status-line {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
}
.current-action-status-line strong { color: #174ea6; }
.current-action-status-time {
  flex: 0 0 auto; font-variant-numeric: tabular-nums; font-weight: 800;
}
.action-sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
[data-testid="stMainBlockContainer"]:has([class*="st-key-current-action-status"]) {
  padding-bottom: 7rem;
}
@media (max-width: 768px) {
  [class*="st-key-night-action-panel"] { min-height: auto; }
  [class*="st-key-night-action-panel"] div[role="radiogroup"] > label { flex-basis: 45%; }
  [class*="st-key-vote-action-panel"] { min-height: auto; }
  [class*="st-key-vote-action-panel"] div[role="radiogroup"] > label { flex-basis: 45%; }
  [class*="st-key-current-action-status"] {
    bottom: max(.5rem, env(safe-area-inset-bottom)); width: calc(100vw - 1rem);
  }
  .current-action-status-line { align-items: flex-start; gap: .5rem; }
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

    remaining = _countdown_remaining_ms(game_id=game_id, snapshot=snapshot)
    # 주기 갱신은 행동 패널만 다시 그린다. POST 처리와 게임 조회는 fragment 밖에
    # 남겨 초당 네트워크 요청이나 결과 불명 command의 자동 재전송을 만들지 않는다.
    interval = 1 if _timer_is_running(snapshot) and remaining and remaining > 0 else None
    st.fragment(run_every=interval)(_render_actions)(game_id=game_id, snapshot=snapshot)


def _render_actions(*, game_id: str, snapshot: dict[str, Any]) -> None:
    """표시용 잔여 시간만 복사해 적용하고 원본 서버 snapshot은 변경하지 않는다."""

    remaining = _countdown_remaining_ms(game_id=game_id, snapshot=snapshot)
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    window = _window(snapshot)
    snapshot = {**snapshot, "action_window": {
        **window, "remaining_ms": remaining,
        "paused": bool(window.get("paused") or game.get("status") == "SAVED"),
    }}
    phase = str(game.get("phase", ""))
    _render_action_status(snapshot=snapshot)
    if phase in DISCUSSION_PHASES:
        _render_discussion(game_id=game_id, snapshot=snapshot)
    elif phase == "NIGHT_ACTION":
        _render_night_action(game_id=game_id, snapshot=snapshot)
    elif phase in VOTE_PHASES:
        _render_vote_action(game_id=game_id, snapshot=snapshot)
    # 이 component는 화면을 그리지 않는다. 같은 fragment tick에서 임계 경고의
    # 변경만 live region에 알리고, 새 window일 때만 행동 입력으로 focus를 옮긴다.
    _mount_action_attention(snapshot=snapshot)


def _render_discussion(*, game_id: str, snapshot: dict[str, Any]) -> None:
    """내 발언 차례에만 200자 입력과 PASS를 제공하고 나머지는 대기시킨다."""

    window = _window(snapshot)
    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    legal = set(snapshot.get("legal_actions", []))
    my_turn = window.get("deadline_at") is not None or window.get("turn_player_id") == me.get("player_id")
    pending = _pending_for_window(game_id=game_id, window=window)

    with st.container(key="discussion-action-panel", border=True):
        _render_pending_feedback(pending=pending)
        if not my_turn or not ({"SPEAK", "PASS"} & legal):
            if window.get("has_submitted"):
                st.info("발언이 제출되었습니다. 다음 차례를 기다려 주세요.")
            else:
                st.info("다른 플레이어의 발언을 기다리고 있습니다.")
            return

        locked = _is_locked(window=window, pending=pending)
        message_key = f"form.message.{window.get('window_id', 'current')}"
        message = st.text_area(
            "발언 내용",
            max_chars=200,
            height=146,
            disabled=locked,
            key=message_key,
            placeholder="이곳에 발언을 입력하세요. (최대 200자)",
        )
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
    """역할별 밤 행동을 서버가 허용한 대상 안에서만 선택하게 한다."""

    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    window = _window(snapshot)
    pending = _pending_for_window(game_id=game_id, window=window)
    role = str(me.get("role", "CITIZEN"))
    title, _, submit_label = {
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
    role_label = {
        "MAFIA": "마피아",
        "DETECTIVE": "탐정",
        "DOCTOR": "의사",
        "CITIZEN": "시민",
    }.get(role, "확인 중")

    with st.container(key="night-action-panel", border=True):
        st.markdown("### 🌙 밤 행동")
        st.divider()
        time_label, time_value = st.columns([1, 1])
        time_label.markdown("**남은 시간**")
        time_value.markdown(f"## {_countdown_text(snapshot)}")
        st.caption("제한 시간 내에 행동을 선택하고 제출하세요.")
        st.markdown(f"**내 역할: {role_label}**")
        st.divider()
        st.markdown("#### 행동 선택")
        st.caption(title)
        _render_pending_feedback(pending=pending)

        legal = set(snapshot.get("legal_actions", []))
        targets = _valid_targets(snapshot=snapshot, command_type="SUBMIT_NIGHT_ACTION")
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
        target_key = f"form.night_target.{game_id}.{window.get('window_id', 'current')}"
        _clear_invalid_selection(key=target_key, options=option_ids)
        target_id = st.radio(
            "대상 선택",
            option_ids,
            index=None,
            format_func=lambda value: names.get(value, "플레이어"),
            disabled=locked,
            key=target_key,
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
    targets = _valid_targets(snapshot=snapshot, command_type="SUBMIT_VOTE")
    phase = str(game.get("phase", "DAY_VOTE"))
    phase_label = {
        "DAY_VOTE": "투표",
        "REVOTE": "재투표",
        "FINAL_ACCUSATION": "최종 지목",
    }.get(phase, "투표")

    with st.container(key="vote-action-panel", border=True):
        st.markdown(f"### ⚑ {phase_label}")
        st.divider()
        time_label, time_value = st.columns([1, 1])
        time_label.markdown("**남은 시간**")
        time_value.markdown(f"## {_countdown_text(snapshot)}")
        st.caption("⚠ 제한 시간 내에 투표를 완료하세요.")
        st.divider()
        if phase == "FINAL_ACCUSATION":
            st.markdown("#### 최종 판정할 플레이어를 지목해 주세요")
            st.warning(
                "이번 투표는 마지막 판정 투표입니다. 마피아를 찾으면 시민이 승리하고, "
                "시민을 선택하면 마피아가 승리합니다."
            )
            st.caption(
                "동률이어도 재투표하지 않으며, 동률 후보 중 한 명을 서버가 결정적으로 선택합니다."
            )
            submit_label = "최종 지목 제출  →"
        else:
            st.markdown("#### 투표할 대상을 선택하세요.")
            submit_label = "투표 제출  →"
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
        target_key = f"form.vote_target.{game_id}.{window.get('window_id', 'current')}"
        _clear_invalid_selection(key=target_key, options=options)
        target_id = st.radio(
            "대상 선택",
            options,
            index=None,
            format_func=lambda value: f"🤖 {names.get(value, '플레이어')}",
            captions=["생존"] * len(options),
            disabled=locked,
            horizontal=True,
            key=target_key,
        )
        if st.button(
            submit_label,
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
        st.info("🔒 개별 투표는 공개되지 않으며, 모두 투표를 종료한 뒤 결과가 공개됩니다.")


def _action_status(snapshot: dict[str, Any]) -> tuple[str, str, str | None] | None:
    """현재 인간에게 필요한 행동·시각·임계 경고만 고정 문구로 만든다.

    후보나 자동 선택 대상은 표시하지 않는다. Front는 서버 마감 전 자동 선택 대상을
    알 수 없고, 공개되지 않은 선택을 추정해서도 안 된다.
    """

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    window = _window(snapshot)
    legal = set(snapshot.get("legal_actions", []))
    phase = str(game.get("phase", ""))
    pending = _pending_for_window(game_id=str(game.get("game_id", "")), window=window)
    if _is_locked(window=window, pending=pending):
        return None
    if phase in DISCUSSION_PHASES:
        if (window.get("deadline_at") is None and window.get("turn_player_id") != me.get("player_id")) or not ({"SPEAK", "PASS"} & legal):
            return None
        label = "발언하거나 PASS하세요"
    elif phase == "NIGHT_ACTION" and "SUBMIT_NIGHT_ACTION" in legal:
        label = {
            "MAFIA": "공격 대상을 선택하세요",
            "DETECTIVE": "조사 대상을 선택하세요",
            "DOCTOR": "보호 대상을 선택하세요",
        }.get(str(me.get("role", "")), "밤 행동을 선택하세요")
    elif phase in VOTE_PHASES and "SUBMIT_VOTE" in legal:
        label = (
            "최종 판정 대상을 지목하세요"
            if phase == "FINAL_ACCUSATION"
            else "투표 대상을 선택하세요"
        )
    else:
        return None
    return label, _countdown_text(snapshot), _countdown_warning_text(snapshot)


def _render_action_status(*, snapshot: dict[str, Any]) -> None:
    """페이지를 읽는 동안에도 현재 행동과 잔여 시간을 하단에 유지한다."""

    status = _action_status(snapshot)
    if status is None:
        return
    label, countdown, _ = status
    with st.container(key="current-action-status", border=True):
        st.markdown(
            '<div class="current-action-status-line">'
            f'<span><strong>지금 할 일</strong> · {escape(label)} · '
            f'<strong>남은 시간 {escape(countdown)}</strong></span>'
            "</div>",
            unsafe_allow_html=True,
        )


def _mount_action_attention(*, snapshot: dict[str, Any]) -> None:
    """새 행동 window에서만 브라우저가 행동 영역과 첫 입력에 focus하도록 요청한다."""

    ACTION_ATTENTION_COMPONENT(
        data=_attention_payload(snapshot),
        default={},
        key="action-attention",
    )


def _attention_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """focus 여부와 중복 제거할 live announcement만 browser component에 전달한다."""

    status = _action_status(snapshot)
    warning = _countdown_warning_text(snapshot)
    window_id = _canonical_player_id(_window(snapshot).get("window_id"))
    announcement = None
    if status is not None:
        announcement = f"새 행동: {status[0]}." + (f" {warning}" if warning else "")
    elif warning:
        announcement = warning
    return {
        "active": status is not None and window_id is not None,
        "window_id": window_id,
        "announcement": announcement,
    }


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
        else:
            # 투표 단계라 해도 첫날 또는 공개 이벤트 복원 직후에는 확정된 밤 결과가
            # 아직 없을 수 있다. 빈 카드로 보이지 않게 하되, Front가 사망자나 밤
            # 결과를 추측해서 만들어 내지 않도록 사실 그대로 안내한다.
            st.caption("현재 표시할 공개 밤 결과가 없습니다.")


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
        if command_type in {"SUBMIT_VOTE", "SUBMIT_NIGHT_ACTION"}:
            game = snapshot.get("game", {})
            targets = _valid_targets(snapshot=snapshot, command_type=command_type)
            if (_canonical_player_id(game.get("game_id")) != _canonical_player_id(game_id)
                    or _canonical_player_id(game_id) is None
                    or command["target_player_id"] not in {target["player_id"] for target in targets}):
                raise ValueError("현재 선택할 수 없는 대상입니다. 최신 후보에서 다시 선택해 주세요.")
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
        if pending["command"].get("type") == "SPEAK" and _window(snapshot).get("deadline_at") is not None:
            st.session_state[f"form.message.{game_id}"] = ""
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


def _canonical_player_id(value: Any) -> str | None:
    """외부 식별자를 UUID로 정규화해 형식 변형으로 후보 검증을 우회하지 못하게 한다."""

    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _valid_targets(*, snapshot: dict[str, Any], command_type: str) -> list[dict[str, Any]]:
    """서버 후보를 현재 게임 생존자와 교차 확인하며 후보를 임의로 보충하지 않는다."""

    targets = _window(snapshot).get("valid_targets")
    players = snapshot.get("players")
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    game_id = _canonical_player_id(game.get("game_id"))
    actor_id = _canonical_player_id(me.get("player_id"))
    if not isinstance(targets, list) or not isinstance(players, list) or game_id is None:
        return []
    if command_type == "SUBMIT_VOTE" and actor_id is None:
        return []
    alive = {
        player_id
        for player in players
        if isinstance(player, dict) and player.get("alive") is True
        and ("game_id" not in player or _canonical_player_id(player["game_id"]) == game_id)
        and (player_id := _canonical_player_id(player.get("player_id"))) is not None
    }
    result = []
    seen = set()
    for target in targets:
        if not isinstance(target, dict):
            continue
        player_id = _canonical_player_id(target.get("player_id"))
        if (player_id not in alive or player_id in seen
                or (command_type == "SUBMIT_VOTE" and player_id == actor_id)
                or ("alive" in target and target["alive"] is not True)
                or ("game_id" in target and _canonical_player_id(target["game_id"]) != game_id)):
            continue
        seen.add(player_id)
        result.append({"player_id": player_id, "display_name": str(target.get("display_name", "플레이어"))})
    return result


def _clear_invalid_selection(*, key: str, options: list[str]) -> None:
    """동률 재투표·사망 반영 뒤 사라진 선택은 해제하고 다른 후보로 대체하지 않는다."""

    if st.session_state.get(key) is not None and st.session_state[key] not in options:
        st.session_state[key] = None


def _is_locked(*, window: dict[str, Any], pending: dict[str, Any] | None) -> bool:
    """일시정지·제출 완료·마감·처리 중 상태에서는 모든 행동 입력을 잠근다."""

    pending_status = pending.get("status") if pending else None
    remaining = window.get("remaining_ms")
    expired = type(remaining) is int and remaining <= 0
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


def _render_turn_status(*, snapshot: dict[str, Any]) -> None:
    """현재 window와 본인 projection으로 차례·제출 상태를 표시한다.

    낮 발언은 Backend가 제공한 turn_player_id를 이름으로 변환한다. 밤 행동과
    투표는 여러 플레이어가 동시에 제출하므로 다른 사람의 개별 선택은 노출하지
    않고, 본인의 제출 필요 여부와 현재 단계의 진행 방식만 안내한다.
    """

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    window = _window(snapshot)
    me = snapshot.get("me") if isinstance(snapshot.get("me"), dict) else {}
    legal = set(snapshot.get("legal_actions", []))
    kind = str(window.get("kind", ""))
    if kind == "SPEECH":
        if window.get("has_submitted") and window.get("turn_player_id") == me.get("player_id"):
            st.caption("내 행동: 발언 제출 완료 · 다음 차례를 기다리는 중")
        elif window.get("turn_player_id") == me.get("player_id"):
            st.caption("내 행동: 확인한 사건 정보를 바탕으로 의견을 말해주세요.")
        return
    if kind == "NIGHT":
        if "SUBMIT_NIGHT_ACTION" in legal:
            st.caption("밤 행동: 내 선택을 제출해야 합니다.")
        elif window.get("has_submitted"):
            st.caption("밤 행동: 내 선택 제출 완료 · 다른 플레이어의 선택을 기다리는 중")
        else:
            st.caption("밤 행동: 역할별 선택을 모으는 중입니다.")
        return
    if kind in {"VOTE", "REVOTE", "FINAL_VOTE"}:
        if "SUBMIT_VOTE" in legal:
            st.caption(f"{game.get('day_number', 1)}일차 투표: 내 투표를 제출해야 합니다.")
        elif window.get("has_submitted"):
            st.caption("투표: 내 투표 제출 완료 · 다른 플레이어의 투표를 기다리는 중")
        else:
            st.caption("투표: 모든 생존자가 동시에 투표하는 단계입니다.")


def _server_datetime(value: Any) -> datetime | None:
    """서버가 보낸 timezone 포함 시각만 사용하고 로컬 벽시계로 대체하지 않는다."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _timer_is_running(snapshot: dict[str, Any]) -> bool:
    """저장·일시정지·무제한 창에는 주기 갱신을 등록하지 않는다."""

    window = _window(snapshot)
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    return bool(
        game.get("status") == "IN_PROGRESS" and not window.get("paused")
        and _server_datetime(window.get("deadline_at")) is not None
        and _server_datetime(window.get("server_time")) is not None
    )


def _countdown_remaining_ms(*, game_id: str, snapshot: dict[str, Any]) -> int | None:
    """서버 마감과 시각의 차이에서 수신 후 경과 시간만 빼 표시용 잔여 시간을 만든다.

    같은 응답을 다시 렌더링해도 기준점을 재설정하지 않는다. 더 최신 서버 시각이나
    새 창·재개 deadline을 받았을 때만 기준점을 교체하여 서버 보정을 반영한다.
    결과는 입력 잠금 안내에만 사용하며 서버 상태·자동 선택·command를 만들지 않는다.
    """

    window = _window(snapshot)
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    remaining = window.get("remaining_ms")
    remaining = max(0, remaining) if type(remaining) is int else None
    if window.get("paused") or game.get("status") == "SAVED":
        st.session_state.pop("game.action_clock", None)
        return remaining
    if not _timer_is_running(snapshot):
        st.session_state.pop("game.action_clock", None)
        return None

    server_time = _server_datetime(window.get("server_time"))
    deadline = _server_datetime(window.get("deadline_at"))
    identity = (game_id, window.get("window_id"), window.get("deadline_at"))
    now = monotonic()
    anchor = st.session_state.get("game.action_clock")
    if (not isinstance(anchor, dict) or anchor.get("identity") != identity
            or server_time > anchor["server_time"]):
        duration = max(0, round((deadline - server_time).total_seconds() * 1000))
        anchor = {
            "identity": identity,
            "server_time": server_time,
            "started_at": now,
            "remaining_ms": min(duration, remaining) if remaining is not None else duration,
        }
        st.session_state["game.action_clock"] = anchor
    elapsed = max(0, int((now - anchor["started_at"]) * 1000))
    return max(0, anchor["remaining_ms"] - elapsed)


def _countdown_text(snapshot: dict[str, Any]) -> str:
    """저장된 시간과 시간 제한 없는 창을 진행 중 countdown과 구분해 표시한다."""

    window = _window(snapshot)
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    remaining = _remaining_text(window.get("remaining_ms"))
    if window.get("paused") or game.get("status") == "SAVED":
        return f"{remaining} · 일시 정지" if remaining else "일시 정지 · 시간 제한 없음"
    if window.get("kind") == "SPEECH" and window.get("deadline_at") is None:
        return "시간 제한 없음"
    return remaining or "시간 확인 중"


def _render_countdown_warning(snapshot: dict[str, Any]) -> None:
    """마감 경고는 표시만 갱신하고 최종 해소는 기존 서버 동기화를 기다린다."""

    warning = _countdown_warning_text(snapshot)
    if warning == "입력 시간이 끝났습니다. 서버의 확정 결과를 기다리고 있습니다.":
        st.info("입력 시간이 끝났습니다. 서버의 확정 결과를 기다리고 있습니다.")
    elif warning:
        st.warning(warning)


def _countdown_warning_text(snapshot: dict[str, Any]) -> str | None:
    """서버 clock이 유효할 때만 phase별 임계 경고의 고정 문구를 반환한다."""

    if not _timer_is_running(snapshot):
        return None
    window = _window(snapshot)
    remaining = window.get("remaining_ms")
    if type(remaining) is not int:
        return None
    if remaining <= 0:
        return "입력 시간이 끝났습니다. 서버의 확정 결과를 기다리고 있습니다."
    if window.get("kind") == "NIGHT" and remaining <= 10_000:
        return "밤 행동 마감까지 10초 이하 남았습니다."
    if window.get("kind") in {"VOTE", "REVOTE", "FINAL_VOTE"}:
        if remaining <= 5_000:
            return "투표 마감까지 5초 이하 남았습니다."
        if remaining <= 15_000:
            return "투표 마감까지 15초 이하 남았습니다."
    return None


def _remaining_text(value: Any) -> str | None:
    """1초 미만이 남아도 00:00으로 오인하지 않도록 초 단위로 올림해 표시한다."""

    if type(value) is not int:
        return None
    seconds = (max(0, value) + 999) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
