"""The signed-in smoke script is opt-in and cannot write the shop database."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.smoke_signed_in import ReadOnlyClient, SmokeWriteBlocked, main

ROOT = Path(__file__).resolve().parent.parent


class _InnerTable:
    def select(self, *args, **kwargs):
        return ("select", args)

    def insert(self, *args, **kwargs):
        raise AssertionError("inner insert ran")

    def update(self, *args, **kwargs):
        raise AssertionError("inner update ran")


class _InnerClient:
    def table(self, name):
        return _InnerTable()


def test_read_only_client_allows_select_and_blocks_writes():
    log = []
    client = ReadOnlyClient(_InnerClient(), log)
    assert client.table("specialty_tools_store").select("data") == ("select", ("data",))
    for op in ("insert", "update", "upsert", "delete"):
        try:
            getattr(client.table("specialty_tools_store"), op)({})
        except SmokeWriteBlocked:
            pass
        else:
            raise AssertionError(f"{op} was allowed")
    assert [item["op"] for item in log] == ["insert", "update", "upsert", "delete"]
    assert all(item["table"] == "specialty_tools_store" for item in log)


def test_smoke_script_skips_unless_opted_in(monkeypatch, capsys):
    monkeypatch.delenv("TOOL_ROOM_SMOKE", raising=False)
    assert main() == 0
    assert "TOOL_ROOM_SMOKE=1" in capsys.readouterr().out


def test_smoke_script_opens_each_tech_tab_without_writing(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    original = {
        "version": 4,
        "source": "smoke",
        "tools": [
            {
                "id": "t1",
                "tool_no": "T-1",
                "description": "SMOKE TOOL",
                "quantity": 1,
                "status": "active",
                "location": "SHELF A",
            }
        ],
        "active_checkouts": [],
        "history": [],
    }
    live.write_text(json.dumps(original))
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    techs = ROOT / "data" / "technicians.json"
    before_techs = techs.read_bytes()
    monkeypatch.setenv("TOOL_ROOM_SMOKE", "1")
    monkeypatch.setenv("TOOL_ROOM_SMOKE_ROLE", "technician")
    monkeypatch.setenv("TOOL_ROOM_SMOKE_PASSWORD", "smoke-secret")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    assert main() == 0
    assert json.loads(live.read_text()) == original
    assert techs.read_bytes() == before_techs
    assert not (ROOT / "data" / "admin_users.json").exists()
    assert not (ROOT / "data" / "app_errors.jsonl").exists()
