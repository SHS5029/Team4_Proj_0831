"""진행 중 게임의 공통 shell과 공개 timeline 화면."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from html import escape
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from frontend_user.components.action_panel import render as render_action_panel
from frontend_user.components.sync_bridge import apply_sync, mount_sse
from frontend_user.components.theme import render_page_navigation
from frontend_user.core.api_client import ApiResponseError, ApiUnavailableError
from frontend_user.core.sync import SyncEnvelopeError
from frontend_user.core.view_models import own_private_view, public_players, public_timeline

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
  min-height: 37rem; padding: 1rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-game-timeline-panel"] {
  padding: 1rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-game-timeline-scroll"] {
  margin-top: .7rem; padding-right: .2rem;
}
.game-panel-title {
  margin-bottom: .1rem; color: var(--game-ink); font-size: 1.05rem; font-weight: 800;
}
.game-panel-caption { margin-bottom: .85rem; color: var(--game-muted); font-size: .78rem; }
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
.game-night-callout {
  display: grid; min-height: 9.5rem; margin-top: 1rem; padding: 1.1rem; place-items: center;
  border-radius: .7rem; color: #e6efff; text-align: center;
  background: radial-gradient(circle at 82% 18%, #9fbde7 0 4%, transparent 5%),
              linear-gradient(155deg, #07162b, #163d68);
}
.game-night-callout strong { display: block; margin-bottom: .35rem; font-size: 1.05rem; }
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

PHASE_LABELS = {
    "DAY_DISCUSSION": "사건 설명과 낮 토론",
    "NIGHT_ACTION": "밤 행동",
    "DAY_VOTE": "처형 투표",
    "REVOTE": "재투표",
    "FINAL_DISCUSSION": "마지막 토론",
    "FINAL_ACCUSATION": "최종 지목",
}

ROLE_PRESENTATION = {
    "MAFIA": ("마피아", "🥷"),
    "DETECTIVE": ("탐정", "🕵️"),
    "DOCTOR": ("의사", "🩺"),
    "CITIZEN": ("시민", "🧑"),
}


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
    connection_class = {
        "POLLING": " game-status-polling",
        "STALE": " game-status-stale",
    }.get(connection, "")

    st.markdown(GAME_PAGE_CSS, unsafe_allow_html=True)
    st.markdown(
        '<header class="game-header"><div><span class="game-brand">AI 마피아</span>'
        f'<span class="game-status{connection_class}">{connection_label}</span></div>'
        '<nav class="game-nav"><span>▣&nbsp; 피드백</span><span>⚙&nbsp; 설정</span></nav></header>',
        unsafe_allow_html=True,
    )
    render_page_navigation(current_page="game")
    # 응답 유실 뒤 서버가 phase를 변경했어도 기존 요청의 재시도 UI를 유지한다.
    # 정상 시작 버튼은 역할 공개 화면에서만 표시한다.
    for command_type in ("BEGIN_GAME", "RESUME"):
        pending = st.session_state.get(SHELL_COMMANDS[command_type][2])
        if (isinstance(pending, dict) and pending.get("game_id") == str(game_id)
                and pending.get("status") in SHELL_LOCKED
                and not (command_type == "RESUME" and game.get("status") == "SAVED")):
            _render_shell_command(client=client, game_id=str(game_id), snapshot=snapshot, command_type=command_type)

    day_number = game.get("day_number", 1)
    phase = game.get("phase", "확인 중")
    spectating = me.get("alive") is False
    title_col, save_col = st.columns([5, 1])
    with title_col:
        if spectating:
            st.markdown(f"# ☀️ 낮 {day_number}일차 · 관전 중")
            caption = "게임의 공개 정보와 이미 허용된 본인 정보만 확인할 수 있습니다."
        else:
            phase_label = PHASE_LABELS.get(phase, str(phase))
            phase_icon = "🌙" if phase == "NIGHT_ACTION" else "☀️"
            cycle_label = (
                f"밤 {game.get('round', 1)}" if phase == "NIGHT_ACTION" else f"낮 {day_number}일차"
            )
            st.markdown(f"# {phase_icon} {cycle_label} · {phase_label}")
            caption = (
                "역할에 허용된 행동을 선택하세요. 다른 플레이어의 밤 행동은 공개되지 않습니다."
                if phase == "NIGHT_ACTION"
                else "생존자들과 함께 공개된 사건 정보를 확인하세요."
            )
        st.markdown(f'<p class="game-phase-caption">{caption}</p>', unsafe_allow_html=True)
    with save_col:
        if not spectating:
            _render_save_control(
                client=client,
                game_id=str(game.get("game_id")),
                snapshot=snapshot,
            )

    if game.get("status") == "SAVED":
        if spectating:
            _render_save_control(client=client, game_id=str(game_id), snapshot=snapshot)
        render_saved_control(client=client, snapshot=snapshot)
        left, center, right = st.columns([1, 1.65, 1.08])
        with left:
            _render_players(snapshot=snapshot, me=me, phase=str(phase))
        with center:
            _render_agent_activity(snapshot=snapshot)
            _render_timeline(snapshot=snapshot, scenario=scenario, phase=str(phase), day_number=day_number)
        with right:
            _render_private_panel(snapshot=snapshot, me=me)
        return

    if spectating:
        _render_spectator_layout(
            client=client,
            game_id=str(game.get("game_id")),
            snapshot=snapshot,
            me=me,
        )
        return

    left, center, right = st.columns([1, 1.65, 1.08])
    with left:
        _render_players(snapshot=snapshot, me=me, phase=str(phase))
    with center:
        _render_agent_activity(snapshot=snapshot)
        _render_timeline(
            snapshot=snapshot,
            scenario=scenario,
            phase=str(phase),
            day_number=day_number,
        )
        # 공개 대화는 정해진 높이 안에서 스크롤하고, 행동 입력은 같은 중앙 열의
        # 하단에 둔다. 따라서 현재 차례가 생겨도 좌·우 정보 panel 사이에서 입력창을
        # 찾을 필요가 없으며, focus bridge의 기존 action region 계약도 유지한다.
        with st.container(key="current-action-region"):
            _render_visible_action_panel(
                client=client,
                game_id=str(game.get("game_id")),
                snapshot=snapshot,
            )
    with right:
        _render_private_panel(snapshot=snapshot, me=me)

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


def _render_players(*, snapshot: dict[str, Any], me: dict[str, Any], phase: str) -> None:
    """좌석순 공개 player를 생존·탈락·본인 표식과 함께 표시한다."""

    players = public_players(snapshot)
    alive_count = sum(1 for player in players if player.get("alive"))
    with st.container(key="game-player-panel", border=True):
        st.markdown('<div class="game-panel-title">생존자 목록</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="game-panel-caption">현재 생존 중인 플레이어 · {alive_count}명</div>',
            unsafe_allow_html=True,
        )
        for player in players:
            alive = bool(player.get("alive"))
            mine = player.get("player_id") == me.get("player_id")
            status_class = "game-alive" if alive else "game-dead"
            status_label = "생존" if alive else "탈락"
            icon = "🤖" if player.get("kind") == "AI" else "🕵️"
            with st.container(border=True):
                columns = st.columns([0.5, 2.2, 0.8])
                columns[0].write(icon)
                name = str(player.get("display_name", "플레이어"))
                mine_label = " · 나" if mine else ""
                columns[1].write(f"**{name}**{mine_label}")
                columns[2].markdown(
                    f'<span class="{status_class}">{status_label}</span>',
                    unsafe_allow_html=True,
                )
                revealed_role = player.get("revealed_role")
                if revealed_role:
                    st.caption(f"공개 역할: {revealed_role}")
        if phase == "NIGHT_ACTION":
            st.markdown(
                '<div class="game-night-callout"><div><strong>🌙 밤이 되었습니다</strong>'
                "모두 조용히 행동을 선택하세요.</div></div>",
                unsafe_allow_html=True,
            )


def _render_spectator_layout(
    *,
    client: Any,
    game_id: str,
    snapshot: dict[str, Any],
    me: dict[str, Any],
) -> None:
    """사망한 인간에게 공개 정보와 본인 정보만 남긴 관전 3열 화면을 표시한다."""

    left, center, right = st.columns([1, 1.8, 1.05])
    with left:
        _render_spectator_players(snapshot=snapshot, me=me)
    with center:
        with st.container(key="spectator-notice", border=True):
            st.markdown("### ℹ️ 플레이어가 사망하여 관전 모드로 전환되었습니다.")
            st.caption("게임은 AI 플레이어끼리 계속 진행되며 공개 범위의 정보만 표시됩니다.")
        _render_spectator_timeline(snapshot=snapshot)
        _render_agent_activity(snapshot=snapshot)
        _render_spectator_controls(client=client, game_id=game_id, snapshot=snapshot)
    with right:
        _render_spectator_private(snapshot=snapshot, me=me)


def _render_spectator_players(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """공개 player를 생존자와 사망자로 나누되 숨은 역할은 표시하지 않는다."""

    players = public_players(snapshot)
    alive_players = [player for player in players if player.get("alive")]
    dead_players = [player for player in players if not player.get("alive")]
    with st.container(key="spectator-player-panel", border=True):
        st.markdown(f"### 🔵 생존자 ({len(alive_players)})")
        st.caption("마을을 위해 토론하는 플레이어입니다.")
        for player in alive_players:
            _render_spectator_player_row(
                player=player, mine=player.get("player_id") == me.get("player_id")
            )
        st.markdown(f"### ⚫ 사망자 ({len(dead_players)})")
        st.caption("사망한 플레이어입니다.")
        for player in dead_players:
            _render_spectator_player_row(
                player=player, mine=player.get("player_id") == me.get("player_id")
            )


def _render_spectator_player_row(*, player: dict[str, Any], mine: bool) -> None:
    """좌석·공개 이름·생존 상태만 사용해 관전 목록 한 행을 그린다."""

    alive = bool(player.get("alive"))
    with st.container(border=True):
        seat_col, icon_col, name_col, status_col = st.columns([0.45, 0.55, 1.8, 0.7])
        seat_col.write(f"{int(player.get('seat', 0)):02d}")
        icon_col.write("🤖" if player.get("kind") == "AI" else "🧑")
        name = str(player.get("display_name", "플레이어"))
        name_col.write(f"**{name}**" + (" · 나" if mine else ""))
        status_col.write("🟢 생존" if alive else "⚫ 사망")


def _render_spectator_timeline(*, snapshot: dict[str, Any]) -> None:
    """관전자에게 허용된 공개 event만 시간 순서대로 표시한다."""

    events = public_timeline(snapshot)
    player_names = {
        str(player.get("player_id")): str(player.get("display_name", "플레이어"))
        for player in public_players(snapshot)
    }
    with st.container(key="spectator-timeline-panel", border=True):
        st.markdown("### ▣ 공개 타임라인")
        st.caption("게임의 공개 이벤트와 발언만 표시됩니다.")
        if not events:
            st.info("아직 표시할 공개 기록이 없습니다.")
        for index, event in enumerate(events):
            with st.container(key=f"spectator-public-event-{index}", border=True):
                speaker = _event_speaker(event=event, player_names=player_names)
                if speaker:
                    st.markdown(f"**💬 {speaker}**")
                else:
                    st.markdown(f"**{_event_heading(event)}**")
                st.write(_event_text(event=event, player_names=player_names))


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
    """사건 설명과 Front-visible 공개 이벤트만 중앙 timeline에 표시한다."""

    with st.container(key="game-timeline-panel", border=True):
        st.markdown('<div class="game-panel-title">공개 타임라인</div>', unsafe_allow_html=True)
        events = public_timeline(snapshot)
        st.markdown(
            '<div class="game-panel-caption">모든 플레이어가 확인할 수 있는 정보입니다.</div>',
            unsafe_allow_html=True,
        )
        discussion_started = phase in {"DAY_DISCUSSION", "FINAL_DISCUSSION"} and bool(events)
        if discussion_started:
            st.markdown(f"### ☀️ 낮 {day_number}일차 · 토론")
        else:
            st.markdown('<div class="game-scene" aria-hidden="true"></div>', unsafe_allow_html=True)
            st.subheader(str(scenario.get("title", "사건 정보")))
            victim = scenario.get("victim", "알 수 없음")
            locations = scenario.get("locations", [])
            location_text = (
                ", ".join(str(item) for item in locations) if isinstance(locations, list) else ""
            )
            st.caption(f"피해자: {victim} · 장소: {location_text}")
            st.write(str(scenario.get("background", "")))
        # 발언 누적 길이가 화면을 밀어내지 않도록 공개 이벤트만 독립 scroll 영역에
        # 넣는다. 사건 설명과 입력 panel은 화면의 고정된 문맥으로 남긴다.
        with st.container(key="game-timeline-scroll", height=340, border=False):
            if not events:
                st.info("사건 설명을 확인한 뒤 공개 대화가 이곳에 표시됩니다.")
            player_names = {
                str(player.get("player_id")): str(player.get("display_name", "플레이어"))
                for player in public_players(snapshot)
            }
            for index, event in enumerate(events):
                with st.container(key=f"game-public-event-{index}", border=True):
                    speaker = _event_speaker(event=event, player_names=player_names)
                    if speaker:
                        st.markdown(f"**{speaker}**")
                    st.write(_event_text(event=event, player_names=player_names))


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
            try:
                saved_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if saved_at.utcoffset() == timedelta(0):
                    return f"게임을 저장했습니다. (저장 시각: {saved_at:%Y-%m-%d %H:%M:%S} UTC)"
            except ValueError:
                pass
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
    """Backend legal_actions가 허용한 저장 command만 표시한다."""

    _render_shell_command(client=client, game_id=game_id, snapshot=snapshot, command_type="SAVE_AND_EXIT")


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
    with st.container(key="game-agent-activity", border=True):
        st.markdown("#### AI 판단과 실행")
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
            with st.expander("최근 공개 처리 기록", expanded=False):
                for item in records:
                    scope = "현재 차례" if _is_current_activity(item, snapshot) else "이전 기록"
                    time = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).strftime("%H:%M:%S UTC")
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
            st.session_state[pending_key] = {"status": "IN_FLIGHT", "game_id": game_id,
                "expected_state_version": snapshot["game"]["state_version"], "idempotency_key": str(uuid4())}
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
