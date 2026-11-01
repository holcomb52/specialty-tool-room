"""Keep the suite off the shop database and off the repo's data files."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _never_touch_production_supabase(monkeypatch, tmp_path):
    """No test talks to Supabase unless it installs its own fake client.

    Empty credentials plus a patched client constructor. A test that needs a
    fake overrides ``lib.supabase_client.get_supabase`` after this fixture.
    """
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setattr("lib.supabase_client.get_supabase", lambda: None)

    import lib.admin_users as admin_users
    import lib.app_errors as app_errors
    import lib.specialty_tools_storage as storage

    monkeypatch.setattr(storage, "LIVE_PATH", tmp_path / "specialty_tools.json")
    monkeypatch.setattr(admin_users, "ADMIN_PATH", tmp_path / "admin_users.json")
    monkeypatch.setattr(app_errors, "LOCAL_LOG", tmp_path / "app_errors.jsonl")
