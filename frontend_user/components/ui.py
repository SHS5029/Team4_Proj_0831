# ruff: noqa: E501
"""Streamlit 인증 화면에서 사용하는 순수 HTML/CSS 생성 도우미.

이 모듈은 인증 판단이나 세션 변경을 하지 않고 마크업 생성만 담당한다. 호출부가
``unsafe_allow_html=True``로 결과를 렌더링하므로, 외부에서 온 프로필 값은 이
모듈의 경계에서 반드시 HTML 이스케이프해야 한다. 정적 마크업과 사용자 입력을
구분해 유지하는 것이 핵심 보안 계약이다.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from auth.identity import IdentityProfile

# Google 로고는 코드에 고정된 장식 이미지다. 보조 기술이 버튼의 실제 레이블을
# 중복해서 읽지 않도록 SVG 자체는 ``aria-hidden``으로 표시한다.
GOOGLE_G_LOGO = """<svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
  <path fill="#4285F4" d="M17.64 9.205c0-.638-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 0 1-1.797 2.716v2.259h2.909c1.702-1.567 2.684-3.874 2.684-6.615z"/>
  <path fill="#34A853" d="M9 18c2.43 0 4.468-.806 5.956-2.18l-2.909-2.259c-.806.54-1.835.859-3.047.859-2.344 0-4.328-1.585-5.037-3.714H.956v2.332A9 9 0 0 0 9 18z"/>
  <path fill="#FBBC05" d="M3.963 10.706A5.41 5.41 0 0 1 3.681 9c0-.592.102-1.167.282-1.706V4.962H.956A9 9 0 0 0 0 9c0 1.452.347 2.827.956 4.038l3.007-2.332z"/>
  <path fill="#EA4335" d="M9 3.58c1.321 0 2.507.454 3.442 1.345l2.581-2.581C13.464.892 11.426 0 9 0A9 9 0 0 0 .956 4.962l3.007 2.332C4.672 5.165 6.656 3.58 9 3.58z"/>
</svg>"""

# SVG를 CSS ``background-image``에서 외부 파일 요청 없이 사용할 수 있도록 data URI로
# 변환한다. ``quote``의 허용 문자 목록은 SVG 문법에 필요한 문자만 그대로 보존한다.
_GOOGLE_G_DATA_URI = "data:image/svg+xml," + quote(
    GOOGLE_G_LOGO.replace("\n", " "),
    safe="/:=;,%",
)

# 기본 디자인은 프로젝트 주제와 무관한 의미 기반 토큰만 사용한다. Streamlit 위젯은
# 명시적으로 부여한 컨테이너 key에서 생성되는 ``st-key-*`` 클래스를 기준으로
# 한정한다. 난수성 내부 클래스 이름에 직접 의존하면 버전 변경 시 스타일이 쉽게
# 깨질 수 있다.
APP_CSS = f"""
<style>
/* 프로젝트 주제가 정해진 뒤에도 값만 교체할 수 있도록 역할 중심으로 정의한다. */
:root {{
  --color-primary: #2563eb;
  --color-primary-hover: #1d4ed8;
  --color-primary-soft: #eff6ff;
  --color-ink: #111827;
  --color-muted: #667085;
  --color-surface: #ffffff;
  --color-background: #f5f7fa;
  --color-border: #e5e7eb;
  --shadow-card: 0 12px 32px rgba(15, 23, 42, 0.08);
  --radius-sm: 10px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --space-2: 0.5rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
}}

html {{ color-scheme: light; }}

/* 기본 셸은 단일 인증 카드에 집중할 수 있는 중립 배경과 폭만 제공한다. */
[data-testid="stAppViewContainer"] {{
  background: var(--color-background);
  color: var(--color-ink);
}}

[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ visibility: hidden; }}
[data-testid="stDecoration"] {{ display: none; }}

[data-testid="stMainBlockContainer"] {{
  display: flex;
  min-height: 100vh;
  min-height: 100svh;
  width: min(100%, 500px);
  max-width: 500px;
  padding: var(--space-8) var(--space-4);
  flex-direction: column;
  justify-content: center;
}}

/* Streamlit이 본문에 추가하는 직접 자식 블록 안에서도 카드를 수직 중앙에 둔다. */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{
  justify-content: center;
}}

/* key="auth-card"로 만든 컨테이너에만 기본 카드 표면을 적용한다. */
[class*="st-key-auth-card"] {{
  padding: var(--space-8) !important;
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}}

.auth-intro {{
  padding: 0 0 var(--space-6);
  text-align: center;
}}

.auth-symbol {{
  display: grid;
  width: 3rem;
  height: 3rem;
  margin: 0 auto var(--space-4);
  place-items: center;
  border-radius: var(--radius-md);
  color: var(--color-primary);
  background: var(--color-primary-soft);
}}

.auth-symbol svg {{
  width: 1.45rem;
  height: 1.45rem;
  stroke: currentColor;
}}

.auth-symbol-success {{
  color: #067647;
  background: #ecfdf3;
}}

