"""Specialty tool room inventory + check-out / check-in persistence."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from lib.specialty_tools_import import empty_inventory

STORE_KEY = "specialty_tools"
TABLE = "specialty_tools_store"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LIVE_PATH = DATA_DIR / "specialty_tools.json"
SEED_PATH = DATA_DIR / "specialty_tools_seed.json"

HISTORY_LIMIT = 500
OVERDUE_AFTER_DAYS = 5

ACCOUNTABILITY_LOCATED = "located"
ACCOUNTABILITY_SIGNED_OUT = "signed_out"
ACCOUNTABILITY_UNACCOUNTED = "unaccounted"
ACCOUNTABILITY_OPTIONS = (
    ACCOUNTABILITY_LOCATED,
    ACCOUNTABILITY_SIGNED_OUT,
    ACCOUNTABILITY_UNACCOUNTED,
)
ACCOUNTABILITY_LABELS = {
    ACCOUNTABILITY_LOCATED: "Located",
    ACCOUNTABILITY_SIGNED_OUT: "Signed out",
    ACCOUNTABILITY_UNACCOUNTED: "Unaccounted for",
}


def normalize_accountability(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"signedout", "checked_out", "checkedout", "out"}:
        return ACCOUNTABILITY_SIGNED_OUT
    if raw in {"missing", "lost", "unaccounted_for", "unaccounted"}:
        return ACCOUNTABILITY_UNACCOUNTED
    if raw in {"found", "located", "ok"}:
        return ACCOUNTABILITY_LOCATED
    if raw in ACCOUNTABILITY_OPTIONS:
        return raw
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(iso: str) -> Optional[datetime]:
    raw = str(iso or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _today_local() -> date:
    return datetime.now(timezone.utc).astimezone().date()


def days_checked_out(checkout: Dict[str, Any]) -> int:
    at = _parse_iso(str(checkout.get("checked_out_at") or ""))
    if not at:
        return 0
    now = datetime.now(timezone.utc)
    return max(0, (now - at).days)


def format_duration(start_iso: str, end_iso: str = "") -> str:
    """Human duration between two ISO timestamps (end defaults to now)."""
    start = _parse_iso(str(start_iso or ""))
    if not start:
        return "—"
    end = _parse_iso(str(end_iso or "")) if end_iso else datetime.now(timezone.utc)
    if end is None:
        end = datetime.now(timezone.utc)
    if end < start:
        return "—"
    delta = end - start
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    if days:
        if hours:
            return f"{days} day{'s' if days != 1 else ''}, {hours}h"
        return f"{days} day{'s' if days != 1 else ''}"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return "< 1m"


def format_report_when(iso: str) -> str:
    dt = _parse_iso(str(iso or ""))
    if not dt:
        return "—"
    return dt.astimezone().strftime("%m/%d/%Y %I:%M %p")


def checkout_report_rows(
    checkouts: List[Dict[str, Any]],
    *,
    still_out_label: str = "Still out",
) -> List[Dict[str, Any]]:
    """Normalize active checkouts into report table rows."""
    rows: List[Dict[str, Any]] = []
    for checkout in checkouts:
        start = str(checkout.get("checked_out_at") or "")
        rows.append(
            {
                "tool_no": checkout.get("tool_no", ""),
                "description": checkout.get("description", ""),
                "tech_name": checkout.get("tech_name", ""),
                "qty": checkout.get("qty", 1),
                "signed_out": format_report_when(start),
                "signed_in": still_out_label,
                "duration": format_duration(start),
                "days_out": days_checked_out(checkout),
                "ro_number": checkout.get("ro_number", ""),
                "note": checkout.get("note", ""),
                "checked_out_at": start,
            }
        )
    rows.sort(
        key=lambda r: (int(r.get("days_out") or 0), str(r.get("checked_out_at") or "")),
        reverse=True,
    )
    return rows


def all_open_checkout_report_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return checkout_report_rows(list(data.get("active_checkouts") or []))


def returned_tool_report_rows(
    data: Dict[str, Any], *, limit: int = 150
) -> List[Dict[str, Any]]:
    """Completed check-ins with signed-out / signed-in times and duration held."""
    rows: List[Dict[str, Any]] = []
    for entry in data.get("history") or []:
        if entry.get("action") != "checkin":
            continue
        start = str(entry.get("checked_out_at") or "")
        end = str(entry.get("at") or "")
        days = 0
        start_dt = _parse_iso(start)
        end_dt = _parse_iso(end)
        if start_dt and end_dt and end_dt >= start_dt:
            days = (end_dt - start_dt).days
        rows.append(
            {
                "tool_no": entry.get("tool_no", ""),
                "description": entry.get("description", ""),
                "tech_name": entry.get("tech_name", ""),
                "qty": entry.get("qty", 1),
                "signed_out": format_report_when(start) if start else "—",
                "signed_in": format_report_when(end) if end else "—",
                "duration": format_duration(start, end) if start and end else "—",
                "days_out": days,
                "ro_number": entry.get("ro_number", ""),
                "note": entry.get("note", ""),
                "checked_out_at": start,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def checkouts_for_technician(
    data: Dict[str, Any], tech_name: str
) -> List[Dict[str, Any]]:
    """Active checkouts for one technician, longest out first."""
    needle = str(tech_name or "").strip().lower()
    if not needle:
        return []
    matched = [
        c
        for c in data.get("active_checkouts") or []
        if str(c.get("tech_name") or "").strip().lower() == needle
    ]
    return checkout_report_rows(matched)


def technicians_with_open_checkouts(data: Dict[str, Any]) -> List[str]:
    names = {
        str(c.get("tech_name") or "").strip()
        for c in data.get("active_checkouts") or []
        if str(c.get("tech_name") or "").strip()
    }
    return sorted(names, key=lambda n: (n.split()[0].lower() if n.split() else n.lower(), n.lower()))


def is_overdue_alert_dismissed(
    checkout: Dict[str, Any], *, today: Optional[date] = None
) -> bool:
    """True when alert is snoozed until a future date (returns on that date)."""
    until_raw = checkout.get("alert_dismissed_until")
    if not until_raw:
        return False
    try:
        until = date.fromisoformat(str(until_raw)[:10])
    except ValueError:
        return False
    current = today or _today_local()
    return current < until


def list_overdue_checkouts(
    data: Dict[str, Any],
    *,
    days: int = OVERDUE_AFTER_DAYS,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Active checkouts out for `days` or more that are not snoozed."""
    overdue: List[Dict[str, Any]] = []
    for checkout in data.get("active_checkouts") or []:
        out_days = days_checked_out(checkout)
        if out_days < days:
            continue
        if is_overdue_alert_dismissed(checkout, today=today):
            continue
        item = dict(checkout)
        item["days_out"] = out_days
        overdue.append(item)
    overdue.sort(key=lambda c: int(c.get("days_out") or 0), reverse=True)
    return overdue


