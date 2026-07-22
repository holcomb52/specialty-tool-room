"""Specialty Tool Room — check-out / check-in accountability for SST inventory."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from components.ui import page_hero, stat_card, status_banner
from lib.app_auth import (
    current_admin_name,
    is_admin,
    is_manager,
    logout,
    pages_for_role,
    require_login,
)
from lib.admin_users import add_admin_user, load_admin_users, remove_admin_user
from lib.specialty_tools_import import parse_tool_inventory_file
from lib.specialty_tools_storage import (
    ACCOUNTABILITY_LABELS,
    ACCOUNTABILITY_LOCATED,
    ACCOUNTABILITY_OPTIONS,
    ACCOUNTABILITY_SIGNED_OUT,
    ACCOUNTABILITY_UNACCOUNTED,
    INVENTORY_RESULT_LOCATED,
    INVENTORY_RESULT_MISSING,
    INVENTORY_RESULT_RETURNED,
    OVERDUE_AFTER_DAYS,
    add_tool,
    all_open_checkout_report_rows,
    apply_inventory_mark,
    checkin_checkout,
    checkout_tool,
    checkouts_for_technician,
    clear_inventory_mark,
    days_checked_out,
    dismiss_overdue_alert,
    find_tool,
    inventory_count_rows,
    inventory_count_stats,
    inventory_stats,
    list_overdue_checkouts,
    load_inventory,
    normalize_accountability,
    qty_out,
    replace_tools_from_import,
    returned_tool_report_rows,
    save_inventory,
    search_tools,
    technicians_with_open_checkouts,
    unique_locations,
    update_checkout,
    update_tool,
)
from lib.reports_pdf import build_checkout_report_pdf, build_inventory_report_pdf
from lib.supabase_client import is_configured
from lib.tech_list import _normalize, add_technician, load_technicians, remove_technician
from styles import CUSTOM_CSS

st.set_page_config(
    page_title="Specialty Tool Room",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if not require_login():
    st.stop()


def _goto_page(page_name: str, **prefs) -> None:
    """Navigate from a dashboard stat card (applied on next run before widgets)."""
    allowed = pages_for_role()
    if page_name not in allowed:
        st.warning(f"“{page_name}” is not available for this login.")
        return
    # Cannot set nav_page after the sidebar radio exists — queue for next run
    st.session_state["_pending_nav"] = page_name
    if prefs:
        st.session_state["_pending_prefs"] = dict(prefs)
    st.rerun()


def _apply_pending_navigation() -> None:
    """Apply queued stat-card navigation before any keyed widgets render."""
    prefs = st.session_state.pop("_pending_prefs", None)
    if isinstance(prefs, dict):
        for key, value in prefs.items():
            st.session_state[key] = value
    pending = st.session_state.pop("_pending_nav", None)
    if pending is not None:
        st.session_state.nav_page = pending


def _clear_checkout_pending() -> None:
    st.session_state.pop("co_pending", None)
    st.session_state.pop("co_ack_checks", None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("co_ack_"):
            del st.session_state[key]


def _complete_pending_checkout(data) -> None:
    pending = st.session_state.get("co_pending") or {}
    tool_id = pending.get("tool_id")
    tech = pending.get("tech")
    if not tool_id or not tech:
        _clear_checkout_pending()
        st.error("Checkout expired — try again.")
        return
    ok, msg = checkout_tool(
        data,
        tool_id,
        tech,
        qty=int(pending.get("qty") or 1),
        note=str(pending.get("note") or ""),
        ro_number=str(pending.get("ro") or ""),
    )
    if ok:
        _persist(data)
        _clear_checkout_pending()
        st.success(msg)
        st.rerun()
    else:
        st.error(msg)


@st.dialog("STOP — Tools already signed out", width="large")
def _multi_tool_ack_dialog(data) -> None:
    pending = st.session_state.get("co_pending") or {}
    tech = str(pending.get("tech") or "")
    existing = checkouts_for_technician(data, tech)
    new_tool = find_tool(data, str(pending.get("tool_id") or ""))
    new_label = (
        f"{new_tool.get('tool_no')} — {new_tool.get('description')}"
        if new_tool
        else "the selected tool"
    )

    st.markdown(
        f"""
        <div class="ack-danger">
            <div class="ack-danger-title">⚠ Acknowledgment required</div>
            <div class="ack-danger-sub">
                <strong>{tech}</strong> already has tool(s) signed out.
                Confirm each one below before signing out <strong>{new_label}</strong>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not existing:
        st.info("No other tools are out for this technician anymore.")
        if st.button("Continue check out", type="primary", use_container_width=True):
            _complete_pending_checkout(data)
        if st.button("Cancel", use_container_width=True):
            _clear_checkout_pending()
            st.rerun()
        return

    checks = {}
    all_checked = True
    for item in existing:
        cid = str(item.get("id") or item.get("tool_no") or "")
        tool_no = item.get("tool_no", "")
        desc = item.get("description", "")
        st.markdown(
            f"""
            <div class="ack-tool-row">
                I acknowledge that I have tool
                <strong>{tool_no}</strong> — <strong>{desc}</strong> signed out.
            </div>
            """,
            unsafe_allow_html=True,
        )
        checked = st.checkbox(
            f"I acknowledge: {tool_no} — {desc}",
            key=f"co_ack_{cid}",
        )
        checks[cid] = checked
        if not checked:
            all_checked = False

    if not all_checked:
        st.error("Check every acknowledgment box before continuing.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancel", use_container_width=True, key="co_ack_cancel"):
            _clear_checkout_pending()
            st.rerun()
    with c2:
        if st.button(
            "I acknowledge — continue check out",
            type="primary",
            use_container_width=True,
            key="co_ack_continue",
            disabled=not all_checked,
        ):
            _complete_pending_checkout(data)


