"""진행 중 게임의 공통 shell과 공개 timeline 화면."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import streamlit as st

from frontend_user.components.action_panel import render as render_action_panel
from frontend_user.components.sync_bridge import apply_sync, mount_sse, poll_game_progress
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
[class*="st-key-game-player-panel"],
[class*="st-key-game-timeline-panel"],
[class*="st-key-game-my-panel"] {
  min-height: 37rem; padding: 1rem !important; border: 1px solid var(--game-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
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
.game-scene::after { content: "LIVE FEED  /  NIGHT DISTRICT  /  23:40"; color: #d6a9f2; font:600 .72rem/1.2 monospace; letter-spacing:.1rem; }
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
  [class*="st-key-game-timeline-panel"],
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
    "MAFIA": ("마피아", "🕶️"),
    "DETECTIVE": ("탐정", "🕵️"),
    "DOCTOR": ("의사", "🩺"),
    "CITIZEN": ("시민", "👤"),
}


def render(snapshot: dict[str, Any]) -> None:
    """snapshot을 authoritative source로 사용해 desktop 3열 shell을 표시한다."""

    # GET snapshot·sync 결과가 화면의 단일 기준이다. Backend가 제공한 문자열은
    # 일반 Streamlit 텍스트로만 렌더링하고, CSS용 HTML에는 정적 장식만 사용한다.
    client = st.session_state["game.client"]
    game = snapshot.get("game", {})
    game_id = game.get("game_id")
    envelope = mount_sse(
        backend_url=client.config.api_url,
        game_id=str(game.get("game_id")),
        user_id=client.user_id,
        last_sequence=int(game.get("last_sequence", 0)),
    )
    received_from_sse = envelope is not None
    if envelope is None:
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
        if _has_delta_operations(envelope):
            # SSE delta는 공통 공개 operation 중심이므로 사용자별 legal_actions와
            # valid_targets가 비어 있을 수 있다. 변경 batch를 받은 직후 같은
            # game_id의 authoritative snapshot으로 전체 projection을 보강한다.
            try:
                response = client.get_game(str(game.get("game_id")))
                refreshed = response.get("data") if isinstance(response.get("data"), dict) else response
                if isinstance(refreshed, dict) and isinstance(refreshed.get("game"), dict):
                    snapshot = refreshed
            except Exception:
                # delta는 이미 원자적으로 반영했으므로 재조회 일시 실패 시에도
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
        st.session_state["game.sync_status"] = (
            "LIVE" if received_from_sse else "POLLING" if envelope else "STALE"
        )

    poll_game_progress(game_id=str(game_id))

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
        '<nav class="game-nav"><span>피드백</span><span>설정</span></nav></header>',
        unsafe_allow_html=True,
    )

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
        if phase in {"NIGHT_ACTION", "DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}:
            render_action_panel(
                client=client,
                game_id=str(game.get("game_id")),
                snapshot=snapshot,
            )
        else:
            _render_timeline(
                snapshot=snapshot,
                scenario=scenario,
                phase=str(phase),
                day_number=day_number,
            )
            if me.get("alive", False):
                render_action_panel(
                    client=client,
                    game_id=str(game.get("game_id")),
                    snapshot=snapshot,
                )
    with right:
        _render_private_panel(me=me)

    # 사망자는 위의 전용 분기에서 반환되므로 이 아래에는 생존자 입력만 존재한다.


def _has_delta_operations(envelope: dict[str, Any] | None) -> bool:
    """실제 SSE 변경 batch가 있어 개인 projection 재조회가 필요한지 판단한다."""

    if not isinstance(envelope, dict):
        return False
    data = envelope.get("data", envelope)
    if not isinstance(data, dict) or data.get("mode") != "DELTA":
        return False
    operations = data.get("operations")
    return isinstance(operations, list) and bool(operations)


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
                '<div class="game-night-callout"><div><strong>밤이 되었습니다</strong>'
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
        _render_spectator_controls(client=client, game_id=game_id, snapshot=snapshot)
    with right:
        _render_spectator_private(snapshot=snapshot, me=me)


def _render_spectator_players(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """공개 player를 생존자와 사망자로 나누되 숨은 역할은 표시하지 않는다."""

    players = public_players(snapshot)
    alive_players = [player for player in players if player.get("alive")]
    dead_players = [player for player in players if not player.get("alive")]
    with st.container(key="spectator-player-panel", border=True):
        st.markdown(f"### 👥 생존자 ({len(alive_players)})")
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
        icon_col.write("🤖" if player.get("kind") == "AI" else "👤")
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
        st.markdown("### 💬 공개 타임라인")
        st.caption("게임의 공개 이벤트와 발언만 표시됩니다.")
        if not events:
            st.info("아직 표시할 공개 기록이 없습니다.")
        for index, event in enumerate(events):
            with st.container(key=f"spectator-public-event-{index}", border=True):
                speaker = _event_speaker(event=event, player_names=player_names)
                if speaker:
                    st.markdown(f"**💬 {speaker}의 발언**")
                else:
                    st.markdown(f"**{_event_heading(event)}**")
                st.write(_event_text(event=event, player_names=player_names))


def _render_spectator_private(*, snapshot: dict[str, Any], me: dict[str, Any]) -> None:
    """관전 중에도 유지되는 본인의 역할·사망 시점·기존 private 정보만 표시한다."""

    role_name, role_icon = ROLE_PRESENTATION.get(me.get("role"), ("확인 중", "?"))
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
        eliminated_phase = own_public.get("eliminated_phase")
        eliminated_round = own_public.get("eliminated_round")
        with st.container(border=True):
            st.markdown("**📜 기록**")
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


def _render_private_panel(*, me: dict[str, Any]) -> None:
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
            st.markdown("#### 🗝️ 나의 알리바이")
            st.write(str(me.get("alibi", "없음")))
        with st.container(key="game-observation", border=True):
            st.markdown("#### 👁️ 내가 본 것")
            st.write(str(me.get("observation", "없음")))
        private_events = me.get("private_events", [])
        if isinstance(private_events, list) and private_events:
            st.markdown("#### 나에게만 공개된 결과")
            for event in private_events:
                if isinstance(event, dict) and isinstance(event.get("message"), str):
                    st.write(event["message"])


def _event_text(*, event: dict[str, Any], player_names: dict[str, str]) -> str:
    """공개 event의 허용된 data만 사람이 읽을 수 있는 문장으로 변환한다."""

    # PublicEvent는 본문을 data 아래에 두는 폐쇄형 union이다. 다른 player의 선택이나
    # 비공개 payload를 추측해 표시하지 않고 정본에 정의된 공개 필드만 읽는다.
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    message = data.get("message")
    if isinstance(message, str):
        return message
    event_type = event.get("event_type")
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
    if event_type == "VOTE_RESOLVED":
        return "공개 투표 집계가 확정되었습니다."
    if event_type == "FAST_FORWARD_ENABLED":
        return "남은 AI 행동을 빠르게 진행합니다."
    return "공개 사건 기록이 갱신되었습니다."


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
                disabled=enabled
                or "FAST_FORWARD" not in snapshot.get("legal_actions", [])
                or pending_status
                in {"PENDING_TO_RENDER", "IN_FLIGHT", "SUCCEEDED", "RETRYABLE_UNKNOWN"},
                key=toggle_key,
            )
            st.caption("남은 AI 발언·투표·밤 행동을 빠르게 진행합니다.")
            if requested and not enabled and not isinstance(pending, dict):
                st.session_state["game.f6_pending"] = {
                    "status": "IN_FLIGHT",
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
            if st.button("같은 요청 다시 확인", key="spectator.fast_forward.retry"):
                st.session_state["game.f6_pending"] = {
                    **pending,
                    "status": "IN_FLIGHT",
                }
                st.rerun()
        elif pending_status == "REJECTED":
            st.error("게임 상태가 바뀌어 빠른 진행을 켜지 못했습니다.")
            if st.button("최신 상태 다시 확인", key="spectator.fast_forward.refresh"):
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

    if "SAVE_AND_EXIT" not in snapshot.get("legal_actions", []):
        return
    if st.button("💾 저장하고 나가기", key="game.save_exit", use_container_width=True):
        try:
            client.submit_command(
                game_id=game_id,
                command={
                    "type": "SAVE_AND_EXIT",
                    "expected_state_version": snapshot["game"]["state_version"],
                },
                idempotency_key=uuid4(),
            )
            st.session_state["navigation.page"] = "home"
            st.session_state.pop("game.game_id", None)
            st.rerun()
        except Exception:
            st.error("게임을 저장하지 못했어요.")
