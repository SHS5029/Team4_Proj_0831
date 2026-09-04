"""새 게임 설정과 생성 요청을 담당하는 F2 화면."""

from __future__ import annotations

from uuid import uuid4

import streamlit as st

from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError


ROLE_COUNTS = {
    6: {"마피아": 1, "탐정": 1, "의사": 1, "시민": 3},
    7: {"마피아": 1, "탐정": 1, "의사": 1, "시민": 4},
    8: {"마피아": 2, "탐정": 1, "의사": 1, "시민": 4},
    9: {"마피아": 2, "탐정": 1, "의사": 1, "시민": 5},
}

SETUP_CSS = """
<style>
:root { --setup-ink:#172033; --setup-muted:#65728b; --setup-blue:#2468ed; --setup-dark:#0b1730; --setup-border:#dfe5ef; --setup-bg:#f4f7fb; }
[data-testid="stAppViewContainer"] { background:var(--setup-bg); }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stMainBlockContainer"] { width:min(100%,1180px); max-width:1180px; padding:0 1.5rem 3rem; }
.setup-header { display:flex; align-items:center; justify-content:space-between; min-height:4.2rem; margin:0 -1.5rem 2rem; padding:0 1.5rem; color:#fff; background:var(--setup-dark); border-bottom:1px solid #24324c; }
.setup-brand { font-size:1.55rem; font-weight:800; letter-spacing:-.06em; }
.setup-status { display:inline-flex; align-items:center; gap:.4rem; margin-left:1rem; padding:.42rem .7rem; border:1px solid #2b3b57; border-radius:.55rem; color:#d8e2f3; font-size:.78rem; }
.setup-status::before { content:""; width:.45rem; height:.45rem; border-radius:50%; background:#31c477; }
.setup-nav { display:flex; gap:.7rem; color:#d8e2f3; font-size:.82rem; }
.setup-nav span { padding:.55rem .75rem; border:1px solid #2b3b57; border-radius:.5rem; }
.setup-intro { display:grid; grid-template-columns:.8fr 1.2fr; gap:1.5rem; align-items:center; margin-bottom:1.25rem; }
.setup-breadcrumb { margin-bottom:1.5rem; color:var(--setup-muted); font-size:.9rem; }
.setup-breadcrumb strong { color:var(--setup-blue); }
.setup-intro h1 { margin:0; color:var(--setup-ink); font-size:clamp(2.3rem,5vw,3.5rem); line-height:1.15; letter-spacing:-.06em; }
.setup-intro p { margin:.85rem 0 0; color:var(--setup-muted); font-size:1.1rem; }
.setup-art { min-height:14rem; position:relative; overflow:hidden; border-radius:.7rem; background:linear-gradient(160deg,#eaf2fd 0%,#f9fbff 55%,#d9e5f5 100%); }
.setup-art::before { content:"☾"; position:absolute; top:.5rem; right:24%; color:#1f4c87; font-size:3.2rem; }
.setup-art::after { content:"🏠   🤖   🕵️   🤖   🤖   👓"; position:absolute; right:1rem; bottom:1.1rem; color:#18365f; font-size:2rem; white-space:nowrap; filter:saturate(.75); }
.setup-skyline { position:absolute; right:1rem; bottom:5rem; color:#557aab; font-size:2rem; letter-spacing:.5rem; }
.setup-panel { padding:1.2rem; border:1px solid var(--setup-border); border-radius:.8rem; background:#fff; box-shadow:0 .6rem 1.6rem rgba(20,42,81,.06); }
.setup-panel-title { margin-bottom:.9rem; color:var(--setup-ink); font-size:1.15rem; font-weight:800; }
.setup-count { min-height:8.5rem; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:.75rem; border:1px solid var(--setup-border); border-radius:.8rem; background:#fff; text-align:center; }
.setup-count-selected { border:2px solid var(--setup-blue); box-shadow:0 0 0 3px rgba(36,104,237,.08); }
.setup-count-pieces { display:flex; flex-wrap:wrap; justify-content:center; gap:.08rem; max-width:8.5rem; min-height:1.8rem; color:#71809a; font-size:1.2rem; line-height:1; }
.setup-count-pieces span { display:inline-block; }
.setup-count-selected .setup-count-pieces { color:var(--setup-blue); }
.setup-count-selected .setup-count-icon, .setup-count-selected .setup-count-number { color:var(--setup-blue); }
.setup-count-number { margin-top:.3rem; color:var(--setup-ink); font-size:1.7rem; font-weight:800; }
.setup-count-subtitle { margin-top:.25rem; color:var(--setup-muted); font-size:.82rem; }
[class*="st-key-game-player-count"] [data-testid="stButton"] button { color:#1f4fbd !important; background:#f7faff !important; border:1px solid #b8cdf8 !important; }
[class*="st-key-game-player-count"] [data-testid="stButton"] button:hover:not(:disabled) { color:#17449f !important; background:#eaf2ff !important; }
[data-testid="stButton"] button[kind="primary"] { color:#fff !important; background:linear-gradient(135deg,#3568f2,#5b83ff) !important; border-color:#3568f2 !important; }
[class*="st-key-game-create-cancel"] button { color:#53627a !important; background:#f1f4f8 !important; border-color:#cbd5e1 !important; }
[class*="st-key-game-create-cancel"] button:hover:not(:disabled) { color:#334155 !important; background:#e3e9f1 !important; }
.setup-rules { display:flex; align-items:center; gap:1.5rem; margin-top:1.1rem; padding:1rem 1.2rem; border:1px solid var(--setup-border); border-radius:.8rem; background:#fff; }
.setup-rule-book { font-size:2.6rem; }
.setup-rules-title { margin-bottom:.4rem; color:var(--setup-ink); font-size:1.05rem; font-weight:800; }
.setup-rules-list { display:flex; flex-wrap:wrap; gap:1rem 1.7rem; margin:0; padding:0; color:var(--setup-muted); list-style:none; }
.setup-rules-list li::before { content:"•"; margin-right:.5rem; color:var(--setup-blue); font-size:1.2rem; }
.setup-note { margin-top:1rem; color:var(--setup-muted); text-align:center; }
@media (max-width:760px) { .setup-intro { grid-template-columns:1fr; } .setup-art { min-height:10rem; } .setup-nav { display:none; } .setup-rules { align-items:flex-start; } .setup-rules-list { display:block; } .setup-rules-list li { margin:.35rem 0; } }
</style>
"""


