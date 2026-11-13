"""Overdue threshold, usage report, and cached tool search."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lib.specialty_tools_storage import (
    HISTORY_LIMIT,
    _normalize,
    add_tool,
    checkout_tool,
    list_overdue_checkouts,
    overdue_after_days,
    replace_tools_from_import,
    save_inventory,
    search_tools,
    set_overdue_after_days,
    update_checkout,
)
from lib.tool_search import clear_search_cache, search_index_stats
from lib.usage_report import build_usage_report, usage_history_note


def _blank() -> dict:
    return {
        "version": 1,
        "source": "test",
        "tools": [],
        "active_checkouts": [],
        "history": [],
    }


def _at(day: date, hour: int = 15) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc).isoformat()


def _add(data: dict, tool_no: str, *, status: str = "active", location: str = "SHELF") -> dict:
    ok, msg, tool = add_tool(
        data,
        tool_no=tool_no,
        description=f"{tool_no} DESC",
        location=location,
        status=status,
    )
    assert ok, msg
    return tool


def test_overdue_threshold_is_configurable_and_saved():
    data = _blank()
    tool = _add(data, "T-OVD")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", ro_number="RO-1")
    assert ok, msg
    data["active_checkouts"][0]["checked_out_at"] = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()

    assert overdue_after_days(data) == 5
    assert list_overdue_checkouts(data) == []

    ok, msg = set_overdue_after_days(data, 3)
    assert ok, msg
    flagged = list_overdue_checkouts(data)
    assert len(flagged) == 1
    assert flagged[0]["tech_name"] == "Dale Potts"
    assert flagged[0]["days_out"] >= 3
    assert flagged[0]["alert_snoozed"] is False

    # An explicit threshold still overrides the saved shop setting.
    assert list_overdue_checkouts(data, days=10) == []

    for bad in (0, 91, "nope", True, 2.5, None):
        ok, msg = set_overdue_after_days(data, bad)
        assert not ok
        assert overdue_after_days(data) == 3

    stored = _normalize(data)
    assert stored["settings"]["overdue_after_days"] == 3


def test_overdue_setting_round_trips_and_survives_import(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    monkeypatch.setattr(
        "lib.specialty_tools_storage._save_remote",
        lambda _data, expected_version=None: (True, ""),
    )
    data = _blank()
    _add(data, "T-KEEP")
    ok, msg = set_overdue_after_days(data, 12)
    assert ok, msg
    data["settings"]["shop_note"] = "floor 2"
    ok, err = save_inventory(data)
    assert ok, err
    saved = json.loads(live.read_text())
    assert saved["settings"]["overdue_after_days"] == 12
    assert saved["settings"]["shop_note"] == "floor 2"

    imported = replace_tools_from_import(
        saved,
        [
            {
                "id": "new",
                "tool_no": "T-KEEP",
                "description": "REPLACED",
                "quantity": 1,
                "location": "",
                "status": "active",
            }
        ],
        source="sheet",
    )
    assert imported["settings"]["overdue_after_days"] == 12
    assert _normalize(imported)["settings"]["overdue_after_days"] == 12


def test_dismissed_overdue_stays_on_the_full_list():
    data = _blank()
    tool = _add(data, "T-SNOOZE")
    ok, msg = checkout_tool(data, tool["id"], "Armand Liebes", ro_number="RO-2")
    assert ok, msg
    checkout = data["active_checkouts"][0]
    checkout["checked_out_at"] = (
        datetime.now(timezone.utc) - timedelta(days=9)
    ).isoformat()
    checkout["alert_dismissed_until"] = (date.today() + timedelta(days=2)).isoformat()
    assert list_overdue_checkouts(data) == []
    full = list_overdue_checkouts(data, include_dismissed=True)
    assert len(full) == 1
    assert full[0]["alert_snoozed"] is True
    assert full[0]["tech_name"] == "Armand Liebes"


def test_open_checkout_is_not_double_counted_and_keeps_corrected_tech():
    data = _blank()
    tool = _add(data, "T-OPEN")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", ro_number="RO-A")
    assert ok, msg
    when = _at(date.today() - timedelta(days=1))
    data["active_checkouts"][0]["checked_out_at"] = when
    data["history"][0]["at"] = when
    ok, msg = update_checkout(data, data["active_checkouts"][0]["id"], tech_name="Carson Linker")
    assert ok, msg
    report = build_usage_report(
        data,
        start=date.today() - timedelta(days=7),
        end=date.today(),
    )
    assert report["event_count"] == 1
    assert report["most_used"][0]["technicians"] == "Carson Linker"
    assert report["most_used"][0]["checkouts"] == 1


def test_usage_report_counts_history_and_open_checkouts_once():
    data = _blank()
    puller = _add(data, "T-PULL")
    quiet = _add(data, "T-QUIET")
    rare = _add(data, "T-RARE")
    old = _add(data, "T-OLD", status="non_current")
    today = date.today()

    def _loan(tool: dict, tech: str, day: date, *, action: str) -> dict:
        return {
            "id": f"{action}-{tool['tool_no']}-{day.isoformat()}",
            "action": action,
            "tool_id": tool["id"],
            "tool_no": tool["tool_no"],
            "description": tool["description"],
            "tech_name": tech,
            "qty": 1,
            "at": _at(day),
            "checked_out_at": _at(day),
            "ro_number": "RO",
        }

    # Two returned loans, plus one still out. The open loan's history row is gone.
    data["history"] = [
        _loan(puller, "Dale Potts", today - timedelta(days=10), action="checkin"),
        _loan(puller, "Dale Potts", today - timedelta(days=4), action="checkin"),
        _loan(rare, "dale potts", today - timedelta(days=3), action="checkin"),
        _loan(old, "Dale Potts", today - timedelta(days=40), action="checkout"),
    ]
    data["active_checkouts"] = [
        {
            "id": "open-pull",
            "tool_id": puller["id"],
            "tool_no": puller["tool_no"],
            "description": puller["description"],
            "tech_name": "Carson Linker",
            "qty": 1,
            "checked_out_at": _at(today - timedelta(days=1)),
            "ro_number": "RO-NOW",
        }
    ]

    report = build_usage_report(
        data,
        start=today - timedelta(days=30),
        end=today,
        rare_at_most=1,
        technician_names=["Carson Linker", "Dale Potts", "Noah Ihnken"],
    )
    assert report["ok"] is True
    assert "500" in usage_history_note(report)
    assert report["history_capped"] is False
    by_no = {row["tool_no"]: row for row in report["most_used"]}
    assert by_no["T-PULL"]["checkouts"] == 3
    assert "Carson Linker" in by_no["T-PULL"]["technicians"]
    assert "Dale Potts" in by_no["T-PULL"]["technicians"]
    assert by_no["T-RARE"]["checkouts"] == 1
    assert "T-OLD" not in by_no
    assert "T-QUIET" not in by_no

    never_nos = {row["tool_no"] for row in report["never"]}
    rare_nos = {row["tool_no"] for row in report["rarely"]}
    assert "T-QUIET" in never_nos
    assert "T-OLD" not in never_nos
    assert "T-RARE" in rare_nos
    assert "T-PULL" not in rare_nos and "T-PULL" not in never_nos

    techs = {row["tech_name"]: row for row in report["by_technician"]}
    assert techs["Carson Linker"]["checkouts"] == 1
    assert techs["Dale Potts"]["checkouts"] == 3
    assert techs["Noah Ihnken"]["checkouts"] == 0
    assert techs["Dale Potts"]["distinct_tools"] == 2

    wider = build_usage_report(
        data,
        start=today - timedelta(days=60),
        end=today,
        include_non_current=True,
    )
    wider_nos = {row["tool_no"]: row["checkouts"] for row in wider["most_used"]}
    assert wider_nos["T-OLD"] == 1
    assert any(row["tool_no"] == "T-OLD" for row in wider["rarely"])

    swapped = build_usage_report(data, start=today, end=today - timedelta(days=30))
    assert swapped["ok"] is False
    assert swapped["event_count"] == 0


def test_usage_report_flags_full_history():
    data = _blank()
    tool = _add(data, "T-CAP")
    data["active_checkouts"] = [
        {
            "id": "open-1",
            "tool_id": tool["id"],
            "tool_no": "T-CAP",
            "description": "T-CAP DESC",
            "tech_name": "Dale Potts",
            "qty": 1,
            "checked_out_at": _at(date.today()),
        }
    ]
    data["history"] = [
        {
            "id": f"h-{index}",
            "action": "updated",
            "at": _at(date.today() - timedelta(days=index + 1)),
        }
        for index in range(HISTORY_LIMIT)
    ]
    report = build_usage_report(data, start=date.today() - timedelta(days=1), end=date.today())
    assert report["history_capped"] is True
    assert report["history_count"] == HISTORY_LIMIT
    assert report["event_count"] == 1
    note = usage_history_note(report)
    assert "500" in note
    assert "full" in note.lower()


def test_search_index_matches_filters_and_stays_cached():
    from lib.specialty_tools_storage import _load_seed

    clear_search_cache()
    data = _load_seed()
    first = search_tools(data, "bearing", status="all")
    warmup = time.perf_counter()
    queries = ("c-4150", "puller", "shelf", "ball joint", "")
    for query in queries:
        search_tools(data, query, status="all")
        search_tools(data, query, status="active", location="shelf")
    elapsed = time.perf_counter() - warmup
    assert first
    assert search_index_stats()["builds"] == 1
    assert search_index_stats()["hits"] >= 1
    assert elapsed < 2.0, f"cached searches took {elapsed:.2f}s"

    legacy = _legacy_search(data, "bearing", status="all")
    assert [(row["id"], row["qty_out"], row["accountability"]) for row in first] == [
        (row["id"], row["qty_out"], row["accountability"]) for row in legacy
    ]
    indexed = search_tools(data, "", status="active", location="diff gray")
    legacy_loc = _legacy_search(data, "", status="active", location="diff gray")
    assert [row["id"] for row in indexed] == [row["id"] for row in legacy_loc]

    dodge = search_tools(data, "C-293B-18", status="all", brand="dodge")
    jeep = search_tools(data, "C-293B-18", status="all", brand="jeep", brand_level="essential")
    chrysler = search_tools(
        data, "C-293B-18", status="all", brand="chrysler", brand_level="essential"
    )
    assert dodge == []
    assert [row["tool_no"] for row in jeep] == ["C-293B-18"]
    assert chrysler == []

    tool = next(row for row in data["tools"] if row.get("tool_no") == "C-4150A")
    tool["description"] = "UNIQUE ZZZ SEARCH TOKEN"
    assert search_index_stats()["builds"] == 1
    hits = search_tools(data, "unique zzz", status="all")
    assert [row["id"] for row in hits] == [tool["id"]]
    assert search_index_stats()["builds"] == 2

    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", ro_number="RO-SEARCH")
    assert ok, msg
    out = search_tools(data, "C-4150A", status="all", only_out=True)
    assert len(out) == 1
    assert out[0]["qty_available"] == 0
    assert out[0]["qty_out"] == 1


def _legacy_search(data, query="", *, status="active", location=""):
    """Previous scan, kept so the index cannot drift from the shop filters."""
    from lib.specialty_tools_storage import (
        normalize_accountability,
        qty_available,
        qty_out,
    )

    q = str(query or "").strip().lower()
    loc_filter = str(location or "").strip().lower()
    results = []
    for tool in data.get("tools") or []:
        if status != "all" and tool.get("status") != status:
            continue
        acct = normalize_accountability(tool.get("accountability"))
        tool_loc = str(tool.get("location") or "").strip()
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


def test_role_pages_include_overdue_and_admin_usage():
    from lib.app_auth import pages_for_role

    assert "Overdue" in pages_for_role("tech")
    assert "Usage" not in pages_for_role("tech")
    assert "Overdue" in pages_for_role("admin")
    assert "Usage" in pages_for_role("admin")
    assert "Usage" in pages_for_role("manager")


def test_overdue_and_usage_pages_render(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    live = tmp_path / "specialty_tools.json"
    today = date.today()
    checked_out = _at(today - timedelta(days=10))
    store = {
        "version": 3,
        "source": "test",
        "settings": {"overdue_after_days": 4},
        "tools": [
            {
                "id": "tool-1",
                "tool_no": "T-1",
                "description": "HOLDER",
                "quantity": 1,
                "status": "active",
                "location": "SHELF A",
            }
        ],
        "active_checkouts": [
            {
                "id": "co-1",
                "tool_id": "tool-1",
                "tool_no": "T-1",
                "description": "HOLDER",
                "tech_name": "Dale Potts",
                "qty": 1,
                "checked_out_at": checked_out,
                "ro_number": "100",
                "note": "",
            }
        ],
        "history": [
            {
                "id": "h-1",
                "action": "checkout",
                "tool_id": "tool-1",
                "tool_no": "T-1",
                "description": "HOLDER",
                "tech_name": "Dale Potts",
                "qty": 1,
                "at": checked_out,
                "ro_number": "100",
            }
        ],
    }
    live.write_text(json.dumps(store))
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: None)
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=90)
    at.session_state["tool_room_authenticated"] = True
    at.session_state["tool_room_role"] = "manager"
    at.session_state["nav_page"] = "Overdue"
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    visible = _visible(at)
    assert "Dale Potts" in visible
    assert "4 days" in visible

    at.radio(key="nav_page").set_value("Usage")
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    assert "500" in _visible(at)

    at.session_state["tool_room_role"] = "tech"
    at.session_state["nav_page"] = "Overdue"
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    options = list(at.radio(key="nav_page").options)
    assert "Overdue" in options
    assert "Usage" not in options


def _exception_text(at) -> str:
    chunks = []
    for exc in at.exception:
        chunks.append(str(getattr(exc.proto, "message", "") or ""))
        chunks.extend(list(exc.stack_trace or []))
    return "\n".join(chunks)


def _visible(at) -> str:
    parts = []
    for group_name in ("markdown", "caption", "text", "info", "warning", "success"):
        group = getattr(at, group_name, None)
        if not group:
            continue
        for item in group:
            parts.append(str(getattr(item, "value", "")))
    return "\n".join(parts)
