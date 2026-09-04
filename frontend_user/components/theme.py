"""일반 사용자 화면 전체에서 공유하는 시각 토큰과 접근성 스타일."""

from __future__ import annotations

import streamlit as st


APP_THEME_CSS = """
<style>
:root {
  --ai-ink: #152238;
  --ai-muted: #66758f;
  --ai-primary: #3568f2;
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
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
[data-testid="stButton"] button:hover:not(:disabled) {
  transform: translateY(-1px); border-color: #a8bced; box-shadow: 0 8px 18px rgba(39, 78, 170, .12);
}
[data-testid="stButton"] button[kind="primary"] { border-color: var(--ai-primary); background: linear-gradient(135deg, var(--ai-primary), #5b83ff); }
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] > div > div { border-radius: .68rem; }
[data-testid="stAlert"] { border-radius: .75rem; }
button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 3px solid rgba(53, 104, 242, .28) !important; outline-offset: 2px; }
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
