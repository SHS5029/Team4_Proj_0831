# ruff: noqa: E501
"""Pure HTML and CSS helpers for the Streamlit authentication screen."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from auth.identity import IdentityProfile

GOOGLE_G_LOGO = """<svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
  <path fill="#4285F4" d="M17.64 9.205c0-.638-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 0 1-1.797 2.716v2.259h2.909c1.702-1.567 2.684-3.874 2.684-6.615z"/>
  <path fill="#34A853" d="M9 18c2.43 0 4.468-.806 5.956-2.18l-2.909-2.259c-.806.54-1.835.859-3.047.859-2.344 0-4.328-1.585-5.037-3.714H.956v2.332A9 9 0 0 0 9 18z"/>
  <path fill="#FBBC05" d="M3.963 10.706A5.41 5.41 0 0 1 3.681 9c0-.592.102-1.167.282-1.706V4.962H.956A9 9 0 0 0 0 9c0 1.452.347 2.827.956 4.038l3.007-2.332z"/>
  <path fill="#EA4335" d="M9 3.58c1.321 0 2.507.454 3.442 1.345l2.581-2.581C13.464.892 11.426 0 9 0A9 9 0 0 0 .956 4.962l3.007 2.332C4.672 5.165 6.656 3.58 9 3.58z"/>
</svg>"""

_GOOGLE_G_DATA_URI = "data:image/svg+xml," + quote(
    GOOGLE_G_LOGO.replace("\n", " "),
    safe="/:=;,%",
)

APP_CSS = f"""
<style>
:root {{
  --color-ocean: #1f6f78;
  --color-ocean-deep: #123f48;
  --color-ocean-soft: #dff0ed;
  --color-sun: #f6b95f;
  --color-sand: #f7f1e7;
  --color-ink: #15343a;
  --color-muted: #64777a;
  --color-surface: rgba(255, 255, 255, 0.94);
  --color-border: rgba(21, 52, 58, 0.12);
  --shadow-card: 0 28px 80px rgba(18, 63, 72, 0.16);
  --radius-sm: 12px;
  --radius-md: 22px;
  --radius-lg: 34px;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
}}

html {{ color-scheme: light; }}

[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(circle at 10% 12%, rgba(246, 185, 95, 0.25), transparent 24rem),
    radial-gradient(circle at 92% 86%, rgba(67, 145, 146, 0.2), transparent 28rem),
    linear-gradient(135deg, #f9f5ed 0%, #edf5f2 48%, #f8fbf9 100%);
  color: var(--color-ink);
}}

[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ visibility: hidden; }}
[data-testid="stDecoration"] {{ display: none; }}

[data-testid="stMainBlockContainer"] {{
  width: min(100%, 1180px);
  max-width: 1180px;
  padding: clamp(2rem, 6vh, 5rem) clamp(1.25rem, 4vw, 3.5rem);
}}

