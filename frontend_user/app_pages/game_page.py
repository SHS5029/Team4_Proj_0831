"""진행 중 게임의 공통 shell과 공개 timeline 화면."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from html import escape
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from frontend_user.components.action_panel import render as render_action_panel
from frontend_user.components.action_panel import render_status_bar
from frontend_user.components.sync_bridge import apply_sync, mount_sse
from frontend_user.components.theme import render_application_header, render_header_back_button
from frontend_user.core.api_client import ApiResponseError, ApiUnavailableError
from frontend_user.core.scenario_images import scenario_image_path
from frontend_user.core.sync import SyncEnvelopeError
from frontend_user.core.time_display import display_timestamp
from frontend_user.core.view_models import own_private_view, public_players, public_timeline

CLOSED_PLAYER_SELECTION = "__closed__"

GAME_PAGE_CSS = """
<style>
:root {
  --game-blue: #2468ed;
  --game-blue-soft: #eaf2ff;
  --game-dark: #071426;
  --game-ink: #172033;
  --game-muted: #65728b;
  --game-border: #d9e2ef;
  --game-bg: #f4f7fb;
  --game-green: #16864d;
}
[data-testid="stAppViewContainer"] { color: var(--game-ink); background: var(--game-bg); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] {
  width: min(100%, 1240px); max-width: 1240px; padding: 0 1.4rem 3rem;
}
.game-header {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 4.2rem; margin: 0 -1.4rem 1.6rem; padding: 0 1.5rem;
  color: #fff; background: var(--game-dark); border-bottom: 1px solid #24324c;
}
.game-brand { font-size: 1.55rem; font-weight: 800; letter-spacing: -.06em; }
.game-status {
  display: inline-flex; align-items: center; gap: .4rem; margin-left: 1rem;
  padding: .42rem .7rem; border: 1px solid #2b3b57; border-radius: .55rem;
  color: #d8e2f3; font-size: .78rem;
}
.game-status::before {
  content: ""; width: .45rem; height: .45rem; border-radius: 50%; background: #31c477;
}
.game-status-polling::before { background: #f2b84b; }
.game-status-stale::before { background: #ef6666; }
.game-nav { display: flex; gap: .7rem; color: #d8e2f3; font-size: .82rem; }
.game-nav span { padding: .55rem .75rem; border: 1px solid #2b3b57; border-radius: .5rem; }
.game-phase-title {
  margin: 0; color: var(--game-ink); font-size: clamp(1.7rem, 4vw, 2.35rem);
  letter-spacing: -.045em;
}
.game-phase-caption { margin: .35rem 0 1rem; color: var(--game-muted); }
[class*="st-key-current-action-region"] { margin-bottom: 1.1rem; }
[class*="st-key-game-player-panel"],
[class*="st-key-game-my-panel"] {
  min-height: 40rem; padding: 1rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-game-timeline-panel"] {
  padding: 1rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-side-action-region"] [class*="st-key-night-action-panel"],
[class*="st-key-side-action-region"] [class*="st-key-vote-action-panel"] {
  min-height: 40rem;
}
[class*="st-key-side-action-region"] [class*="st-key-night-action-panel"] div[role="radiogroup"] > label {
  flex: 1 1 29%; min-width: 0; padding: .7rem .35rem;
}
[class*="st-key-side-action-region"] [class*="st-key-vote-action-panel"] div[role="radiogroup"] > label {
  flex: 1 1 100%; min-width: 0; padding: .65rem .7rem;
}
[class*="st-key-game-timeline-scroll"] {
  margin-top: .7rem; padding-right: .2rem;
}
.game-panel-title {
  margin-bottom: .1rem; color: var(--game-ink); font-size: 1.05rem; font-weight: 800;
}
.game-panel-caption { margin-bottom: .85rem; color: var(--game-muted); font-size: .78rem; }
.game-my-label { margin-bottom: .18rem; color: var(--game-muted); font-size: .72rem; font-weight: 700; }
.game-my-row { display: flex; align-items: center; justify-content: space-between; gap: .6rem; }
.game-my-player { color: var(--game-ink); font-size: .86rem; font-weight: 800; }
.game-my-role { margin-top: .08rem; color: var(--game-blue); font-size: .96rem; font-weight: 850; line-height: 1.2; }
.game-my-icon { flex: 0 0 auto; font-size: 1.6rem; line-height: 1; }
.game-my-status { display: inline-block; width: max-content; margin-top: .1rem; padding: .1rem .35rem; border-radius: .3rem; color: var(--game-green); background: #e5f8ec; font-size: .68rem; font-weight: 750; line-height: 1.2; }
[class*="st-key-game-my-summary"] {
  min-height: 0 !important; margin-bottom: .65rem; padding: .28rem .55rem !important;
}
[class*="st-key-game-my-summary"] [data-testid="stMarkdownContainer"] p {
  margin: 0 !important; line-height: 1.3 !important;
}
[class*="st-key-game-player-row"],
[class*="st-key-spectator-player-row"] {
  min-height: 0 !important; margin-bottom: .25rem; padding: .18rem .35rem !important;
}
[class*="st-key-game-player-row"] [data-testid="stHorizontalBlock"],
[class*="st-key-spectator-player-row"] [data-testid="stHorizontalBlock"] {
  gap: .35rem;
}
[class*="st-key-game-player-row"] [data-testid="stButton"] button,
[class*="st-key-spectator-player-row"] [data-testid="stButton"] button {
  justify-content: center !important; text-align: center !important;
}
.game-player {
  display: flex; align-items: center; gap: .7rem; margin-bottom: .55rem; padding: .65rem .7rem;
  border: 1px solid var(--game-border); border-radius: .65rem; background: #fff;
}
.game-player-icon {
  display: grid; flex: 0 0 2.35rem; width: 2.35rem; height: 2.35rem;
  place-items: center; border-radius: .55rem; background: var(--game-blue-soft); font-size: 1.15rem;
}
.game-player-name {
  flex: 1; min-width: 0; color: var(--game-ink); font-size: .88rem; font-weight: 750;
}
.game-player-me {
  margin-left: .28rem; padding: .18rem .35rem; border: 1px solid #8cb5ff;
  border-radius: .3rem; color: var(--game-blue); font-size: .67rem;
}
.game-alive {
  padding: .2rem .42rem; border-radius: .35rem; color: var(--game-green);
  background: #e5f8ec; font-size: .68rem;
}
.game-dead {
  padding: .2rem .42rem; border-radius: .35rem; color: #a04444;
  background: #fde9e9; font-size: .68rem;
}
.game-scene {
  min-height: 11rem; display: grid; position: relative; place-items: center; overflow: hidden;
  margin-bottom: .8rem; border-radius: .65rem;
  background: radial-gradient(circle at 72% 25%, #355987 0 2%, transparent 3%),
              linear-gradient(145deg, #07162b, #163d68);
}
.game-scene::after { content: "📡  🖥️  🔴 ON AIR  🖥️  🕰️"; color: #dceaff; font-size: 1.25rem; }
.game-private-banner {
  margin-bottom: .85rem; padding: .55rem .7rem; border-radius: .45rem;
  color: #51617b; background: #f5f7fb; font-size: .76rem; text-align: center;
}
.game-role-card {
  margin-bottom: .8rem; padding: .9rem; border: 1px solid var(--game-border);
  border-radius: .7rem; background: linear-gradient(135deg, #fff, #f6f9ff);
}
.game-role-icon { font-size: 2.2rem; }
.game-role-name { color: var(--game-blue); font-size: 1.2rem; font-weight: 800; }
[class*="st-key-game-alibi"], [class*="st-key-game-observation"] {
  padding: .75rem .85rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .65rem !important; background: #fff !important;
}
[class*="st-key-game-alibi"] h4, [class*="st-key-game-observation"] h4 {
  margin-bottom: .15rem; color: #354765; font-size: .9rem;
}
.game-event {
  margin-top: .6rem; padding: .65rem .8rem; border-left: 3px solid var(--game-blue);
  border-radius: .25rem .55rem .55rem .25rem; color: #354765; background: #f6f9ff;
}
[class*="st-key-game-public-event"] {
  margin-top: .65rem; padding: .7rem .8rem !important;
  border: 1px solid var(--game-border) !important;
  border-radius: .65rem !important; background: #fff !important;
}
[class*="st-key-spectator-player-panel"],
[class*="st-key-spectator-timeline-panel"],
[class*="st-key-spectator-my-panel"] {
  min-height: 39rem; padding: 1rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-spectator-notice"] {
  margin-bottom: .9rem; padding: .9rem 1rem !important; border: 1px solid #8eb6ff !important;
  border-radius: .7rem !important; background: linear-gradient(135deg, #f8fbff, #edf4ff) !important;
}
[class*="st-key-spectator-controls"] {
  margin-top: .9rem; padding: .85rem !important; border: 1px solid #8eb6ff !important;
  border-radius: .7rem !important; background: #fff !important;
}
.spectator-section-title { margin: .8rem 0 .45rem; font-size: 1rem; font-weight: 800; }
.spectator-death-note {
  margin-top: .75rem; padding: .75rem; border-radius: .55rem;
  color: #536078; background: #f4f6f9; font-size: .78rem;
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: 0 .8rem 2rem; }
  .game-header { margin: 0 -.8rem 1rem; padding: 0 .9rem; }
  .game-nav { display: none; }
  [class*="st-key-game-player-panel"],
  [class*="st-key-game-my-panel"],
  [class*="st-key-spectator-player-panel"],
  [class*="st-key-spectator-timeline-panel"],
  [class*="st-key-spectator-my-panel"] { min-height: auto; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: .01ms !important; animation-duration: .01ms !important;
  }
}
</style>
"""

# 밤 화면은 역할 공개와 같은 어두운 배경을 쓰되, 낮 화면의 색상을 덮지 않도록
# NIGHT_ACTION phase에서만 별도로 주입한다. 공개 발언·역할 등 서버 문자열은 이
# 정적 스타일에 넣지 않고 기존 Streamlit 텍스트 렌더링을 유지한다.
NIGHT_GAME_PAGE_CSS = """
<style>
[data-testid="stAppViewContainer"] {
  color: #e8f0ff;
  background:
    radial-gradient(circle at 76% 22%, rgba(52, 101, 164, .32), transparent 24rem),
    linear-gradient(115deg, #06111f 0%, #0a1e38 52%, #06111f 100%) !important;
}
[class*="st-key-game-player-panel"],
[class*="st-key-game-timeline-panel"],
[class*="st-key-game-selected-player-summary"] {
  border-color: #29486e !important;
  background: rgba(9, 28, 53, .92) !important;
  box-shadow: 0 .8rem 2rem rgba(0, 5, 18, .28);
}
[class*="st-key-game-player-panel"] [data-testid="stMarkdownContainer"],
[class*="st-key-game-timeline-panel"] [data-testid="stMarkdownContainer"],
[class*="st-key-game-selected-player-summary"] [data-testid="stMarkdownContainer"],
[class*="st-key-game-player-panel"] [data-testid="stCaptionContainer"],
[class*="st-key-game-timeline-panel"] [data-testid="stCaptionContainer"],
[class*="st-key-game-selected-player-summary"] [data-testid="stCaptionContainer"] {
  color: #d9e6fb !important;
}
[class*="st-key-game-player-panel"] [data-testid="stBaseButton-secondary"],
[class*="st-key-game-player-panel"] [data-testid="stVerticalBlockBorderWrapper"] {
  border-color: #29486e !important;
  background: rgba(13, 38, 70, .75) !important;
}
[data-testid="stChatMessage"] {
  border: 1px solid #29486e;
  border-radius: .7rem;
  background: rgba(13, 38, 70, .72);
}
[class*="st-key-night-transition-banner"] {
  margin-bottom: .8rem;
  padding: 1rem 1.1rem !important;
  border: 1px solid #466d9d !important;
  border-radius: .8rem !important;
  color: #eaf2ff !important;
  background: linear-gradient(135deg, rgba(20, 56, 102, .95), rgba(7, 21, 42, .96)) !important;
  box-shadow: 0 .8rem 2rem rgba(0, 5, 18, .24);
}
[class*="st-key-night-transition-banner"] h3,
[class*="st-key-night-transition-banner"] [data-testid="stCaptionContainer"] {
  color: #eaf2ff !important;
}
</style>
"""

PHASE_LABELS = {
    "DAY_DISCUSSION": "사건 설명과 낮 토론",
    "NIGHT_ACTION": "밤 행동",
    "DAY_VOTE": "처형 투표",
    "REVOTE": "재투표",
    "FINAL_DISCUSSION": "마지막 토론",
    "FINAL_ACCUSATION": "최종 지목",
}
RIGHT_ACTION_PHASES = frozenset({"NIGHT_ACTION", "DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"})

ROLE_PRESENTATION = {
    "MAFIA": ("마피아", "🥷"),
    "DETECTIVE": ("탐정", "🕵️"),
    "DOCTOR": ("의사", "🩺"),
    "CITIZEN": ("시민", "🧑"),
}

# player ID의 공개 문자열만 이용해 같은 player에게 같은 색을 부여한다. 이 색은
# 역할·진영·행동 결과와 무관한 발언 식별용 표현이며 게임 정보를 암시하지 않는다.
PLAYER_CHAT_PRESENTATIONS = (
    ("🔵", "#2563eb"),
    ("🟢", "#15803d"),
    ("🟣", "#7e22ce"),
    ("🟠", "#c2410c"),
    ("🔴", "#be123c"),
    ("🟡", "#a16207"),
    ("🟤", "#92400e"),
    ("⚫", "#334155"),
    ("⚪", "#64748b"),
    ("🔷", "#0f766e"),
)


def render(snapshot: dict[str, Any]) -> None:
    """snapshot을 authoritative source로 사용해 desktop 3열 shell을 표시한다."""

    # GET snapshot·sync 결과가 화면의 단일 기준이다. Backend가 제공한 문자열은
    # 일반 Streamlit 텍스트로만 렌더링하고, CSS용 HTML에는 정적 장식만 사용한다.
    client = st.session_state["game.client"]
    game = snapshot.get("game", {})
    game_id = game.get("game_id")
    _process_shell_pending(client=client, game_id=str(game_id))
    envelope = mount_sse(
        backend_url=client.config.api_url,
        game_id=str(game.get("game_id")),
        user_id=client.user_id,
        last_sequence=int(game.get("last_sequence", 0)),
        after_state_version=int(game.get("state_version", 0)),
    )
    tick = st.session_state.get("game.sync_tick", 0)
    if envelope is None and (not tick or st.session_state.get("game.sync_component_failed")):
        try:
            envelope = client.get_sync(
                game_id=str(game.get("game_id")),
                after_state_version=int(game.get("state_version", 0)),
                after_sequence=int(game.get("last_sequence", 0)),
            )
        except Exception:
            envelope = None
    try:
        snapshot = apply_sync(snapshot=snapshot, envelope=envelope)
        tick = st.session_state.get("game.sync_tick")
        tick_changed = tick is not None and tick != st.session_state.get("game.activity_tick")
        if _has_sync_updates(envelope) or tick_changed:
            # SSE delta는 공통 공개 operation 중심이므로 사용자별 legal_actions와
            # valid_targets가 비어 있을 수 있고, sync SNAPSHOT에는 메모리의 AI
            # 기록이 없을 수 있다. 실제 수신 때 같은 사용자·게임의 GET으로 보강하며
            # 재시작 전 run의 기록을 복사하지 않고 최신 응답의 빈 배열도 그대로 따른다.
            try:
                response = client.get_game(str(game.get("game_id")))
                refreshed = response.get("data") if isinstance(response.get("data"), dict) else response
                if isinstance(refreshed, dict) and isinstance(refreshed.get("game"), dict):
                    refreshed_game = refreshed["game"]
                    if (refreshed_game.get("game_id") != game_id
                            or refreshed.get("me", {}).get("player_id") != snapshot.get("me", {}).get("player_id")
                            or any(type(refreshed_game.get(key)) is not int
                                   or refreshed_game[key] < snapshot["game"][key]
                                   for key in ("state_version", "last_sequence"))):
                        raise ValueError("INVALID_RESPONSE")
                    snapshot = refreshed
                    st.session_state["game.activity_tick"] = tick
            except Exception:
                # sync는 이미 원자적으로 반영했으므로 재조회 일시 실패 시에도
                # 화면을 비우지 않고 다음 event 또는 polling에서 다시 시도한다.
                pass
    except SyncEnvelopeError:
        # sequence/version gap은 기존 화면을 계속 신뢰하면 안 되므로, 부분 적용
        # 없이 Backend의 전체 snapshot을 다시 읽는다. 재조회도 실패한 경우에만
        # STALE로 전환해 사용자가 명시적으로 복구를 시도할 수 있게 한다.
        try:
            response = client.get_game(str(game.get("game_id")))
            refreshed = response.get("data") if isinstance(response.get("data"), dict) else response
            if not isinstance(refreshed, dict) or not isinstance(refreshed.get("game"), dict):
                raise ValueError("INVALID_RESPONSE")
            snapshot = refreshed
            st.session_state["game.latest_snapshot"] = snapshot
            st.session_state["game.sync_status"] = "POLLING"
        except Exception:
            st.session_state["game.sync_status"] = "STALE"
            st.warning("게임 상태를 다시 확인하고 있어요.")
    else:
        # SSE·polling으로 반영한 authoritative snapshot을 다음 Streamlit rerun에도
        # 보존한다. 이 값을 저장하지 않으면 component 상태만 갱신되고, 다른 화면
        # 전환이나 재렌더링에서 이전 phase·action window가 다시 사용될 수 있다.
        st.session_state["game.latest_snapshot"] = snapshot
        st.session_state.setdefault("game.sync_status", "POLLING")

    game = snapshot.get("game", {})
    scenario = snapshot.get("scenario", {})
    me = own_private_view(snapshot)
    connection = st.session_state.get("game.sync_status", "POLLING")
    connection_label = {
        "LIVE": "연결됨",
        "POLLING": "다시 연결 중",
        "STALE": "상태 확인 필요",
    }.get(connection, "연결 확인 중")
    st.markdown(GAME_PAGE_CSS, unsafe_allow_html=True)
    spectating = me.get("alive") is False
    day_number = game.get("day_number", 1)
    phase = str(game.get("phase", "확인 중"))
    if phase == "NIGHT_ACTION":
        st.markdown(NIGHT_GAME_PAGE_CSS, unsafe_allow_html=True)
    if spectating:
        header_phase = f"☀️ 낮 {day_number}일차 · 관전 중"
    else:
        phase_label = PHASE_LABELS.get(phase, phase)
        phase_icon = "🌙" if phase == "NIGHT_ACTION" else "☀️"
        cycle_label = (
            f"밤 {game.get('round', 1)}" if phase == "NIGHT_ACTION" else f"낮 {day_number}일차"
        )
        header_phase = f"{phase_icon} {cycle_label} · {phase_label}"

    def render_header_actions() -> None:
        save_column, back_column = st.columns(2)
        with save_column:
            # 저장 노출은 관전자 여부가 아니라 Backend legal_actions가 최종 결정한다.
            # 저장된 관전 게임도 기존 복구 흐름을 유지하기 위해 같은 제어를 사용한다.
            if not spectating or game.get("status") == "SAVED":
                _render_save_control(
                    client=client,
                    game_id=str(game.get("game_id")),
                    snapshot=snapshot,
                )
        with back_column:
            render_header_back_button(current_page="game")

    render_application_header(
        title="AI 마피아",
        connection_label=connection_label,
        phase_label=header_phase,
        action_renderer=render_header_actions,
    )
    # 낮·밤·투표·관전·저장 분기 전에 한 번만 렌더링해 모든 진행 화면 하단에
    # 현재 할 일과 Backend 기준 남은 시간을 같은 위치로 유지한다.
    render_status_bar(game_id=str(game.get("game_id")), snapshot=snapshot)
    # 응답 유실 뒤 서버가 phase를 변경했어도 기존 요청의 재시도 UI를 유지한다.
    # 정상 시작 버튼은 역할 공개 화면에서만 표시한다.
    for command_type in ("BEGIN_GAME", "RESUME"):
        pending = st.session_state.get(SHELL_COMMANDS[command_type][2])
        if (isinstance(pending, dict) and pending.get("game_id") == str(game_id)
                and pending.get("status") in SHELL_LOCKED
                and not (command_type == "RESUME" and game.get("status") == "SAVED")):
            _render_shell_command(client=client, game_id=str(game_id), snapshot=snapshot, command_type=command_type)

    if game.get("status") == "SAVED":
        render_saved_control(client=client, snapshot=snapshot)
        left, center = st.columns([0.82, 2.55])
        with left:
            _render_players(snapshot=snapshot, me=me, phase=str(phase))
        with center:
            _render_timeline(snapshot=snapshot, scenario=scenario, phase=str(phase), day_number=day_number)
            _render_agent_activity(snapshot=snapshot)
        return

    if spectating:
        _render_spectator_layout(
            client=client,
            game_id=str(game.get("game_id")),
            snapshot=snapshot,
            me=me,
        )
        return

    action_in_right_panel = phase in RIGHT_ACTION_PHASES
    if action_in_right_panel:
        # 밤 행동·투표에서는 공개 대화와 중복되는 내 정보·플레이어 목록 카드를
        # 제거하고, 역할·대상·제출에 집중하는 행동 카드만 전체 폭으로 표시한다.
        with st.container(key="action-only-region"):
            _render_visible_action_panel(
                client=client,
                game_id=str(game.get("game_id")),
                snapshot=snapshot,
            )
        return

    # 낮 토론은 보조 내 정보 열을 없애고 대화와 발언 입력에 화면 폭을 우선 배정한다.
    left, center = st.columns([0.82, 2.55])
    with left:
        _render_players(snapshot=snapshot, me=me, phase=str(phase))
    with center:
        _render_timeline(
            snapshot=snapshot,
            scenario=scenario,
            phase=str(phase),
            day_number=day_number,
        )
        with st.container(key="current-action-region"):
            _render_visible_action_panel(
                client=client,
                game_id=str(game.get("game_id")),
                snapshot=snapshot,
            )
        _render_agent_activity(snapshot=snapshot)

    # 사망자는 위의 전용 분기에서 반환되므로 이 아래에는 생존자 입력만 존재한다.


def _render_visible_action_panel(**kwargs: Any) -> None:
    """백그라운드에서 복귀한 상태를 확인하기 전에는 오래된 행동 입력을 표시하지 않는다."""

    if st.session_state.get("game.sync_hidden"):
        st.info("최신 게임 상태를 확인한 뒤 행동을 선택할 수 있습니다.")
        return
    render_action_panel(**kwargs)


def _has_sync_updates(envelope: dict[str, Any] | None) -> bool:
    """검증된 sync 교체·변경 수신 때만 GET으로 부가 projection을 보강한다."""

    if not isinstance(envelope, dict):
        return False
    data = envelope.get("data", envelope)
    if not isinstance(data, dict):
        return False
    if data.get("mode") == "SNAPSHOT":
        return True
    operations = data.get("operations")
    return data.get("mode") == "DELTA" and isinstance(operations, list) and bool(operations)


def _render_game_progress(*, game: dict[str, Any], compact: bool = False) -> None:
    """최대 다섯 번째 밤 규칙을 기준으로 현재 게임의 대략적인 진행 위치를 표시한다.

    게임은 승패 조건에 따라 더 일찍 끝날 수 있으므로, 이 값은 남은 시간을 예측하거나
    Front가 종료를 판정하는 용도가 아니다. 현재 공개 phase와 day_number만 사용한
    화면용 진행 안내다.
    """

    day_number = game.get("day_number", 1)
    if type(day_number) is not int:
        day_number = 1
    day_number = min(max(day_number, 1), 5)
    phase = str(game.get("phase", "DAY_DISCUSSION"))
    phase_weight = {
        "DAY_DISCUSSION": 0.15,
        "DAY_VOTE": 0.45,
        "REVOTE": 0.55,
        "NIGHT_ACTION": 0.75,
        "FINAL_DISCUSSION": 0.85,
        "FINAL_ACCUSATION": 0.95,
    }.get(phase, 0.1)
    progress_value = min(100, max(1, round(((day_number - 1 + phase_weight) / 5) * 100)))
    progress_text = f"{progress_value}%" if compact else f"게임 진행률 · 낮 {day_number}일차 / 최대 5번째 밤"
    st.progress(progress_value, text=progress_text)
    if not compact:
        st.caption("승패 조건이 충족되면 최대 진행 전에도 게임이 종료될 수 있습니다.")


def _render_phase_briefing(*, snapshot: dict[str, Any], phase: str, day_number: Any) -> None:
    """공개 대화 panel의 고정 상단에서 AI GM 브리핑을 표시한다."""

    if type(day_number) is not int or day_number < 1:
        day_number = 1
    player_names = {
        str(player.get("player_id")): str(player.get("display_name", "플레이어"))
        for player in public_players(snapshot)
    }
    transition_types = {
        "GAME_BEGAN",
        "NIGHT_RESOLVED",
        "VOTE_RESOLVED",
        "PLAYER_EXECUTED",
    }
    latest_transition = next(
        (
            event
            for event in reversed(public_timeline(snapshot))
            if event.get("event_type") in transition_types
        ),
        None,
    )
    latest_text = (
        _event_text(event=latest_transition, player_names=player_names)
        if isinstance(latest_transition, dict)
        else None
    )
    latest_night = next(
        (
            event
            for event in reversed(public_timeline(snapshot))
            if event.get("event_type") == "NIGHT_RESOLVED"
        ),
        None,
    )

    if phase == "NIGHT_ACTION":
        briefing = latest_text or "낮 토론이 마감되었습니다. 각자에게 허용된 행동만 선택해 주세요."
        with st.container(key="night-transition-banner", border=True):
            st.markdown("### 🌙 밤이 되었습니다")
            st.caption("모두 조용히 행동을 선택하세요.")
        _render_gm_briefing(
            title="🌙 AI GM · 밤 브리핑",
            message=f"{briefing} 밤 행동과 선택 대상은 공개되지 않습니다.",
        )
        return

    if day_number >= 2 and isinstance(latest_night, dict):
        night_text = _event_text(event=latest_night, player_names=player_names)
        players = public_players(snapshot)
        alive_count = sum(1 for player in players if player.get("alive"))
        total_count = len(players)
        default_briefing = (
            f"{day_number}일차 낮이 되었습니다. 다시 토론을 진행해 주세요. "
            f"{night_text} 현재 생존자는 전체 {total_count}명 중 "
            f"{alive_count}명입니다."
        )
    elif day_number == 1:
        default_briefing = (
            "사건 정보와 플레이어들의 알리바이를 비교해 마피아를 추리하세요. "
            "첫날은 투표 없이 토론만 진행합니다. 의심되는 점은 발언하고, "
            "할 말이 없으면 PASS를 선택하세요."
        )
    else:
        default_briefing = "공개된 사건 정보와 앞선 기록을 확인한 뒤 의견을 나눠 주세요."
    # GAME_BEGAN event에는 Backend의 기존 시작 문구가 들어 있을 수 있다.
    # 1일차는 Front에서 정의한 짧은 안내를 우선해 과거 event 문구가 다시 보이지
    # 않게 하고, 2일차 이후에는 공개된 최신 밤 결과를 브리핑으로 사용한다.
    briefing = (
        default_briefing
        if day_number == 1 or (day_number >= 2 and isinstance(latest_night, dict))
        else latest_text or default_briefing
    )
    _render_gm_briefing(
        title=f"☀️ AI GM · 낮 {day_number}일차 브리핑",
        message=briefing,
    )


def _render_gm_briefing(*, title: str, message: str) -> None:
    """AI GM 안내를 플레이어 발언과 구분되는 네이비 카드로 표시한다.

    브리핑은 외부 문자열이 포함될 수 있으므로 HTML로 해석하지 않도록 escape하고,
    Streamlit 알림 컴포넌트의 기본 초록색 테마 대신 고정된 안내 카드 색을 사용한다.
    """

    st.markdown(
        '<div style="margin:.7rem 0 .85rem;padding:.85rem 1rem;'
        'border:1px solid #29486e;border-radius:.7rem;'
        'color:#dceaff;background:linear-gradient(135deg,#102b50,#071a33);'
        'box-shadow:0 .6rem 1.4rem rgba(7,20,38,.16);">'
        f'<div style="margin-bottom:.35rem;color:#fff;font-weight:800;">'
        f'{escape(title)}</div>'
        f'<div style="white-space:pre-wrap;overflow-wrap:anywhere;">'
        f'{escape(message)}</div></div>',
        unsafe_allow_html=True,
    )


def _render_players(*, snapshot: dict[str, Any], me: dict[str, Any], phase: str) -> None:
    """좌석순 공개 player와 선택한 player의 최근 공개 발언을 함께 표시한다."""

    players = public_players(snapshot)
    presentations = _player_presentations(players)
    alive_count = sum(1 for player in players if player.get("alive"))
    selected_player_id = _selected_player_id(snapshot=snapshot, players=players, me=me)
    with st.container(key="game-player-panel", border=True):
        role_name, role_icon = ROLE_PRESENTATION.get(
            me.get("role"),
            ("확인 중", "❔"),
        )
        with st.container(key="game-my-summary", border=True):
            st.markdown('<div class="game-my-label">내 정보</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="game-my-row">'
                '<div><div class="game-my-player">플레이어 1</div>'
                f'<div class="game-my-role">{escape(str(role_name))}</div>'
                f'<div class="game-my-status">{"생존 중" if me.get("alive") else "관전 중"}</div></div>'
                f'<div class="game-my-icon" aria-hidden="true">{escape(str(role_icon))}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        st.markdown('<div class="game-panel-title">플레이어 목록</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="game-panel-caption">전체 {len(players)}명 · 생존 {alive_count}명</div>',
            unsafe_allow_html=True,
        )
        st.caption("플레이어를 선택하면 해당 플레이어의 공개 발언을 확인할 수 있어요.")
        for player in players:
            if player.get("player_id") == me.get("player_id"):
                continue
            alive = bool(player.get("alive"))
            mine = player.get("player_id") == me.get("player_id")
            status_class = "game-alive" if alive else "game-dead"
            status_label = "생존" if alive else "탈락"
            color_marker, _ = _presentation_for_player(
                player_id=player.get("player_id"),
                presentations=presentations,
            )
            with st.container(key=f"game-player-row.{player.get('player_id')}", border=True):
                columns = st.columns([0.3, 2.35, 0.8])
                # 역할이나 플레이어 종류 아이콘은 노출하지 않고, 공개 대화와 연결되는
                # 색상 표식만 남겨 목록 행을 작고 빠르게 읽을 수 있게 한다.
                columns[0].write(color_marker)
                name = str(player.get("display_name", "플레이어"))
                mine_label = " · 나" if mine else ""
                if columns[1].button(
                    f"{name}{mine_label}",
                    key=f"game.player_select.{player.get('player_id')}",
                    width="stretch",
                ):
                    player_id = str(player.get("player_id"))
                    selection_key = _player_selection_key(snapshot)
                    if selected_player_id == player_id:
                        selected_player_id = None
                        st.session_state[selection_key] = CLOSED_PLAYER_SELECTION
                    else:
                        selected_player_id = player_id
                        st.session_state[selection_key] = selected_player_id
                columns[2].markdown(
                    f'<span class="{status_class}">{status_label}</span>',
                    unsafe_allow_html=True,
                )
                revealed_role = player.get("revealed_role")
                if revealed_role:
                    st.caption(f"공개 역할: {revealed_role}")
            if str(player.get("player_id")) == selected_player_id:
                _render_selected_player_summary(
                    snapshot=snapshot,
                    players=players,
                    selected_player_id=selected_player_id,
                )


def _player_selection_key(snapshot: dict[str, Any]) -> str:
    """게임별 player 선택 상태를 분리해 다른 게임의 선택이 섞이지 않게 한다."""

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    game_id = str(game.get("game_id", "current"))
    return f"game.selected_player.{game_id}"


def _selected_player_id(
    *, snapshot: dict[str, Any], players: list[dict[str, Any]], me: dict[str, Any],
) -> str | None:
    """선택값이 없거나 오래됐으면 본인, 그다음 첫 공개 player로 안전하게 초기화한다."""

    player_ids = [str(player.get("player_id")) for player in players if player.get("player_id")]
    if not player_ids:
        return None
    selection_key = _player_selection_key(snapshot)
    selected = st.session_state.get(selection_key)
    if selected == CLOSED_PLAYER_SELECTION:
        return None
    if selected not in player_ids:
        own_id = str(me.get("player_id"))
        selected = own_id if own_id in player_ids else player_ids[0]
        st.session_state[selection_key] = selected
    return str(selected)


def _selected_player_speeches(
    *, snapshot: dict[str, Any], selected_player_id: str | None, player_names: dict[str, str],
) -> list[str]:
    """선택한 player가 실제로 말한 공개 발언만 최신 순으로 반환한다.

    투표·밤 행동·AI 내부 판단을 '요약'이라는 이름으로 섞어 표시하지 않는다. 선택한
    공개 player ID와 일치하는 PLAYER_SPOKE event의 message만 사용한다.
    """

    if selected_player_id is None:
        return []
    messages: list[str] = []
    for event in public_timeline(snapshot):
        if event.get("event_type") != "PLAYER_SPOKE":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if str(data.get("player_id")) != selected_player_id:
            continue
        message = _event_text(event=event, player_names=player_names)
        if message:
            messages.append(message)
    return messages


def _render_selected_player_summary(
    *, snapshot: dict[str, Any], players: list[dict[str, Any]], selected_player_id: str | None,
) -> None:
    """선택 player의 최근 공개 발언을 왼쪽 목록 바로 아래에서 빠르게 확인하게 한다."""

    selected = next(
        (player for player in players if str(player.get("player_id")) == selected_player_id),
        None,
    )
    if selected is None:
        return
    player_names = {
        str(player.get("player_id")): str(player.get("display_name", "플레이어"))
        for player in players
    }
    messages = _selected_player_speeches(
        snapshot=snapshot,
        selected_player_id=selected_player_id,
        player_names=player_names,
    )
    name = str(selected.get("display_name", "플레이어"))
    # 선택이 바뀔 때 이전 요약 영역과 Streamlit 위젯 식별자가 충돌하지 않게
    # player별로 고유한 container key를 사용한다. 발언이 없어도 빈 목록을 정상 상태로 처리한다.
    summary_key = f"game-selected-player-summary.{selected_player_id or 'none'}"
    with st.container(key=summary_key, border=True):
        st.markdown("#### 💬 선택한 플레이어의 대화")
        st.caption(f"{name} · 공개 발언 {len(messages)}회")
        if not messages:
            st.caption("아직 공개된 발언이 없습니다.")
            return
        for message in messages[-3:]:
            # 공개 발언도 사용자 입력이므로 Markdown·HTML로 해석하지 않고 일반 텍스트로 출력한다.
            st.text(f"• {message}")


def _render_spectator_layout(
    *,
    client: Any,
    game_id: str,
    snapshot: dict[str, Any],
    me: dict[str, Any],
) -> None:
    """사망한 인간에게 공개 정보와 본인 정보만 남긴 관전 3열 화면을 표시한다."""

    left, center, right = st.columns([0.95, 2.05, 1.05])
    with left:
        _render_spectator_players(snapshot=snapshot, me=me)
    with center:
        with st.container(key="spectator-notice", border=True):
            st.markdown("### ℹ️ 플레이어가 사망하여 관전 모드로 전환되었습니다.")
            st.caption("게임은 AI 플레이어끼리 계속 진행되며 공개 범위의 정보만 표시됩니다.")
        _render_spectator_timeline(snapshot=snapshot, me=me)
        _render_agent_activity(snapshot=snapshot)
        _render_spectator_controls(client=client, game_id=game_id, snapshot=snapshot)
    with right:
        _render_spectator_private(snapshot=snapshot, me=me)


def _render_spectator_players(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """공개 player를 생존자와 사망자로 나누되 숨은 역할은 표시하지 않는다."""

    players = public_players(snapshot)
    presentations = _player_presentations(players)
    alive_players = [player for player in players if player.get("alive")]
    dead_players = [player for player in players if not player.get("alive")]
    selected_player_id = _selected_player_id(snapshot=snapshot, players=players, me=me)
    with st.container(key="spectator-player-panel", border=True):
        st.markdown(f"### 생존자 ({len(alive_players)})")
        st.caption("플레이어를 선택하면 해당 플레이어의 공개 발언을 확인할 수 있어요.")
        for player in alive_players:
            selected_player_id = _render_spectator_player_row(
                player=player,
                mine=player.get("player_id") == me.get("player_id"),
                selected_player_id=selected_player_id,
                selection_key=_player_selection_key(snapshot),
                presentations=presentations,
            )
            if str(player.get("player_id")) == selected_player_id:
                _render_selected_player_summary(
                    snapshot=snapshot,
                    players=players,
                    selected_player_id=selected_player_id,
                )
        st.markdown(f"### 사망자 ({len(dead_players)})")
        for player in dead_players:
            selected_player_id = _render_spectator_player_row(
                player=player,
                mine=player.get("player_id") == me.get("player_id"),
                selected_player_id=selected_player_id,
                selection_key=_player_selection_key(snapshot),
                presentations=presentations,
            )
            if str(player.get("player_id")) == selected_player_id:
                _render_selected_player_summary(
                    snapshot=snapshot,
                    players=players,
                    selected_player_id=selected_player_id,
                )


def _render_spectator_player_row(
    *, player: dict[str, Any], mine: bool, selected_player_id: str | None, selection_key: str,
    presentations: dict[str, tuple[str, str]],
) -> str | None:
    """공개 이름과 컬러 표식만 사용해 관전 목록 한 행을 그린다."""

    color_marker, _ = _presentation_for_player(
        player_id=player.get("player_id"),
        presentations=presentations,
    )
    with st.container(key=f"spectator-player-row.{player.get('player_id')}", border=True):
        marker_col, name_col = st.columns([0.3, 2.2])
        # 색상 표식은 공개 대화의 player별 색상과 연결하고, 종류를 드러내는
        # 로봇·사람 아이콘과 좌석·생존 상태 텍스트는 제거해 목록 정보를 단순하게 유지한다.
        marker_col.write(color_marker)
        name = str(player.get("display_name", "플레이어"))
        if name_col.button(
            f"{name}" + (" · 나" if mine else ""),
            key=f"spectator.player_select.{player.get('player_id')}",
            use_container_width=True,
        ):
            player_id = str(player.get("player_id"))
            if selected_player_id == player_id:
                selected_player_id = None
                st.session_state[selection_key] = CLOSED_PLAYER_SELECTION
            else:
                selected_player_id = player_id
                st.session_state[selection_key] = selected_player_id
    return selected_player_id


def _render_spectator_timeline(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """관전자에게 허용된 공개 event만 시간 순서대로 표시한다."""

    events = _player_conversation_events(snapshot)
    player_names = {
        str(player.get("player_id")): str(player.get("display_name", "플레이어"))
        for player in public_players(snapshot)
    }
    presentations = _player_presentations(public_players(snapshot))
    with st.container(key="spectator-timeline-panel", border=True):
        title_column, progress_column = st.columns([3, 1])
        title_column.markdown("### ▣ 공개 타임라인")
        with progress_column:
            st.caption("게임 진행률")
            game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
            _render_game_progress(game=game, compact=True)
        _render_incident_summary(snapshot.get("scenario"), me=me)
        _render_phase_briefing(
            snapshot=snapshot,
            phase=str(game.get("phase", "DAY_DISCUSSION")),
            day_number=game.get("day_number", 1),
        )
        # 관전 중에도 공개 발언이 계속 누적되므로, timeline만 고정 높이로 스크롤해
        # 하단의 빠른 진행·저장 제어가 화면 밖으로 밀리지 않게 한다.
        with st.container(key="spectator-timeline-scroll", height=560, border=False):
            if not events:
                st.info("아직 플레이어의 공개 발언이 없습니다.")
            for event in events:
                _render_public_chat_event(
                    event=event,
                    player_names=player_names,
                    presentations=presentations,
                    my_player_id=me.get("player_id"),
                )


def _render_incident_summary(scenario: Any, *, me: dict[str, Any] | None = None) -> None:
    """사건 정보를 공개 대화 위에 접을 수 있는 고정 영역으로 표시한다.

    사건 내용은 대화 event가 아니므로 player 대화 스크롤 안에 넣지 않는다. 개인
    알리바이와 관찰 단서는 snapshot의 ``me``에서만 읽어 다른 player에게 노출하지
    않는다. 패널은 기본 접힘으로 두고 필요한 경우 사용자가 직접 펼친다.
    """

    details = scenario if isinstance(scenario, dict) else {}
    private = me if isinstance(me, dict) else {}
    with st.expander("🗂️ 사건 내용", expanded=False):
        image_path = scenario_image_path(details)
        if image_path is not None:
            # 사건 이미지는 공개 시나리오의 분위기만 전달하며, 개인 알리바이·단서는
            # 이미지 자산에 포함하지 않는다. 자산이 없으면 기존 텍스트 화면을 유지한다.
            st.image(str(image_path), width="stretch")
        st.markdown(f"#### {details.get('title', '사건 정보')}")
        victim = details.get("victim", "알 수 없음")
        locations = details.get("locations", [])
        location_text = ", ".join(str(item) for item in locations) if isinstance(locations, list) else ""
        st.caption(f"피해자: {victim} · 장소: {location_text}")
        st.write(str(details.get("background", "")))
        st.markdown("**내 알리바이**")
        st.write(str(private.get("alibi", "없음")))
        st.markdown("**사건 단서**")
        st.write(str(private.get("observation", "없음")))


def _render_spectator_private(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """관전 중에도 유지되는 본인의 역할·사망 시점·기존 private 정보만 표시한다."""

    role_name, role_icon = ROLE_PRESENTATION.get(me.get("role"), ("확인 중", "❔"))
    own_public = next(
        (
            player
            for player in public_players(snapshot)
            if player.get("player_id") == me.get("player_id")
        ),
        {},
    )
    with st.container(key="spectator-my-panel", border=True):
        st.markdown("### 내 정보 (당신)")
        st.markdown(f"## {role_icon} {role_name}")
        st.error("사망")
        st.markdown("#### 🔒 내 정보 (비공개)")
        st.caption("이 정보는 다른 플레이어에게 공개되지 않습니다.")
        with st.container(border=True):
            st.markdown("**확인된 사실**")
            st.write(f"역할: {role_name}")
            st.write(f"알리바이: {str(me.get('alibi', '없음'))}")
            st.write(f"관찰: {str(me.get('observation', '없음'))}")
        _render_investigation_results(snapshot=snapshot)
        eliminated_phase = own_public.get("eliminated_phase")
        eliminated_round = own_public.get("eliminated_round")
        with st.container(border=True):
            st.markdown("**◷ 기록**")
            if eliminated_round is not None:
                st.write(f"탈락 시점: {eliminated_round}번째 밤·낮 진행 중")
            if eliminated_phase:
                st.write(f"탈락 단계: {_phase_public_label(str(eliminated_phase))}")
            st.caption("사망 원인은 공개 이벤트에 포함된 범위에서만 확인할 수 있습니다.")


def _render_timeline(
    *,
    snapshot: dict[str, Any],
    scenario: dict[str, Any],
    phase: str,
    day_number: Any,
) -> None:
    """사건 설명과 공개 대화를 중앙의 큰 스크롤 영역에 표시한다."""

    with st.container(key="game-timeline-panel", border=True):
        title_column, progress_column = st.columns([3, 1])
        title_column.markdown("### 💬 공개 대화")
        with progress_column:
            st.caption("게임 진행률")
            game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
            _render_game_progress(game=game, compact=True)
        # AI GM 브리핑은 player 발언이 쌓이는 scroll 영역 밖에 둔다. 따라서 최신
        # 대화로 자동 스크롤돼도 낮·밤 전환과 사건의 공개 안내를 계속 확인할 수 있다.
        me = own_private_view(snapshot)
        _render_incident_summary(scenario, me=me)
        _render_phase_briefing(snapshot=snapshot, phase=phase, day_number=day_number)
        events = _player_conversation_events(snapshot)
        # 공개 대화가 게임의 핵심이므로 독립 스크롤 영역을 크게 확보한다. 이벤트가
        # 누적되어도 player 목록·행동 panel의 위치는 유지된다.
        # 입력 panel을 대화 바로 아래에서 함께 볼 수 있도록, 관전용 timeline보다
        # 낮은 높이를 사용한다. 긴 기록은 이 영역에서 최신 발언 중심으로 스크롤한다.
        with st.container(key="game-timeline-scroll", height=360, border=False):
            if not events:
                st.info("아직 플레이어의 공개 발언이 없습니다.")
            player_names = {
                str(player.get("player_id")): str(player.get("display_name", "플레이어"))
                for player in public_players(snapshot)
            }
            presentations = _player_presentations(public_players(snapshot))
            for event in events:
                _render_public_chat_event(
                    event=event,
                    player_names=player_names,
                    presentations=presentations,
                    my_player_id=me.get("player_id"),
                )


def _player_conversation_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """공개 대화 영역에는 player 대화 흐름 event만 남긴다.

    `TURN_OPENED`는 현재 발언자 강조, `PLAYER_PASSED`는 compact 상태 행으로
    표시한다. 게임 시작·투표·밤 결과는 공개 정보여도 player 발언 목록에는 섞지
    않고, 같은 panel의 고정 AI GM 브리핑에서만 안내한다.
    """

    return [
        event
        for event in public_timeline(snapshot)
        if event.get("event_type") in {"TURN_OPENED", "PLAYER_SPOKE", "PLAYER_PASSED"}
    ]


def _render_public_chat_event(
    *,
    event: dict[str, Any],
    player_names: dict[str, str],
    presentations: dict[str, tuple[str, str]],
    my_player_id: str | None = None,
) -> None:
    """공개 발언은 말풍선, 행동은 작은 알림으로 표현하고 외부 문자열을 escape한다."""

    speaker = _event_speaker(event=event, player_names=player_names)
    message = _event_text(event=event, player_names=player_names)
    event_type = event.get("event_type")
    if event_type == "PLAYER_SPOKE":
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        avatar, accent_color = _presentation_for_player(
            player_id=data.get("player_id"),
            presentations=presentations,
        )
        is_mine = my_player_id is not None and str(data.get("player_id")) == str(my_player_id)
        speaker_label = (
            f"{speaker or '플레이어'} (나)"
            if is_mine
            else speaker or "플레이어"
        )
        bubble_background = "#1f4f9a" if is_mine else "#edf1f7"
        bubble_text = "#f7fbff" if is_mine else "#334155"
        bubble_border = "#8eb6ff" if is_mine else accent_color
        with st.chat_message(speaker_label, avatar=avatar):
            st.markdown(
                '<div style="margin:.35rem 0;padding:.65rem 1rem;'
                f'border-left:3px solid {escape(bubble_border)};border-radius:8px;'
                f'background:{escape(bubble_background)};color:{escape(bubble_text)};overflow-wrap:anywhere">'
                f'<strong>{escape(speaker_label)}</strong> · 발언'
                f'<div style="margin-top:.35rem;white-space:pre-wrap">{escape(message)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        return

    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    player_name = player_names.get(str(data.get("player_id")), "플레이어")
    is_mine = my_player_id is not None and str(data.get("player_id")) == str(my_player_id)
    player_label = f"{player_name} (나)" if is_mine else player_name
    if event_type == "TURN_OPENED":
        st.info(f"🗣️ 현재 발언 · {player_label}님이 발언 중입니다.")
        return
    if event_type == "PLAYER_PASSED":
        st.caption(f"↪ {player_label}님이 PASS했습니다.")


def _player_presentations(players: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """좌석순 공개 player에게 최대 10개의 서로 다른 발언 색상 표식을 배정한다.

    색상은 역할·진영·행동과 무관하며, 공개 player 목록의 좌석순만 기준으로 삼는다.
    따라서 게임 중 새로고침해도 같은 좌석의 목록 표식과 대화 아바타가 일치한다.
    """

    presentations: dict[str, tuple[str, str]] = {}
    for index, player in enumerate(players):
        player_id = str(player.get("player_id", ""))
        if player_id:
            presentations[player_id] = PLAYER_CHAT_PRESENTATIONS[index % len(PLAYER_CHAT_PRESENTATIONS)]
    return presentations


def _presentation_for_player(
    *, player_id: Any, presentations: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    """목록에 없는 과거 event도 안전하게 표시할 수 있도록 결정적 보조 색을 반환한다."""

    canonical_id = str(player_id or "")
    presentation = presentations.get(canonical_id)
    if presentation is not None:
        return presentation
    palette_index = sum(ord(character) for character in canonical_id) % len(PLAYER_CHAT_PRESENTATIONS)
    return PLAYER_CHAT_PRESENTATIONS[palette_index]


def _render_private_panel(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """본인에게 허용된 role·사실·private event만 오른쪽 패널에 표시한다."""

    role_name, role_icon = ROLE_PRESENTATION.get(
        me.get("role"),
        ("확인 중", "❔"),
    )
    with st.container(key="game-my-panel", border=True):
        st.markdown('<div class="game-panel-title">내 정보</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="game-private-banner">🔒 이 정보는 나에게만 표시됩니다.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="game-role-icon" aria-hidden="true">{role_icon}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="game-role-name">{role_name}</div>', unsafe_allow_html=True)
        st.success("생존 중" if me.get("alive") else "관전 중")
        with st.container(key="game-alibi", border=True):
            st.markdown("#### ◷ 나의 알리바이")
            st.write(str(me.get("alibi", "없음")))
        with st.container(key="game-observation", border=True):
            st.markdown("#### ◉ 내가 본 것")
            st.write(str(me.get("observation", "없음")))
        _render_investigation_results(snapshot=snapshot)


def _validated_investigation_results(
    snapshot: dict[str, Any], *, expected_game_id: Any,
) -> list[str]:
    """현재 게임의 인간 탐정에게 허용된 조사 결과만 공개 이름과 고정 문구로 투영한다.

    PrivateEvent에는 actor를 추가하지 않는다. 소유권 검사를 거친 snapshot의 me와
    같은 게임의 유일한 인간 player를 연결하고, 폐쇄형 event·data 계약 밖의 필드는
    거부한다. 이미 확정된 과거 결과이므로 현재 본인이나 대상의 생존 여부는 묻지 않는다.
    """

    game = snapshot.get("game")
    me = own_private_view(snapshot)
    players = snapshot.get("players")
    events = me.get("private_events")
    own_id = _canonical_uuid(me.get("player_id"))
    if (not isinstance(game, dict) or not isinstance(players, list)
            or not isinstance(events, list) or me.get("role") != "DETECTIVE"
            or own_id is None or own_id != me.get("player_id")):
        return []
    game_id = _canonical_uuid(game.get("game_id"))
    current_round = game.get("round")
    if (game_id is None or game_id != game.get("game_id") or game_id != expected_game_id
            or type(current_round) is not int or not 0 <= current_round <= 5):
        return []
    names = {}
    human_ids = []
    for player in players:
        if not isinstance(player, dict):
            return []
        player_id = _canonical_uuid(player.get("player_id"))
        name = player.get("display_name")
        if (player_id is None or player_id != player.get("player_id") or player_id in names
                or not isinstance(name, str) or not name.strip()):
            return []
        names[player_id] = " ".join(name.split())
        if player.get("kind") == "HUMAN":
            human_ids.append(player_id)
    if human_ids != [own_id]:
        return []

    results = []
    seen = set()
    for event in events:
        if (not isinstance(event, dict)
                or set(event) != {"event_id", "event_type", "created_at", "data"}
                or event.get("event_type") != "INVESTIGATION_RESULT"):
            continue
        event_id = _canonical_uuid(event.get("event_id"))
        created_at = event.get("created_at")
        data = event.get("data")
        if (event_id is None or event_id != event.get("event_id")
                or not isinstance(created_at, str)
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", created_at) is None
                or not isinstance(data, dict) or set(data) != {"round", "target_player_id", "is_mafia"}):
            continue
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        target_id = _canonical_uuid(data.get("target_player_id"))
        night = data.get("round")
        if (target_id is None or target_id != data.get("target_player_id")
                or target_id not in names or target_id == own_id
                or type(night) is not int or not 1 <= night <= current_round
                or type(data.get("is_mafia")) is not bool):
            continue
        if event_id in seen:
            return []
        seen.add(event_id)
        verdict = "마피아입니다" if data["is_mafia"] else "마피아가 아닙니다"
        results.append(f"밤 {night} 조사 결과 · {names[target_id]}: {verdict}.")
    return results


def _render_investigation_results(*, snapshot: dict[str, Any]) -> None:
    """생존·저장·관전 패널에서 동일한 검증을 거쳐 본인 조사 결과만 표시한다."""

    results = _validated_investigation_results(
        snapshot, expected_game_id=st.session_state.get("game.game_id"),
    )
    if results:
        st.markdown("#### 나에게만 공개된 결과")
        for result in results:
            # 공개 이름에 Markdown·HTML이 있어도 링크나 이미지로 해석하지 않는다.
            st.text(result)


def _event_text(*, event: dict[str, Any], player_names: dict[str, str]) -> str:
    """공개 event의 허용된 data만 사람이 읽을 수 있는 문장으로 변환한다."""

    # PublicEvent는 본문을 data 아래에 두는 폐쇄형 union이다. 다른 player의 선택이나
    # 비공개 payload를 추측해 표시하지 않고 정본에 정의된 공개 필드만 읽는다.
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    event_type = event.get("event_type")
    if event_type == "GAME_SAVED":
        created_at = event.get("created_at")
        if isinstance(created_at, str):
            saved_at = display_timestamp(created_at)
            if saved_at != "확인할 수 없음":
                return f"게임을 저장했습니다. (저장 시각: {saved_at})"
        return "게임을 저장했습니다. 저장한 지점부터 이어서 진행할 수 있습니다."
    if event_type == "GAME_RESUMED":
        return "게임을 재개했습니다. 저장한 지점부터 이어서 진행합니다."
    if event_type == "VOTE_RESOLVED":
        vote_result = _vote_result_text(data=data, player_names=player_names)
        return vote_result or "공개 투표 집계를 확인할 수 없습니다."
    message = data.get("message")
    if isinstance(message, str):
        return message
    player_name = player_names.get(str(data.get("player_id")), "플레이어")
    if event_type == "PLAYER_PASSED":
        return f"{player_name}님이 발언을 넘겼습니다."
    if event_type == "TURN_OPENED":
        prompt = data.get("prompt")
        return (
            str(prompt)
            if isinstance(prompt, str) and prompt
            else f"{player_name}님의 발언 차례입니다."
        )
    if event_type == "NIGHT_RESOLVED":
        killed_name = player_names.get(str(data.get("killed_player_id")))
        return (
            f"밤사이 {killed_name}님이 사망했습니다."
            if killed_name
            else "밤사이 사망자가 없습니다."
        )
    if event_type == "PLAYER_EXECUTED":
        executed_name = player_names.get(str(data.get("player_id")), "플레이어")
        revealed_role = ROLE_PRESENTATION.get(data.get("revealed_role"), ("역할 확인", ""))[0]
        return f"{executed_name}님이 처형되었습니다. 공개 역할은 {revealed_role}입니다."
    if event_type == "FAST_FORWARD_ENABLED":
        return "남은 AI 행동을 빠르게 진행합니다."
    return "공개 사건 기록이 갱신되었습니다."


def _vote_result_text(*, data: dict[str, Any], player_names: dict[str, str]) -> str | None:
    """폐쇄형 공개 투표 집계만 후보 이름과 고정 결과 문구로 변환한다.

    개별 ballot, 자동 선택 여부와 actor는 게임 종료 전 공개 대상이 아니다. 계약 밖
    필드나 알 수 없는 UUID가 하나라도 섞이면 원문을 일부 표시하지 않고 전체 집계를
    거부해 비공개 payload가 화면으로 새는 일을 막는다.
    """

    if set(data) != {"round", "phase", "counts", "tied", "needs_revote"}:
        return None
    round_number = data.get("round")
    phase = data.get("phase")
    tied = data.get("tied")
    needs_revote = data.get("needs_revote")
    counts = data.get("counts")
    if (
        type(round_number) is not int
        or not 1 <= round_number <= 5
        or phase not in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
        or type(tied) is not bool
        or type(needs_revote) is not bool
        or needs_revote != (phase == "DAY_VOTE" and tied)
        or not isinstance(counts, list)
        or not counts
    ):
        return None

    labels = []
    seen = set()
    for item in counts:
        if not isinstance(item, dict) or set(item) != {"target_player_id", "vote_count"}:
            return None
        player_id = _canonical_uuid(item.get("target_player_id"))
        vote_count = item.get("vote_count")
        if (
            player_id is None
            or player_id != item.get("target_player_id")
            or player_id not in player_names
            or player_id in seen
            or type(vote_count) is not int
            or not 0 <= vote_count <= len(player_names)
        ):
            return None
        seen.add(player_id)
        labels.append(f"{player_names[player_id]} {vote_count}표")

    maximum = max(item["vote_count"] for item in counts)
    computed_tied = sum(item["vote_count"] == maximum for item in counts) > 1
    if tied != computed_tied or sum(item["vote_count"] for item in counts) > len(player_names):
        return None

    phase_label = {
        "DAY_VOTE": "낮 투표",
        "REVOTE": "재투표",
        "FINAL_ACCUSATION": "최종 지목",
    }[phase]
    outcome = (
        "최다 득표 동률 · 재투표를 진행합니다."
        if needs_revote
        else "최다 득표 동률 · 재투표 없이 다음 단계로 진행합니다."
        if tied
        else "동률 없이 집계가 확정됐습니다."
    )
    return f"밤 {round_number} 이후 {phase_label} · {', '.join(labels)} · {outcome}"


def _event_speaker(*, event: dict[str, Any], player_names: dict[str, str]) -> str | None:
    """발언 event일 때만 공개 player 이름을 머리말로 반환한다."""

    if event.get("event_type") != "PLAYER_SPOKE":
        return None
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    return player_names.get(str(data.get("player_id")), "플레이어")


def _event_heading(event: dict[str, Any]) -> str:
    """공개 event 종류를 관전 타임라인의 짧은 머리말로 변환한다."""

    return {
        "GAME_BEGAN": "게임 시작",
        "TURN_OPENED": "발언 차례",
        "PLAYER_PASSED": "발언 넘김",
        "NIGHT_RESOLVED": "밤 결과",
        "VOTE_RESOLVED": "투표 결과",
        "PLAYER_EXECUTED": "처형 결과",
        "FAST_FORWARD_ENABLED": "빠른 진행",
        "GAME_SAVED": "게임 저장",
        "GAME_RESUMED": "게임 재개",
    }.get(str(event.get("event_type")), "공개 기록")


def _phase_public_label(phase: str) -> str:
    """탈락 phase enum을 공개 가능한 한국어 단계 이름으로 변환한다."""

    return {
        "NIGHT_ACTION": "밤 행동",
        "DAY_VOTE": "낮 투표",
        "REVOTE": "재투표",
        "FINAL_ACCUSATION": "최종 지목",
    }.get(phase, "게임 진행")


def _render_spectator_controls(
    *,
    client: Any,
    game_id: str,
    snapshot: dict[str, Any],
) -> None:
    """빠른 진행을 한 번만 제출하고 저장 제어와 함께 관전 중앙 영역에 표시한다."""

    _process_fast_forward(client=client, game_id=game_id, snapshot=snapshot)
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    enabled = bool(game.get("fast_forward_enabled"))
    pending = st.session_state.get("game.f6_pending")
    if isinstance(pending, dict) and "status" not in pending:
        # 이전 단순 구현의 session 값은 멱등 상태를 구분할 수 없으므로 새 요청을
        # 막지 않도록 폐기한다. 이미 처리된 요청 여부는 최신 snapshot이 판정한다.
        st.session_state.pop("game.f6_pending", None)
        pending = None
    pending_status = pending.get("status") if isinstance(pending, dict) else None
    toggle_key = f"spectator.fast_forward.{game_id}"
    if enabled:
        st.session_state[toggle_key] = True

    with st.container(key="spectator-controls", border=True):
        fast_col, save_col = st.columns([1.5, 1])
        with fast_col:
            requested = st.toggle(
                "빠른 진행 켜기",
                value=enabled,
                disabled=bool(st.session_state.get("game.sync_hidden"))
                or enabled
                or "FAST_FORWARD" not in snapshot.get("legal_actions", [])
                or pending_status
                in {"PENDING_TO_RENDER", "IN_FLIGHT", "SUCCEEDED", "RETRYABLE_UNKNOWN"},
                key=toggle_key,
            )
            st.caption("남은 AI 발언·투표·밤 행동을 빠르게 진행합니다.")
            if requested and not enabled and not isinstance(pending, dict):
                st.session_state["game.f6_pending"] = {
                    "status": "PENDING_TO_RENDER",
                    "expected_state_version": game.get("state_version"),
                    "idempotency_key": str(uuid4()),
                    "game_id": game_id,
                    "toggle_key": toggle_key,
                }
                st.rerun()
        with save_col:
            _render_save_control(client=client, game_id=game_id, snapshot=snapshot)

        if enabled:
            st.success("빠른 진행이 켜졌습니다.")
        elif pending_status == "SUCCEEDED":
            st.info("요청이 접수되었습니다. Backend 상태 반영을 기다리고 있습니다.")
        elif pending_status == "RETRYABLE_UNKNOWN":
            st.warning("빠른 진행 요청 결과를 확인하지 못했습니다.")
            if st.button("같은 요청 다시 확인", key="spectator.fast_forward.retry", disabled=bool(st.session_state.get("game.sync_hidden"))):
                st.session_state["game.f6_pending"] = {
                    **pending,
                    "status": "PENDING_TO_RENDER",
                }
                st.rerun()
        elif pending_status == "REJECTED":
            st.error("게임 상태가 바뀌어 빠른 진행을 켜지 못했습니다.")
            if st.button("최신 상태 다시 확인", key="spectator.fast_forward.refresh", disabled=bool(st.session_state.get("game.sync_hidden"))):
                st.session_state.pop("game.f6_pending", None)
                st.rerun()


def _process_fast_forward(*, client: Any, game_id: str, snapshot: dict[str, Any]) -> None:
    """FAST_FORWARD를 고정 body·key로 전송하고 terminal 결과를 session에 보관한다."""

    pending = st.session_state.get("game.f6_pending")
    if not isinstance(pending, dict) or pending.get("game_id") != game_id:
        return
    if pending.get("status") == "PENDING_TO_RENDER":
        st.session_state["game.f6_pending"] = {**pending, "status": "IN_FLIGHT"}
        st.rerun()
    if pending.get("status") != "IN_FLIGHT":
        return
    try:
        client.submit_command(
            game_id=game_id,
            command={
                "type": "FAST_FORWARD",
                "expected_state_version": pending["expected_state_version"],
            },
            idempotency_key=pending["idempotency_key"],
        )
        refreshed = client.get_game(game_id)
        st.session_state["game.latest_snapshot"] = refreshed
        st.session_state["game.f6_pending"] = {**pending, "status": "SUCCEEDED"}
    except ApiResponseError as error:
        status = "RETRYABLE_UNKNOWN" if error.status_code >= 500 else "REJECTED"
        st.session_state["game.f6_pending"] = {**pending, "status": status}
        if status == "REJECTED":
            st.session_state[pending["toggle_key"]] = False
    except (ApiUnavailableError, ValueError):
        st.session_state["game.f6_pending"] = {
            **pending,
            "status": "RETRYABLE_UNKNOWN",
        }
    finally:
        if st.session_state.get("game.f6_pending", {}).get("status") != "IN_FLIGHT":
            st.rerun()


def _render_save_control(
    *,
    client: Any,
    game_id: str,
    snapshot: dict[str, Any],
) -> None:
    """저장 확인 다이얼로그를 거친 뒤 Backend 허용 command만 제출한다."""

    command_type = "SAVE_AND_EXIT"
    label, button_key, pending_key = SHELL_COMMANDS[command_type]
    pending = st.session_state.get(pending_key)
    if not isinstance(pending, dict) or pending.get("game_id") != game_id:
        pending = {}
    status = pending.get("status")
    allowed = command_type in snapshot.get("legal_actions", [])
    locked = bool(st.session_state.get("game.sync_hidden")) or any(
        isinstance(existing := st.session_state.get(key), dict)
        and existing.get("game_id") == game_id
        and existing.get("status") in SHELL_LOCKED
        for _, _, key in SHELL_COMMANDS.values()
    )
    if allowed or status in SHELL_LOCKED:
        if st.button(
            label,
            key=button_key,
            type="secondary",
            disabled=locked or not allowed,
            use_container_width=True,
        ):
            # header button의 클릭 직후 dialog를 같은 실행 회차에서만 열면 다른
            # fragment·SSE 갱신이 발생할 때 modal이 사라질 수 있다. 대상 game_id를
            # session에 먼저 보존하고 다음 rerun에서도 dialog를 다시 렌더링한다.
            st.session_state[SAVE_DIALOG_GAME_KEY] = game_id
            st.rerun()
    if st.session_state.get(SAVE_DIALOG_GAME_KEY) == game_id:
        _render_save_confirmation_dialog(game_id=game_id, snapshot=snapshot)
    if status == "RETRYABLE_UNKNOWN":
        st.warning("요청 결과를 확인하지 못했습니다. 같은 요청 다시 확인을 눌러 주세요.")
    elif status == "REFRESH_FAILED":
        st.warning("요청 응답은 확인했지만 최신 게임 상태를 불러오지 못했습니다.")
    elif status == "REJECTED" and allowed:
        st.warning("게임 상태가 바뀌어 저장이 거부되었습니다. 최신 상태를 확인해 주세요.")
    if status in {"RETRYABLE_UNKNOWN", "REFRESH_FAILED"}:
        if st.button(
            "같은 요청 다시 확인" if status == "RETRYABLE_UNKNOWN" else "최신 상태 다시 확인",
            key=f"{button_key}_retry",
            disabled=bool(st.session_state.get("game.sync_hidden")),
        ):
            st.session_state[pending_key] = {
                **pending,
                "status": "IN_FLIGHT" if status == "RETRYABLE_UNKNOWN" else "REFRESH_REQUIRED",
            }
            st.rerun()


ACTIVITY_STAGES = {
    "STARTED": "정보 확인 준비", "CONTEXT_READY": "정보 확인 완료", "DECIDING": "판단 중",
    "DECIDED": "행동 선택 완료", "APPLIED": "적용 완료", "FALLBACK": "기본 행동 선택",
    "FAILED": "적용 실패", "SKIPPED": "지난 작업 건너뜀",
}
PUBLIC_ACTIVITY_PHASES = {"DAY_DISCUSSION", "FINAL_DISCUSSION"}
PRIVATE_ACTIVITY_PHASES = {"NIGHT_ACTION", "NIGHT_RESOLUTION", "DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
ACTIVITY_FIELDS = {"sequence", "run_id", "created_at", "player_id", "phase", "state_version", "stage", "action", "summary"}
ACTIVITY_OPTIONAL_FIELDS = {"decision_source", "reason_code", "decision_basis"}
ACTIVITY_SOURCES = {"MODEL": "모델 판단", "DUMMY": "더미 모드", "FALLBACK": "규칙 대체"}
ACTIVITY_REASONS = {
    "PROVIDER_TIMEOUT": "모델 응답 시간 초과", "PROVIDER_AUTHENTICATION": "모델 인증 실패",
    "PROVIDER_RATE_LIMIT": "모델 요청 한도 초과", "PROVIDER_MODEL_UNAVAILABLE": "설정한 모델에 접근할 수 없음",
    "PROVIDER_INCOMPLETE": "응답 생성 미완료", "PROVIDER_UNAVAILABLE": "모델 연결 불가",
    "PROPOSAL_INVALID": "응답 형식·행동 검증 실패", "MCP_UNAVAILABLE": "게임 정보 조회 실패",
    "MCP_SUBMISSION_FAILED": "선택한 행동 전달 실패", "AGENT_DEPENDENCY_ERROR": "AI 처리 의존성 오류",
}
ACTIVITY_BASES = {
    "PUBLIC_EVIDENCE": "공개 단서 검토 · 공개된 사건 단서를 근거로 의견을 냈습니다.",
    "COMPARE_STATEMENTS": "진술 비교 · 공개 발언과 알리바이를 비교했습니다.",
    "ASK_FOR_CLARIFICATION": "확인 질문 · 불분명한 진술을 확인하기 위해 질문했습니다.",
    "INSUFFICIENT_EVIDENCE": "근거 부족 · 판단할 공개 근거가 아직 부족하다고 보았습니다.",
    "NO_NEW_INFORMATION": "추가 의견 없음 · 이미 나온 의견 외에 추가할 내용이 없다고 보았습니다.",
}


def _canonical_uuid(value: Any) -> str | None:
    """외부 식별자를 UUID 문자열로 정규화하고 임의 객체·손상된 값은 거부한다."""

    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _validated_agent_activity(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """같은 게임 AI의 공개 처리 기록만 제한 크기로 투영한다.

    서버의 자유 문자열을 판단 내용으로 신뢰하지 않는다. summary는 계약 형식만
    확인한 뒤 버리고 화면 설명은 허용된 stage·action enum으로만 생성한다.
    """

    raw = snapshot.get("agent_activity", [])
    version = snapshot.get("game", {}).get("state_version")
    if not isinstance(raw, list) or type(version) is not int or version < 1:
        return []
    ai_ids = {_canonical_uuid(p.get("player_id")) for p in public_players(snapshot) if p.get("kind") == "AI"}
    ai_ids.discard(None)
    records = []
    for item in raw[-50:]:
        if (not isinstance(item, dict) or not ACTIVITY_FIELDS <= set(item)
                or set(item) - ACTIVITY_FIELDS - ACTIVITY_OPTIONAL_FIELDS):
            continue
        if any(item.get(key) is not None and (
            not isinstance(item[key], str) or item[key] not in allowed
        ) for key, allowed in (("decision_source", ACTIVITY_SOURCES), ("reason_code", ACTIVITY_REASONS),
                               ("decision_basis", ACTIVITY_BASES))):
            continue
        actor = _canonical_uuid(item.get("player_id"))
        run_id = _canonical_uuid(item.get("run_id"))
        sequence, observed = item.get("sequence"), item.get("state_version")
        stage, action, phase = item.get("stage"), item.get("action"), item.get("phase")
        summary, created_at = item.get("summary"), item.get("created_at")
        if (actor not in ai_ids or run_id is None or type(sequence) is not int or sequence < 1
                or type(observed) is not int or not 1 <= observed <= version
                or not isinstance(stage, str) or stage not in ACTIVITY_STAGES
                or not isinstance(phase, str) or phase not in PUBLIC_ACTIVITY_PHASES
                or (action is not None and (not isinstance(action, str) or action not in {"SPEAK", "PASS"}))
                or not isinstance(summary, str) or not 1 <= len(summary) <= 200
                or not isinstance(created_at, str)
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", created_at) is None):
            continue
        try:
            if datetime.fromisoformat(created_at.replace("Z", "+00:00")).utcoffset() != timedelta(0):
                continue
        except ValueError:
            continue
        dummy_summary = "더미 제공자의 고정 행동을 처리하고 있습니다."
        if stage == "DECIDED" and action:
            dummy_summary += f" ({'발언' if action == 'SPEAK' else '차례 넘김'})"
        # 더미 안내도 Backend가 정본 enum으로 만든 정확한 문구일 때만 허용한다.
        # 유사한 자유 문장이나 임의 suffix로 내부 사고가 화면에 섞이지 않게 한다.
        dummy = item.get("decision_source") == "DUMMY" or (stage in {"DECIDING", "DECIDED"} and summary == dummy_summary)
        records.append({key: value for key, value in item.items() if key != "summary"}
                       | {"player_id": actor, "run_id": run_id, "dummy": dummy})
    # 한 응답에는 현재 실행의 단조 증가 기록만 존재해야 한다. 서로 다른 실행이나
    # 역순·중복 sequence가 섞이면 현재 진행을 잘못 추측하지 않도록 모두 숨긴다.
    if len({item["run_id"] for item in records}) > 1:
        return []
    if any(a["sequence"] >= b["sequence"] for a, b in zip(records, records[1:])):
        return []
    return records


def _is_current_activity(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """과거 window의 적용 완료를 새 차례의 진행 상태로 오인하지 않게 한다."""

    game = snapshot.get("game", {})
    window = snapshot.get("action_window")
    return (game.get("status") == "IN_PROGRESS" and isinstance(window, dict)
            and window.get("paused") is False
            and _canonical_uuid(window.get("turn_player_id")) == item["player_id"]
            and window.get("kind") == "SPEECH"
            and item["phase"] == game.get("phase")
            and item["state_version"] == game.get("state_version"))


def _activity_label(item: dict[str, Any]) -> str:
    """처리 단계와 공개 행동 enum만 사용하여 내부 사고 없는 고정 안내를 만든다."""

    action = {"SPEAK": "발언", "PASS": "차례 넘김"}.get(item["action"])
    suffix = f" · {action}" if action else ""
    if action and item["stage"] != "APPLIED":
        suffix += " (미적용)"
    label = ACTIVITY_STAGES[item["stage"]]
    if item.get("dummy") and item["stage"] in {"DECIDING", "DECIDED"}:
        label = "더미 · 고정 행동 처리 중" if item["stage"] == "DECIDING" else "더미 · 고정 행동 선택 완료"
    source = ACTIVITY_SOURCES.get(item.get("decision_source"))
    if source:
        label = source + " · " + label
    return label + suffix


def _render_agent_activity(*, snapshot: dict[str, Any]) -> None:
    """밤·투표는 공통 안내만, 공개 발언은 현재 진행과 접힌 과거 이력을 표시한다."""

    phase = snapshot.get("game", {}).get("phase")
    with st.expander("AI 판단과 실행", expanded=False):
        if phase in PRIVATE_ACTIVITY_PHASES:
            st.info("비공개 단계가 진행 중입니다. 각 AI의 역할·대상·응답 여부는 공개하지 않습니다.")
            return
        if phase not in PUBLIC_ACTIVITY_PHASES:
            st.caption("공개 발언 단계에서 AI 진행을 확인할 수 있습니다.")
            return
        st.caption("정보 확인 → 판단 → 선택 → 적용")
        st.caption("모델이 선택한 공개 판단 근거와 실제 처리 결과입니다. 내부 사고 원문은 표시하지 않습니다.")
        records = _validated_agent_activity(snapshot)
        players = [p for p in public_players(snapshot) if p.get("kind") == "AI"]
        names = {_canonical_uuid(p.get("player_id")): str(p.get("display_name", "AI")) for p in players}
        for player in players:
            actor = _canonical_uuid(player.get("player_id"))
            if actor is None:
                continue
            current = next((item for item in reversed(records) if item["player_id"] == actor and _is_current_activity(item, snapshot)), None)
            latest = next((item for item in reversed(records) if item["player_id"] == actor), None)
            window = snapshot.get("action_window")
            my_turn = (snapshot.get("game", {}).get("status") == "IN_PROGRESS"
                       and isinstance(window, dict) and window.get("kind") == "SPEECH"
                       and window.get("paused") is False
                       and _canonical_uuid(window.get("turn_player_id")) == actor)
            if player.get("alive") is False:
                label = "탈락"
            elif current:
                label = "현재 차례 · " + _activity_label(current)
            else:
                label = "현재 차례 · 처리 기록 대기" if my_turn else "대기"
                if latest:
                    label += " · 이전 기록: " + _activity_label(latest)
            st.markdown(f"<div><strong>{escape(names[actor])}</strong> · {escape(label)}</div>", unsafe_allow_html=True)
            detail = current or latest
            if detail:
                reason = ACTIVITY_REASONS.get(detail.get("reason_code"))
                basis = ACTIVITY_BASES.get(detail.get("decision_basis"))
                if detail.get("decision_source") == "FALLBACK" or detail["stage"] == "FALLBACK":
                    reason = reason or "정상적인 모델 응답을 사용할 수 없음"
                    scope = "현재 차례" if current else "이전 차례"
                    st.warning(f"{scope} · {reason}. 게임 규칙의 기본 행동으로 처리했습니다.")
                elif detail.get("dummy"):
                    st.warning("더미 모드: 실제 모델 추론 없이 고정 행동을 사용하고 있습니다.")
                elif basis:
                    st.markdown(f"<div style='margin:.3rem 0 .8rem;color:#4b5870'>판단 근거 · {escape(basis)}</div>", unsafe_allow_html=True)
                elif detail["stage"] in {"DECIDED", "APPLIED"}:
                    st.caption("이번 선택에는 공개 판단 근거가 제공되지 않았습니다.")
        if not records:
            st.caption("최근 처리 기록이 없습니다. 서버 재시작 뒤에는 새 기록부터 표시됩니다.")
        else:
            with st.container():
                st.caption("최근 공개 처리 기록")
                for item in records:
                    scope = "현재 차례" if _is_current_activity(item, snapshot) else "이전 기록"
                    time = display_timestamp(item["created_at"])
                    text = f"{time} · {scope} · {names[item['player_id']]} · {_activity_label(item)}"
                    explanation = ACTIVITY_REASONS.get(item.get("reason_code")) or ACTIVITY_BASES.get(item.get("decision_basis"))
                    if explanation:
                        text += f" · {explanation}"
                    st.markdown(f"<div>{escape(text)}</div>", unsafe_allow_html=True)


SHELL_COMMANDS = {
    "SAVE_AND_EXIT": ("💾 저장", "game.save_exit", "game.save_pending"),
    "RESUME": ("불러오기", "game.resume", "game.resume_pending"),
    "BEGIN_GAME": ("게임 시작  ›", "game.begin", "game.begin_pending"),
}
SHELL_LOCKED = {"PENDING_TO_RENDER", "IN_FLIGHT", "RETRYABLE_UNKNOWN", "REFRESH_REQUIRED", "REFRESH_FAILED"}
SAVE_DIALOG_GAME_KEY = "game.save_dialog_game_id"


def _render_save_confirmation_dialog(*, game_id: str, snapshot: dict[str, Any]) -> None:
    """사용자가 저장 시점을 확인한 뒤에만 게임 중단 command를 대기열에 넣는다."""

    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    window = snapshot.get("action_window") if isinstance(snapshot.get("action_window"), dict) else {}
    phase = str(game.get("phase", ""))
    phase_label = PHASE_LABELS.get(phase, "게임 진행")
    cycle = (
        f"밤 {game.get('round', 1)}일차"
        if phase == "NIGHT_ACTION"
        else f"낮 {game.get('day_number', 1)}일차"
    )
    remaining_ms = window.get("remaining_ms")
    if type(remaining_ms) is int and remaining_ms >= 0:
        remaining_seconds = (remaining_ms + 999) // 1000
        remaining_text = f"{remaining_seconds // 60:02}:{remaining_seconds % 60:02}"
    else:
        remaining_text = "시간 확인 중"

    @st.dialog("게임 저장")
    def save_dialog() -> None:
        st.markdown("## 💾 게임 저장")
        st.caption("현재 상황")
        with st.container(border=True):
            phase_col, time_col = st.columns([2, 1])
            phase_col.markdown(f"**{phase_label}**")
            phase_col.caption(cycle)
            time_col.metric("남은 시간", remaining_text)
        st.info("게임을 저장하고 나가면 나중에 이어서 플레이할 수 있습니다.")
        save_col, continue_col = st.columns(2)
        if save_col.button(
            "저장하고 나가기",
            key="game.save_confirm",
            type="primary",
            use_container_width=True,
        ):
            _queue_shell_command(
                game_id=game_id,
                snapshot=snapshot,
                command_type="SAVE_AND_EXIT",
            )
            st.session_state.pop(SAVE_DIALOG_GAME_KEY, None)
            st.rerun()
        if continue_col.button(
            "계속 플레이",
            key="game.save_cancel",
            use_container_width=True,
        ):
            st.session_state.pop(SAVE_DIALOG_GAME_KEY, None)
            st.rerun()

    save_dialog()


def _queue_shell_command(*, game_id: str, snapshot: dict[str, Any], command_type: str) -> None:
    """확인된 shell command의 상태 버전과 idempotency key를 한 번만 고정한다."""

    _, _, pending_key = SHELL_COMMANDS[command_type]
    st.session_state[pending_key] = {
        "status": "IN_FLIGHT",
        "game_id": game_id,
        "expected_state_version": snapshot["game"]["state_version"],
        "idempotency_key": str(uuid4()),
    }


def _process_shell_pending(*, client: Any, game_id: str) -> None:
    """화면 phase가 바뀌어도 이미 제출한 시작·저장·재개 요청의 결과를 처리한다."""

    for command_type, (_, _, pending_key) in SHELL_COMMANDS.items():
        pending = st.session_state.get(pending_key)
        if not isinstance(pending, dict) or pending.get("game_id") != game_id:
            continue
        if pending.get("status") in {"PENDING_TO_RENDER", "IN_FLIGHT"}:
            try:
                client.submit_command(game_id=game_id, command={
                    "type": command_type, "expected_state_version": pending["expected_state_version"],
                }, idempotency_key=pending["idempotency_key"])
                pending = {**pending, "status": "REFRESH_REQUIRED", "accepted": True}
            except ApiResponseError as error:
                uncertain = isinstance(error, ApiUnavailableError) or error.status_code >= 500
                pending = {**pending, "status": "RETRYABLE_UNKNOWN" if uncertain else "REFRESH_REQUIRED", "accepted": False}
            except ValueError:
                pending = {**pending, "status": "RETRYABLE_UNKNOWN"}
            st.session_state[pending_key] = pending
        if pending.get("status") != "REFRESH_REQUIRED":
            continue
        try:
            response = client.get_game(game_id)
            refreshed = response.get("data", response)
            game = refreshed.get("game") if isinstance(refreshed, dict) else None
            if (not isinstance(game, dict) or game.get("game_id") != game_id
                    or game.get("status") not in {"SAVED", "IN_PROGRESS", "COMPLETED", "FAILED"}
                    or type(game.get("state_version")) is not int or game["state_version"] < 1):
                raise ValueError("INVALID_RESPONSE")
        except (ApiResponseError, ValueError, AttributeError):
            st.session_state[pending_key] = {**pending, "status": "REFRESH_FAILED"}
            continue
        st.session_state["game.latest_snapshot"] = refreshed
        # 홈 목록만 무효화하여 다음 방문 시 서버 상태를 조회한다. UUID와 다른
        # 페이지의 결과 불명 요청은 지우지 않는다.
        for key in ("home.games", "home.games_error", "home.games_loaded_at", "home.games_loading"):
            st.session_state.pop(key, None)
        st.session_state[pending_key] = {**pending, "status": "SUCCEEDED" if pending.get("accepted") else "REJECTED"}
        if command_type == "SAVE_AND_EXIT" and game["status"] == "SAVED":
            st.session_state["navigation.page"] = "home"
            for key in ("game.game_id", "game.latest_snapshot", "game.activity_tick", "game.sync_status", pending_key):
                st.session_state.pop(key, None)
        else:
            st.session_state["navigation.page"] = "game"
        st.rerun()


def _render_shell_command(*, client: Any, game_id: str, snapshot: dict[str, Any], command_type: str) -> None:
    """결과 불명일 때 신규 요청을 잠그고 동일 key 재전송 또는 GET 재조회만 제공한다."""

    _process_shell_pending(client=client, game_id=game_id)
    label, button_key, pending_key = SHELL_COMMANDS[command_type]
    pending = st.session_state.get(pending_key)
    if not isinstance(pending, dict) or pending.get("game_id") != game_id:
        pending = {}
    status = pending.get("status")
    allowed = command_type in snapshot.get("legal_actions", [])
    locked = bool(st.session_state.get("game.sync_hidden")) or any(isinstance(p := st.session_state.get(key), dict)
                 and p.get("game_id") == game_id and p.get("status") in SHELL_LOCKED
                 for _, _, key in SHELL_COMMANDS.values())
    if allowed or status in SHELL_LOCKED:
        if st.button(label, key=button_key, type="primary" if command_type != "SAVE_AND_EXIT" else "secondary",
                     disabled=locked or not allowed, use_container_width=True):
            _queue_shell_command(game_id=game_id, snapshot=snapshot, command_type=command_type)
            st.rerun()
    if status == "RETRYABLE_UNKNOWN":
        st.warning("요청 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인해 주세요.")
    elif status == "REFRESH_FAILED":
        st.warning("요청 응답은 확인했지만 최신 게임 상태를 불러오지 못했습니다.")
    elif status == "REJECTED" and allowed:
        st.warning("게임 상태가 바뀌어 요청이 거부되었습니다. 최신 상태를 확인한 뒤 다시 선택해 주세요.")
    if status in {"RETRYABLE_UNKNOWN", "REFRESH_FAILED"}:
        if st.button("같은 요청 다시 확인" if status == "RETRYABLE_UNKNOWN" else "최신 상태 다시 확인",
                     key=f"{button_key}_retry", disabled=bool(st.session_state.get("game.sync_hidden"))):
            st.session_state[pending_key] = {**pending, "status": "IN_FLIGHT" if status == "RETRYABLE_UNKNOWN" else "REFRESH_REQUIRED"}
            st.rerun()


def render_saved_control(*, client: Any, snapshot: dict[str, Any]) -> None:
    """저장된 window를 실행하지 않고 명시적인 서버 RESUME을 통해서만 복원한다."""

    st.info("저장된 게임입니다. 불러오기를 누르면 같은 단계에서 계속합니다. 남은 시간은 일시 정지되어 있습니다.")
    _render_shell_command(client=client, game_id=str(snapshot["game"]["game_id"]), snapshot=snapshot, command_type="RESUME")