def render(client: ApiClient) -> None:
    """인원 선택을 검증하고 생성 POST를 rerun 이후 한 번만 실행한다."""

    # POST body·idempotency key·pending 상태는 기존 계약을 유지하고, 이 함수에서는
    # 화면 표현만 설정 화면 형태로 조율한다. 사용자가 시나리오·역할·persona를
    # 직접 선택하는 입력은 추가하지 않는다.
    st.markdown(SETUP_CSS, unsafe_allow_html=True)
    st.markdown(
        '<header class="setup-header"><div><span class="setup-brand">AI 마피아</span>'
        '<span class="setup-status">연결됨</span></div>'
        '<nav class="setup-nav"><span>▣&nbsp; 피드백</span><span>⚙&nbsp; 설정</span></nav></header>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="setup-breadcrumb">⌂ &nbsp; 홈 &nbsp; / &nbsp; <strong>새 게임</strong></div>', unsafe_allow_html=True)
    st.markdown(
        '<section class="setup-intro"><div><h1>새 게임 설정</h1>'
        '<p>함께 플레이할 인원을 선택해 주세요</p></div>'
        '<div class="setup-art"><span class="setup-skyline">▰ ▰ ▰ ▰ ▰</span></div></section>',
        unsafe_allow_html=True,
    )

    pending = st.session_state.get("game.create_pending")
    in_flight = isinstance(pending, dict) and pending.get("status") == "IN_FLIGHT"
    selected = _render_player_choices(in_flight=in_flight)
    st.markdown(
        '<section class="setup-rules"><div class="setup-rule-book">📘</div><div>'
        '<div class="setup-rules-title">게임 방식</div><ul class="setup-rules-list">'
        '<li>역할은 무작위로 배정됩니다</li><li>최대 5번째 밤까지 진행됩니다</li>'
        '<li>게임 중 언제든 저장할 수 있습니다</li></ul></div></section>',
        unsafe_allow_html=True,
    )

    button_left, button_right = st.columns([1.1, .6])
    with button_left:
        create_clicked = st.button("◉  게임 만들기", type="primary", key="game.create_submit", disabled=in_flight, use_container_width=True)
    with button_right:
        cancel_clicked = st.button("취소", key="game.create_cancel", disabled=in_flight, use_container_width=True)
    if create_clicked:
        st.session_state["game.create_pending"] = {
            "status": "PENDING_TO_RENDER",
            "player_count": selected,
            "idempotency_key": str(uuid4()),
        }
        st.rerun()
    if cancel_clicked:
        st.session_state["navigation.page"] = "home"
        st.rerun()
    st.markdown('<div class="setup-note">ⓘ &nbsp; 식별자를 잃어버리면 기존 게임을 복구할 수 없어요</div>', unsafe_allow_html=True)

    pending = st.session_state.get("game.create_pending")
    if not isinstance(pending, dict):
        return
    if pending.get("status") == "PENDING_TO_RENDER":
        pending["status"] = "IN_FLIGHT"
        st.session_state["game.create_pending"] = pending
        st.rerun()
    if pending.get("status") != "IN_FLIGHT":
        _render_terminal(pending)
        return

    st.info("게임을 만들고 있어요. 잠시만 기다려 주세요.")
    try:
        response = client.create_game(player_count=int(pending["player_count"]), idempotency_key=str(pending["idempotency_key"]))
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("game_id"), str):
            raise ApiUnavailableError(status_code=503, code="INVALID_RESPONSE")
        snapshot = client.get_game(data["game_id"])
        st.session_state["game.create_pending"] = {**pending, "status": "SUCCEEDED", "game_id": data["game_id"], "snapshot": snapshot}
        st.session_state["game.latest_snapshot"] = snapshot
        st.session_state["game.game_id"] = data["game_id"]
    except ApiResponseError as error:
        status = "RETRYABLE_UNKNOWN" if error.status_code >= 500 else "REJECTED"
        st.session_state["game.create_pending"] = {**pending, "status": status, "code": error.code}
    except (ApiUnavailableError, ValueError) as error:
        st.session_state["game.create_pending"] = {**pending, "status": "RETRYABLE_UNKNOWN", "code": getattr(error, "code", "DEPENDENCY_UNAVAILABLE")}
    st.rerun()


