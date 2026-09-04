"""게임 목록과 새 게임 CTA를 표시하는 F2 홈 화면."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

import streamlit as st

from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError

HOME_CSS = """
<style>
:root { --home-ink:#172033; --home-muted:#65728b; --home-blue:#2468ed; --home-dark:#0b1730; --home-border:#dfe5ef; --home-bg:#f4f7fb; }
[data-testid="stAppViewContainer"] { background:var(--home-bg); }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stMainBlockContainer"] { width:min(100%,1180px); max-width:1180px; padding:0 1.5rem 3rem; }
.home-header { display:flex; align-items:center; justify-content:space-between; min-height:4.2rem; margin:0 -1.5rem 2rem; padding:0 1.5rem; color:#fff; background:var(--home-dark); border-bottom:1px solid #24324c; }
.home-brand { font-size:1.55rem; font-weight:800; letter-spacing:-.06em; }
.home-status { display:inline-flex; align-items:center; gap:.4rem; margin-left:1rem; padding:.42rem .7rem; border:1px solid #2b3b57; border-radius:.55rem; color:#d8e2f3; font-size:.78rem; }
.home-status::before { content:""; width:.45rem; height:.45rem; border-radius:50%; background:#31c477; }
.home-nav { display:flex; gap:.7rem; color:#d8e2f3; font-size:.82rem; }
.home-nav span { padding:.55rem .75rem; border:1px solid #2b3b57; border-radius:.5rem; }
.home-hero { display:grid; grid-template-columns:.9fr 1.1fr; gap:1.5rem; align-items:stretch; margin-bottom:1.25rem; }
.home-hero-copy { padding:.5rem 0 0; }
.home-hero h1 { margin:0; color:var(--home-ink); font-size:clamp(2rem,4vw,3rem); line-height:1.15; letter-spacing:-.055em; }
.home-hero p { margin:.8rem 0 1.5rem; color:var(--home-muted); font-size:1rem; }
.home-hero-art { min-height:13.5rem; overflow:hidden; position:relative; border-radius:.65rem; background:linear-gradient(160deg,#102e5c,#061327 65%,#1b3152); box-shadow:0 1rem 2rem rgba(20,42,81,.14); }
.home-hero-art::before { content:"☾"; position:absolute; top:.75rem; right:24%; color:#8ec8fa; font-size:3rem; }
.home-hero-art::after { content:"🤖  🤖  🤖  🤖  🤖  🤖"; position:absolute; right:1rem; bottom:.85rem; color:#f6f8fb; font-size:2.1rem; letter-spacing:-.5rem; filter:saturate(.8); }
.home-hero-scene { position:absolute; right:1rem; bottom:4.1rem; color:#80a6d6; font-size:.75rem; letter-spacing:.35rem; }
.home-section-title { margin:1.3rem 0 .7rem; color:var(--home-ink); font-size:1.25rem; font-weight:800; }
.home-player-box { padding:1rem 1.15rem; border:1px solid var(--home-border); border-radius:.65rem; background:#fff; }
.home-player-title { margin-bottom:.5rem; color:var(--home-ink); font-weight:800; }
.home-tabs { display:flex; gap:.4rem; margin-bottom:.8rem; }
.home-tab { padding:.45rem .8rem; border:1px solid var(--home-border); border-radius:.45rem; color:var(--home-muted); background:#eef2f8; font-size:.82rem; }
.home-tab-active { color:var(--home-blue); background:#fff; box-shadow:0 2px 6px rgba(20,42,81,.08); }
.home-card { min-height:10rem; padding:.75rem; border:1px solid var(--home-border); border-radius:.65rem; background:#fff; box-shadow:0 .35rem 1rem rgba(20,42,81,.05); }
.home-card-thumb { display:grid; min-height:7.1rem; place-items:center; overflow:hidden; border-radius:.45rem; color:#fff; background:linear-gradient(145deg,#0a1c39,#315a86); font-size:2rem; }
.home-card-thumb.snow { background:linear-gradient(145deg,#20395d,#8eb2da); }
.home-card-title { margin-top:.65rem; color:var(--home-ink); font-size:1rem; font-weight:800; }
.home-card-meta { margin:.25rem 0 .6rem; color:var(--home-muted); font-size:.75rem; }
.home-card-badge { display:inline-block; padding:.25rem .45rem; border-radius:.35rem; color:#16864d; background:#e5f8ec; font-size:.72rem; }
.home-card-badge.saved { color:#c66c08; background:#fff2d9; }
[data-testid="stButton"] button:not([kind="primary"]), [data-testid="baseButton-secondary"] { color:#1f4fbd !important; background:#f7faff !important; border:1px solid #b8cdf8 !important; }
[data-testid="stButton"] button:not([kind="primary"]) *, [data-testid="baseButton-secondary"] * { color:#1f4fbd !important; }
[data-testid="stButton"] button:not([kind="primary"]):hover:not(:disabled), [data-testid="baseButton-secondary"]:hover:not(:disabled) { color:#17449f !important; background:#eaf2ff !important; }
[data-testid="stButton"] button[kind="primary"] { color:#fff !important; background:linear-gradient(135deg,#3568f2,#5b83ff) !important; border-color:#3568f2 !important; }
[data-testid="stButton"] button[kind="primary"] p { color:#fff !important; }
[class*="st-key-home-retry"] button { color:#fff !important; background:linear-gradient(135deg,#3568f2,#5b83ff) !important; border-color:#3568f2 !important; }
[class*="st-key-home-retry"] button p { color:#fff !important; }
@media (max-width:760px) { .home-hero { grid-template-columns:1fr; } .home-hero-art { min-height:10rem; } .home-nav { display:none; } }
</style>
"""


def should_load_games(session_state: Mapping[str, object]) -> bool:
    """최초 목록 조회만 시작하고, 실패 상태에서는 사용자의 재시도 입력을 기다린다."""

    return (
        "home.games" not in session_state
        and "home.games_error" not in session_state
        and not bool(session_state.get("home.games_loading"))
    )


def render(client: ApiClient) -> None:
    """게임 목록의 loading·empty·error·success 상태를 홈 레이아웃 안에서 표시한다."""

    st.markdown(HOME_CSS, unsafe_allow_html=True)
    st.markdown(
        '<header class="home-header"><div><span class="home-brand">AI 마피아</span>'
        '<span class="home-status">연결됨</span></div>'
        '<nav class="home-nav"><span>▣&nbsp; 피드백</span><span>⚙&nbsp; 설정</span></nav></header>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<section class="home-hero"><div class="home-hero-copy">'
        "<h1>AI와 함께 시작하는 추리 게임</h1>"
        "<p>한 명의 플레이어와 개성 있는 AI들이 펼치는 마피아 게임</p>"
        '</div><div class="home-hero-art"><span class="home-hero-scene">▰ ▰ ▰ ▰ ▰</span></div></section>',
        unsafe_allow_html=True,
    )
    if st.button("새 게임 시작  ›", type="primary", key="home.new_game", width="stretch"):
        st.session_state["navigation.page"] = "create"
        st.rerun()
    st.caption("6~9명 · 약 15분")
    with st.container(border=True):
        st.markdown('<div class="home-player-title">플레이어 정보</div>', unsafe_allow_html=True)
        st.caption("현재 구조에서는 UUID를 게임 식별자로 사용합니다. 닉네임은 저장하지 않습니다.")
        user_id = st.session_state.get("identity.user_id")
        st.text_input(
            "게임 식별자 (UUID)", value=str(user_id or ""), disabled=True, key="home.user_id"
        )
    st.markdown('<div class="home-section-title">게임 불러오기</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-tabs"><span class="home-tab home-tab-active">진행 중</span><span class="home-tab">저장됨</span><span class="home-tab">완료</span></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("home.games_loading"):
        st.info("게임 목록을 불러오는 중이에요.")
        return
    error = st.session_state.get("home.games_error")
    if isinstance(error, str):
        st.error("게임 목록을 불러오지 못했어요.")
        if st.button("다시 시도", key="home.retry"):
            st.session_state.pop("home.games_error", None)
            st.session_state.pop("home.games", None)
            st.rerun()
        return
    games = st.session_state.get("home.games", [])
    if not isinstance(games, list) or not games:
        st.info("아직 게임이 없어요. 새 게임을 시작해 보세요.")
        return
    _render_group([g for g in games if g.get("status") in {"IN_PROGRESS", "SAVED"}][:3])


def load_games(client: ApiClient) -> None:
    """목록 endpoint를 호출하고 raw payload를 화면에 노출하지 않는다."""

    # Backend가 소유한 목록만 사용하고, Front가 status나 소유권을 추론하지 않도록 한다.
    try:
        response = client.get_games(limit=20)
        data = response.get("data")
        items = data.get("items", []) if isinstance(data, Mapping) else []
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ApiUnavailableError(status_code=503, code="INVALID_RESPONSE")
        st.session_state["home.games"] = items
        st.session_state.pop("home.games_error", None)
    except (ApiResponseError, ApiUnavailableError) as error:
        st.session_state["home.games_error"] = getattr(error, "code", "DEPENDENCY_UNAVAILABLE")
    finally:
        st.session_state["home.games_loading"] = False


def _render_group(games: list[dict[str, Any]]) -> None:
    """공개 요약 필드만 카드에 표시하고 게임 상태 변경은 Backend에 위임한다."""

    if not games:
        st.caption("진행 중인 게임이 없습니다.")
        return
    columns = st.columns(min(2, len(games)))
    for column, game in zip(columns, games, strict=False):
        with column:
            status = game.get("status")
            title = escape(str(game.get("scenario_title", "사건 정보 없음")))
            thumb_class = " snow" if "SNOW" in str(game.get("scenario_id", "")) else ""
            icon = "❄️" if thumb_class else "📺"
            label = "저장됨" if status == "SAVED" else "토론 중"
            badge_class = " saved" if status == "SAVED" else ""
            st.markdown(
                f'<article class="home-card"><div class="home-card-thumb{thumb_class}">{icon}</div>'
                f'<div class="home-card-title">{title}</div>'
                f'<div class="home-card-meta"><span class="home-card-badge{badge_class}">{label}</span>'
                f" · Day {escape(str(game.get('day_number', 1)))} · Round {escape(str(game.get('round', 0)))}</div></article>",
                unsafe_allow_html=True,
            )
            action = "계속하기" if game.get("can_resume") else "불러오기"
            if st.button(
                action + "  ›", key=f"home.game.{game.get('game_id')}", width="stretch"
            ):
                game_id = game.get("game_id")
                if isinstance(game_id, str):
                    st.session_state["game.game_id"] = game_id
                    st.session_state["navigation.page"] = "game"
                    st.rerun()
