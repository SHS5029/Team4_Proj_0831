"""일반 사용자 화면 전체에서 공유하는 시각 토큰과 접근성 스타일."""

from __future__ import annotations

import streamlit as st


APP_THEME_CSS = """
<style>
:root {
  --ai-ink: #24152f;
  --ai-muted: #665879;
  --ai-primary: #4b176f;
  --ai-primary-hover: #64258c;
  --ai-surface: #ffffff;
  --ai-bg: #f4f0f8;
  --ai-border: #ddd2e8;
}
html { color-scheme: light; }
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 92% 2%, rgba(131, 69, 170, .18), transparent 24rem),
    linear-gradient(145deg, #f8f5fa 0%, var(--ai-bg) 55%, #ebe1f1 100%);
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
  transform: translateY(-1px); border-color: #8d53aa; box-shadow: 0 8px 18px rgba(75, 23, 111, .18);
}
[data-testid="stButton"] button[kind="primary"],
html body [data-testid="stButton"] button[kind="primary"] {
  color: #ffffff !important;
  border-color: var(--ai-primary) !important;
  background: linear-gradient(135deg, #32104f, var(--ai-primary-hover)) !important;
}
html body [data-testid="stButton"] button[kind="primary"] p { color: #ffffff !important; }
html body [data-testid="stButton"] button:not([kind="primary"]),
html body [data-testid="baseButton-secondary"] {
  color: #3b1952 !important;
  background: #f8f2fb !important;
  border-color: #bfa3ce !important;
}
html body [data-testid="stButton"] button:not([kind="primary"]) p,
html body [data-testid="baseButton-secondary"] p { color: #3b1952 !important; }
html body [data-testid="stTextInput"] input,
html body [data-testid="stTextArea"] textarea,
html body [data-testid="stSelectbox"] > div > div {
  color: #24152f !important;
  background: #ffffff !important;
  border: 1px solid #a88db6 !important;
  border-radius: .68rem;
  caret-color: #4b176f;
}
html body [data-testid="stTextInput"] input:disabled {
  color: #24152f !important;
  -webkit-text-fill-color: #24152f !important;
  opacity: 1 !important;
}
html body [data-testid="stTextInput"] input::placeholder,
html body [data-testid="stTextArea"] textarea::placeholder { color: #756681 !important; opacity: 1; }
[data-testid="stAlert"] { border-radius: .75rem; }
button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 3px solid rgba(75, 23, 111, .35) !important; outline-offset: 2px; }
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
