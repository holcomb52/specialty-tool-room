"""Failed shop-database saves are recorded without changing the on-screen wording."""

from __future__ import annotations

import json
from datetime import datetime

import lib.app_errors as app_errors
from lib.app_errors import prepend_errors, record_save_failure
from lib.specialty_tools_storage import save_inventory


class _Result:
    def __init__(self, data):
        self.data = data


class FakeClient:
    """In-memory Supabase. Inventory updates fail; error logging is configurable."""

    def __init__(self):
        self.fail_tables = set()
        self.errors = []
        self.store_rows = {}
        self.calls = []

    def table(self, name):
        return _Query(self, name)


class _Query:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.op = None
        self.payload = None
        self.filters = {}

    def select(self, *args, **kwargs):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        self.client.calls.append(
            (self.name, self.op, self.filters.get("store_key"))
        )
        if self.name in self.client.fail_tables or (
            self.name == "specialty_tools_store"
            and self.op == "update"
            and self.filters.get("store_key") == "specialty_tools"
        ):
            raise RuntimeError(
                "database unreachable"
                if self.filters.get("store_key") == "specialty_tools"
                else f"{self.name} unavailable"
            )
        if self.name == "app_errors" and self.op == "insert":
            self.client.errors.append(self.payload)
            return _Result([self.payload])
        if self.name == "specialty_tools_store" and self.op == "select":
            key = self.filters.get("store_key")
            if key == "specialty_tools":
                return _Result([{"store_key": key, "data": {"version": 3}}])
            if key in self.client.store_rows:
                return _Result([{"store_key": key, "data": self.client.store_rows[key]}])
            return _Result([])
        if self.name == "specialty_tools_store" and self.op == "update":
            self.client.store_rows[self.filters["store_key"]] = self.payload["data"]
            return _Result([self.payload])
        if self.name == "specialty_tools_store" and self.op == "insert":
            key = self.payload["store_key"]
            if key == "specialty_tools":
                raise AssertionError("refusing to insert the live inventory row")
            self.client.store_rows[key] = self.payload["data"]
            return _Result([self.payload])
        raise AssertionError((self.name, self.op))


def _inventory():
    return {
        "version": 3,
        "source": "t",
        "tools": [],
        "active_checkouts": [],
        "history": [],
    }


def test_remote_save_failure_is_inserted_into_app_errors(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: client)
    data = _inventory()
    ok, err = save_inventory(data, action="checkout", user="Dale Potts")
    assert ok is False
    assert err == "database unreachable"
    assert data["version"] == 3
    assert len(client.errors) == 1
    row = client.errors[0]
    assert row["action"] == "checkout"
    assert row["user_name"] == "Dale Potts"
    assert row["error"] == "database unreachable"
    datetime.fromisoformat(row["occurred_at"])
    assert row["detail"]["store_key"] == "specialty_tools"
    assert row["detail"]["version"] == 3
    assert "specialty_tools" not in client.store_rows
    assert not app_errors.LOCAL_LOG.exists()


def test_save_failure_uses_store_row_when_error_table_is_missing(monkeypatch):
    client = FakeClient()
    client.fail_tables.add("app_errors")
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: client)
    first = record_save_failure(action="checkin", error="database unreachable", user="Charles Hinxman")
    second = record_save_failure(action="checkout", error="still down", user="Dale Potts")
    assert first == "store"
    assert second == "store"
    stored = client.store_rows["app_errors"]["errors"]
    assert [item["action"] for item in stored] == ["checkout", "checkin"]
    assert stored[0]["user_name"] == "Dale Potts"
    assert stored[1]["error"] == "database unreachable"
    datetime.fromisoformat(stored[0]["occurred_at"])
    assert "specialty_tools" not in client.store_rows
    assert not any(
        call[0] == "specialty_tools_store" and call[2] == "specialty_tools" and call[1] != "select"
        for call in client.calls
    )


def test_save_failure_falls_back_to_local_log_when_cloud_logging_fails(monkeypatch):
    monkeypatch.setattr(
        "lib.specialty_tools_storage._save_remote",
        lambda data, expected_version=None: (False, "network down"),
    )
    data = _inventory()
    ok, err = save_inventory(data, action="checkin", user="Charles Hinxman")
    assert ok is False
    assert "network down" in err
    lines = app_errors.LOCAL_LOG.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["action"] == "checkin"
    assert row["user_name"] == "Charles Hinxman"
    assert "network down" in row["error"]
    datetime.fromisoformat(row["occurred_at"])


def test_successful_save_and_silent_retry_do_not_log(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "lib.specialty_tools_storage._save_remote",
        lambda data, expected_version=None: (True, ""),
    )
    monkeypatch.setattr(
        "lib.specialty_tools_storage.LIVE_PATH", tmp_path / "live.json"
    )
    ok, err = save_inventory(_inventory(), action="checkout", user="Dale Potts")
    assert ok, err
    assert not app_errors.LOCAL_LOG.exists()

    monkeypatch.setattr(
        "lib.specialty_tools_storage._save_remote",
        lambda data, expected_version=None: (False, "database unreachable"),
    )
    ok, err = save_inventory(
        _inventory(), action="retry_unsaved", user="Dale Potts", log_failure=False
    )
    assert ok is False
    assert not app_errors.LOCAL_LOG.exists()


def test_unserializable_save_is_logged_and_not_sent(monkeypatch):
    called = {"remote": 0}

    def _remote(data, expected_version=None):
        called["remote"] += 1
        return True, ""

    monkeypatch.setattr("lib.specialty_tools_storage._save_remote", _remote)
    bad = _inventory()
    bad["active_checkouts"] = [{"id": "c2", "tags": {"not", "json"}}]
    ok, err = save_inventory(bad, action="checkout", user="Dale Potts")
    assert ok is False
    assert "not JSON serializable" in err
    assert called["remote"] == 0
    row = json.loads(app_errors.LOCAL_LOG.read_text(encoding="utf-8"))
    assert row["action"] == "checkout"
    assert row["user_name"] == "Dale Potts"


def test_error_store_keeps_newest_two_hundred():
    existing = [{"action": f"old-{index}"} for index in range(200)]
    capped = prepend_errors(existing, {"action": "newest"}, limit=200)
    assert len(capped) == 200
    assert capped[0]["action"] == "newest"
    assert capped[-1]["action"] == "old-198"
