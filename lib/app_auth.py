"""Optional password gate for cloud deployments."""

from __future__ import annotations

import streamlit as st


def _configured_password() -> str:
    try:
        return str(st.secrets.get("APP_PASSWORD", "") or "").strip()
    except Exception:
        return ""


def require_login() -> bool:
    password = _configured_password()
    if not password:
        return True

    if st.session_state.get("tool_room_authenticated"):
        return True

    st.markdown("## Specialty Tool Room")
    st.caption("Enter the app password to continue.")
    entered = st.text_input("Password", type="password", key="tool_room_login_password")
    if st.button("Sign in", type="primary", use_container_width=True):
        if entered == password:
            st.session_state.tool_room_authenticated = True
            st.rerun()
        st.error("Incorrect password.")
    return False
