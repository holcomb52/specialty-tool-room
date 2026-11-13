"""Admin usage report from check-out history and tools still signed out.

History keeps the newest ``HISTORY_LIMIT`` entries (500). A returned loan whose
history row has aged out is not counted. An open checkout is counted even when
its original history row is gone, so tools still on the floor stay visible.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from lib.specialty_tools_storage import HISTORY_LIMIT, _parse_iso

RARELY_AT_MOST = 1


def usage_history_note(report: Dict[str, Any]) -> str:
    """Shop-facing explanation of the history cap. Always mentions the limit."""
    limit = int(report.get("history_limit") or HISTORY_LIMIT)
    note = (
        f"Counts use check-out history, which keeps only the newest {limit} entries "
        "(newest first), plus any tool that is still checked out. Returned loans "
        "older than that log do not appear."
    )
    if report.get("history_capped"):
        oldest = str(report.get("oldest_history_at") or "").strip()
        note += " This log is full."
        if oldest:
            note += f" Oldest entry still kept: {oldest}."
    return note


def _local_day(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


def _qty(value: Any) -> int:
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return 1


def _history_bounds(history: List[Any]) -> Dict[str, Any]:
    stamps: List[datetime] = []
    count = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        count += 1
        parsed = _parse_iso(str(entry.get("at") or ""))
        if parsed is not None:
            stamps.append(parsed)
    oldest = min(stamps) if stamps else None
    newest = max(stamps) if stamps else None
    return {
        "history_count": count,
        "history_limit": HISTORY_LIMIT,
        "history_capped": count >= HISTORY_LIMIT,
        "oldest_history_at": oldest.isoformat() if oldest else "",
        "newest_history_at": newest.isoformat() if newest else "",
    }


def _empty_report(
    bounds: Dict[str, Any],
    *,
    start: Optional[date],
    end: Optional[date],
    rare_at_most: int,
    ok: bool,
    error: str,
) -> Dict[str, Any]:
    return {
        "ok": ok,
        "error": error,
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "rare_at_most": rare_at_most,
        "event_count": 0,
        "most_used": [],
        "never": [],
        "rarely": [],
        "by_technician": [],
        **bounds,
    }


def _consider(
    events: List[Dict[str, Any]],
    seen: set,
    *,
    tool_id: str,
    tool_no: str,
    description: str,
    tech_name: str,
    qty: Any,
    when_iso: str,
) -> None:
    parsed = _parse_iso(str(when_iso or ""))
    if parsed is None:
        return
    slot = (
        str(tool_id or "").strip() or str(tool_no or "").strip().lower(),
        parsed.isoformat(),
    )
    if not slot[0] or slot in seen:
        return
    seen.add(slot)
    events.append(
        {
            "tool_id": str(tool_id or "").strip(),
            "tool_no": str(tool_no or "").strip(),
            "description": str(description or "").strip(),
            "tech_name": str(tech_name or "").strip(),
            "qty": _qty(qty),
            "at": parsed,
            "at_iso": str(when_iso or "").strip() or parsed.isoformat(),
        }
    )


def collect_usage_events(data: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    """One row per checkout. Open loans win over history so a corrected tech is kept.

    A check-in counts only when it still has ``checked_out_at``, and only if the
    matching check-out row is no longer in the capped history.
    """
    payload = data if isinstance(data, dict) else {}
    events: List[Dict[str, Any]] = []
    seen: set = set()

    for checkout in payload.get("active_checkouts") or []:
        if not isinstance(checkout, dict):
            continue
        _consider(
            events,
            seen,
            tool_id=str(checkout.get("tool_id") or ""),
            tool_no=str(checkout.get("tool_no") or ""),
            description=str(checkout.get("description") or ""),
            tech_name=str(checkout.get("tech_name") or ""),
            qty=checkout.get("qty"),
            when_iso=str(checkout.get("checked_out_at") or ""),
        )

    history = [entry for entry in (payload.get("history") or []) if isinstance(entry, dict)]
    for entry in history:
        if entry.get("action") != "checkin":
            continue
        _consider(
            events,
            seen,
            tool_id=str(entry.get("tool_id") or ""),
            tool_no=str(entry.get("tool_no") or ""),
            description=str(entry.get("description") or ""),
            tech_name=str(entry.get("tech_name") or ""),
            qty=entry.get("qty"),
            when_iso=str(entry.get("checked_out_at") or ""),
        )
    for entry in history:
        if entry.get("action") != "checkout":
            continue
        _consider(
            events,
            seen,
            tool_id=str(entry.get("tool_id") or ""),
            tool_no=str(entry.get("tool_no") or ""),
            description=str(entry.get("description") or ""),
            tech_name=str(entry.get("tech_name") or ""),
            qty=entry.get("qty"),
            when_iso=str(entry.get("at") or ""),
        )
    return events


def _in_range(dt: datetime, start: Optional[date], end: Optional[date]) -> bool:
    day = _local_day(dt)
    if start is not None and day < start:
        return False
    if end is not None and day > end:
        return False
    return True


def _canonical_tech(name: str, by_lower: Dict[str, str]) -> str:
    cleaned = str(name or "").strip()
    if not cleaned:
        return ""
    return by_lower.get(cleaned.lower(), cleaned)


def build_usage_report(
    data: Dict[str, Any] | None,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    rare_at_most: int = RARELY_AT_MOST,
    include_non_current: bool = False,
    technician_names: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Most-used tools, never/rarely used tools, and checkouts per technician.

    Dates are inclusive shop-local calendar days. ``rare_at_most`` is the
    highest checkout count that still counts as rare (never is always zero).
    """
    payload = data if isinstance(data, dict) else {}
    bounds = _history_bounds(list(payload.get("history") or []))
    try:
        rare_max = int(rare_at_most)
    except (TypeError, ValueError):
        rare_max = RARELY_AT_MOST
    if rare_max < 1:
        rare_max = 1

    if start is not None and end is not None and start > end:
        return _empty_report(
            bounds,
            start=start,
            end=end,
            rare_at_most=rare_max,
            ok=False,
            error="Start date must be on or before the end date.",
        )

    tools = [tool for tool in (payload.get("tools") or []) if isinstance(tool, dict)]
    catalog_ids = {str(tool.get("id") or "") for tool in tools if str(tool.get("id") or "")}
    by_no: Dict[str, List[str]] = {}
    for tool in tools:
        number = str(tool.get("tool_no") or "").strip().lower()
        tool_id = str(tool.get("id") or "")
        if number and tool_id:
            by_no.setdefault(number, []).append(tool_id)

    def resolve(event: Dict[str, Any]) -> str:
        tool_id = event["tool_id"]
        if tool_id and tool_id in catalog_ids:
            return tool_id
        matches = by_no.get(event["tool_no"].lower(), [])
        if len(matches) == 1:
            return matches[0]
        return tool_id or event["tool_no"].lower()

    grouped: Dict[str, Dict[str, Any]] = {}
    tech_rows: Dict[str, Dict[str, Any]] = {}
    known_techs = {
        str(name).strip().lower(): str(name).strip()
        for name in (technician_names or [])
        if str(name or "").strip()
    }
    event_count = 0

    for event in collect_usage_events(payload):
        if not _in_range(event["at"], start, end):
            continue
        event_count += 1
        key = resolve(event)
        row = grouped.get(key)
        if row is None:
            row = {
                "tool_id": event["tool_id"],
                "tool_no": event["tool_no"],
                "description": event["description"],
                "checkouts": 0,
                "qty": 0,
                "techs": set(),
                "last_at": event["at"],
                "last_checked_out_at": event["at_iso"],
            }
            grouped[key] = row
        row["checkouts"] += 1
        row["qty"] += int(event["qty"])
        if event["tech_name"]:
            row["techs"].add(event["tech_name"])
        if event["at"] >= row["last_at"]:
            row["last_at"] = event["at"]
            row["last_checked_out_at"] = event["at_iso"]
            if event["tool_no"]:
                row["tool_no"] = event["tool_no"]
            if event["description"]:
                row["description"] = event["description"]
            if event["tool_id"]:
                row["tool_id"] = event["tool_id"]

        tech_name = _canonical_tech(event["tech_name"], known_techs)
        if tech_name:
            tech = tech_rows.get(tech_name.lower())
            if tech is None:
                tech = {
                    "tech_name": tech_name,
                    "checkouts": 0,
                    "qty": 0,
                    "tools": set(),
                }
                tech_rows[tech_name.lower()] = tech
            tech["checkouts"] += 1
            tech["qty"] += int(event["qty"])
            tech["tools"].add(key)

    for tool in tools:
        tool_id = str(tool.get("id") or "")
        if tool_id and tool_id in grouped:
            grouped[tool_id]["tool_no"] = str(tool.get("tool_no") or grouped[tool_id]["tool_no"])
            grouped[tool_id]["description"] = str(
                tool.get("description") or grouped[tool_id]["description"]
            )
            grouped[tool_id]["tool_id"] = tool_id

    most_used = []
    for row in grouped.values():
        most_used.append(
            {
                "tool_id": row["tool_id"],
                "tool_no": row["tool_no"],
                "description": row["description"],
                "checkouts": row["checkouts"],
                "qty": row["qty"],
                "technicians": ", ".join(sorted(row["techs"], key=str.lower)),
                "last_checked_out_at": row["last_checked_out_at"],
            }
        )
    most_used.sort(
        key=lambda item: (
            -int(item["checkouts"]),
            -int(item["qty"]),
            str(item["tool_no"]).lower(),
        )
    )

    never: List[Dict[str, Any]] = []
    rarely: List[Dict[str, Any]] = []
    for tool in tools:
        if not include_non_current and tool.get("status") == "non_current":
            continue
        tool_id = str(tool.get("id") or "")
        count = int(grouped.get(tool_id, {}).get("checkouts") or 0)
        record = {
            "tool_id": tool_id,
            "tool_no": str(tool.get("tool_no") or ""),
            "description": str(tool.get("description") or ""),
            "location": str(tool.get("location") or ""),
            "status": str(tool.get("status") or ""),
            "checkouts": count,
        }
        if count == 0:
            never.append(record)
        elif count <= rare_max:
            rarely.append(record)
    never.sort(key=lambda item: str(item["tool_no"]).lower())
    rarely.sort(key=lambda item: (int(item["checkouts"]), str(item["tool_no"]).lower()))

    for lowered, display in known_techs.items():
        if lowered not in tech_rows:
            tech_rows[lowered] = {
                "tech_name": display,
                "checkouts": 0,
                "qty": 0,
                "tools": set(),
            }

    by_technician = [
        {
            "tech_name": row["tech_name"],
            "checkouts": row["checkouts"],
            "qty": row["qty"],
            "distinct_tools": len(row["tools"]),
        }
        for row in tech_rows.values()
    ]
    by_technician.sort(
        key=lambda item: (-int(item["checkouts"]), str(item["tech_name"]).lower())
    )

    report = _empty_report(
        bounds,
        start=start,
        end=end,
        rare_at_most=rare_max,
        ok=True,
        error="",
    )
    report["event_count"] = event_count
    report["most_used"] = most_used
    report["never"] = never
    report["rarely"] = rarely
    report["by_technician"] = by_technician
    return report
