"""Daily backup reads specialty_tools and writes a copy. It does not update that row."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.backup_specialty_tools import _request, backup

URL = "https://tool-room-backup.invalid"
KEY = "test-service-role-key-not-real-000000"
INVENTORY = {
    "version": 41,
    "source": "live",
    "tools": [{"id": "t1", "tool_no": "C-4150A"}],
    "active_checkouts": [{"id": "c1", "tech_name": "Dale Potts"}],
    "history": [],
}


class _Resp:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self._body

    def close(self):
        return None


def _env():
    return {"SUPABASE_URL": URL, "SUPABASE_SERVICE_ROLE_KEY": KEY}


def test_backup_writes_artifact_and_posts_backup_table_only(tmp_path):
    requests = []

    def opener(req, timeout=60):
        requests.append(req)
        method = req.get_method()
        if method == "GET":
            body = json.dumps(
                [
                    {
                        "store_key": "specialty_tools",
                        "data": INVENTORY,
                        "updated_at": "2026-10-31T12:00:00+00:00",
                    }
                ]
            )
            return _Resp(body)
        if method == "DELETE":
            raise RuntimeError("prune failed on purpose")
        return _Resp(b"")

    code = backup(
        _env(),
        opener,
        tmp_path,
        now=datetime(2026, 11, 1, 11, 15, tzinfo=timezone.utc),
    )
    assert code == 0
    methods = [req.get_method() for req in requests]
    assert methods == ["GET", "POST", "DELETE"]
    assert "specialty_tools_store" in requests[0].full_url
    assert requests[0].full_url.startswith(URL + "/")
    assert "specialty_tools_backups" in requests[1].full_url
    assert "specialty_tools_store" not in requests[1].full_url
    assert "specialty_tools_backups" in requests[2].full_url
    assert requests[1].get_header("Authorization") == f"Bearer {KEY}"
    assert requests[1].get_header("Apikey") == KEY
    posted = json.loads(requests[1].data.decode("utf-8"))
    assert posted["store_key"] == "specialty_tools"
    assert posted["data"] == INVENTORY
    assert posted["source_updated_at"] == "2026-10-31T12:00:00+00:00"

    artifact = json.loads((tmp_path / "specialty_tools.json").read_text(encoding="utf-8"))
    assert artifact["data"] == INVENTORY
    assert artifact["backed_up_at"].startswith("2026-11-01T11:15")
    assert KEY not in (tmp_path / "specialty_tools.json").read_text(encoding="utf-8")


def test_backup_keeps_the_artifact_when_the_table_insert_fails(tmp_path):
    def opener(req, timeout=60):
        if req.get_method() == "GET":
            return _Resp(json.dumps([{"store_key": "specialty_tools", "data": INVENTORY, "updated_at": None}]))
        raise RuntimeError("relation specialty_tools_backups does not exist")

    code = backup(_env(), opener, tmp_path)
    assert code == 1
    assert json.loads((tmp_path / "specialty_tools.json").read_text())["data"]["version"] == 41


def test_backup_does_not_call_the_network_without_secrets(tmp_path):
    def opener(req, timeout=60):
        raise AssertionError(f"unexpected request {req.full_url}")

    assert backup({}, opener, tmp_path) == 2
    assert backup(
        {"SUPABASE_URL": "https://YOUR_PROJECT.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": KEY},
        opener,
        tmp_path,
    ) == 2
    assert not (tmp_path / "specialty_tools.json").exists()


def test_request_refuses_to_send_the_key_to_another_host():
    def opener(req, timeout=60):
        raise AssertionError("sent")

    try:
        _request(
            opener,
            method="GET",
            url="https://evil.example/rest/v1/specialty_tools_store",
            key=KEY,
            base_host="tool-room-backup.invalid",
        )
    except RuntimeError as exc:
        assert "different host" in str(exc)
    else:
        raise AssertionError("cross-host request was allowed")
