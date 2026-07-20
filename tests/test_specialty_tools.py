"""Specialty tool room storage + checkout smoke tests."""

from __future__ import annotations

from lib.specialty_tools_storage import (
    _load_seed,
    add_tool,
    checkin_checkout,
    checkout_tool,
    inventory_stats,
    qty_available,
    search_tools,
)


def test_seed_inventory_loads():
    data = _load_seed()
    stats = inventory_stats(data)
    assert stats["total"] >= 1700
    assert stats["active"] > 1500
    assert stats["out_now"] == 0


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
