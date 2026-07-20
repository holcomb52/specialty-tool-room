"""Specialty tool room inventory + check-out / check-in persistence."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib.specialty_tools_import import empty_inventory

STORE_KEY = "specialty_tools"
TABLE = "specialty_tools_store"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LIVE_PATH = DATA_DIR / "specialty_tools.json"
SEED_PATH = DATA_DIR / "specialty_tools_seed.json"

HISTORY_LIMIT = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return _save_remote(normalized)


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
        "ro_number": str(ro_number or "").strip(),
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
            "at": _now_iso(),
            "checkout_id": checkout_id,
        },
    )
    return True, f"Checked in {match.get('tool_no')} from {match.get('tech_name')}."


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
    clean_no = str(tool_no or "").strip()
    clean_desc = str(description or "").strip()
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
        "location": str(location or "").strip(),
        "notes": str(notes or "").strip(),
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
) -> Tuple[bool, str]:
    tool = find_tool(data, tool_id)
    if not tool:
        return False, "Tool not found."
    if description is not None:
        tool["description"] = str(description).strip()
    if quantity is not None:
        tool["quantity"] = max(1, int(quantity))
    if location is not None:
        tool["location"] = str(location).strip()
    if notes is not None:
        tool["notes"] = str(notes).strip()
    if status is not None and status in ("active", "non_current"):
        tool["status"] = status
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
            "note": f"Location set to {tool.get('location') or '(none)'}",
            "ro_number": "",
            "at": _now_iso(),
        },
    )
    return True, f"Updated {tool.get('tool_no')}."


def replace_tools_from_import(
    data: Dict[str, Any],
    imported_tools: List[Dict[str, Any]],
    *,
    source: str,
    keep_checkouts: bool = True,
) -> Dict[str, Any]:
    new_data = empty_inventory(source)
    new_data["tools"] = copy.deepcopy(imported_tools)
    new_data["history"] = list(data.get("history") or [])

    if keep_checkouts:
        by_no = {
            str(t.get("tool_no") or "").strip().lower(): t
            for t in new_data["tools"]
            if str(t.get("tool_no") or "").strip()
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

    _append_history(
        new_data,
        {
            "id": str(uuid.uuid4()),
            "action": "import",
            "tool_id": "",
            "tool_no": "",
            "description": "",
            "tech_name": "",
            "qty": len(imported_tools),
            "note": f"Imported {len(imported_tools)} tools from {source}",
            "ro_number": "",
            "at": _now_iso(),
        },
    )
    return new_data


def inventory_stats(data: Dict[str, Any]) -> Dict[str, int]:
    tools = data.get("tools") or []
    checkouts = data.get("active_checkouts") or []
    return {
        "total": len(tools),
        "active": sum(1 for t in tools if t.get("status") == "active"),
        "non_current": sum(1 for t in tools if t.get("status") == "non_current"),
        "out_now": len(checkouts),
        "units_out": sum(int(c.get("qty") or 1) for c in checkouts),
        "with_location": sum(1 for t in tools if str(t.get("location") or "").strip()),
    }


def search_tools(
    data: Dict[str, Any],
    query: str = "",
    *,
    status: str = "active",
    location: str = "",
    only_out: bool = False,
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
        tool_loc = str(tool.get("location") or "").strip().lower()
        if loc_filter and loc_filter not in tool_loc:
            continue
        if q:
            hay = " ".join(
                [
                    str(tool.get("tool_no") or ""),
                    str(tool.get("description") or ""),
                    str(tool.get("location") or ""),
                    str(tool.get("notes") or ""),
                ]
            ).lower()
            if q not in hay:
                continue
        enriched = dict(tool)
        enriched["qty_out"] = qty_out(data, tool["id"])
        enriched["qty_available"] = qty_available(data, tool)
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
