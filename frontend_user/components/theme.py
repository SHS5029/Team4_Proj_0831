"""일반 사용자 화면 전체에서 공유하는 시각 토큰과 접근성 스타일."""

from __future__ import annotations

import streamlit as st


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