def dismiss_overdue_alert(
    data: Dict[str, Any],
    checkout_id: str,
    until: Union[date, str],
    *,
    today: Optional[date] = None,
) -> Tuple[bool, str]:
    """Hide the overdue alert for a checkout until the given date."""
    if isinstance(until, str):
        try:
            until_date = date.fromisoformat(str(until)[:10])
        except ValueError:
            return False, "Pick a valid date."
    else:
        until_date = until

    current = today or _today_local()
    if until_date <= current:
        return False, "Pick a future date to dismiss the alert until."

    for checkout in data.get("active_checkouts") or []:
        if checkout.get("id") == checkout_id:
            checkout["alert_dismissed_until"] = until_date.isoformat()
            tool_no = checkout.get("tool_no") or "tool"
            return True, f"Alert for {tool_no} hidden until {until_date.strftime('%m/%d/%Y')}."
    return False, "Checkout not found."


def _normalize(data: Dict[str, Any] | None) -> Dict[str, Any]:
    base = empty_inventory()
    if not isinstance(data, dict):
        return base
    tools = data.get("tools")
    checkouts = data.get("active_checkouts")
    history = data.get("history")
    base["source"] = str(data.get("source") or "")
    base["version"] = int(data.get("version") or 1)
    base["tools"] = list(tools) if isinstance(tools, list) else []
    base["active_checkouts"] = list(checkouts) if isinstance(checkouts, list) else []
    base["history"] = list(history) if isinstance(history, list) else []
    return base


