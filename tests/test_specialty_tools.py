"""Specialty tool room storage + checkout smoke tests."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lib.specialty_tools_storage import (
    ACCOUNTABILITY_LOCATED,
    ACCOUNTABILITY_PART_ORDERED,
    ACCOUNTABILITY_SIGNED_OUT,
    ACCOUNTABILITY_UNACCOUNTED,
    HISTORY_LIMIT,
    REMOTE_ERROR,
    REMOTE_OK,
    _load_seed,
    add_tool,
    checkin_checkout,
    checkout_tool,
    checkouts_for_technician,
    delete_tool,
    dismiss_overdue_alert,
    find_tool,
    find_tool_by_number,
    inventory_stats,
    last_checkout_tech,
    list_overdue_checkouts,
    load_inventory,
    qty_available,
    save_inventory,
    search_tools,
    update_checkout,
    update_tool,
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

    ok, msg = checkout_tool(data, tool["id"], "Alex Rivera", qty=1, ro_number="RO2")
    assert not ok

    ok, msg = checkout_tool(data, tool["id"], "Alex Rivera", qty=1, ro_number="")
    assert not ok
    assert "RO" in msg

    checkout_id = data["active_checkouts"][0]["id"]
    ok, msg = update_checkout(data, checkout_id, tech_name="Dale Potts")
    assert ok, msg
    assert data["active_checkouts"][0]["tech_name"] == "Dale Potts"
    assert any(h.get("action") == "checkout_corrected" for h in data["history"])

    ok, msg = checkin_checkout(data, checkout_id)
    assert ok, msg
    assert qty_available(data, tool) == 1


def test_last_checkout_tech_follows_open_and_returned_loans():
    data = {"tools": [], "active_checkouts": [], "history": [], "source": "", "version": 1}
    ok, msg, tool = add_tool(
        data, tool_no="T-LAST", description="LAST TECH TEST", quantity=1
    )
    assert ok, msg
    assert last_checkout_tech(data, tool_id=tool["id"]) == ""

    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-A")
    assert ok, msg
    assert last_checkout_tech(data, tool_id=tool["id"]) == "Dale Potts"

    ok, msg = checkin_checkout(data, data["active_checkouts"][0]["id"])
    assert ok, msg
    assert last_checkout_tech(data, tool_id=tool["id"], tool_no="T-LAST") == "Dale Potts"

    ok, msg = checkout_tool(data, tool["id"], "Armand Liebes", qty=1, ro_number="RO-B")
    assert ok, msg
    ok, msg = checkin_checkout(data, data["active_checkouts"][0]["id"])
    assert ok, msg
    assert last_checkout_tech(data, tool_id=tool["id"]) == "Armand Liebes"


def test_overdue_alert_and_dismiss_until_date():
    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-OVERDUE")
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
        checkout_report_rows,
        checkouts_for_technician,
        returned_tool_report_rows,
    )

    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-REPORT")
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
    assert tech_rows[0] is data["active_checkouts"][0]
    assert tech_rows[0]["id"]
    tech_report = checkout_report_rows(tech_rows)
    assert tech_report[0]["id"] == tech_rows[0]["id"]
    assert tech_report[0]["signed_in"] == "Still out"

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


def test_check_in_my_tools_keeps_checkout_id():
    """Check In crashed with KeyError when My tools was selected.

    The live screen (Charles Hinxman, My tools (1), Everyone (3)) built
    ``ids = {c["id"] for c in checkouts_sorted}`` from
    ``checkouts_for_technician()``. That helper returned report rows, which
    omitted ``id``, so the page died even though every stored checkout had one.
    """
    data = {
        "tools": [],
        "active_checkouts": [],
        "history": [],
        "source": "",
        "version": 1,
    }
    ok, msg, tool = add_tool(
        data, tool_no="T-HINX", description="HINGE TOOL", quantity=2
    )
    assert ok, msg
    ok, msg = checkout_tool(
        data, tool["id"], "Charles Hinxman", qty=1, ro_number="RO-1"
    )
    assert ok, msg
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-2")
    assert ok, msg

    stored = next(
        c for c in data["active_checkouts"] if c["tech_name"] == "Charles Hinxman"
    )
    mine = checkouts_for_technician(data, "Charles Hinxman")
    assert len(mine) == 1
    assert mine[0] is stored
    # This is the line that raised KeyError in production.
    ids = {c["id"] for c in mine}
    assert ids == {stored["id"]}

    ok, msg = checkin_checkout(data, stored["id"])
    assert ok, msg
    assert checkouts_for_technician(data, "Charles Hinxman") == []
    assert len(data["active_checkouts"]) == 1


def test_checkout_missing_id_is_repaired_and_still_checkable():
    """A checkout stored without id is shown and can be checked in.

    The id is derived from the row, so a rerun that reloads the same unsaved
    repair still matches the button the technician tapped.
    """
    from lib.specialty_tools_storage import (
        _normalize,
        checkout_report_rows,
        repair_checkout_ids,
    )

    old = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    fields = {
        "tool_id": "tool-1",
        "tool_no": "T-NOID",
        "description": "NO ID TOOL",
        "tech_name": "Charles Hinxman",
        "qty": 1,
        "checked_out_at": old,
        "ro_number": "RO-NOID",
        "note": "",
    }
    data = {
        "tools": [],
        "active_checkouts": [dict(fields), dict(fields), "not-a-checkout"],
        "history": [],
        "source": "",
        "version": 1,
    }

    loaded = _normalize(data)
    assert loaded["active_checkouts"][0]["id"].startswith("repaired-")
    assert loaded["active_checkouts"][0]["id"] != loaded["active_checkouts"][1]["id"]

    mine = checkouts_for_technician(data, "Charles Hinxman")
    ids = {c["id"] for c in mine}
    assert len(mine) == 2
    assert len(ids) == 2
    assert mine[0] is data["active_checkouts"][0]
    assert mine[1] is data["active_checkouts"][1]

    stamped = [c["id"] for c in mine]
    for checkout in data["active_checkouts"]:
        if isinstance(checkout, dict):
            checkout.pop("id", None)
    assert [c["id"] for c in checkouts_for_technician(data, "Charles Hinxman")] == stamped

    # Out Now keys its correction dropdown by checkout id.
    labels = {c["id"]: c.get("tool_no") for c in repair_checkout_ids(list(data["active_checkouts"]))}
    assert set(labels) == set(stamped)

    report_rows = checkout_report_rows(mine)
    assert [r["id"] for r in report_rows] == stamped
    assert report_rows[0]["signed_in"] == "Still out"

    overdue = list_overdue_checkouts(data)
    assert {item["id"] for item in overdue} == set(stamped)

    today = date.today()
    ok, msg = dismiss_overdue_alert(
        data, stamped[0], today + timedelta(days=3), today=today
    )
    assert ok, msg
    assert [item["id"] for item in list_overdue_checkouts(data, today=today)] == [
        stamped[1]
    ]

    ok, msg = checkin_checkout(data, stamped[0])
    assert ok, msg
    ok, msg = checkin_checkout(data, stamped[1])
    assert ok, msg
    assert [c for c in data["active_checkouts"] if isinstance(c, dict)] == []
    assert data["active_checkouts"] == ["not-a-checkout"]


def test_inventory_missing_goes_unaccounted_and_signed_out_blocks_mark():
    from lib.reports_pdf import build_inventory_report_pdf
    from lib.specialty_tools_storage import (
        ACCOUNTABILITY_LOCATED,
        ACCOUNTABILITY_UNACCOUNTED,
        apply_inventory_mark,
        clear_inventory_mark,
        inventory_count_rows,
        inventory_stats,
        search_tools,
    )

    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    tid = tool["id"]

    ok, msg = apply_inventory_mark(data, tid, "missing", counted_by="Manager")
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_UNACCOUNTED
    assert tool["inventory_result"] == "missing"
    assert inventory_stats(data)["unaccounted"] >= 1
    missing_hits = search_tools(data, only_unaccounted=True)
    assert any(t["id"] == tid for t in missing_hits)

    ok, msg = apply_inventory_mark(data, tid, "returned", counted_by="Manager")
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_LOCATED
    assert tool["inventory_result"] == "returned"
    assert not any(t["id"] == tid for t in search_tools(data, only_unaccounted=True))

    ok, msg = checkout_tool(data, tid, "Dale Potts", qty=1, ro_number="RO-INV")
    assert ok, msg
    ok, msg = apply_inventory_mark(data, tid, "located")
    assert not ok
    assert "signed out" in msg.lower()

    rows = inventory_count_rows(data, query="C-4150A", focus="signed_out")
    assert len(rows) == 1
    assert rows[0]["is_signed_out"] is True
    assert "Dale Potts" in rows[0]["signed_out_to"]

    ok, msg = checkin_checkout(data, data["active_checkouts"][0]["id"])
    assert ok, msg
    ok, msg = apply_inventory_mark(data, tid, "located")
    assert ok, msg
    ok, msg = clear_inventory_mark(data, tid)
    assert ok, msg
    assert not tool.get("inventory_result")

    pdf = build_inventory_report_pdf(
        title="Inventory Test",
        rows=inventory_count_rows(data, query="C-4150A"),
        summary=[("In filter", "1")],
    )
    assert pdf.startswith(b"%PDF")


def test_part_ordered_box_and_receive_assigns_location():
    from lib.specialty_tools_storage import (
        ACCOUNTABILITY_LOCATED,
        ACCOUNTABILITY_PART_ORDERED,
        inventory_stats,
        receive_ordered_part,
        update_tool,
    )

    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    tid = tool["id"]
    before = inventory_stats(data)["part_ordered"]

    ok, msg = update_tool(data, tid, accountability=ACCOUNTABILITY_PART_ORDERED)
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_PART_ORDERED
    assert inventory_stats(data)["part_ordered"] == before + 1
    ordered = search_tools(data, only_part_ordered=True)
    assert any(t["id"] == tid for t in ordered)
    assert not any(t["id"] == tid for t in search_tools(data, only_unaccounted=True))
    assert not any(
        t["id"] == tid for t in search_tools(data, only_without_location=True)
    )

    ok, msg = receive_ordered_part(data, tid, "")
    assert not ok
    assert "location" in msg.lower()
    assert tool["accountability"] == ACCOUNTABILITY_PART_ORDERED

    ok, msg = receive_ordered_part(data, tid, "shelf d")
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_LOCATED
    assert tool["location"] == "SHELF D"
    assert not any(t["id"] == tid for t in search_tools(data, only_part_ordered=True))
    assert inventory_stats(data)["part_ordered"] == before


def test_locate_unaccounted_tool_puts_in_inventory():
    from lib.specialty_tools_storage import (
        ACCOUNTABILITY_LOCATED,
        ACCOUNTABILITY_UNACCOUNTED,
        inventory_stats,
        locate_unaccounted_tool,
        unaccounted_replacement_totals,
        update_tool,
    )

    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    tid = tool["id"]
    ok, msg = update_tool(data, tid, accountability=ACCOUNTABILITY_UNACCOUNTED)
    assert ok, msg
    before = unaccounted_replacement_totals(data)["tool_count"]
    assert before >= 1
    assert any(t["id"] == tid for t in search_tools(data, only_unaccounted=True))

    ok, msg = locate_unaccounted_tool(data, tid, "")
    assert not ok
    assert "location" in msg.lower()
    assert tool["accountability"] == ACCOUNTABILITY_UNACCOUNTED

    ok, msg = locate_unaccounted_tool(data, tid, "wall 14")
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_LOCATED
    assert tool["location"] == "WALL 14"
    assert not any(t["id"] == tid for t in search_tools(data, only_unaccounted=True))
    assert unaccounted_replacement_totals(data)["tool_count"] == before - 1
    assert inventory_stats(data)["with_location"] >= 1


def test_locate_unaccounted_tools_puts_several_in_same_location():
    from lib.specialty_tools_storage import (
        ACCOUNTABILITY_LOCATED,
        ACCOUNTABILITY_PART_ORDERED,
        ACCOUNTABILITY_UNACCOUNTED,
        locate_unaccounted_tools,
        mark_tools_part_ordered,
        update_tool,
    )

    data = {"tools": [], "active_checkouts": [], "history": [], "source": "", "version": 1}
    ids = []
    for no in ("T-A", "T-B", "T-C"):
        ok, msg, tool = add_tool(data, tool_no=no, description=f"BATCH {no}")
        assert ok, msg
        ok, msg = update_tool(data, tool["id"], accountability=ACCOUNTABILITY_UNACCOUNTED)
        assert ok, msg
        ids.append(tool["id"])

    ok, msg = locate_unaccounted_tools(data, ids[:2], "shelf d")
    assert ok, msg
    assert "2 tools" in msg
    assert find_tool(data, ids[0])["location"] == "SHELF D"
    assert find_tool(data, ids[1])["accountability"] == ACCOUNTABILITY_LOCATED
    assert find_tool(data, ids[2])["accountability"] == ACCOUNTABILITY_UNACCOUNTED

    ok, msg = mark_tools_part_ordered(data, [ids[2]])
    assert ok, msg
    assert find_tool(data, ids[2])["accountability"] == ACCOUNTABILITY_PART_ORDERED


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


def test_delete_tool_removes_number_from_catalog():
    data = {"tools": [], "active_checkouts": [], "history": [], "source": "", "version": 1}
    ok, msg, tool = add_tool(
        data,
        tool_no="Z-9999",
        description="TEMP TEST TOOL",
        quantity=1,
        location="BENCH",
    )
    assert ok, msg
    assert find_tool_by_number(data, "Z-9999") is not None

    ok, msg = delete_tool(data, tool["id"], deleted_by="Manager")
    assert ok, msg
    assert find_tool(data, tool["id"]) is None
    assert find_tool_by_number(data, "Z-9999") is None
    assert any(h.get("action") == "deleted" for h in data["history"])


def test_delete_tool_blocked_when_signed_out_unless_forced():
    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-DEL")
    assert ok, msg

    ok, msg = delete_tool(data, tool["id"])
    assert not ok
    assert "signed out" in msg.lower()
    assert find_tool(data, tool["id"]) is not None

    ok, msg = delete_tool(data, tool["id"], force=True, deleted_by="Admin")
    assert ok, msg
    assert find_tool(data, tool["id"]) is None
    assert all(c.get("tool_id") != tool["id"] for c in data["active_checkouts"])


def test_checkout_blocked_when_unaccounted_or_part_ordered():
    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = update_tool(data, tool["id"], accountability=ACCOUNTABILITY_UNACCOUNTED)
    assert ok, msg
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-MISS")
    assert not ok
    assert "Unaccounted" in msg
    assert data["active_checkouts"] == []

    ok, msg = update_tool(data, tool["id"], accountability=ACCOUNTABILITY_PART_ORDERED)
    assert ok, msg
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-ORD")
    assert not ok
    assert "Part Ordered" in msg
    assert data["active_checkouts"] == []


def test_checkout_marks_signed_out_and_checkin_marks_located():
    data = _load_seed()
    tool = next(t for t in data["tools"] if t.get("tool_no") == "C-4150A")
    ok, msg = checkout_tool(data, tool["id"], "Dale Potts", qty=1, ro_number="RO-ACCT")
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_SIGNED_OUT

    ok, msg = checkin_checkout(data, data["active_checkouts"][0]["id"])
    assert ok, msg
    assert tool["accountability"] == ACCOUNTABILITY_LOCATED


def test_last_checkout_tech_prefers_tool_id_when_number_is_reused():
    data = {
        "tools": [],
        "active_checkouts": [
            {
                "id": "c-new",
                "tool_id": "new-id",
                "tool_no": "C-100",
                "tech_name": "Dale Potts",
                "checked_out_at": "2026-01-02T00:00:00+00:00",
            },
            {
                "id": "c-old",
                "tool_id": "old-id",
                "tool_no": "C-100",
                "tech_name": "Armand Liebes",
                "checked_out_at": "2026-01-03T00:00:00+00:00",
            },
        ],
        "history": [],
        "source": "",
        "version": 1,
    }
    assert last_checkout_tech(data, tool_id="new-id", tool_no="C-100") == "Dale Potts"
    assert last_checkout_tech(data, tool_id="old-id", tool_no="C-100") == "Armand Liebes"


def test_load_inventory_does_not_reseed_when_remote_errors(monkeypatch):
    saved = {"n": 0}

    monkeypatch.setattr(
        "lib.specialty_tools_storage._load_remote",
        lambda: (None, REMOTE_ERROR),
    )
    monkeypatch.setattr("lib.specialty_tools_storage._load_local", lambda: None)

    def _fail_if_saved(_data):
        saved["n"] += 1
        return True, ""

    monkeypatch.setattr("lib.specialty_tools_storage.save_inventory", _fail_if_saved)
    data = load_inventory()
    assert saved["n"] == 0
    assert data.get("_load_error")
    assert data.get("tools") == []
    assert data.get("source") == "cloud-unavailable"


def test_load_inventory_keeps_empty_remote_catalog(monkeypatch):
    empty = {
        "version": 4,
        "source": "live",
        "tools": [],
        "active_checkouts": [],
        "history": [{"action": "deleted"}],
    }
    saved = {"n": 0}
    monkeypatch.setattr(
        "lib.specialty_tools_storage._load_remote",
        lambda: (empty, REMOTE_OK),
    )
    monkeypatch.setattr(
        "lib.specialty_tools_storage.save_inventory",
        lambda _data: saved.__setitem__("n", saved["n"] + 1) or (True, ""),
    )
    data = load_inventory()
    assert data["tools"] == []
    assert data["version"] == 4
    assert saved["n"] == 0


def test_save_inventory_keeps_version_when_remote_fails(monkeypatch):
    captured = {}

    monkeypatch.setattr("lib.specialty_tools_storage._save_local", lambda _data: None)

    def fake_remote(data, *, expected_version=None):
        captured["data"] = dict(data)
        captured["expected_version"] = expected_version
        return False, "network down"

    monkeypatch.setattr("lib.specialty_tools_storage._save_remote", fake_remote)
    payload = {
        "version": 3,
        "source": "t",
        "tools": [],
        "active_checkouts": [],
        "history": [],
    }
    ok, err = save_inventory(payload)
    assert ok is False
    assert "network" in err
    assert payload["version"] == 3
    assert captured["expected_version"] == 3
    assert captured["data"]["version"] == 4


def test_load_admin_users_does_not_save_seed_when_remote_errors(monkeypatch):
    from lib import admin_users

    saved = {"n": 0}
    seed = [
        {
            "id": "s1",
            "name": "Administrator",
            "username": "admin",
            "password_hash": "pbkdf2_sha256$salt$digest",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    monkeypatch.setattr(
        admin_users, "_load_remote", lambda: (None, admin_users.REMOTE_ERROR)
    )
    monkeypatch.setattr(admin_users, "_load_local", lambda: [])
    monkeypatch.setattr(admin_users, "_load_seed", lambda: seed)
    monkeypatch.setattr(
        admin_users,
        "save_admin_users",
        lambda _users: saved.__setitem__("n", saved["n"] + 1) or (True, ""),
    )
    users = admin_users.load_admin_users()
    assert saved["n"] == 0
    assert [u["username"] for u in users] == ["admin"]


def test_removed_seed_admin_is_not_restored_from_live_remote(monkeypatch):
    from lib import admin_users

    live = [
        {
            "id": "1",
            "name": "Shop Admin",
            "username": "shop",
            "password_hash": "pbkdf2_sha256$salt$digest",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    seed = [
        {
            "id": "s1",
            "name": "Administrator",
            "username": "admin",
            "password_hash": "pbkdf2_sha256$salt$digest",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    saved = {"n": 0}
    monkeypatch.setattr(
        admin_users, "_load_remote", lambda: (live, admin_users.REMOTE_OK)
    )
    monkeypatch.setattr(admin_users, "_load_seed", lambda: seed)
    monkeypatch.setattr(
        admin_users,
        "save_admin_users",
        lambda _users: saved.__setitem__("n", saved["n"] + 1) or (True, ""),
    )
    users = admin_users.load_admin_users()
    assert [u["username"] for u in users] == ["shop"]
    assert saved["n"] == 0


def test_bootstrap_admin_skips_save_when_remote_errors(monkeypatch):
    from lib import admin_users

    saved = {"n": 0}
    monkeypatch.setattr(
        admin_users, "_load_remote", lambda: (None, admin_users.REMOTE_ERROR)
    )
    monkeypatch.setattr(admin_users, "_load_local", lambda: [])
    monkeypatch.setattr(admin_users, "_load_seed", lambda: [])
    monkeypatch.setattr(
        admin_users,
        "add_admin_user",
        lambda *a, **k: saved.__setitem__("n", saved["n"] + 1) or (True, "nope", []),
    )
    admin_users.ensure_bootstrap_admin("secret-password")
    assert saved["n"] == 0


def _production_shaped_store() -> dict:
    """Same shape that was on the live row: full history, one open checkout."""
    assert HISTORY_LIMIT == 500
    history = [
        {
            "id": f"hist-{index:04d}",
            "action": "updated",
            "tool_no": "OLD",
            "at": "2026-01-01T00:00:00+00:00",
        }
        for index in range(HISTORY_LIMIT)
    ]
    return {
        "version": 38,
        "source": "Chrysler Tool Organization inventory",
        "tools": [
            {
                "id": "tool-c4150a",
                "tool_no": "C-4150A",
                "description": "BALL JOINT",
                "quantity": 1,
                "status": "active",
                "accountability": "located",
                "location": "SHELF A",
            },
            {
                "id": "tool-10198a",
                "tool_no": "10198A",
                "description": "VIBRATION DAMPENER HOLDER",
                "quantity": 1,
                "status": "active",
                "accountability": "signed_out",
                "location": "OUT",
            },
        ],
        "active_checkouts": [
            {
                "id": "f3a3fa92-9ae2-4dc1-a8d3-defb9a01c384",
                "tool_id": "tool-10198a",
                "tool_no": "10198A",
                "description": "VIBRATION DAMPENER HOLDER",
                "tech_name": "Gregory Phillips",
                "qty": 1,
                "checked_out_at": "2026-10-06T15:00:00+00:00",
                "ro_number": "583899",
                "note": "",
                "alert_dismissed_until": "2026-10-22",
            }
        ],
        "history": history,
    }


def test_checkout_at_history_cap_saves_and_trims(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)

    def fake_remote(data, *, expected_version=None):
        assert expected_version == 38
        assert data["version"] == 39
        return True, ""

    monkeypatch.setattr("lib.specialty_tools_storage._save_remote", fake_remote)
    data = _production_shaped_store()
    oldest_id = data["history"][-1]["id"]
    ok, msg = checkout_tool(data, "tool-c4150a", "Dale Potts", ro_number="599001")
    assert ok, msg
    ok, err = save_inventory(data)
    assert ok, err
    assert data["version"] == 39

    saved = json.loads(live.read_text())
    assert saved["version"] == 39
    assert [c["tech_name"] for c in saved["active_checkouts"]] == [
        "Gregory Phillips",
        "Dale Potts",
    ]
    assert saved["active_checkouts"][0]["alert_dismissed_until"] == "2026-10-22"
    assert saved["active_checkouts"][1]["ro_number"] == "599001"
    assert len(saved["history"]) == HISTORY_LIMIT
    assert saved["history"][0]["action"] == "checkout"
    assert saved["history"][0]["tech_name"] == "Dale Potts"
    assert saved["history"][0]["tool_no"] == "C-4150A"
    assert all(entry["id"] != oldest_id for entry in saved["history"])


def test_save_inventory_serializes_dates_and_rejects_other_types(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    captured = {}

    def fake_remote(data, *, expected_version=None):
        captured["data"] = data
        captured["expected_version"] = expected_version
        return True, ""

    monkeypatch.setattr("lib.specialty_tools_storage._save_remote", fake_remote)
    payload = {
        "version": 5,
        "source": "t",
        "tools": [],
        "active_checkouts": [
            {
                "id": "c1",
                "checked_out_at": date(2026, 10, 22),
                "alert_dismissed_until": datetime(
                    2026, 10, 22, 17, 54, tzinfo=timezone.utc
                ),
            }
        ],
        "history": [],
    }
    ok, err = save_inventory(payload)
    assert ok, err
    assert payload["version"] == 6
    checkout = captured["data"]["active_checkouts"][0]
    assert checkout["checked_out_at"] == "2026-10-22"
    assert checkout["alert_dismissed_until"].startswith("2026-10-22T17:54")
    on_disk = json.loads(live.read_text())
    assert on_disk["active_checkouts"][0]["checked_out_at"] == "2026-10-22"

    local_calls = {"n": 0}
    remote_calls = {"n": 0}
    monkeypatch.setattr(
        "lib.specialty_tools_storage._save_local",
        lambda _data: local_calls.__setitem__("n", local_calls["n"] + 1),
    )
    monkeypatch.setattr(
        "lib.specialty_tools_storage._save_remote",
        lambda _data, expected_version=None: remote_calls.__setitem__(
            "n", remote_calls["n"] + 1
        )
        or (True, ""),
    )
    bad = {
        "version": 7,
        "source": "t",
        "tools": [],
        "active_checkouts": [{"id": "c2", "tags": {"not", "json"}}],
        "history": [],
    }
    ok, err = save_inventory(bad)
    assert ok is False
    assert "set is not JSON serializable" in err
    assert bad["version"] == 7
    assert local_calls["n"] == 0
    assert remote_calls["n"] == 0
    assert json.loads(live.read_text())["version"] == 6


def _exception_text(at) -> str:
    chunks = []
    for exc in at.exception:
        chunks.append(str(getattr(exc.proto, "message", "") or ""))
        chunks.extend(list(exc.stack_trace or []))
    return "\n".join(chunks)


def _alert_text(at) -> str:
    return "\n".join(err.value for err in at.error)


def _open_checkout_app(monkeypatch, live: Path, store: dict):
    from streamlit.testing.v1 import AppTest

    live.write_text(json.dumps(store))
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: None)
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=90)
    at.session_state["tool_room_authenticated"] = True
    at.session_state["tool_room_role"] = "tech"
    at.session_state["nav_page"] = "Check Out"
    at.session_state["shop_tech_name"] = "Dale Potts"
    at.run()
    return at


def test_checkout_page_saves_without_widget_error(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    store = _production_shaped_store()
    at = _open_checkout_app(monkeypatch, live, store)
    assert len(at.exception) == 0, _exception_text(at)
    at.text_input(key="co_ro").set_value("599001")
    at.text_input(key="co_find").set_value("C-4150A")
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    at.button(key="co_btn").click()
    at.run()
    # AppTest follows st.rerun(), so this tree is the run after the save:
    # desk values applied, success flash shown, no widget exception.
    assert "cannot be modified" not in _exception_text(at)
    assert len(at.exception) == 0, _exception_text(at)
    assert at.text_input(key="co_ro").value == "599001"
    assert at.text_input(key="co_find").value == ""
    assert any("Dale Potts" in item.value for item in at.success)
    assert not any("Not saved" in item.value for item in at.error)

    saved = json.loads(live.read_text())
    assert [c["tech_name"] for c in saved["active_checkouts"]] == [
        "Gregory Phillips",
        "Dale Potts",
    ]
    assert saved["version"] == 39
    assert len(saved["history"]) == HISTORY_LIMIT
    assert saved["history"][0]["action"] == "checkout"
    assert saved["history"][0]["ro_number"] == "599001"


def test_failed_checkout_save_is_visible(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    store = _production_shaped_store()

    def fail_save(_data):
        return False, "database unreachable"

    monkeypatch.setattr("lib.specialty_tools_storage.save_inventory", fail_save)
    at = _open_checkout_app(monkeypatch, live, store)
    assert len(at.exception) == 0, _exception_text(at)
    at.text_input(key="co_ro").set_value("599001")
    at.text_input(key="co_find").set_value("C-4150A")
    at.run()
    at.button(key="co_btn").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    visible = _alert_text(at) + "\n" + "\n".join(item.value for item in at.success)
    assert "Not saved to the shop database" in visible
    assert "database unreachable" in visible
    assert not any("Checked out" in item.value for item in at.success)
    on_disk = json.loads(live.read_text())
    assert [c["tech_name"] for c in on_disk["active_checkouts"]] == ["Gregory Phillips"]
    assert on_disk["version"] == 38
    assert len(at.session_state["specialty_tools_data"]["active_checkouts"]) == 2
