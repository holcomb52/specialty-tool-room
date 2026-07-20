"""Specialty tool room storage + checkout smoke tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from lib.specialty_tools_storage import (
    _load_seed,
    add_tool,
    checkin_checkout,
    checkout_tool,
    dismiss_overdue_alert,
    inventory_stats,
    list_overdue_checkouts,
    qty_available,
    search_tools,
)
from lib.tech_list import _normalize


def test_technicians_sorted_by_first_name():
    names = _normalize(
        ["Thomas Wyke", "Armand Liebes", "Dale Potts", "Carson Linker"]
    )
    assert names == [
        "Armand Liebes",
        "Carson Linker",
        "Dale Potts",
        "Thomas Wyke",
    ]


def test_seed_inventory_loads():
    data = _load_seed()
    stats = inventory_stats(data)
    assert stats["total"] >= 1700
    assert stats["active"] > 1500
    assert stats["out_now"] == 0
    assert stats["overdue"] == 0


def test_checkout_and_checkin_cycle():
    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    assert qty_available(data, tool) == 1

    ok, msg = checkout_tool(data, tool["id"], "Jordan Kim", qty=1, ro_number="RO1")
    assert ok, msg
    assert qty_available(data, tool) == 0

    ok, msg = checkout_tool(data, tool["id"], "Alex Rivera", qty=1)
    assert not ok

    checkout_id = data["active_checkouts"][0]["id"]
    ok, msg = checkin_checkout(data, checkout_id)
    assert ok, msg
    assert qty_available(data, tool) == 1


def test_overdue_alert_and_dismiss_until_date():
    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1)
    assert ok, msg

    checkout = data["active_checkouts"][0]
    checkout["checked_out_at"] = (
        datetime.now(timezone.utc) - timedelta(days=6)
    ).isoformat()

    overdue = list_overdue_checkouts(data)
    assert len(overdue) == 1
    assert overdue[0]["days_out"] >= 5

    today = date.today()
    ok, msg = dismiss_overdue_alert(
        data, checkout["id"], today + timedelta(days=10), today=today
    )
    assert ok, msg
    assert list_overdue_checkouts(data, today=today) == []

    # Alert returns on the dismiss-until date
    assert len(list_overdue_checkouts(data, today=today + timedelta(days=10))) == 1


def test_report_rows_and_pdf():
    from lib.reports_pdf import build_checkout_report_pdf
    from lib.specialty_tools_storage import (
        all_open_checkout_report_rows,
        checkouts_for_technician,
        returned_tool_report_rows,
    )

    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1)
    assert ok, msg
    data["active_checkouts"][0]["checked_out_at"] = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).isoformat()

    open_rows = all_open_checkout_report_rows(data)
    assert len(open_rows) == 1
    assert open_rows[0]["signed_in"] == "Still out"
    assert open_rows[0]["tech_name"] == "Dale Potts"

    tech_rows = checkouts_for_technician(data, "Dale Potts")
    assert len(tech_rows) == 1

    cid = data["active_checkouts"][0]["id"]
    ok, msg = checkin_checkout(data, cid)
    assert ok, msg
    returned = returned_tool_report_rows(data)
    assert len(returned) == 1
    assert returned[0]["signed_out"] != "—"
    assert returned[0]["signed_in"] != "Still out"

    pdf = build_checkout_report_pdf(
        title="Test Report",
        rows=open_rows,
        summary=[("Tools signed out", "1")],
    )
    assert pdf.startswith(b"%PDF")


def test_add_and_search_tool():
    data = _load_seed()
    ok, msg, tool = add_tool(
        data,
        tool_no="ZZ-TEST-99",
        description="Smoke test puller",
        location="SHELF A",
        notes="NEW TOOL",
    )
    assert ok, msg
    assert tool is not None
    hits = search_tools(data, "ZZ-TEST-99")
    assert len(hits) == 1
    assert hits[0]["location"] == "SHELF A"


def test_import_dedupes_and_keeps_system_location():
    from lib.specialty_tools_storage import replace_tools_from_import

    data = {
        "version": 1,
        "source": "local",
        "tools": [
            {
                "id": "keep-me",
                "tool_no": "C-100",
                "description": "OLD DESC",
                "quantity": 1,
                "location": "WALL 14 / SYSTEM",
                "notes": "",
                "status": "active",
            }
        ],
        "active_checkouts": [],
        "history": [],
    }
    imported = [
        {
            "id": "new-1",
            "tool_no": "C-100",
            "description": "NEW DESC",
            "quantity": 2,
            "location": "SPREADSHEET LOC",
            "notes": "",
            "status": "active",
        },
        {
            "id": "dup-noncurrent",
            "tool_no": "C-100",
            "description": "DUP",
            "quantity": 1,
            "location": "OTHER",
            "notes": "",
            "status": "non_current",
        },
        {
            "id": "new-2",
            "tool_no": "C-200",
            "description": "SECOND",
            "quantity": 1,
            "location": "BIN A",
            "notes": "",
            "status": "active",
        },
    ]
    merged = replace_tools_from_import(data, imported, source="test.xls")
    tools = merged["tools"]
    assert len(tools) == 2
    c100 = next(t for t in tools if t["tool_no"] == "C-100")
    assert c100["id"] == "keep-me"
    assert c100["location"] == "WALL 14 / SYSTEM"
    assert c100["description"] == "NEW DESC"
    assert merged["_import_stats"]["duplicates_removed"] == 1
    assert merged["_import_stats"]["locations_kept"] == 1
