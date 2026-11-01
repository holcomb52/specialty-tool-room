"""CI, the migration, and password env vars stay pointed away from production."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_migration_defines_locked_down_error_and_backup_tables():
    files = list((ROOT / "supabase" / "migrations").glob("*app_errors*.sql"))
    assert len(files) == 1
    sql = files[0].read_text(encoding="utf-8").lower()
    for needle in (
        "create table if not exists public.app_errors",
        "occurred_at",
        "action text not null",
        "error text not null",
        "user_name",
        "enable row level security",
        "revoke all on table public.app_errors from anon, authenticated",
        "grant select, insert, update, delete on table public.app_errors to service_role",
        "create table if not exists public.specialty_tools_backups",
        "revoke all on table public.specialty_tools_backups from anon, authenticated",
    ):
        assert needle in sql
    assert "drop table" not in sql
    assert "alter table public.specialty_tools_store" not in sql
    assert "alter table specialty_tools_store" not in sql


def test_test_workflow_runs_on_push_and_pr_without_secrets():
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "push:" in text
    assert "pull_request:" in text
    assert "pytest" in text
    assert "${{ secrets" not in text


def test_backup_workflow_is_scheduled_and_names_the_secrets():
    text = (ROOT / ".github" / "workflows" / "backup-specialty-tools.yml").read_text(
        encoding="utf-8"
    )
    assert "schedule:" in text
    assert "workflow_dispatch:" in text
    assert "secrets.SUPABASE_URL" in text
    assert "secrets.SUPABASE_SERVICE_ROLE_KEY" in text
    assert "upload-artifact" in text


def test_smoke_workflow_is_manual_only():
    text = (ROOT / ".github" / "workflows" / "smoke-signed-in.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "push:" not in text
    assert "pull_request:" not in text
    assert "secrets.TOOL_ROOM_SMOKE_PASSWORD" in text
    assert "secrets.TOOL_ROOM_SMOKE_ROLE" in text


def test_password_env_overrides_streamlit_secrets(monkeypatch):
    monkeypatch.setenv("TECH_PASSWORD", "from-env")
    from lib.app_auth import _secret

    assert _secret("TECH_PASSWORD") == "from-env"