.travel-hero {{
  position: relative;
  min-height: 590px;
  padding: clamp(2rem, 5vw, 4.25rem);
  overflow: hidden;
  border-radius: var(--radius-lg);
  color: #fff;
  background:
    linear-gradient(155deg, rgba(10, 45, 53, 0.05), rgba(7, 39, 46, 0.72)),
    linear-gradient(145deg, #3d9291 0%, #246a72 48%, #123f48 100%);
  box-shadow: var(--shadow-card);
  isolation: isolate;
}}

.travel-hero::before,
.travel-hero::after {{
  content: "";
  position: absolute;
  z-index: -1;
  border-radius: 999px 999px 0 0;
  transform: rotate(-7deg);
}}

.travel-hero::before {{
  width: 125%; height: 42%; left: -17%; bottom: -18%;
  background: rgba(247, 241, 231, 0.18);
}}

.travel-hero::after {{
  width: 100%; height: 31%; right: -36%; bottom: -4%;
  background: rgba(246, 185, 95, 0.26);
}}

.brand-lockup {{
  display: inline-flex;
  align-items: center;
  gap: 0.65rem;
  color: #fff;
  font-weight: 800;
  letter-spacing: 0.16em;
  font-size: 0.88rem;
}}

.brand-mark {{
  display: grid;
  width: 2.1rem; height: 2.1rem;
  place-items: center;
  border: 1px solid rgba(255,255,255,.52);
  border-radius: 50%;
  background: rgba(255,255,255,.13);
  backdrop-filter: blur(10px);
}}

.hero-copy {{ margin-top: clamp(4.5rem, 11vh, 7rem); }}
.hero-eyebrow {{
  margin: 0 0 1rem;
  color: rgba(255,255,255,.74);
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .17em;
}}

.hero-title {{
  margin: 0;
  color: #fff;
  font-size: clamp(2.65rem, 5.4vw, 4.7rem);
  font-weight: 780;
  line-height: 1.04;
  letter-spacing: -.065em;
}}

.hero-title span {{ color: #ffdc9b; }}
.hero-description {{
  max-width: 29rem;
  margin: 1.5rem 0 0;
  color: rgba(255,255,255,.78);
  font-size: clamp(.95rem, 1.5vw, 1.08rem);
  line-height: 1.75;
  word-break: keep-all;
}}

.route-card {{
  display: flex;
  align-items: center;
  gap: .9rem;
  width: fit-content;
  max-width: 100%;
  margin-top: 3.25rem;
  padding: .8rem 1rem .8rem .85rem;
  border: 1px solid rgba(255,255,255,.25);
  border-radius: 999px;
  background: rgba(8, 42, 49, .26);
  backdrop-filter: blur(14px);
}}

.route-icon {{
  display: grid;
  flex: 0 0 2.35rem;
  width: 2.35rem; height: 2.35rem;
  place-items: center;
  border-radius: 50%;
  color: var(--color-ocean-deep);
  background: #ffdc9b;
}}

.route-card p {{ margin: 0; line-height: 1.3; }}
.route-label {{ color: rgba(255,255,255,.62); font-size: .68rem; letter-spacing: .08em; }}
.route-name {{ margin-top: .16rem !important; color: #fff; font-size: .9rem; font-weight: 680; }}

[class*="st-key-auth-card"] {{
  padding: clamp(1.4rem, 2.6vw, 2.15rem) !important;
  border: 1px solid rgba(255,255,255,.82) !important;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(22px);
}}

.auth-intro {{ padding: .2rem .1rem .7rem; }}
.auth-kicker {{
  margin: 0 0 .7rem;
  color: var(--color-ocean);
  font-size: .73rem;
  font-weight: 800;
  letter-spacing: .14em;
}}

.auth-title {{
  margin: 0;
  color: var(--color-ink);
  font-size: clamp(1.9rem, 3.5vw, 2.55rem);
  font-weight: 780;
  line-height: 1.22;
  letter-spacing: -.045em;
  word-break: keep-all;
}}

.auth-description {{
  margin: 1rem 0 0;
  color: var(--color-muted);
  font-size: .96rem;
  line-height: 1.72;
  word-break: keep-all;
}}

[class*="st-key-google-login"] button {{
  min-height: 3.35rem;
  border: 1px solid #d7dfde !important;
  border-radius: var(--radius-sm) !important;
  color: #25383b !important;
  background: #fff !important;
  font-size: .95rem !important;
  font-weight: 680 !important;
  box-shadow: 0 8px 22px rgba(20, 58, 65, .08);
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}}

[class*="st-key-google-login"] button::before {{
  content: "";
  width: 1.2rem; height: 1.2rem;
  margin-right: .65rem;
  background: center / contain no-repeat url("{_GOOGLE_G_DATA_URI}");
}}

[class*="st-key-google-login"] button:hover:not(:disabled) {{
  transform: translateY(-1px);
  border-color: #a9bfbc !important;
  box-shadow: 0 12px 28px rgba(20, 58, 65, .13);
}}

button:focus-visible,
a:focus-visible {{
  outline: 3px solid rgba(31,111,120,.34) !important;
  outline-offset: 3px !important;
}}

.privacy-note {{
  margin: .75rem 0 0;
  color: #819092;
  font-size: .76rem;
  line-height: 1.55;
  text-align: center;
  word-break: keep-all;
}}

.profile-card {{
  padding: 1.25rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: linear-gradient(145deg, #fff, #f1f7f5);
}}

.profile-row {{ display: flex; align-items: center; gap: 1rem; }}
.profile-avatar,
.profile-avatar-fallback {{
  display: grid;
  flex: 0 0 3.5rem;
  width: 3.5rem; height: 3.5rem;
  place-items: center;
  overflow: hidden;
  border: 3px solid #fff;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(135deg, var(--color-ocean), #70aaa5);
  box-shadow: 0 6px 18px rgba(18,63,72,.14);
  font-size: 1.2rem;
  font-weight: 800;
}}

.profile-avatar img {{ width: 100%; height: 100%; object-fit: cover; }}
.profile-copy {{ min-width: 0; }}
.profile-name {{ margin: 0; color: var(--color-ink); font-size: 1.08rem; font-weight: 780; }}
.profile-email {{
  margin: .22rem 0 0;
  overflow: hidden;
  color: var(--color-muted);
  font-size: .82rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

.verified-badge {{
  display: inline-flex;
  align-items: center;
  gap: .32rem;
  margin-top: .7rem;
  padding: .3rem .55rem;
  border-radius: 999px;
  color: #286b60;
  background: #dff2ea;
  font-size: .69rem;
  font-weight: 720;
}}

.verified-badge::before {{ content: "✓"; }}
.sr-only {{
  position: absolute !important;
  width: 1px !important; height: 1px !important;
  padding: 0 !important; margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0,0,0,0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}}

@media (max-width: 760px) {{
  [data-testid="stMainBlockContainer"] {{ padding: 1rem .9rem 2rem; }}
  [data-testid="stHorizontalBlock"] {{ gap: 1rem !important; }}
  .travel-hero {{ min-height: 390px; padding: 1.75rem; border-radius: 26px; }}
  .hero-copy {{ margin-top: 3.5rem; }}
  .hero-description {{ max-width: 21rem; }}
  .route-card {{ margin-top: 2rem; }}
  [class*="st-key-auth-card"] {{ padding: 1.35rem !important; border-radius: 26px; }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: .01ms !important; }}
}}
</style>
"""


def hero_html() -> str:
    return """
    <section class="travel-hero" aria-labelledby="travel-hero-title">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">✦</span>
        <span>YEOJEONG</span>
      </div>
      <div class="hero-copy">
        <p class="hero-eyebrow">YOUR NEXT SCENE</p>
        <h1 class="hero-title" id="travel-hero-title">어디든,<br><span>당신답게.</span></h1>
        <p class="hero-description">낯선 풍경과 오래 남을 순간을 한곳에 담아보세요. 당신만의 다음 여정을 가볍게 시작할 수 있어요.</p>
        <div class="route-card" aria-label="추천 여정">
          <span class="route-icon" aria-hidden="true">↗</span>
          <div>
            <p class="route-label">TODAY'S INSPIRATION</p>
            <p class="route-name">제주 · 오름 너머의 아침</p>
          </div>
        </div>
      </div>
    </section>
    """


def login_intro_html() -> str:
    return """
    <section class="auth-intro" aria-labelledby="login-title">
      <p class="auth-kicker">WELCOME ABOARD</p>
      <h2 class="auth-title" id="login-title">다음 여행을<br>시작해 볼까요?</h2>
      <p class="auth-description">Google 계정 하나로 저장한 장소와 여행 기록을 어디서든 이어서 만나보세요.</p>
    </section>
    """


def profile_card_html(profile: IdentityProfile) -> str:
    name = escape(profile.display_name)
    email = escape(profile.email)
    initial = escape((profile.display_name or "여")[0])
    if profile.avatar_url:
        avatar = (
            '<span class="profile-avatar">'
            f'<img src="{escape(profile.avatar_url, quote=True)}" alt="">'
            "</span>"
        )
    else:
        avatar = f'<span class="profile-avatar-fallback" aria-hidden="true">{initial}</span>'

    verified = (
        '<span class="verified-badge">확인된 Google 계정</span>'
        if profile.email_verified
        else ""
    )
    return f"""
    <section class="profile-card" aria-label="로그인한 사용자">
      <div class="profile-row">
        {avatar}
        <div class="profile-copy">
          <p class="profile-name">{name}님</p>
          <p class="profile-email">{email}</p>
          {verified}
        </div>
      </div>
    </section>
    """
