"""Login gate: Manager (APP_PASSWORD), Admin users, Technician (shared)."""

from __future__ import annotations

from typing import List

import streamlit as st

from lib.admin_users import authenticate_admin, ensure_bootstrap_admin, load_admin_users

ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"
ROLE_TECH = "tech"

# Manager — full access including managing Admin accounts
MANAGER_PAGES = [
    "Check Out",
    "Check In",
    "Out Now",
    "Catalog",
    "Reports",
    "Add Tool",
    "Technicians",
    "Admin users",
    "Import",
    "History",
]

# Admin accounts — full tool-room access, but cannot manage Admin users
ADMIN_PAGES = [
    "Check Out",
    "Check In",
    "Out Now",
    "Catalog",
    "Reports",
    "Add Tool",
    "Technicians",
    "Import",
    "History",
]

TECH_PAGES = [
    "Check Out",
    "Check In",
    "Out Now",
    "Catalog",
    "Reports",
    "History",
]


def _secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "") or "").strip()
    except Exception:
        return ""


def _manager_password() -> str:
    return _secret("APP_PASSWORD")


def _tech_password() -> str:
    return _secret("TECH_PASSWORD")


def auth_enabled() -> bool:
    ensure_bootstrap_admin(_manager_password())
    return bool(
        _tech_password() or _manager_password() or load_admin_users()
    )


def current_role() -> str:
    return str(st.session_state.get("tool_room_role") or ROLE_MANAGER)


def current_admin_name() -> str:
    return str(st.session_state.get("tool_room_admin_name") or "Admin")


def is_admin() -> bool:
    """True for Manager or Admin account — full app access."""
    return current_role() in (ROLE_MANAGER, ROLE_ADMIN)


def is_manager() -> bool:
    return current_role() == ROLE_MANAGER


def pages_for_role(role: str | None = None) -> List[str]:
    r = role or current_role()
    if r == ROLE_TECH:
        return list(TECH_PAGES)
    if r == ROLE_MANAGER:
        return list(MANAGER_PAGES)
    return list(ADMIN_PAGES)


def logout() -> None:
    for key in (
        "tool_room_authenticated",
        "tool_room_role",
        "tool_room_admin_name",
        "tool_room_admin_username",
    ):
        st.session_state.pop(key, None)


def require_login() -> bool:
    """Return True when the session may use the app."""
    ensure_bootstrap_admin(_manager_password())

    if not auth_enabled():
        st.session_state.tool_room_authenticated = True
        st.session_state.tool_room_role = ROLE_MANAGER
        st.session_state.tool_room_admin_name = "Manager"
        return True

    if st.session_state.get("tool_room_authenticated") and st.session_state.get(
        "tool_room_role"
    ):
        return True

    st.markdown("## Specialty Tool Room")
    st.caption("Sign in to continue.")

    tech_tab, admin_tab, manager_tab = st.tabs(
        ["Technician", "Admin", "Manager"]
    )

    with tech_tab:
        st.caption("Shared shop-floor login for check-out / check-in.")
        tech_pw = st.text_input(
            "Technician password",
            type="password",
            key="tool_room_tech_password",
        )
        if st.button(
            "Sign in as Technician", type="primary", use_container_width=True
        ):
            expected = _tech_password()
            if not expected:
                st.error("Technician login is not set up yet (TECH_PASSWORD).")
            elif tech_pw == expected:
                st.session_state.tool_room_authenticated = True
                st.session_state.tool_room_role = ROLE_TECH
                st.session_state.pop("tool_room_admin_name", None)
                st.session_state.pop("tool_room_admin_username", None)
                st.rerun()
            else:
                st.error("Incorrect password.")

    with admin_tab:
        st.caption(
            "Admin accounts can add tools, manage technicians, and import inventory. "
            "Only a Manager can add or remove Admin users."
        )
        admins = load_admin_users()
        if not admins:
            st.info(
                "No admin users yet. A Manager can add them under **Admin users**, "
                "or sign in on the Manager tab first."
            )
        username = st.text_input("Username", key="tool_room_admin_username_input")
        password = st.text_input(
            "Password", type="password", key="tool_room_admin_password_input"
        )
        if st.button("Sign in as Admin", type="primary", use_container_width=True):
            ok, msg, user = authenticate_admin(username, password)
            if ok and user:
                st.session_state.tool_room_authenticated = True
                st.session_state.tool_room_role = ROLE_ADMIN
                st.session_state.tool_room_admin_name = user.get("name") or "Admin"
                st.session_state.tool_room_admin_username = user.get("username") or ""
                st.rerun()
            else:
                st.error(msg)

    with manager_tab:
        st.caption("Full access with the manager password from secrets.")
        manager_pw = st.text_input(
            "Manager password",
            type="password",
            key="tool_room_manager_password",
        )
        if st.button(
            "Sign in as Manager", type="primary", use_container_width=True
        ):
            expected = _manager_password()
            if not expected:
                st.error("Manager login is not set up yet (APP_PASSWORD).")
            elif manager_pw == expected:
                st.session_state.tool_room_authenticated = True
                st.session_state.tool_room_role = ROLE_MANAGER
                st.session_state.tool_room_admin_name = "Manager"
                st.session_state.pop("tool_room_admin_username", None)
                st.rerun()
            else:
                st.error("Incorrect password.")

    return False
