import os
from typing import Optional
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

_PLACEHOLDER_MARKERS = (
    "your_project",
    "your-project",
    "example.supabase",
    "placeholder",
)


def _looks_like_real_supabase_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or "." not in host:
        return False
    if host in {"localhost", "127.0.0.1"}:
        return True
    return "supabase" in host or host.endswith(".co") or host.endswith(".com")


def _looks_like_real_key(key: str) -> bool:
    raw = str(key or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if lowered.startswith("your_") or "service_role" in lowered and len(raw) < 40:
        return False
    if raw in {"your_service_role_key", "your-service-role-key", "changeme"}:
        return False
    return len(raw) >= 20


@st.cache_resource
def get_supabase() -> Optional[Client]:
    load_dotenv()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    try:
        url = url or st.secrets["SUPABASE_URL"]
        key = key or st.secrets["SUPABASE_KEY"]
    except (KeyError, FileNotFoundError, TypeError):
        pass

    url = str(url or "").strip()
    key = str(key or "").strip()
    if not _looks_like_real_supabase_url(url) or not _looks_like_real_key(key):
        return None

    try:
        return create_client(url, key)
    except Exception:
        return None


def is_configured() -> bool:
    return get_supabase() is not None