def _fmt_when(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%m/%d %I:%M %p")
    except ValueError:
        return iso[:16]


def _get_data():
    if "specialty_tools_data" not in st.session_state:
        st.session_state.specialty_tools_data = load_inventory()
    return st.session_state.specialty_tools_data


def _persist(data) -> None:
    st.session_state.specialty_tools_data = data
    ok, err = save_inventory(data)
    if not ok and err:
        st.session_state["_sync_error"] = err
    else:
        st.session_state.pop("_sync_error", None)


def _set_flash(message: str, kind: str = "success") -> None:
    st.session_state["_flash"] = {"message": message, "kind": kind}


def _force_upper(key: str) -> None:
    """Keep inventory text fields in ALL CAPS as the user types."""
    val = st.session_state.get(key)
    if isinstance(val, str):
        uppered = val.upper()
        if uppered != val:
            st.session_state[key] = uppered


def _show_flash() -> None:
    flash = st.session_state.pop("_flash", None)
    if not flash:
        return
    msg = str(flash.get("message") or "")
    kind = str(flash.get("kind") or "success")
    if not msg:
        return
    st.markdown(status_banner(msg, kind), unsafe_allow_html=True)
    if kind == "error":
        st.error(msg)
    elif kind == "warn":
        st.warning(msg)
    else:
        st.success(msg)


def _tech_names() -> list[str]:
    # Always reload so local saves (and failed-cloud cases) stay in sync
    st.session_state.tech_names = _normalize(load_technicians())
    return st.session_state.tech_names


def _refresh_app_data() -> None:
    """Reload inventory/tech lists without clearing login session."""
    st.session_state.specialty_tools_data = load_inventory()
    st.session_state.tech_names = _normalize(load_technicians())
    st.session_state.pop("_sync_error", None)
    # Drop transient checkout acknowledgment so refresh isn't stuck on a stale popup
    for key in list(st.session_state.keys()):
        if str(key) in {"co_pending", "co_ack_checks"} or str(key).startswith("co_ack_"):
            st.session_state.pop(key, None)


_apply_pending_navigation()

with st.sidebar:
    st.markdown(
        """
        <div class="brand-block">
            <div class="brand-logo">🔧</div>
            <div class="brand-name">Specialty Tool Room</div>
            <div class="brand-tag">Check-out desk</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    nav_pages = pages_for_role()
    if "nav_page" not in st.session_state or st.session_state.nav_page not in nav_pages:
        st.session_state.nav_page = nav_pages[0]
    page = st.radio(
        "Navigate",
        nav_pages,
        key="nav_page",
        label_visibility="collapsed",
    )
    st.markdown("---")
    if is_manager():
        role_label = "Manager"
    elif is_admin():
        role_label = f"Admin · {current_admin_name()}"
    else:
        role_label = "Technician"
    db_status = "ONLINE" if is_configured() else "LOCAL"
    st.markdown(
        f"""
        <div class="sidebar-footer">
            <div>Signed in as <strong>{role_label}</strong></div>
            <div style="margin-top:0.35rem">Database <strong>{db_status}</strong></div>
            <div style="margin-top:0.35rem">NSB Chrysler · SST</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Refresh", use_container_width=True, key="refresh_app"):
        _refresh_app_data()
        st.rerun()
    if st.button("Sign out", use_container_width=True, key="sign_out"):
        logout()
        st.rerun()

data = _get_data()
tool_count = len(data.get("tools") or [])

st.markdown(
    page_hero(
        "Specialty Tool Room",
        "Every specialty tool that leaves the room gets a name on it — and every return gets logged.",
        tag="Live" if tool_count else "Import Needed",
        tag_style="live" if tool_count else "warn",
    ),
    unsafe_allow_html=True,
)

if st.session_state.get("_sync_error"):
    st.markdown(
        status_banner(
            f"Saved locally, but cloud sync failed. Run supabase/schema.sql. ({st.session_state['_sync_error']})",
            "warn",
        ),
        unsafe_allow_html=True,
    )

stats = inventory_stats(data)
row1 = st.columns(3)
row2 = st.columns(3)
with row1[0]:
    if st.button(
        f"🔧  Tools on file\n{stats['active']}",
        key="stat_tools_on_file",
        use_container_width=True,
        help="Open Catalog — all active tools",
    ):
        _goto_page(
            "Catalog",
            cat_query="",
            cat_status="active",
            cat_loc="(any location)",
            cat_out=False,
            cat_with_loc=False,
            cat_without_loc=False,
            cat_unaccounted=False,
        )
with row1[1]:
    if st.button(
        f"📤  Checked out now\n{stats['out_now']}",
        key="stat_checked_out",
        use_container_width=True,
        help="Open Out Now — tools currently signed out",
    ):
        _goto_page("Out Now", out_now_overdue_only=False)
with row1[2]:
    if st.button(
        f"⚠  Out over 5 days\n{stats['overdue']}",
        key="stat_overdue",
        use_container_width=True,
        help="Open Out Now — tools out 5+ days",
    ):
        _goto_page("Out Now", out_now_overdue_only=True)
with row2[0]:
    if st.button(
        f"📍  With location\n{stats['with_location']}",
        key="stat_with_location",
        use_container_width=True,
        help="Open Catalog — tools that have a location assigned",
    ):
        _goto_page(
            "Catalog",
            cat_query="",
            cat_status="all",
            cat_loc="(any location)",
            cat_out=False,
            cat_with_loc=True,
            cat_without_loc=False,
            cat_unaccounted=False,
        )
with row2[1]:
    if st.button(
        f"⬚  No location\n{stats['without_location']}",
        key="stat_without_location",
        use_container_width=True,
        help="Open Catalog — assign locations to tools missing one",
    ):
        _goto_page(
            "Catalog",
            cat_query="",
            cat_status="active",
            cat_loc="(any location)",
            cat_out=False,
            cat_with_loc=False,
            cat_without_loc=True,
            cat_unaccounted=False,
        )
with row2[2]:
    if st.button(
        f"❓  Unaccounted\n{stats['unaccounted']}",
        key="stat_unaccounted",
        use_container_width=True,
        help="Open Catalog — tools marked unaccounted for (relocate or replace)",
    ):
        _goto_page(
            "Catalog",
            cat_query="",
            cat_status="all",
            cat_loc="(any location)",
            cat_out=False,
            cat_with_loc=False,
            cat_without_loc=False,
            cat_unaccounted=True,
        )

overdue = list_overdue_checkouts(data)
if overdue:
    st.markdown(
        status_banner(
            f"{len(overdue)} tool(s) have been out {OVERDUE_AFTER_DAYS}+ days — dismiss until a date if still needed.",
            "warn",
        ),
        unsafe_allow_html=True,
    )
    for item in overdue:
        cid = str(item.get("id") or "")
        days_out = int(item.get("days_out") or days_checked_out(item))
        with st.container():
            st.markdown(
                f"""
                <div class="overdue-alert">
                    <div class="overdue-title">{item.get('tool_no', '')} — {item.get('description', '')}</div>
                    <div class="overdue-meta">With <strong>{item.get('tech_name', '')}</strong>
                    · out {days_out} day(s)
                    · since {_fmt_when(item.get('checked_out_at', ''))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            d1, d2, d3 = st.columns([1.4, 1.2, 1])
            with d1:
                snooze_until = st.date_input(
                    "Dismiss alert until",
                    value=date.today() + timedelta(days=7),
                    min_value=date.today() + timedelta(days=1),
                    key=f"overdue_until_{cid}",
                )
            with d2:
                st.write("")
                st.write("")
                if st.button(
                    "Dismiss until date",
                    key=f"overdue_dismiss_{cid}",
                    use_container_width=True,
                ):
                    ok, msg = dismiss_overdue_alert(data, cid, snooze_until)
                    if ok:
                        _persist(data)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            with d3:
                st.write("")
                st.write("")
                if st.button(
                    "Check in now",
                    key=f"overdue_checkin_{cid}",
                    use_container_width=True,
                    type="primary",
                ):
                    ok, msg = checkin_checkout(data, cid)
                    if ok:
                        _persist(data)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

st.markdown("<hr>", unsafe_allow_html=True)

if page == "Check Out / In":
    if st.session_state.get("co_pending"):
        _multi_tool_ack_dialog(data)

    left, right = st.columns(2)
    with left:
        st.markdown("##### Check out a tool")
        techs = _tech_names()
        find = st.text_input(
            "Find tool # or description",
            placeholder="e.g. C-4150 or ball joint",
            key="co_find",
        )
        tools = search_tools(data, find, status="active")
        available = [t for t in tools if t.get("qty_available", 0) > 0][:75]
        if not find.strip():
            st.caption("Type a tool number or keyword, then pick from the matches.")
        if available:
            labels = {
                t["id"]: (
                    f"{t.get('tool_no')} — {t.get('description')}"
                    + (f"  [{t.get('location')}]" if t.get("location") else "")
                    + f"  ({t.get('qty_available')} avail)"
                )
                for t in available
            }
            pick = st.selectbox(
                "Matching tools",
                options=list(labels.keys()),
                format_func=lambda i: labels[i],
                key="co_tool",
            )
            selected = next((t for t in available if t["id"] == pick), None)
            a1, a2 = st.columns(2)
            with a1:
                if techs:
                    tech = st.selectbox("Technician", options=techs, key="co_tech")
                else:
                    tech = st.text_input("Technician name", key="co_tech_manual")
                    st.caption("Add names under Technicians for a dropdown.")
            with a2:
                max_qty = int(selected.get("qty_available") or 1) if selected else 1
                qty = st.number_input(
                    "Qty", min_value=1, max_value=max(1, max_qty), value=1, key="co_qty"
                )
            b1, b2 = st.columns(2)
            with b1:
                ro = st.text_input("RO #", key="co_ro", placeholder="Required")
            with b2:
                note = st.text_input("Note (optional)", key="co_note")
            if st.button("Check out", type="primary", use_container_width=True, key="co_btn"):
                tech_name = str(tech or "").strip()
                ro_clean = str(ro or "").strip()
                if not tech_name:
                    st.error("Select a technician.")
                elif not ro_clean:
                    st.error("Enter an RO number.")
                else:
                    already_out = checkouts_for_technician(data, tech_name)
                    if already_out:
                        st.session_state.co_pending = {
                            "tool_id": pick,
                            "tech": tech_name,
                            "qty": int(qty),
                            "note": note,
                            "ro": ro_clean,
                        }
                        st.rerun()
                    else:
                        ok, msg = checkout_tool(
                            data,
                            pick,
                            tech_name,
                            qty=int(qty),
                            note=note,
                            ro_number=ro_clean,
                        )
                        if ok:
                            _persist(data)
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
        elif find.strip():
            st.info("No available tools match that search.")

    with right:
        st.markdown("##### Check in a tool")
        checkouts = list(data.get("active_checkouts") or [])
        if not checkouts:
            st.info("Nothing is checked out right now.")
        else:
            checkouts_sorted = sorted(
                checkouts, key=lambda c: c.get("checked_out_at") or "", reverse=True
            )
            labels = {
                c["id"]: (
                    f"{c.get('tool_no')} — {c.get('tech_name')}"
                    + (f" ×{c.get('qty')}" if int(c.get("qty") or 1) > 1 else "")
                    + f"  (out {_fmt_when(c.get('checked_out_at', ''))})"
                )
                for c in checkouts_sorted
            }
            pick = st.selectbox(
                "Open checkout",
                options=list(labels.keys()),
                format_func=lambda i: labels[i],
                key="ci_pick",
            )
            note = st.text_input("Check-in note (optional)", key="ci_note")
            if st.button("Check in", type="primary", use_container_width=True, key="ci_btn"):
                ok, msg = checkin_checkout(data, pick, note=note)
                if ok:
                    _persist(data)
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

elif page == "Out Now":
    checkouts = list(data.get("active_checkouts") or [])
    overdue_only = bool(st.session_state.get("out_now_overdue_only"))
    if overdue_only:
        checkouts = [c for c in checkouts if days_checked_out(c) >= OVERDUE_AFTER_DAYS]
        st.caption(f"Showing tools out {OVERDUE_AFTER_DAYS}+ days only.")
        if st.button("Show all checked out", key="out_now_clear_overdue"):
            st.session_state.out_now_overdue_only = False
            st.rerun()

    if not checkouts:
        if overdue_only:
            st.markdown(
                status_banner(
                    f"No tools have been out {OVERDUE_AFTER_DAYS}+ days right now.",
                    "success",
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                status_banner("Special tool room is clear — nothing checked out.", "success"),
                unsafe_allow_html=True,
            )
    else:
        rows = [
            {
                "Tool #": c.get("tool_no", ""),
                "Description": c.get("description", ""),
                "Technician": c.get("tech_name", ""),
                "Qty": c.get("qty", 1),
                "Days out": days_checked_out(c),
                "RO #": c.get("ro_number", ""),
                "Out since": _fmt_when(c.get("checked_out_at", "")),
                "Note": c.get("note", ""),
            }
            for c in sorted(
                checkouts,
                key=lambda x: (days_checked_out(x), str(x.get("checked_out_at") or "")),
                reverse=True,
            )
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("##### Correct technician / details")
        st.caption("Use this if the wrong tech was selected when the tool was checked out.")
        checkouts_sorted = sorted(
            checkouts,
            key=lambda x: (days_checked_out(x), str(x.get("checked_out_at") or "")),
            reverse=True,
        )
        fix_labels = {
            c["id"]: (
                f"{c.get('tool_no')} — {c.get('tech_name') or '(no tech)'}"
                + f"  (out {_fmt_when(c.get('checked_out_at', ''))})"
            )
            for c in checkouts_sorted
        }
        fix_id = st.selectbox(
            "Checkout to correct",
            options=list(fix_labels.keys()),
            format_func=lambda i: fix_labels[i],
            key="out_now_fix_id",
        )
        selected_fix = next((c for c in checkouts_sorted if c["id"] == fix_id), None)
        techs = _tech_names()
        current_tech = str((selected_fix or {}).get("tech_name") or "")
        tech_options = list(techs)
        if current_tech and current_tech not in tech_options:
            tech_options = [current_tech] + tech_options
        if not tech_options:
            st.warning("Add technicians under Technicians first.")
        else:
            # Key by checkout id so fields refresh when a different row is selected
            tech_key = f"out_now_fix_tech_{fix_id}"
            ro_key = f"out_now_fix_ro_{fix_id}"
            note_key = f"out_now_fix_note_{fix_id}"
            if tech_key not in st.session_state:
                st.session_state[tech_key] = (
                    current_tech if current_tech in tech_options else tech_options[0]
                )
            if ro_key not in st.session_state:
                st.session_state[ro_key] = str((selected_fix or {}).get("ro_number") or "")
            if note_key not in st.session_state:
                st.session_state[note_key] = str((selected_fix or {}).get("note") or "")

            new_tech = st.selectbox(
                "Correct technician",
                options=tech_options,
                key=tech_key,
            )
            f1, f2 = st.columns(2)
            with f1:
                new_ro = st.text_input("RO #", key=ro_key)
            with f2:
                new_note = st.text_input("Note", key=note_key)
            if st.button(
                "Save correction",
                type="primary",
                use_container_width=True,
                key="out_now_fix_save",
            ):
                ok, msg = update_checkout(
                    data,
                    fix_id,
                    tech_name=new_tech,
                    ro_number=new_ro,
                    note=new_note,
                )
                if ok:
                    _persist(data)
                    for key in (tech_key, ro_key, note_key):
                        st.session_state.pop(key, None)
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

elif page == "Catalog":
    locs = ["(any location)"] + unique_locations(data)
    # Defaults from clickable dashboard stats (session prefs)
    if "cat_status" not in st.session_state:
        st.session_state.cat_status = "active"
    if "cat_loc" not in st.session_state:
        st.session_state.cat_loc = "(any location)"
    if "cat_out" not in st.session_state:
        st.session_state.cat_out = False
    if "cat_with_loc" not in st.session_state:
        st.session_state.cat_with_loc = False
    if "cat_without_loc" not in st.session_state:
        st.session_state.cat_without_loc = False
    if "cat_unaccounted" not in st.session_state:
        st.session_state.cat_unaccounted = False

    f1, f2, f3, f4 = st.columns([2.2, 1.2, 1.2, 1.4])
    with f1:
        query = st.text_input(
            "Search tool #, description, or location",
            placeholder="e.g. C-4150 or ball joint",
            key="cat_query",
        )
    with f2:
        status = st.selectbox(
            "Status",
            options=["active", "non_current", "all"],
            format_func=lambda s: {
                "active": "Active",
                "non_current": "Non-current",
                "all": "All",
            }[s],
            key="cat_status",
        )
    with f3:
        loc_pick = st.selectbox("Location", options=locs, key="cat_loc")
    with f4:
        only_out = st.checkbox("Out only", key="cat_out")
        only_with_loc = st.checkbox("Has location", key="cat_with_loc")
        only_without_loc = st.checkbox("No location", key="cat_without_loc")
        only_unaccounted = st.checkbox("Unaccounted", key="cat_unaccounted")

    # Keep location filters exclusive with unaccounted / each other
    if only_unaccounted:
        only_with_loc = False
        only_without_loc = False
    elif only_without_loc and only_with_loc:
        only_with_loc = False

    location = "" if loc_pick == "(any location)" else loc_pick
    matches = search_tools(
        data,
        query,
        status=status,
        location=location,
        only_out=only_out,
        only_with_location=only_with_loc,
        only_without_location=only_without_loc,
        only_unaccounted=only_unaccounted,
    )
    st.caption(f"{len(matches)} tool(s)")

    if only_without_loc:
        st.markdown(
            status_banner(
                "Tools with no published location — assign location and mark Located, Signed out, or Unaccounted for.",
                "warn",
            ),
            unsafe_allow_html=True,
        )
    if only_unaccounted:
        st.markdown(
            status_banner(
                "Unaccounted tools — relocate them or note replacement plans here.",
                "error",
            ),
            unsafe_allow_html=True,
        )

    show_assign = (only_without_loc or only_unaccounted) and matches and is_admin()
    if show_assign:
        st.markdown(
            "##### Assign location & status"
            if only_without_loc
            else "##### Update unaccounted tool"
        )
        assign_options = {
            t["id"]: f"{t.get('tool_no')} — {t.get('description')}"
            for t in matches[:400]
        }
        assign_id = st.selectbox(
            "Tool",
            options=list(assign_options.keys()),
            format_func=lambda i: assign_options[i],
            key="assign_loc_tool",
        )
        selected_assign = next((t for t in matches if t["id"] == assign_id), None)
        currently_out = bool(
            selected_assign and qty_out(data, selected_assign["id"]) > 0
        )
        default_acct = ACCOUNTABILITY_UNACCOUNTED if only_unaccounted else (
            ACCOUNTABILITY_SIGNED_OUT if currently_out else ACCOUNTABILITY_LOCATED
        )
        if only_unaccounted and selected_assign:
            existing_acct = normalize_accountability(
                selected_assign.get("accountability")
            )
            if existing_acct in ACCOUNTABILITY_OPTIONS:
                default_acct = existing_acct

        a1, a2 = st.columns([1.4, 1.6])
        with a1:
            assign_loc = st.text_input(
                "Special location / assignment",
                placeholder="E.G. SHELF D / WALL 14 (OPTIONAL IF UNACCOUNTED)",
                key="assign_loc_value",
                on_change=_force_upper,
                args=("assign_loc_value",),
            )
        with a2:
            if "assign_acct_status" not in st.session_state:
                st.session_state.assign_acct_status = default_acct
            assign_acct = st.radio(
                "This tool is",
                options=list(ACCOUNTABILITY_OPTIONS),
                format_func=lambda s: ACCOUNTABILITY_LABELS[s],
                horizontal=True,
                key="assign_acct_status",
            )
            st.caption(
                "Located = found in room · Signed out = with a tech · Unaccounted for = missing"
            )

        if currently_out and assign_acct != ACCOUNTABILITY_SIGNED_OUT:
            st.caption("Note: this tool currently has an open checkout.")

        save_label = (
            "Save location & status" if only_without_loc else "Save status / location"
        )
        if st.button(
            save_label,
            type="primary",
            use_container_width=True,
            key="assign_loc_save",
        ):
            clean_loc = str(assign_loc or "").strip()
            if assign_acct != ACCOUNTABILITY_UNACCOUNTED and not clean_loc:
                st.error("Enter a location, or mark the tool Unaccounted for.")
            else:
                ok, msg = update_tool(
                    data,
                    assign_id,
                    location=clean_loc,
                    accountability=assign_acct,
                )
                if ok:
                    _persist(data)
                    st.session_state.pop("assign_loc_value", None)
                    st.session_state.pop("assign_acct_status", None)
                    if assign_acct == ACCOUNTABILITY_UNACCOUNTED:
                        st.success(f"{msg} — moved to Unaccounted list.")
                    elif assign_acct == ACCOUNTABILITY_SIGNED_OUT:
                        st.success(f"{msg} — marked Signed out.")
                    else:
                        st.success(f"{msg} — moved to With location list.")
                    st.rerun()
                else:
                    st.error(msg)
        st.markdown("---")
    elif (only_without_loc or only_unaccounted) and matches and not is_admin():
        st.caption("Sign in as Manager or Admin to update locations and status.")

    if matches:
        rows = []
        for t in matches[:400]:
            avail = t.get("qty_available", 0)
            out = t.get("qty_out", 0)
            status_label = "OUT" if out and avail == 0 else ("PARTIAL" if out else "IN")
            acct = normalize_accountability(t.get("accountability"))
            rows.append(
                {
                    "Tool #": t.get("tool_no", ""),
                    "Description": t.get("description", ""),
                    "Location": t.get("location", "") or "(none)",
                    "Accountability": ACCOUNTABILITY_LABELS.get(acct, "—"),
                    "Qty": t.get("quantity", 1),
                    "Avail": avail,
                    "Out": out,
                    "Status": status_label,
                    "Notes": t.get("notes", ""),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if len(matches) > 400:
            st.caption(f"Showing first 400 of {len(matches)}. Narrow your search.")

        if is_admin() and not only_without_loc and not only_unaccounted:
            st.markdown("---")
            st.markdown("##### Edit location / assignment")
            edit_options = {
                t["id"]: f"{t.get('tool_no')} — {t.get('description')}" for t in matches[:200]
            }
            edit_id = st.selectbox(
                "Tool to edit",
                options=list(edit_options.keys()),
                format_func=lambda i: edit_options[i],
                key="edit_tool_id",
            )
            tool = next((t for t in matches if t["id"] == edit_id), None)
            if tool:
                e1, e2 = st.columns(2)
                with e1:
                    new_loc = st.text_input(
                        "Special location / assignment",
                        value=str(tool.get("location", "") or "").upper(),
                        key="edit_loc",
                        on_change=_force_upper,
                        args=("edit_loc",),
                    )
                    new_qty = st.number_input(
                        "Quantity on hand",
                        min_value=1,
                        value=max(1, int(tool.get("quantity") or 1)),
                        key="edit_qty",
                    )
                    new_acct = st.selectbox(
                        "Accountability",
                        options=[""] + list(ACCOUNTABILITY_OPTIONS),
                        index=(
                            (list(ACCOUNTABILITY_OPTIONS).index(
                                normalize_accountability(tool.get("accountability"))
                            )
                            + 1)
                            if normalize_accountability(tool.get("accountability"))
                            in ACCOUNTABILITY_OPTIONS
                            else 0
                        ),
                        format_func=lambda s: ACCOUNTABILITY_LABELS.get(s, "(not set)"),
                        key="edit_acct",
                    )
                with e2:
                    new_desc = st.text_input(
                        "Description",
                        value=str(tool.get("description", "") or "").upper(),
                        key="edit_desc",
                        on_change=_force_upper,
                        args=("edit_desc",),
                    )
                    new_notes = st.text_input(
                        "Notes",
                        value=str(tool.get("notes", "") or "").upper(),
                        key="edit_notes",
                        on_change=_force_upper,
                        args=("edit_notes",),
                    )
                    new_status = st.selectbox(
                        "Catalog status",
                        options=["active", "non_current"],
                        index=0 if tool.get("status") == "active" else 1,
                        format_func=lambda s: "Active" if s == "active" else "Non-current",
                        key="edit_status",
                    )
                if st.button("Save tool changes", use_container_width=True, key="edit_save"):
                    ok, msg = update_tool(
                        data,
                        edit_id,
                        description=new_desc,
                        quantity=int(new_qty),
                        location=new_loc,
                        notes=new_notes,
                        status=new_status,
                        accountability=new_acct,
                    )
                    if ok:
                        _persist(data)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
    else:
        if only_without_loc:
            st.markdown(
                status_banner("Every tool in this filter has a location assigned.", "success"),
                unsafe_allow_html=True,
            )
        elif only_unaccounted:
            st.markdown(
                status_banner("No unaccounted tools right now.", "success"),
                unsafe_allow_html=True,
            )
        else:
            st.info("No tools match those filters.")

elif page == "Add Tool":
    if not is_admin():
        st.warning("Admin login required.")
        st.stop()
    if "add_form_nonce" not in st.session_state:
        st.session_state.add_form_nonce = 0
    # Remount inputs with a new key suffix so the form is blank after a save
    if st.session_state.pop("_clear_add_form", None):
        old = int(st.session_state.add_form_nonce)
        for key in (
            f"add_no_{old}",
            f"add_desc_{old}",
            f"add_notes_{old}",
            f"add_loc_{old}",
            f"add_qty_{old}",
            f"add_status_{old}",
        ):
            st.session_state.pop(key, None)
        st.session_state.add_form_nonce = old + 1
    form_id = int(st.session_state.add_form_nonce)
    _show_flash()
    st.markdown("##### Add a new specialty tool")
    a1, a2 = st.columns(2)
    with a1:
        tool_no = st.text_input(
            "Tool number",
            key=f"add_no_{form_id}",
            placeholder="E.G. 2081700090",
            on_change=_force_upper,
            args=(f"add_no_{form_id}",),
        )
        qty = st.number_input(
            "Quantity", min_value=1, value=1, key=f"add_qty_{form_id}"
        )
        location = st.text_input(
            "Special location / assignment",
            key=f"add_loc_{form_id}",
            placeholder="E.G. SHELF D / WALL 14",
            on_change=_force_upper,
            args=(f"add_loc_{form_id}",),
        )
    with a2:
        description = st.text_input(
            "Description",
            key=f"add_desc_{form_id}",
            placeholder="STRETCH BELT TOOL",
            on_change=_force_upper,
            args=(f"add_desc_{form_id}",),
        )
        notes = st.text_input(
            "Notes",
            key=f"add_notes_{form_id}",
            placeholder="NEW TOOL",
            on_change=_force_upper,
            args=(f"add_notes_{form_id}",),
        )
        status = st.selectbox(
            "Status",
            options=["active", "non_current"],
            format_func=lambda s: "Active" if s == "active" else "Non-current",
            key=f"add_status_{form_id}",
        )
    if st.button("Add tool to inventory", type="primary", use_container_width=True, key="add_btn"):
        ok, msg, tool = add_tool(
            data,
            tool_no=tool_no,
            description=description,
            quantity=int(qty),
            location=location,
            notes=notes,
            status=status,
        )
        if ok:
            _persist(data)
            saved_no = (tool or {}).get("tool_no") or str(tool_no).strip()
            _set_flash(f"Saved — {saved_no} was added to inventory.")
            st.session_state["_clear_add_form"] = True
            st.rerun()
        else:
            st.error(msg)

elif page == "Technicians":
    if not is_admin():
        st.warning("Admin login required.")
        st.stop()
    st.markdown("##### Technicians who can check tools out")
    techs = _tech_names()
    new_name = st.text_input("Add technician", placeholder="Full name", key="tech_add_name")
    if st.button("Add to list", type="primary", key="tech_add_btn"):
        ok, msg, updated = add_technician(techs, new_name)
        if ok:
            st.session_state.tech_names = updated
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

    if techs:
        st.dataframe(
            pd.DataFrame({"Technician": techs}),
            use_container_width=True,
            hide_index=True,
        )
        remove = st.selectbox("Remove technician", options=techs, key="tech_remove")
        if st.button("Remove selected", key="tech_remove_btn"):
            ok, msg, updated = remove_technician(techs, remove)
            if ok:
                st.session_state.tech_names = updated
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    else:
        st.info("No technicians yet. Add names so check-out is a quick dropdown.")

elif page == "Admin users":
    if not is_manager():
        st.warning("Manager login required.")
        st.stop()
    st.markdown("##### Admin users")
    st.caption(
        "Only Managers can add or remove Admin accounts. Admins have full tool-room access "
        "(add tools, technicians, import) but cannot manage other admins."
    )
    admins = load_admin_users()
    a1, a2 = st.columns(2)
    with a1:
        admin_name = st.text_input(
            "Full name", placeholder="e.g. Bruce Holcomb", key="admin_add_name"
        )
        admin_username = st.text_input(
            "Username", placeholder="e.g. bruce", key="admin_add_username"
        )
    with a2:
        admin_password = st.text_input(
            "Password", type="password", key="admin_add_password"
        )
        admin_password2 = st.text_input(
            "Confirm password", type="password", key="admin_add_password2"
        )
    if st.button("Add admin", type="primary", key="admin_add_btn"):
        if admin_password != admin_password2:
            st.error("Passwords do not match.")
        else:
            ok, msg, updated = add_admin_user(
                admins,
                name=admin_name,
                username=admin_username,
                password=admin_password,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    if admins:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": u.get("name", ""),
                        "Username": u.get("username", ""),
                    }
                    for u in admins
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        remove_opts = {
            u["username"]: f"{u.get('name')} ({u.get('username')})" for u in admins
        }
        remove_user = st.selectbox(
            "Remove admin",
            options=list(remove_opts.keys()),
            format_func=lambda u: remove_opts[u],
            key="admin_remove",
        )
        if st.button("Remove selected admin", key="admin_remove_btn"):
            me = str(st.session_state.get("tool_room_admin_username") or "")
            if remove_user == me and len(admins) <= 1:
                st.error("You cannot remove the only admin account.")
            else:
                ok, msg, updated = remove_admin_user(admins, remove_user)
                if ok:
                    if remove_user == me:
                        logout()
                        st.warning("You removed your own account. Sign in again.")
                        st.rerun()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.info("No admin users yet.")

elif page == "Import":
    if not is_admin():
        st.warning("Admin login required.")
        st.stop()
    st.markdown("##### Import / refresh from spreadsheet")
    st.caption(
        "Upload the Chrysler Tool Organization inventory (.xls or .xlsx). "
        "Duplicate tool numbers are merged into one entry. "
        "If a tool already has a location in this system, that location is kept. "
        "Active checkouts are kept when the same tool number still exists after import."
    )
    upload = st.file_uploader(
        "Tool inventory spreadsheet",
        type=["xls", "xlsx"],
        key="inv_upload",
    )
    source = data.get("source") or "seed inventory"
    st.caption(f"Current catalog source: {source} · {len(data.get('tools') or [])} tools")
    if upload is not None and st.button(
        "Import spreadsheet", type="primary", use_container_width=True, key="import_btn"
    ):
        suffix = Path(upload.name).suffix or ".xls"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(upload.getvalue())
            tmp_path = tmp.name
        try:
            tools, summary = parse_tool_inventory_file(tmp_path)
        except Exception as exc:
            st.error(f"Could not read spreadsheet: {exc}")
            tools, summary = [], ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if tools:
            new_data = replace_tools_from_import(
                data, tools, source=upload.name, keep_checkouts=True
            )
            stats = new_data.pop("_import_stats", {}) or {}
            _persist(new_data)
            extras = []
            if int(stats.get("duplicates_removed") or 0):
                extras.append(
                    f"removed {stats['duplicates_removed']} duplicate tool # row(s)"
                )
            if int(stats.get("locations_kept") or 0):
                extras.append(
                    f"kept {stats['locations_kept']} existing location(s) from this system"
                )
            msg = summary
            if extras:
                msg = f"{summary} · " + "; ".join(extras)
            st.success(msg)
            st.rerun()
        elif summary:
            st.error(summary)

elif page == "Reports":
    st.markdown("##### Reports")
    st.caption(
        "Checkout reports for the shop — plus a physical inventory count for Admin / Manager."
    )

    report_options = ["By technician", "All currently out", "Recently returned"]
    if is_admin():
        report_options.append("Inventory count")
    if st.session_state.get("report_mode") not in report_options:
        st.session_state.report_mode = report_options[0]

    report_mode = st.radio(
        "Report",
        report_options,
        horizontal=True,
        key="report_mode",
    )

    def _report_table(rows_raw: list) -> list[dict]:
        return [
            {
                "Technician": r.get("tech_name", ""),
                "Tool #": r.get("tool_no", ""),
                "Description": r.get("description", ""),
                "Signed out": r.get("signed_out", ""),
                "How long out": r.get("duration", ""),
                "Signed in": r.get("signed_in", ""),
                "Qty": r.get("qty", 1),
                "RO #": r.get("ro_number", ""),
                "Note": r.get("note", ""),
            }
            for r in rows_raw
        ]

    def _report_summary(rows_raw: list) -> list[tuple[str, str]]:
        if not rows_raw:
            return [
                ("Tools signed out", "0"),
                ("Longest out", "—"),
                ("Over 5 days", "0"),
            ]
        longest = max(int(r.get("days_out") or 0) for r in rows_raw)
        overdue_n = sum(
            1 for r in rows_raw if int(r.get("days_out") or 0) >= OVERDUE_AFTER_DAYS
        )
        return [
            ("Tools signed out", str(len(rows_raw))),
            ("Longest out", f"{longest} day{'s' if longest != 1 else ''}"),
            ("Over 5 days", str(overdue_n)),
        ]

    def _show_stats(rows_raw: list) -> None:
        summary = dict(_report_summary(rows_raw))
        r1, r2, r3 = st.columns(3)
        with r1:
            st.markdown(
                stat_card("Tools out", summary["Tools signed out"], "orange", "📤"),
                unsafe_allow_html=True,
            )
        with r2:
            longest = summary["Longest out"]
            st.markdown(
                stat_card("Longest out", longest.replace(" days", "d").replace(" day", "d"), "amber", "⏱"),
                unsafe_allow_html=True,
            )
        with r3:
            overdue_n = int(summary["Over 5 days"])
            st.markdown(
                stat_card(
                    "Over 5 days",
                    str(overdue_n),
                    "orange" if overdue_n else "green",
                    "⚠",
                ),
                unsafe_allow_html=True,
            )

    def _pdf_download(
        *,
        title: str,
        subtitle: str,
        rows_raw: list,
        filename: str,
        key: str,
    ) -> None:
        pdf_bytes = build_checkout_report_pdf(
            title=title,
            subtitle=subtitle,
            rows=rows_raw,
            summary=_report_summary(rows_raw),
        )
        st.download_button(
            "Export PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            use_container_width=True,
            key=key,
            type="primary",
        )

    if report_mode == "Inventory count":
        if not is_admin():
            st.warning("Admin or Manager login required for inventory count.")
            st.stop()

        _show_flash()
        st.markdown("##### Physical inventory count")
        st.caption(
            "Walk the tool room location by location. Check **Located**, **Missing**, or "
            "**Found wrong place — returned**. Missing tools go on the Unaccounted list. "
            "Signed-out tools are listed so you do not hunt for something that is not here."
        )

        locs = ["(any location)"] + unique_locations(data)
        if1, if2, if3 = st.columns([2.2, 1.4, 1.4])
        with if1:
            inv_query = st.text_input(
                "Search tool # or description",
                key="inv_query",
                placeholder="e.g. 2113300230 or cable",
            )
        with if2:
            inv_loc = st.selectbox("Location / area", options=locs, key="inv_loc")
        with if3:
            inv_focus = st.selectbox(
                "Show",
                options=["all", "needs_count", "missing", "located", "signed_out"],
                format_func=lambda s: {
                    "all": "All in filter",
                    "needs_count": "Still need count",
                    "missing": "Missing / unaccounted",
                    "located": "Located / returned",
                    "signed_out": "Signed out only",
                }[s],
                key="inv_focus",
            )

        location = "" if inv_loc == "(any location)" else inv_loc
        inv_rows = inventory_count_rows(
            data,
            query=inv_query,
            location=location,
            status="active",
            focus=inv_focus,
        )
        stats = inventory_count_stats(inv_rows)

        s1, s2, s3, s4, s5 = st.columns(5)
        with s1:
            st.markdown(
                stat_card("In filter", str(stats["total"]), "amber", "📋"),
                unsafe_allow_html=True,
            )
        with s2:
            st.markdown(
                stat_card("Need count", str(stats["needs_count"]), "amber", "☐"),
                unsafe_allow_html=True,
            )
        with s3:
            st.markdown(
                stat_card("Located", str(stats["located"]), "green", "✓"),
                unsafe_allow_html=True,
            )
        with s4:
            st.markdown(
                stat_card(
                    "Missing",
                    str(stats["missing"]),
                    "orange" if stats["missing"] else "green",
                    "❓",
                ),
                unsafe_allow_html=True,
            )
        with s5:
            st.markdown(
                stat_card("Signed out", str(stats["signed_out"]), "orange", "📤"),
                unsafe_allow_html=True,
            )

        if not location and not inv_query and inv_focus == "all":
            st.info(
                "Tip: pick a wall/shelf location (or search) so you can count one area at a time."
            )

        page_size = 25
        total = len(inv_rows)
        max_page = max(1, (total + page_size - 1) // page_size) if total else 1
        if "inv_page" not in st.session_state:
            st.session_state.inv_page = 1
        # Reset page when filters change
        filter_sig = f"{inv_query}|{inv_loc}|{inv_focus}"
        if st.session_state.get("_inv_filter_sig") != filter_sig:
            st.session_state._inv_filter_sig = filter_sig
            st.session_state.inv_page = 1
        page_n = int(st.session_state.get("inv_page") or 1)
        page_n = max(1, min(page_n, max_page))
        st.session_state.inv_page = page_n
        start = (page_n - 1) * page_size
        page_rows = inv_rows[start : start + page_size]

        nav1, nav2, nav3 = st.columns([1, 2, 1])
        with nav1:
            if st.button("← Prev", disabled=page_n <= 1, key="inv_prev"):
                st.session_state.inv_page = page_n - 1
                st.rerun()
        with nav2:
            st.caption(
                f"Showing {start + 1}–{min(start + page_size, total)} of {total}"
                if total
                else "No tools match these filters"
            )
        with nav3:
            if st.button("Next →", disabled=page_n >= max_page or not total, key="inv_next"):
                st.session_state.inv_page = page_n + 1
                st.rerun()

        counted_by = current_admin_name() if is_admin() else ""

        for row in page_rows:
            tid = str(row.get("tool_id") or "")
            tool_no = row.get("tool_no") or ""
            desc = row.get("description") or ""
            loc = row.get("location") or "(no location)"
            result = str(row.get("inventory_result") or "")

            if row.get("is_signed_out"):
                st.markdown(
                    f"""
                    <div class="inv-row inv-signed-out">
                        <div class="inv-row-title"><strong>{tool_no}</strong> — {desc}</div>
                        <div class="inv-row-meta">Assigned location: {loc}</div>
                        <div class="inv-row-status">
                            Signed out to <strong>{row.get("signed_out_to") or "—"}</strong>
                            · {row.get("signed_out_at") or ""}
                            — skip looking for this tool
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                continue

            st.markdown(
                f"""
                <div class="inv-row">
                    <div class="inv-row-title"><strong>{tool_no}</strong> — {desc}</div>
                    <div class="inv-row-meta">Look here: <strong>{loc}</strong></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c_loc, c_miss, c_ret, c_clear = st.columns([1.2, 1.2, 1.8, 0.8])
            with c_loc:
                located_on = st.checkbox(
                    "Located",
                    value=result == INVENTORY_RESULT_LOCATED,
                    key=f"inv_located_{tid}",
                )
            with c_miss:
                missing_on = st.checkbox(
                    "Missing",
                    value=result == INVENTORY_RESULT_MISSING,
                    key=f"inv_missing_{tid}",
                )
            with c_ret:
                returned_on = st.checkbox(
                    "Found wrong place — returned to proper place",
                    value=result == INVENTORY_RESULT_RETURNED,
                    key=f"inv_returned_{tid}",
                )
            with c_clear:
                clear_on = st.checkbox(
                    "Clear",
                    value=False,
                    key=f"inv_clear_{tid}",
                    help="Clear this tool's inventory mark",
                )

            desired = None
            if clear_on:
                desired = "clear"
            elif located_on and result != INVENTORY_RESULT_LOCATED:
                desired = INVENTORY_RESULT_LOCATED
            elif missing_on and result != INVENTORY_RESULT_MISSING:
                desired = INVENTORY_RESULT_MISSING
            elif returned_on and result != INVENTORY_RESULT_RETURNED:
                desired = INVENTORY_RESULT_RETURNED
            elif (
                not located_on
                and not missing_on
                and not returned_on
                and result
            ):
                # User unchecked the active box
                desired = "clear"

            # Prefer the newly checked box when multiple flip in one run
            newly = []
            if located_on and result != INVENTORY_RESULT_LOCATED:
                newly.append(INVENTORY_RESULT_LOCATED)
            if missing_on and result != INVENTORY_RESULT_MISSING:
                newly.append(INVENTORY_RESULT_MISSING)
            if returned_on and result != INVENTORY_RESULT_RETURNED:
                newly.append(INVENTORY_RESULT_RETURNED)
            if clear_on:
                newly = ["clear"]
            if len(newly) == 1:
                desired = newly[0]
            elif len(newly) > 1:
                # Last intentional: missing takes priority if conflicting
                if INVENTORY_RESULT_MISSING in newly:
                    desired = INVENTORY_RESULT_MISSING
                elif INVENTORY_RESULT_RETURNED in newly:
                    desired = INVENTORY_RESULT_RETURNED
                else:
                    desired = newly[0]

            if desired == "clear" and result:
                ok, msg = clear_inventory_mark(data, tid)
                if ok:
                    _persist(data)
                    for k in (
                        f"inv_located_{tid}",
                        f"inv_missing_{tid}",
                        f"inv_returned_{tid}",
                        f"inv_clear_{tid}",
                    ):
                        st.session_state.pop(k, None)
                    _set_flash(msg)
                    st.rerun()
                else:
                    st.error(msg)
            elif desired in (
                INVENTORY_RESULT_LOCATED,
                INVENTORY_RESULT_MISSING,
                INVENTORY_RESULT_RETURNED,
            ):
                ok, msg = apply_inventory_mark(
                    data, tid, desired, counted_by=counted_by
                )
                if ok:
                    _persist(data)
                    for k in (
                        f"inv_located_{tid}",
                        f"inv_missing_{tid}",
                        f"inv_returned_{tid}",
                        f"inv_clear_{tid}",
                    ):
                        st.session_state.pop(k, None)
                    if desired == INVENTORY_RESULT_MISSING:
                        _set_flash(
                            f"{msg} It now appears in Catalog → Unaccounted."
                        )
                    else:
                        _set_flash(msg)
                    st.rerun()
                else:
                    st.error(msg)

        pdf_rows = inv_rows
        pdf_bytes = build_inventory_report_pdf(
            title="Physical Inventory Count",
            subtitle=(
                f"Location: {location or 'All'} · Focus: {inv_focus.replace('_', ' ')}"
            ),
            rows=pdf_rows,
            summary=[
                ("In filter", str(stats["total"])),
                ("Need count", str(stats["needs_count"])),
                ("Located / returned", str(stats["located"])),
                ("Missing", str(stats["missing"])),
                ("Signed out", str(stats["signed_out"])),
            ],
        )
        st.download_button(
            "Export inventory PDF",
            data=pdf_bytes,
            file_name="inventory-count.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="pdf_inventory",
            type="primary",
        )

    else:
        rows_raw: list = []
        pdf_title = ""
        pdf_subtitle = ""
        pdf_name = "specialty-tool-report.pdf"

        if report_mode == "By technician":
            listed = _tech_names()
            with_open = technicians_with_open_checkouts(data)
            report_techs = list(listed)
            for name in with_open:
                if name.lower() not in {t.lower() for t in report_techs}:
                    report_techs.append(name)

            if not report_techs:
                st.info("Add technicians under Technicians, or check a tool out first.")
            else:
                default_idx = 0
                if with_open:
                    for i, name in enumerate(report_techs):
                        if name.lower() == with_open[0].lower():
                            default_idx = i
                            break
                tech = st.selectbox(
                    "Technician",
                    options=report_techs,
                    index=default_idx,
                    key="report_tech",
                )
                rows_raw = checkouts_for_technician(data, tech)
                pdf_title = f"Technician Checkout Report — {tech}"
                pdf_subtitle = "Active tools signed out to this technician"
                pdf_name = f"tech-checkout-{tech.lower().replace(' ', '-')}.pdf"

                if not rows_raw:
                    st.markdown(
                        status_banner(f"{tech} has nothing checked out right now.", "success"),
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        "Check a tool out to this technician first — the report will list who has it, "
                        "when it was signed out, and how long it has been out."
                    )
                    _pdf_download(
                        title=pdf_title,
                        subtitle=pdf_subtitle,
                        rows_raw=rows_raw,
                        filename=pdf_name,
                        key="pdf_tech_empty",
                    )
                else:
                    _show_stats(rows_raw)
                    st.dataframe(
                        pd.DataFrame(_report_table(rows_raw)),
                        use_container_width=True,
                        hide_index=True,
                    )
                    _pdf_download(
                        title=pdf_title,
                        subtitle=pdf_subtitle,
                        rows_raw=rows_raw,
                        filename=pdf_name,
                        key="pdf_tech",
                    )
        elif report_mode == "All currently out":
            rows_raw = all_open_checkout_report_rows(data)
            pdf_title = "All Tools Currently Signed Out"
            pdf_subtitle = "Shop-wide specialty tool accountability"
            pdf_name = "all-tools-signed-out.pdf"

            if not rows_raw:
                st.markdown(
                    status_banner("Special tool room is clear — nothing signed out.", "success"),
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Use Check Out / In to sign tools out. Then this report (and the PDF) will show "
                    "each technician, signed-out time, and how long each tool has been out."
                )
                _pdf_download(
                    title=pdf_title,
                    subtitle=pdf_subtitle,
                    rows_raw=rows_raw,
                    filename=pdf_name,
                    key="pdf_all_empty",
                )
            else:
                _show_stats(rows_raw)
                # Sort display by technician first name, then duration
                display = sorted(
                    rows_raw,
                    key=lambda r: (
                        str(r.get("tech_name") or "").split()[0].lower()
                        if str(r.get("tech_name") or "").split()
                        else "",
                        -int(r.get("days_out") or 0),
                    ),
                )
                st.dataframe(
                    pd.DataFrame(_report_table(display)),
                    use_container_width=True,
                    hide_index=True,
                )
                _pdf_download(
                    title=pdf_title,
                    subtitle=pdf_subtitle,
                    rows_raw=display,
                    filename=pdf_name,
                    key="pdf_all",
                )

        elif report_mode == "Recently returned":
            rows_raw = returned_tool_report_rows(data)
            pdf_title = "Recently Returned Specialty Tools"
            pdf_subtitle = "Completed check-outs with time held by technician"
            pdf_name = "recently-returned-tools.pdf"

            if not rows_raw:
                st.info("No returned tools in history yet.")
                _pdf_download(
                    title=pdf_title,
                    subtitle=pdf_subtitle,
                    rows_raw=rows_raw,
                    filename=pdf_name,
                    key="pdf_returned_empty",
                )
            else:
                _show_stats(rows_raw)
                st.dataframe(
                    pd.DataFrame(_report_table(rows_raw)),
                    use_container_width=True,
                    hide_index=True,
                )
                _pdf_download(
                    title=pdf_title,
                    subtitle=pdf_subtitle,
                    rows_raw=rows_raw,
                    filename=pdf_name,
                    key="pdf_returned",
                )

elif page == "History":
    history = list(data.get("history") or [])[:80]
    if not history:
        st.info("No activity yet.")
    else:
        rows = [
            {
                "When": _fmt_when(h.get("at", "")),
                "Action": h.get("action", ""),
                "Tool #": h.get("tool_no", ""),
                "Description": h.get("description", ""),
                "Tech": h.get("tech_name", ""),
                "Qty": h.get("qty", ""),
                "Note": h.get("note", ""),
            }
            for h in history
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