def _render_player_choices(*, in_flight: bool) -> int:
    """6~9명 선택을 카드 형태로 표시하고 기존 session 선택값을 유지한다."""

    selected = st.session_state.setdefault("game.player_count", 6)
    if selected not in ROLE_COUNTS:
        selected = 6
        st.session_state["game.player_count"] = selected
    columns = st.columns(4)
    for column, count in zip(columns, (6, 7, 8, 9), strict=True):
        with column:
            selected_class = " setup-count-selected" if selected == count else ""
            st.markdown(
                f'<div class="setup-count{selected_class}"><div class="setup-count-pieces">'
                + "".join(f'<span aria-hidden="true">♟</span>' for _ in range(count))
                + '</div>'
                f'<div class="setup-count-number">{count}명</div>'
                f'<div class="setup-count-subtitle">AI 플레이어 {count - 1}명</div></div>',
                unsafe_allow_html=True,
            )
            if st.button(f"{count}명 선택", key=f"game.player_count.{count}", disabled=in_flight, width="stretch"):
                st.session_state["game.player_count"] = count
                st.rerun()
    return int(selected)


def _render_terminal(pending: dict[str, object]) -> None:
    """생성 terminal 결과를 고정 문구로 표시하고 같은 key 재시도를 제공한다."""

    status = pending.get("status")
    if status == "SUCCEEDED":
        st.success("게임이 만들어졌어요.")
        st.session_state["navigation.page"] = "game"
    elif status == "RETRYABLE_UNKNOWN":
        st.warning("결과를 확인하지 못했어요. 같은 요청으로 다시 확인할 수 있습니다.")
        if st.button("같은 요청 다시 시도", key="game.create_retry"):
            st.session_state["game.create_pending"] = {**pending, "status": "IN_FLIGHT"}
            st.rerun()
    elif status == "REJECTED":
        st.error("게임을 만들 수 없어요. 입력과 Backend 상태를 확인해 주세요.")