.auth-title {{
  margin: 0;
  color: var(--color-ink);
  font-size: clamp(1.65rem, 5vw, 2rem);
  font-weight: 750;
  line-height: 1.3;
  letter-spacing: -.035em;
  word-break: keep-all;
}}

.auth-description {{
  margin: var(--space-2) 0 0;
  color: var(--color-muted);
  font-size: .94rem;
  line-height: 1.65;
  word-break: keep-all;
}}

/* 로그인 버튼의 실제 클릭·disabled 상태는 Streamlit 위젯이 관리한다. */
[class*="st-key-google-login"] button {{
  min-height: 3.25rem;
  border: 1px solid #d0d5dd !important;
  border-radius: var(--radius-sm) !important;
  color: #344054 !important;
  background: #fff !important;
  font-size: .95rem !important;
  font-weight: 650 !important;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .05);
  transition: background-color .16s ease, border-color .16s ease, box-shadow .16s ease;
}}

[class*="st-key-google-login"] button::before {{
  content: "";
  width: 1.2rem; height: 1.2rem;
  margin-right: .65rem;
  background: center / contain no-repeat url("{_GOOGLE_G_DATA_URI}");
}}

[class*="st-key-google-login"] button:hover:not(:disabled) {{
  border-color: #98a2b3 !important;
  background: #f9fafb !important;
  box-shadow: 0 2px 4px rgba(16, 24, 40, .08);
}}

[class*="st-key-google-login"] button:disabled {{
  color: #98a2b3 !important;
  background: #f9fafb !important;
  opacity: 1;
}}

/* 로그인 후 보이는 로그아웃 버튼도 카드의 중립 스타일과 맞춘다. */
[class*="st-key-account-logout"] button {{
  min-height: 3rem;
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-sm) !important;
  color: #344054 !important;
  background: #fff !important;
  font-weight: 650 !important;
}}

button:focus-visible,
a:focus-visible {{
  outline: 3px solid rgba(37, 99, 235, .28) !important;
  outline-offset: 3px !important;
}}

.privacy-note {{
  margin: var(--space-4) 0 0;
  color: #98a2b3;
  font-size: .76rem;
  line-height: 1.55;
  text-align: center;
  word-break: keep-all;
}}

/* 프로필 값은 아래 ``profile_card_html``에서 이스케이프된 뒤 이 영역에 들어온다. */
.profile-card {{
  padding: 1.25rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: #f9fafb;
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
  background: var(--color-primary);
  box-shadow: 0 4px 10px rgba(37, 99, 235, .18);
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
  color: #067647;
  background: #ecfdf3;
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

/* 좁은 화면에서는 카드가 화면 가장자리와 충분한 간격을 유지하도록 축소한다. */
@media (max-width: 640px) {{
  [data-testid="stMainBlockContainer"] {{ padding: var(--space-6) var(--space-4); }}
  [class*="st-key-auth-card"] {{ padding: var(--space-6) !important; }}
}}

/* 사용자의 운영체제 접근성 설정을 존중해 장식 전환 효과를 사실상 제거한다. */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: .01ms !important; }}
}}
</style>
"""


def login_intro_html() -> str:
    """로그아웃 화면 상단에 표시할 접근성 레이블 포함 정적 HTML을 반환한다."""

    return """
    <section class="auth-intro" aria-labelledby="login-title">
      <span class="auth-symbol" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="5" y="10" width="14" height="10" rx="2"></rect>
          <path d="M8 10V7a4 4 0 0 1 8 0v3"></path>
        </svg>
      </span>
      <h1 class="auth-title" id="login-title">로그인</h1>
      <p class="auth-description">Google 계정으로 안전하게 로그인해 서비스를 이용하세요.</p>
    </section>
    """


def profile_card_html(profile: IdentityProfile) -> str:
    """검증된 프로필 모델을 안전한 사용자 카드 HTML로 변환한다.

    ``IdentityProfile``은 길이와 URL 스킴이 정규화된 도메인 값이지만, HTML 문맥의
    안전성은 별개의 문제다. 텍스트 노드에는 기본 이스케이프를, ``src`` 속성에는
    따옴표까지 포함한 이스케이프를 적용해 마크업 삽입을 막는다. 앞으로 프로필 필드를
    추가할 때도 f-string에 원본 값을 직접 넣지 말고 동일한 경계를 지켜야 한다.
    """

    # 사용자 제공 문자열은 ``unsafe_allow_html=True`` 렌더링 전에 모두 이스케이프한다.
    name = escape(profile.display_name)
    email = escape(profile.email)
    initial = escape((profile.display_name or "U")[0])
    if profile.avatar_url:
        # identity 계층의 HTTPS 검증에 더해 속성 문맥 이스케이프를 방어적으로 적용한다.
        avatar = (
            '<span class="profile-avatar">'
            f'<img src="{escape(profile.avatar_url, quote=True)}" alt="">'
            "</span>"
        )
    else:
        # 이미지가 없을 때 첫 글자를 시각적 아바타로 쓰되 보조 기술에는 숨긴다.
        avatar = f'<span class="profile-avatar-fallback" aria-hidden="true">{initial}</span>'

    # 이메일 검증 배지는 공급자가 전달한 검증 클레임이 참일 때만 표시한다.
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
