CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap');

#MainMenu, footer, header[data-testid="stHeader"] {visibility: hidden; height: 0;}
.stDeployButton {display: none;}

html, body, [class*="css"] {
    font-family: 'Source Sans 3', sans-serif;
    color: #f5f5f4;
}

.stApp {
    background: #0c0a09;
}

.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    background:
        radial-gradient(ellipse 80% 50% at 15% -5%, rgba(245, 158, 11, 0.16), transparent 55%),
        radial-gradient(ellipse 60% 40% at 90% 10%, rgba(234, 88, 12, 0.10), transparent 50%),
        linear-gradient(180deg, #0c0a09 0%, #1c1917 45%, #0c0a09 100%);
    pointer-events: none;
    z-index: 0;
}

.block-container {
    padding-top: 1.25rem !important;
    padding-bottom: 3rem !important;
    max-width: 1200px !important;
}

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1c1917, #0c0a09) !important;
    border-right: 1px solid rgba(245, 158, 11, 0.18);
}

.brand-block { padding: 0.4rem 0 1rem; }
.brand-logo {
    width: 46px; height: 46px; border-radius: 12px;
    background: linear-gradient(135deg, #f59e0b, #ea580c);
    display: flex; align-items: center; justify-content: center;
    font-size: 1.35rem; margin-bottom: 0.7rem;
    box-shadow: 0 0 24px rgba(245, 158, 11, 0.28);
}
.brand-name {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 1.35rem; font-weight: 800; letter-spacing: 0.02em;
    color: #fafaf9;
}
.brand-tag {
    font-size: 0.72rem; color: #a8a29e; letter-spacing: 0.14em;
    text-transform: uppercase; margin-top: 0.1rem;
}
.sidebar-footer {
    margin-top: 1.5rem; padding: 0.9rem;
    border-radius: 10px; background: rgba(245,158,11,0.06);
    border: 1px solid rgba(245,158,11,0.12);
    font-size: 0.8rem; color: #a8a29e;
}

.page-hero {
    position: relative; margin-bottom: 1.25rem; padding: 0.5rem 0 0.75rem;
}
.hero-glow {
    position: absolute; inset: -20% 40% auto -5%; height: 120px;
    background: radial-gradient(ellipse, rgba(245,158,11,0.18), transparent 70%);
    pointer-events: none;
}
.hero-title {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 2.35rem; font-weight: 800; letter-spacing: 0.01em;
    margin: 0.35rem 0 0.35rem; color: #fafaf9;
}
.hero-sub { color: #a8a29e; font-size: 1.02rem; margin: 0; max-width: 42rem; line-height: 1.5; }
.hero-tag {
    display: inline-block; font-size: 0.7rem; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase;
    padding: 0.28rem 0.65rem; border-radius: 999px;
}
.tag-live { background: rgba(34,197,94,0.15); color: #4ade80; border: 1px solid rgba(34,197,94,0.35); }
.tag-warn { background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.35); }

.stat-card {
    position: relative; border-radius: 14px; padding: 1rem 1.1rem;
    background: rgba(28,25,23,0.85);
    border: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 0.75rem;
}
.stat-top { display: flex; align-items: center; gap: 0.45rem; margin-bottom: 0.35rem; }
.stat-icon { font-size: 0.95rem; }
.stat-label { font-size: 0.78rem; color: #a8a29e; letter-spacing: 0.04em; text-transform: uppercase; }
.stat-value {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 2rem; font-weight: 700; line-height: 1;
}
.accent-amber { border-color: rgba(245,158,11,0.28); }
.accent-amber .stat-value { color: #fbbf24; }
.accent-orange { border-color: rgba(234,88,12,0.28); }
.accent-orange .stat-value { color: #fb923c; }
.accent-green { border-color: rgba(34,197,94,0.28); }
.accent-green .stat-value { color: #4ade80; }
.accent-stone { border-color: rgba(168,162,158,0.28); }
.accent-stone .stat-value { color: #d6d3d1; }

.status-banner {
    display: flex; align-items: center; gap: 0.65rem;
    padding: 0.75rem 1rem; border-radius: 10px; margin: 0.5rem 0 1rem;
    font-size: 0.95rem;
}
.banner-success { background: rgba(34,197,94,0.12); border: 1px solid rgba(34,197,94,0.3); color: #bbf7d0; }
.banner-warn { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); color: #fde68a; }
.banner-error { background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.3); color: #fecaca; }
.banner-info { background: rgba(59,130,246,0.12); border: 1px solid rgba(59,130,246,0.3); color: #bfdbfe; }

div[data-testid="stTabs"] button[data-baseweb="tab"] {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 1.05rem; font-weight: 700; letter-spacing: 0.03em;
}
</style>
"""
