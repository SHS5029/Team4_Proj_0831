"""일반 사용자 화면 전체에서 공유하는 시각 토큰과 접근성 스타일."""

from __future__ import annotations

import streamlit as st

NAVIGATION_PAGES = frozenset({
    "home",
    "create",
    "creation_complete",
    "feedback",
    "game_feedback",
    "game",
})
NAVIGATION_HISTORY_KEY = "navigation.history"
NAVIGATION_CURRENT_KEY = "navigation.current_page"


APP_THEME_CSS = """
<style>
:root {
  --ai-ink: #152238;
  --ai-muted: #66758f;
  --ai-primary: #245fd6;
  --ai-surface: #ffffff;
  --ai-bg: #f5f7fb;
  --ai-border: #e1e7f0;
}
html { color-scheme: light; }
[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 92% 2%, rgba(160, 190, 255, .2), transparent 24rem), var(--ai-bg);
  color: var(--ai-ink);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stMainBlockContainer"] { padding-top: 1.1rem; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { line-height: 1.65; }
[data-testid="stWidgetLabel"] p { color: var(--ai-ink); font-weight: 650; }
[data-testid="stButton"] button {
  min-height: 2.9rem; border-radius: .72rem; border: 1px solid var(--ai-border); font-weight: 720;
  color: var(--ai-ink) !important; background: var(--ai-surface) !important;
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
[data-testid="stButton"] button:hover:not(:disabled) {
  transform: translateY(-1px); border-color: #a8bced; box-shadow: 0 8px 18px rgba(39, 78, 170, .12);
}
[data-testid="stButton"] button[kind="primary"] { color: #fff !important; border-color: var(--ai-primary); background: linear-gradient(135deg, var(--ai-primary), #1f5ee5) !important; }
[data-testid="stButton"] button:disabled {
  color: #536179 !important; background: #e5eaf2 !important;
  border-color: #aab6c9 !important; opacity: 1 !important; cursor: not-allowed;
}
[data-testid="stButton"] button [data-testid="stMarkdownContainer"] *,
[data-testid="stButton"] button [data-testid="stMarkdownContainer"] {
  color: inherit !important; -webkit-text-fill-color: currentColor !important;
}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] > div > div { border-radius: .68rem; }
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  color: #152238 !important; -webkit-text-fill-color: #152238 !important;
  background: #fff !important; caret-color: #152238; border: 1px solid #8292ad;
}
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {
  color: #586880 !important; -webkit-text-fill-color: #586880 !important; opacity: 1;
}
[data-testid="stTextInput"] input:disabled, [data-testid="stTextArea"] textarea:disabled {
  color: #536179 !important; -webkit-text-fill-color: #536179 !important;
  background: #e5eaf2 !important; opacity: 1;
}
[data-testid="stWidgetLabel"] { color: var(--ai-ink); }
[data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"],
[data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"] p { color: inherit !important; }
[data-testid="stExpander"] details, [data-testid="stExpander"] summary {
  color: #152238 !important; background: #fff !important;
}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"],
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] * {
  color: inherit !important;
}
[data-testid="stAlert"] { border-radius: .75rem; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]),
[data-testid="stAlertContentSuccess"] {
  color: #173626 !important; background: #e8f5ec !important;
}
[data-testid="stAlertContentSuccess"] [data-testid="stMarkdownContainer"] * { color: inherit !important; }
[class*="st-key-app-page-navigation"] {
  margin: -1.15rem 0 1rem; padding: .55rem .65rem !important;
  border: 1px solid var(--ai-border); border-radius: .8rem; background: rgba(255, 255, 255, .94);
  box-shadow: 0 .35rem 1rem rgba(20, 42, 81, .06);
}
[class*="st-key-app-page-navigation"] [data-testid="stButton"] button {
  min-height: 2.65rem; color: #174ea6 !important; background: #f7faff !important;
  border-color: #b8cdf8 !important;
}
button:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 3px solid #245fd6 !important; outline-offset: 3px;
  box-shadow: 0 0 0 2px #fff !important;
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: .6rem .8rem 2rem; }
  [data-testid="stButton"] button { min-height: 3.1rem; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: .01ms !important; } }
</style>
"""


def render_app_theme() -> None:
    """공통 CSS를 주입해 페이지별 레이아웃이 같은 기본 경험을 갖게 한다."""

    st.markdown(APP_THEME_CSS, unsafe_allow_html=True)


def sync_page_navigation(current_page: str) -> str:
    """직접 page 값을 바꾸는 기존 화면 전환을 검증된 방문 기록으로 동기화한다."""

    page = (
        current_page
        if isinstance(current_page, str) and current_page in NAVIGATION_PAGES
        else "home"
    )
    previous = st.session_state.get(NAVIGATION_CURRENT_KEY)
    history = _navigation_history(current_page=page)
    if page == "home":
        history = []
    elif isinstance(previous, str) and previous in NAVIGATION_PAGES and previous != page:
        if not history or history[-1] != previous:
            history.append(previous)
    st.session_state["navigation.page"] = page
    st.session_state[NAVIGATION_HISTORY_KEY] = history[-12:]
    st.session_state[NAVIGATION_CURRENT_KEY] = page
    return page


def render_page_navigation(*, current_page: str) -> None:
    """홈을 제외한 사용자 화면에 앱 방문 기록 기반 이동 button을 표시한다."""

    if current_page == "home":
        return
    history = _navigation_history(current_page=current_page)
    back_target = history[-1] if history else "home"
    remaining_history = history[:-1] if history else []
    with st.container(key="app-page-navigation"):
        back_column, home_column, _ = st.columns([1, 1, 5])
        with back_column:
            if st.button("← 뒤로가기", key="navigation.back", width="stretch"):
                _navigate(page=back_target, history=remaining_history)
        with home_column:
            if st.button("⌂ 홈", key="navigation.home", width="stretch"):
                _navigate(page="home", history=[])


def _navigation_history(*, current_page: str) -> list[str]:
    """session의 손상된 page 값과 현재 화면의 중복 기록을 제거한다."""

    raw_history = st.session_state.get(NAVIGATION_HISTORY_KEY)
    history = (
        [page for page in raw_history if isinstance(page, str) and page in NAVIGATION_PAGES]
        if isinstance(raw_history, list)
        else []
    )
    while history and history[-1] == current_page:
        history.pop()
    return history


def _navigate(*, page: str, history: list[str]) -> None:
    """게임 상태는 보존하고 목적 화면과 검증된 방문 기록만 원자적으로 교체한다."""

    target = page if isinstance(page, str) and page in NAVIGATION_PAGES else "home"
    if target == "home":
        # 홈으로 돌아오면 진행 게임 자체를 지우지 않고 목록 projection만 다시 읽는다.
        for key in ("home.games", "home.games_error", "home.games_loaded_at", "home.games_loading"):
            st.session_state.pop(key, None)
        history = []
    st.session_state["navigation.page"] = target
    st.session_state[NAVIGATION_CURRENT_KEY] = target
    st.session_state[NAVIGATION_HISTORY_KEY] = history[-12:]
    st.rerun()