def _load_local() -> Optional[Dict[str, Any]]:
    if not LIVE_PATH.exists():
        return None
    try:
        return _normalize(json.loads(LIVE_PATH.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def _load_seed() -> Dict[str, Any]:
    if SEED_PATH.exists():
        try:
            return _normalize(json.loads(SEED_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return empty_inventory("empty")


def _save_local(data: Dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LIVE_PATH.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def _load_remote() -> Optional[Dict[str, Any]]:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return None
    try:
        result = (
            client.table(TABLE)
            .select("data")
            .eq("store_key", STORE_KEY)
            .limit(1)
            .execute()
        )
        if result.data:
            payload = result.data[0].get("data")
            if isinstance(payload, dict):
                return _normalize(payload)
    except Exception:
        return None
    return None


def _save_remote(data: Dict[str, Any]) -> Tuple[bool, str]:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return True, ""

    row = {
        "store_key": STORE_KEY,
        "data": data,
        "updated_at": _now_iso(),
    }
    try:
        existing = (
            client.table(TABLE)
            .select("store_key")
            .eq("store_key", STORE_KEY)
            .execute()
        )
        if existing.data:
            client.table(TABLE).update(
                {"data": data, "updated_at": row["updated_at"]}
            ).eq("store_key", STORE_KEY).execute()
        else:
            client.table(TABLE).insert(row).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def load_inventory() -> Dict[str, Any]:
    remote = _load_remote()
    if remote is not None and remote.get("tools"):
        return remote
    local = _load_local()
    if local is not None and local.get("tools"):
        return local
    seed = _load_seed()
    if seed.get("tools"):
        save_inventory(seed)
    return seed


def save_inventory(data: Dict[str, Any]) -> Tuple[bool, str]:
    normalized = _normalize(data)
    _save_local(normalized)
    ok, err = _save_remote(normalized)
    if not ok:
        # Keep local store; cloud sync can be fixed later
        return True, err or ""
    return True, ""


def _append_history(data: Dict[str, Any], entry: Dict[str, Any]) -> None:
    history = list(data.get("history") or [])
    history.insert(0, entry)
    data["history"] = history[:HISTORY_LIMIT]


def find_tool(data: Dict[str, Any], tool_id: str) -> Optional[Dict[str, Any]]:
    for tool in data.get("tools") or []:
        if tool.get("id") == tool_id:
            return tool
    return None


def find_tool_by_number(data: Dict[str, Any], tool_no: str) -> Optional[Dict[str, Any]]:
    needle = str(tool_no or "").strip().lower()
    if not needle:
        return None
    for tool in data.get("tools") or []:
        if str(tool.get("tool_no") or "").strip().lower() == needle:
            return tool
    return None


def qty_out(data: Dict[str, Any], tool_id: str) -> int:
    return sum(
        int(c.get("qty") or 1)
        for c in data.get("active_checkouts") or []
        if c.get("tool_id") == tool_id
    )


def qty_available(data: Dict[str, Any], tool: Dict[str, Any]) -> int:
    total = max(1, int(tool.get("quantity") or 1))
    return max(0, total - qty_out(data, tool["id"]))


def checkout_tool(
    data: Dict[str, Any],
    tool_id: str,
    tech_name: str,
    *,
    qty: int = 1,
    note: str = "",
    ro_number: str = "",
) -> Tuple[bool, str]:
    tool = find_tool(data, tool_id)
    if not tool:
        return False, "Tool not found."
    tech = str(tech_name or "").strip()
    if not tech:
        return False, "Select a technician."
    clean_ro = str(ro_number or "").strip()
    if not clean_ro:
        return False, "Enter an RO number."
    take = max(1, int(qty or 1))
    available = qty_available(data, tool)
    if take > available:
        return False, f"Only {available} available (qty on hand {tool.get('quantity', 1)})."

    checkout = {
        "id": str(uuid.uuid4()),
        "tool_id": tool_id,
        "tool_no": tool.get("tool_no", ""),
        "description": tool.get("description", ""),
        "tech_name": tech,
        "qty": take,
        "checked_out_at": _now_iso(),
        "note": str(note or "").strip(),
        "ro_number": clean_ro,
    }
    data.setdefault("active_checkouts", []).append(checkout)
    _append_history(
        data,
        {
            "id": str(uuid.uuid4()),
            "action": "checkout",
            "tool_id": tool_id,
            "tool_no": tool.get("tool_no", ""),
            "description": tool.get("description", ""),
            "tech_name": tech,
            "qty": take,
            "note": checkout["note"],
            "ro_number": checkout["ro_number"],
            "at": checkout["checked_out_at"],
        },
    )
    return True, f"Checked out {tool.get('tool_no')} to {tech}."


def checkin_checkout(data: Dict[str, Any], checkout_id: str, note: str = "") -> Tuple[bool, str]:
    checkouts = list(data.get("active_checkouts") or [])
    match = None
    remaining = []
    for item in checkouts:
        if item.get("id") == checkout_id and match is None:
            match = item
        else:
            remaining.append(item)
    if not match:
        return False, "Checkout not found."
    data["active_checkouts"] = remaining
    checked_in_at = _now_iso()
    _append_history(
        data,
        {
            "id": str(uuid.uuid4()),
            "action": "checkin",
            "tool_id": match.get("tool_id", ""),
            "tool_no": match.get("tool_no", ""),
            "description": match.get("description", ""),
            "tech_name": match.get("tech_name", ""),
            "qty": match.get("qty", 1),
            "note": str(note or "").strip() or match.get("note", ""),
            "ro_number": match.get("ro_number", ""),
            "at": checked_in_at,
            "checked_out_at": match.get("checked_out_at", ""),
            "checkout_id": checkout_id,
        },
    )
    return True, f"Checked in {match.get('tool_no')} from {match.get('tech_name')}."


def update_checkout(
    data: Dict[str, Any],
    checkout_id: str,
    *,
    tech_name: Optional[str] = None,
    ro_number: Optional[str] = None,
    note: Optional[str] = None,
) -> Tuple[bool, str]:
    """Correct fields on an open checkout (e.g. wrong technician selected)."""
    checkouts = list(data.get("active_checkouts") or [])
    match = None
    for item in checkouts:
        if item.get("id") == checkout_id:
            match = item
            break
    if not match:
        return False, "Checkout not found."

    changes: List[str] = []
    if tech_name is not None:
        clean_tech = str(tech_name or "").strip()
        if not clean_tech:
            return False, "Select a technician."
        old_tech = str(match.get("tech_name") or "")
        if clean_tech != old_tech:
            match["tech_name"] = clean_tech
            changes.append(f"tech {old_tech or '(blank)'} → {clean_tech}")
    if ro_number is not None:
        clean_ro = str(ro_number or "").strip()
        if not clean_ro:
            return False, "Enter an RO number."
        old_ro = str(match.get("ro_number") or "")
        if clean_ro != old_ro:
            match["ro_number"] = clean_ro
            changes.append(f"RO {old_ro or '(blank)'} → {clean_ro}")
    if note is not None:
        clean_note = str(note or "").strip()
        old_note = str(match.get("note") or "")
        if clean_note != old_note:
            match["note"] = clean_note
            changes.append("note updated")

    if not changes:
        return False, "No changes to save."

    _append_history(
        data,
        {
            "id": str(uuid.uuid4()),
            "action": "checkout_corrected",
            "tool_id": match.get("tool_id", ""),
            "tool_no": match.get("tool_no", ""),
            "description": match.get("description", ""),
            "tech_name": match.get("tech_name", ""),
            "qty": match.get("qty", 1),
            "note": "; ".join(changes),
            "ro_number": match.get("ro_number", ""),
            "at": _now_iso(),
            "checkout_id": checkout_id,
        },
    )
    return True, f"Updated {match.get('tool_no')}: {'; '.join(changes)}."


def add_tool(
    data: Dict[str, Any],
    *,
    tool_no: str,
    description: str,
    quantity: int = 1,
    location: str = "",
    notes: str = "",
    status: str = "active",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    clean_no = str(tool_no or "").strip().upper()
    clean_desc = str(description or "").strip().upper()
    if not clean_no:
        return False, "Tool number is required.", None
    if not clean_desc:
        return False, "Description is required.", None
    existing = find_tool_by_number(data, clean_no)
    if existing and existing.get("status") != "non_current":
        return False, f"Tool {clean_no} already exists in inventory.", None

    tool = {
        "id": str(uuid.uuid4()),
        "tool_no": clean_no,
        "description": clean_desc,
        "quantity": max(1, int(quantity or 1)),
        "location": str(location or "").strip().upper(),
        "notes": str(notes or "").strip().upper(),
        "sort_order": clean_no,
        "status": status if status in ("active", "non_current") else "active",
        "brand_flags": {
            "chrysler": "",
            "jeep": "",
            "ram": "",
            "dodge": "",
        },
    }
    data.setdefault("tools", []).append(tool)
    _append_history(
        data,
        {
            "id": str(uuid.uuid4()),
            "action": "added",
            "tool_id": tool["id"],
            "tool_no": clean_no,
            "description": clean_desc,
            "tech_name": "",
            "qty": tool["quantity"],
            "note": f"Location: {tool['location']}" if tool["location"] else "Added to inventory",
            "ro_number": "",
            "at": _now_iso(),
        },
    )
    return True, f"Added {clean_no}.", tool


def update_tool(
    data: Dict[str, Any],
    tool_id: str,
    *,
    description: Optional[str] = None,
    quantity: Optional[int] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    status: Optional[str] = None,
    accountability: Optional[str] = None,
) -> Tuple[bool, str]:
    tool = find_tool(data, tool_id)
    if not tool:
        return False, "Tool not found."
    if description is not None:
        tool["description"] = str(description).strip().upper()
    if quantity is not None:
        tool["quantity"] = max(1, int(quantity))
    if location is not None:
        tool["location"] = str(location).strip().upper()
    if notes is not None:
        tool["notes"] = str(notes).strip().upper()
    if status is not None and status in ("active", "non_current"):
        tool["status"] = status
    if accountability is not None:
        tool["accountability"] = normalize_accountability(accountability)
    acct = normalize_accountability(tool.get("accountability"))
    loc = tool.get("location") or "(none)"
    note = f"Location set to {loc}"
    if acct:
        note += f" · {ACCOUNTABILITY_LABELS.get(acct, acct)}"
    _append_history(
        data,
        {
            "id": str(uuid.uuid4()),
            "action": "updated",
            "tool_id": tool_id,
            "tool_no": tool.get("tool_no", ""),
            "description": tool.get("description", ""),
            "tech_name": "",
            "qty": tool.get("quantity", 1),
            "note": note,
            "ro_number": "",
            "at": _now_iso(),
        },
    )
    return True, f"Updated {tool.get('tool_no')}."


def _tool_no_key(tool: Dict[str, Any] | None) -> str:
    if not isinstance(tool, dict):
        return ""
    return str(tool.get("tool_no") or "").strip().lower()


def _dedupe_imported_tools(
    imported_tools: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """One row per tool #. Prefer active over non-current; fill empty location from later rows."""
    by_no: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    for raw in imported_tools or []:
        if not isinstance(raw, dict):
            continue
        key = _tool_no_key(raw)
        if not key:
            continue
        tool = copy.deepcopy(raw)
        if key not in by_no:
            by_no[key] = tool
            continue
        duplicates += 1
        current = by_no[key]
        incoming_active = tool.get("status") == "active"
        current_non = current.get("status") == "non_current"
        if incoming_active and current_non:
            kept_loc = str(current.get("location") or "").strip() or str(
                tool.get("location") or ""
            ).strip()
            by_no[key] = tool
            if kept_loc:
                by_no[key]["location"] = kept_loc
        elif not str(current.get("location") or "").strip() and str(
            tool.get("location") or ""
        ).strip():
            current["location"] = str(tool.get("location")).strip()
    return list(by_no.values()), duplicates


def replace_tools_from_import(
    data: Dict[str, Any],
    imported_tools: List[Dict[str, Any]],
    *,
    source: str,
    keep_checkouts: bool = True,
) -> Dict[str, Any]:
    """
    Refresh catalog from an imported spreadsheet.

    Rules:
    - Duplicate tool numbers collapse to a single entry.
    - If this system already has a location for a tool #, that location wins.
    """
    existing_by_no = {
        key: tool
        for tool in data.get("tools") or []
        if (key := _tool_no_key(tool))
    }
    deduped, duplicate_count = _dedupe_imported_tools(imported_tools)

    location_kept = 0
    merged_tools: List[Dict[str, Any]] = []
    for tool in deduped:
        item = copy.deepcopy(tool)
        key = _tool_no_key(item)
        prev = existing_by_no.get(key)
        if prev:
            # Keep stable id so open checkouts / history stay linked
            if prev.get("id"):
                item["id"] = prev["id"]
            prev_loc = str(prev.get("location") or "").strip()
            if prev_loc:
                item["location"] = prev_loc
                location_kept += 1
            prev_acct = normalize_accountability(prev.get("accountability"))
            if prev_acct:
                item["accountability"] = prev_acct
        merged_tools.append(item)

    new_data = empty_inventory(source)
    new_data["tools"] = merged_tools
    new_data["history"] = list(data.get("history") or [])

    if keep_checkouts:
        by_no = {
            key: tool
            for tool in new_data["tools"]
            if (key := _tool_no_key(tool))
        }
        preserved = []
        for checkout in data.get("active_checkouts") or []:
            key = str(checkout.get("tool_no") or "").strip().lower()
            tool = by_no.get(key)
            if not tool:
                continue
            item = dict(checkout)
            item["tool_id"] = tool["id"]
            item["description"] = tool.get("description", item.get("description", ""))
            preserved.append(item)
        new_data["active_checkouts"] = preserved

    note_bits = [f"Imported {len(merged_tools)} tools from {source}"]
    if duplicate_count:
        note_bits.append(f"removed {duplicate_count} duplicate tool # row(s)")
    if location_kept:
        note_bits.append(f"kept {location_kept} existing location(s)")
    _append_history(
        new_data,
        {
            "id": str(uuid.uuid4()),
            "action": "import",
            "tool_id": "",
            "tool_no": "",
            "description": "",
            "tech_name": "",
            "qty": len(merged_tools),
            "note": "; ".join(note_bits),
            "ro_number": "",
            "at": _now_iso(),
            "duplicates_removed": duplicate_count,
            "locations_kept": location_kept,
        },
    )
    # Stash merge stats for the UI success message
    new_data["_import_stats"] = {
        "tools": len(merged_tools),
        "duplicates_removed": duplicate_count,
        "locations_kept": location_kept,
    }
    return new_data


def inventory_stats(data: Dict[str, Any]) -> Dict[str, int]:
    tools = data.get("tools") or []
    checkouts = data.get("active_checkouts") or []
    without_location = 0
    unaccounted = 0
    for t in tools:
        acct = normalize_accountability(t.get("accountability"))
        if acct == ACCOUNTABILITY_UNACCOUNTED:
            unaccounted += 1
            continue
        if not str(t.get("location") or "").strip():
            without_location += 1
    return {
        "total": len(tools),
        "active": sum(1 for t in tools if t.get("status") == "active"),
        "non_current": sum(1 for t in tools if t.get("status") == "non_current"),
        "out_now": len(checkouts),
        "units_out": sum(int(c.get("qty") or 1) for c in checkouts),
        "with_location": sum(
            1
            for t in tools
            if str(t.get("location") or "").strip()
            and normalize_accountability(t.get("accountability"))
            != ACCOUNTABILITY_UNACCOUNTED
        ),
        "without_location": without_location,
        "unaccounted": unaccounted,
        "overdue": len(list_overdue_checkouts(data)),
    }


def search_tools(
    data: Dict[str, Any],
    query: str = "",
    *,
    status: str = "active",
    location: str = "",
    only_out: bool = False,
    only_with_location: bool = False,
    only_without_location: bool = False,
    only_unaccounted: bool = False,
) -> List[Dict[str, Any]]:
    q = str(query or "").strip().lower()
    loc_filter = str(location or "").strip().lower()
    out_ids = {c.get("tool_id") for c in data.get("active_checkouts") or []}
    results = []
    for tool in data.get("tools") or []:
        if status != "all" and tool.get("status") != status:
            continue
        if only_out and tool.get("id") not in out_ids:
            continue
        acct = normalize_accountability(tool.get("accountability"))
        tool_loc = str(tool.get("location") or "").strip()
        if only_unaccounted:
            if acct != ACCOUNTABILITY_UNACCOUNTED:
                continue
        else:
            if only_with_location and (not tool_loc or acct == ACCOUNTABILITY_UNACCOUNTED):
                continue
            if only_without_location and (
                tool_loc or acct == ACCOUNTABILITY_UNACCOUNTED
            ):
                continue
        if loc_filter and loc_filter not in tool_loc.lower():
            continue
        if q:
            hay = " ".join(
                [
                    str(tool.get("tool_no") or ""),
                    str(tool.get("description") or ""),
                    str(tool.get("location") or ""),
                    str(tool.get("notes") or ""),
                    acct,
                ]
            ).lower()
            if q not in hay:
                continue
        enriched = dict(tool)
        enriched["qty_out"] = qty_out(data, tool["id"])
        enriched["qty_available"] = qty_available(data, tool)
        enriched["accountability"] = acct
        results.append(enriched)
    results.sort(key=lambda t: str(t.get("sort_order") or t.get("tool_no") or ""))
    return results


def unique_locations(data: Dict[str, Any]) -> List[str]:
    return sorted(
        {
            str(t.get("location") or "").strip()
            for t in data.get("tools") or []
            if str(t.get("location") or "").strip()
        },
        key=str.lower,
    )


INVENTORY_RESULT_LOCATED = "located"
INVENTORY_RESULT_MISSING = "missing"
INVENTORY_RESULT_RETURNED = "returned"
INVENTORY_RESULTS = (
    INVENTORY_RESULT_LOCATED,
    INVENTORY_RESULT_MISSING,
    INVENTORY_RESULT_RETURNED,
)
INVENTORY_RESULT_LABELS = {
    INVENTORY_RESULT_LOCATED: "Located",
    INVENTORY_RESULT_MISSING: "Missing",
    INVENTORY_RESULT_RETURNED: "Found wrong place — returned",
}


def _open_checkouts_for_tool(
    data: Dict[str, Any], tool_id: str
) -> List[Dict[str, Any]]:
    tid = str(tool_id or "")
    return [
        c
        for c in data.get("active_checkouts") or []
        if str(c.get("tool_id") or "") == tid
    ]


def inventory_result_for_tool(tool: Dict[str, Any]) -> str:
    raw = str(tool.get("inventory_result") or "").strip().lower()
    if raw in INVENTORY_RESULTS:
        return raw
    acct = normalize_accountability(tool.get("accountability"))
    if acct == ACCOUNTABILITY_UNACCOUNTED:
        return INVENTORY_RESULT_MISSING
    return ""


def apply_inventory_mark(
    data: Dict[str, Any],
    tool_id: str,
    result: str,
    *,
    counted_by: str = "",
) -> Tuple[bool, str]:
    """
    Record a physical inventory count for one tool.

    - located: found at assigned location
    - missing: not found → Unaccounted (shows in Unaccounted box)
    - returned: found in wrong place, put back → Located
    """
    tool = find_tool(data, tool_id)
    if not tool:
        return False, "Tool not found."
    clean = str(result or "").strip().lower()
    if clean not in INVENTORY_RESULTS:
        return False, "Choose Located, Missing, or Returned to proper place."

    if qty_out(data, tool_id) > 0:
        return (
            False,
            "This tool is signed out — skip the physical search (shown as Signed out).",
        )

    if clean == INVENTORY_RESULT_MISSING:
        tool["accountability"] = ACCOUNTABILITY_UNACCOUNTED
        note = "Inventory: marked missing — moved to Unaccounted"
    elif clean == INVENTORY_RESULT_RETURNED:
        tool["accountability"] = ACCOUNTABILITY_LOCATED
        note = "Inventory: found in wrong place, returned to proper location"
    else:
        tool["accountability"] = ACCOUNTABILITY_LOCATED
        note = "Inventory: located at assigned location"

    who = str(counted_by or "").strip()
    if who:
        note = f"{note} (by {who})"

    tool["inventory_result"] = clean
    tool["inventory_checked_at"] = _now_iso()
    if who:
        tool["inventory_counted_by"] = who

    _append_history(
        data,
        {
            "id": str(uuid.uuid4()),
            "action": "inventory",
            "tool_id": tool_id,
            "tool_no": tool.get("tool_no", ""),
            "description": tool.get("description", ""),
            "tech_name": who,
            "qty": tool.get("quantity", 1),
            "note": note,
            "ro_number": "",
            "at": tool["inventory_checked_at"],
        },
    )
    label = INVENTORY_RESULT_LABELS.get(clean, clean)
    return True, f"{tool.get('tool_no')}: {label}."


def clear_inventory_mark(data: Dict[str, Any], tool_id: str) -> Tuple[bool, str]:
    """Clear inventory checkboxes / result for a tool (does not wipe location)."""
    tool = find_tool(data, tool_id)
    if not tool:
        return False, "Tool not found."
    tool.pop("inventory_result", None)
    tool.pop("inventory_checked_at", None)
    tool.pop("inventory_counted_by", None)
    # If it was missing via inventory, clear unaccounted so it leaves that list
    if normalize_accountability(tool.get("accountability")) == ACCOUNTABILITY_UNACCOUNTED:
        tool["accountability"] = ""
    return True, f"Cleared inventory mark on {tool.get('tool_no')}."


def inventory_count_rows(
    data: Dict[str, Any],
    *,
    query: str = "",
    location: str = "",
    status: str = "active",
    focus: str = "all",
) -> List[Dict[str, Any]]:
    """
    Rows for the physical inventory report.

    focus: all | needs_count | missing | located | signed_out
    """
    q = str(query or "").strip().lower()
    loc_filter = str(location or "").strip().lower()
    focus_key = str(focus or "all").strip().lower()
    rows: List[Dict[str, Any]] = []

    for tool in data.get("tools") or []:
        if status != "all" and tool.get("status") != status:
            continue
        tool_loc = str(tool.get("location") or "").strip()
        if loc_filter and loc_filter not in tool_loc.lower():
            continue
        if q:
            hay = " ".join(
                [
                    str(tool.get("tool_no") or ""),
                    str(tool.get("description") or ""),
                    tool_loc,
                    str(tool.get("notes") or ""),
                ]
            ).lower()
            if q not in hay:
                continue

        tid = str(tool.get("id") or "")
        open_cos = _open_checkouts_for_tool(data, tid)
        is_signed_out = bool(open_cos)
        result = inventory_result_for_tool(tool)
        acct = normalize_accountability(tool.get("accountability"))

        if focus_key == "signed_out" and not is_signed_out:
            continue
        if focus_key == "missing" and result != INVENTORY_RESULT_MISSING and acct != ACCOUNTABILITY_UNACCOUNTED:
            continue
        if focus_key == "located" and result not in (
            INVENTORY_RESULT_LOCATED,
            INVENTORY_RESULT_RETURNED,
        ):
            continue
        if focus_key == "needs_count" and (is_signed_out or result):
            continue

        tech_names = sorted(
            {
                str(c.get("tech_name") or "").strip()
                for c in open_cos
                if str(c.get("tech_name") or "").strip()
            },
            key=str.lower,
        )
        first_out = ""
        if open_cos:
            starts = [str(c.get("checked_out_at") or "") for c in open_cos]
            first_out = min(starts) if starts else ""

        rows.append(
            {
                "tool_id": tid,
                "tool_no": tool.get("tool_no", ""),
                "description": tool.get("description", ""),
                "location": tool_loc,
                "qty": int(tool.get("quantity") or 1),
                "qty_out": qty_out(data, tid),
                "is_signed_out": is_signed_out,
                "signed_out_to": ", ".join(tech_names),
                "signed_out_at": format_report_when(first_out) if first_out else "",
                "accountability": acct,
                "inventory_result": result,
                "inventory_checked_at": str(tool.get("inventory_checked_at") or ""),
                "inventory_counted_by": str(tool.get("inventory_counted_by") or ""),
            }
        )

    rows.sort(key=lambda r: str(r.get("tool_no") or "").lower())
    return rows


def inventory_count_stats(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(rows),
        "signed_out": sum(1 for r in rows if r.get("is_signed_out")),
        "missing": sum(
            1
            for r in rows
            if not r.get("is_signed_out")
            and r.get("inventory_result") == INVENTORY_RESULT_MISSING
        ),
        "located": sum(
            1
            for r in rows
            if not r.get("is_signed_out")
            and r.get("inventory_result")
            in (INVENTORY_RESULT_LOCATED, INVENTORY_RESULT_RETURNED)
        ),
        "needs_count": sum(
            1
            for r in rows
            if not r.get("is_signed_out") and not r.get("inventory_result")
        ),
    }
