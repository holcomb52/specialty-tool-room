"""Specialty Tool Room — check-out / check-in accountability for SST inventory."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from components.ui import page_hero, stat_card, status_banner
from lib.app_auth import require_login
from lib.specialty_tools_import import parse_tool_inventory_file
from lib.specialty_tools_storage import (
    add_tool,
    checkin_checkout,
    checkout_tool,
    inventory_stats,
    load_inventory,
    replace_tools_from_import,
    save_inventory,
    search_tools,
    unique_locations,
    update_tool,
)
from lib.supabase_client import is_configured
from lib.tech_list import add_technician, load_technicians, remove_technician
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


def _tech_names() -> list[str]:
    if "tech_names" not in st.session_state:
        st.session_state.tech_names = load_technicians()
    return st.session_state.tech_names


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
    page = st.radio(
        "Navigate",
        [
            "Check Out / In",
            "Out Now",
            "Catalog",
            "Add Tool",
            "Technicians",
            "Import",
            "History",
        ],
        label_visibility="collapsed",
    )
    st.markdown("---")
    db_status = "ONLINE" if is_configured() else "LOCAL"
    st.markdown(
        f"""
        <div class="sidebar-footer">
            <div>Database <strong>{db_status}</strong></div>
            <div style="margin-top:0.35rem">NSB Chrysler · SST</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
c1, c2, c3, c4 = st.columns(4)
for col, (label, value, accent, icon) in zip(
    [c1, c2, c3, c4],
    [
        ("Tools on file", str(stats["active"]), "amber", "🔧"),
        ("Checked out now", str(stats["out_now"]), "orange", "📤"),
        ("Units out", str(stats["units_out"]), "stone", "◈"),
        ("With location", str(stats["with_location"]), "green", "📍"),
    ],
):
    with col:
        st.markdown(stat_card(label, value, accent, icon), unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

if page == "Check Out / In":
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
                ro = st.text_input("RO # (optional)", key="co_ro")
            with b2:
                note = st.text_input("Note (optional)", key="co_note")
            if st.button("Check out", type="primary", use_container_width=True, key="co_btn"):
                ok, msg = checkout_tool(
                    data, pick, tech, qty=int(qty), note=note, ro_number=ro
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
    if not checkouts:
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
                "RO #": c.get("ro_number", ""),
                "Out since": _fmt_when(c.get("checked_out_at", "")),
                "Note": c.get("note", ""),
            }
            for c in sorted(checkouts, key=lambda x: x.get("checked_out_at") or "", reverse=True)
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

elif page == "Catalog":
    locs = ["(any location)"] + unique_locations(data)
    f1, f2, f3, f4 = st.columns([2.2, 1.2, 1.2, 1])
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
            format_func=lambda s: {"active": "Active", "non_current": "Non-current", "all": "All"}[s],
            key="cat_status",
        )
    with f3:
        loc_pick = st.selectbox("Location", options=locs, key="cat_loc")
    with f4:
        only_out = st.checkbox("Out only", key="cat_out")

    location = "" if loc_pick == "(any location)" else loc_pick
    matches = search_tools(data, query, status=status, location=location, only_out=only_out)
    st.caption(f"{len(matches)} tool(s)")

    if matches:
        rows = []
        for t in matches[:400]:
            avail = t.get("qty_available", 0)
            out = t.get("qty_out", 0)
            status_label = "OUT" if out and avail == 0 else ("PARTIAL" if out else "IN")
            rows.append(
                {
                    "Tool #": t.get("tool_no", ""),
                    "Description": t.get("description", ""),
                    "Location": t.get("location", ""),
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
                    value=tool.get("location", ""),
                    key="edit_loc",
                )
                new_qty = st.number_input(
                    "Quantity on hand",
                    min_value=1,
                    value=max(1, int(tool.get("quantity") or 1)),
                    key="edit_qty",
                )
            with e2:
                new_desc = st.text_input(
                    "Description", value=tool.get("description", ""), key="edit_desc"
                )
                new_notes = st.text_input("Notes", value=tool.get("notes", ""), key="edit_notes")
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
                )
                if ok:
                    _persist(data)
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.info("No tools match those filters.")

elif page == "Add Tool":
    st.markdown("##### Add a new specialty tool")
    a1, a2 = st.columns(2)
    with a1:
        tool_no = st.text_input("Tool number", key="add_no", placeholder="e.g. 2081700090")
        qty = st.number_input("Quantity", min_value=1, value=1, key="add_qty")
        location = st.text_input(
            "Special location / assignment",
            key="add_loc",
            placeholder="e.g. SHELF D / WALL 14",
        )
    with a2:
        description = st.text_input(
            "Description", key="add_desc", placeholder="STRETCH BELT TOOL"
        )
        notes = st.text_input("Notes", key="add_notes", placeholder="NEW TOOL")
        status = st.selectbox(
            "Status",
            options=["active", "non_current"],
            format_func=lambda s: "Active" if s == "active" else "Non-current",
            key="add_status",
        )
    if st.button("Add tool to inventory", type="primary", use_container_width=True, key="add_btn"):
        ok, msg, _tool = add_tool(
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
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

elif page == "Technicians":
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

elif page == "Import":
    st.markdown("##### Import / refresh from spreadsheet")
    st.caption(
        "Upload the Chrysler Tool Organization inventory (.xls or .xlsx). "
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
            _persist(new_data)
            st.success(summary)
            st.rerun()
        elif summary:
            st.error(summary)

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
