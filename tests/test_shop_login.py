"""Shop login must work when Streamlit secrets do not, or nothing is saved."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from lib.app_auth import _manager_password, _tech_password


class _BrokenSecrets:
    def get(self, name, default=""):
        raise FileNotFoundError("secrets.toml was not found")

    def __getitem__(self, name):
        raise FileNotFoundError("secrets.toml was not found")


class _FileSecrets(dict):
    def get(self, name, default=None):
        return super().get(name, default)


def _state(at, key, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _exception_text(at) -> str:
    chunks = []
    for exc in at.exception:
        chunks.append(str(getattr(exc.proto, "message", "") or ""))
        chunks.extend(list(exc.stack_trace or []))
    return "\n".join(chunks)


def _live_store() -> dict:
    """Same shape as the live row: ISO timestamps, ro 'shrug', newest history first."""
    return {
        "version": 42,
        "source": "2017 NEW SMYRNA BEACH CHRYSLER TOOL INV.xls",
        "tools": [
            {
                "id": "tool-free",
                "tool_no": "C-4150A",
                "description": "BALL JOINT",
                "quantity": 1,
                "status": "active",
                "location": "SHELF A",
                "accountability": "located",
            },
            {
                "id": "af58d303-c1e1-45d8-9079-a859daf82061",
                "tool_no": "2074501080",
                "description": "SCOPE KIT",
                "quantity": 1,
                "status": "active",
                "location": "SHELF D",
                "accountability": "signed_out",
            },
        ],
        "active_checkouts": [
            {
                "id": "18de35d4-20dc-4338-89f3-5b3848353056",
                "qty": 1,
                "note": "",
                "tool_id": "af58d303-c1e1-45d8-9079-a859daf82061",
                "tool_no": "2074501080",
                "ro_number": "shrug",
                "tech_name": "Armand Liebes",
                "description": "SCOPE KIT",
                "checked_out_at": "2026-10-27T12:32:31.763494+00:00",
            }
        ],
        "history": [
            {
                "id": "hist-new",
                "action": "checkout",
                "tool_no": "2074501080",
                "tech_name": "Armand Liebes",
                "ro_number": "shrug",
                "at": "2026-10-27T12:32:31.763494+00:00",
            },
            {
                "id": "hist-old",
                "action": "added",
                "tool_no": "OLD",
                "at": "2026-01-01T00:00:00+00:00",
            },
        ],
    }


def test_password_comes_from_env_when_secrets_file_is_missing(monkeypatch):
    monkeypatch.setattr(st, "secrets", _BrokenSecrets())
    monkeypatch.setenv("TECH_PASSWORD", "floor-secret")
    monkeypatch.setenv("APP_PASSWORD", "manager-secret")
    assert _tech_password() == "floor-secret"
    assert _manager_password() == "manager-secret"


def test_password_still_reads_secrets_when_env_is_empty(monkeypatch):
    monkeypatch.setattr(st, "secrets", _FileSecrets(TECH_PASSWORD="from-file"))
    monkeypatch.delenv("TECH_PASSWORD", raising=False)
    assert _tech_password() == "from-file"


def test_tech_can_check_out_and_check_in_when_secrets_file_is_missing(
    tmp_path, monkeypatch
):
    """The shop PC signs in with TECH_PASSWORD and then loans a tool.

    On 2026-11-13 the cloud app still loaded inventory, but the technician
    password was blank because only ``st.secrets`` was consulted. Sign-in
    never finished, so check-out and check-in never called save.
    """
    live = tmp_path / "specialty_tools.json"
    live.write_text(json.dumps(_live_store()))
    monkeypatch.setattr("lib.specialty_tools_storage.LIVE_PATH", live)
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: None)
    monkeypatch.setattr(st, "secrets", _BrokenSecrets())
    monkeypatch.setenv("TECH_PASSWORD", "floor-secret")
    monkeypatch.delenv("APP_PASSWORD", raising=False)

    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=90)
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    assert _state(at, "tool_room_authenticated") is not True

    at.text_input(key="tool_room_tech_password").set_value("floor-secret")
    signed_in = False
    for button in at.button:
        if button.label == "Sign in as Technician":
            button.click()
            signed_in = True
            break
    assert signed_in, [b.label for b in at.button]
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    assert _state(at, "tool_room_role") == "tech"
    assert _state(at, "tool_room_authenticated") is True

    at.button(key="co_name_Dale_Potts").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    at.text_input(key="co_ro").set_value("599100")
    at.text_input(key="co_find").set_value("C-4150A")
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    at.button(key="co_btn").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    assert any("Dale Potts" in item.value for item in at.success)

    saved = json.loads(live.read_text())
    assert saved["version"] == 43
    assert any(c["tech_name"] == "Dale Potts" for c in saved["active_checkouts"])
    assert saved["history"][0]["action"] == "checkout"
    assert saved["history"][0]["ro_number"] == "599100"

    at.button(key="desk_nav_Check_In").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    # Dale's new loan is the default "My tools" list. Check that in, then the
    # older shrug loan that was already on the live row.
    at.button(key="ci_btn").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    assert any("Checked in" in item.value for item in at.success)

    at.button(key="ci_filter_all").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)
    at.button(key="ci_pick_18de35d4-20dc-4338-89f3-5b3848353056").click()
    at.run()
    at.button(key="ci_btn").click()
    at.run()
    assert len(at.exception) == 0, _exception_text(at)

    saved = json.loads(live.read_text())
    assert saved["active_checkouts"] == []
    assert saved["history"][0]["action"] == "checkin"
    assert saved["history"][0]["ro_number"] == "shrug"
    assert saved["history"][0]["tool_no"] == "2074501080"
    assert saved["version"] == 45
