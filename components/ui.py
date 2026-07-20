from __future__ import annotations


def page_hero(title: str, subtitle: str, tag: str = "", tag_style: str = "live") -> str:
    tag_html = ""
    if tag:
        tag_html = f'<span class="hero-tag tag-{tag_style}">{tag}</span>'
    return f"""
    <div class="page-hero">
        <div class="hero-glow"></div>
        {tag_html}
        <h1 class="hero-title">{title}</h1>
        <p class="hero-sub">{subtitle}</p>
    </div>
    """


def stat_card(label: str, value: str, accent: str = "amber", icon: str = "") -> str:
    icon_html = f'<span class="stat-icon">{icon}</span>' if icon else ""
    return f"""
    <div class="stat-card accent-{accent}">
        <div class="stat-top">
            {icon_html}
            <span class="stat-label">{label}</span>
        </div>
        <div class="stat-value">{value}</div>
    </div>
    """


def status_banner(message: str, kind: str = "success") -> str:
    icons = {"success": "●", "warn": "◆", "error": "▲", "info": "◎"}
    return f"""
    <div class="status-banner banner-{kind}">
        <span class="banner-icon">{icons.get(kind, "●")}</span>
        <span>{message}</span>
    </div>
    """
