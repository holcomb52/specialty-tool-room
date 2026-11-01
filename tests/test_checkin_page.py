"""Check In page: My tools data, check-in save, and the PR #2 KeyError."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import lib.app_errors as app_errors


def _exception_text(at) -> str:
    chunks = []
    for exc in at.exception:
        chunks.append(str(getattr(exc.proto, "message", "") or ""))
        chunks.extend(list(exc.stack_trace or []))
    return "\n".join(chunks)


def _alert_text(at) -> str:
    return "\n".join(item.value for item in at.error)


def _store(*, charles_id="ck-charles"):
    recent = datetime.now(timezone.utc).isoformat()
    charles = {
        "tool_id": "t-charles",
        "tool_no": "T-HINX",
        "description": "HINGE",
        "tech_name": "Charles Hinxman",
        "qty": 1,
        "checked_out_at": recent,
        "ro_number": "RO-1",
        "note": "",
    }
    if charles_id is not None:
        charles["id"] = charles_id
    return {
        "version": 10,
        "source": "test",
        "tools": [
            {
                "id": "t-charles",
                "tool_no": "T-HINX",
                "description": "HINGE",
                "quantity": 2,
                "status": "active",
                "accountability": "signed_out",
            },
            {
                "id": "t-dale",
                "tool_no": "T-DALE",
                "description": "PULLER",
                "quantity": 1,
                "status": "active",
                "accountability": "signed_out",
            },
        ],
        "active_checkouts": [
            charles,
            {
                "id": "ck-dale",
                "tool_id": "t-dale",
                "tool_no": "T-DALE",
                "description": "PULLER",
                "tech_name": "Dale Potts",
                "qty": 1,
                "checked_out_at": recent,
                "ro_number": "RO-2",
                "note": "",
            },
        ],
        "history": [],
    }


def _open_checkin(monkeypatch, live: Path, store: dict):
    from streamlit.testing.v1 import AppTest

    live.write_text(json.dumps(store))
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: None)
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=90)
    at.session_state["tool_room_authenticated"] = True
    at.session_state["tool_room_role"] = "tech"
    at.session_state["nav_page"] = "Check In"
    at.session_state["shop_tech_name"] = "Charles Hinxman"
    at.run()
    return at


def test_my_tools_tab_checks_in_only_that_tech(tmp_path, monkeypatch):
    """My tools is the stored checkout, including id, and Check in saves it.

    Regression for PR #2: the page used to build ``{c["id"] for c in ...}``
    from report rows and die with KeyError before the button could work.
    """
    live = tmp_path / "specialty_tools.json"
    at = _open_checkin(monkeypatch, live, _store())
    assert len(at.exception) == 0, _exception_text(at)
    assert any(button.label == "My tools (1)" for button in at.button)
    assert any(button.label == "Everyone (2)" for button in at.button)
    assert at.button(key="ci_pick_ck-charles").label.startswith("T-HINX")
    assert all(button.key != "ci_pick_ck-dale" for button in at.button)

    at.button(key="ci_btn").click()
    at.run()
    assert "cannot be modified" not in _exception_text(at)
    assert len(at.exception) == 0, _exception_text(at)
    assert any("Checked in" in item.value and "T-HINX" in item.value for item in at.success)
    assert not any("Not saved" in item.value for item in at.error)

    saved = json.loads(live.read_text())
    assert [checkout["tech_name"] for checkout in saved["active_checkouts"]] == ["Dale Potts"]
    assert saved["version"] == 11
    assert saved["history"][0]["action"] == "checkin"
    assert saved["history"][0]["tech_name"] == "Charles Hinxman"
    assert saved["history"][0]["tool_no"] == "T-HINX"


def test_my_tools_repairs_a_checkout_stored_without_id(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"
    at = _open_checkin(monkeypatch, live, _store(charles_id=None))
    assert len(at.exception) == 0, _exception_text(at)
    picked = [button for button in at.button if str(button.key or "").startswith("ci_pick_")]
    assert len(picked) == 1
    assert "repaired-" in str(picked[0].key)
    at.button(key="ci_btn").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    saved = json.loads(live.read_text())
    assert [checkout["tech_name"] for checkout in saved["active_checkouts"]] == ["Dale Potts"]


def test_failed_checkin_save_is_visible_and_logged(tmp_path, monkeypatch):
    live = tmp_path / "specialty_tools.json"

    def fail_remote(data, expected_version=None):
        return False, "database unreachable"

    monkeypatch.setattr("lib.specialty_tools_storage._save_remote", fail_remote)
    at = _open_checkin(monkeypatch, live, _store())
    assert len(at.exception) == 0, _exception_text(at)
    at.button(key="ci_btn").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    visible = _alert_text(at)
    assert "Not saved to the shop database" in visible
    assert "database unreachable" in visible
    assert not any("Checked in" in item.value for item in at.success)

    lines = app_errors.LOCAL_LOG.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["action"] == "checkin"
    assert row["user_name"] == "Charles Hinxman"
    assert row["error"] == "database unreachable"
    assert row["occurred_at"]
