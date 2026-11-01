#!/usr/bin/env python3
"""Copy the live specialty_tools row out of Supabase.

Reads store_key ``specialty_tools`` and:

1. Writes ``backups/specialty_tools.json`` (uploaded as a GitHub Actions artifact).
2. Inserts that same payload into ``public.specialty_tools_backups``.
3. Deletes backup rows older than 45 days.

The inventory row is only read. This script never updates or deletes it.

Secrets (environment variables, never arguments):

- SUPABASE_URL — project URL, same value as Streamlit's SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY — service_role key, same value as Streamlit's
  SUPABASE_KEY. The anon key cannot insert the backup row once RLS is on.

Exit codes: 0 saved, 2 secrets missing or still placeholders, 1 the read or
the backup-table insert failed. A prune failure is only a warning.

If the backup table does not exist yet, the JSON file is still written and
the process exits 1 so the missing migration is visible. Run
``supabase/migrations/20261101223000_app_errors_and_backups.sql`` in the
SQL editor first.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

STORE_KEY = "specialty_tools"
BACKUP_TABLE = "specialty_tools_backups"
SOURCE_TABLE = "specialty_tools_store"
RETAIN_DAYS = 45

Opener = Callable[..., Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw.lower().startswith("https://"):
        return False
    lowered = raw.lower()
    if any(marker in lowered for marker in ("your_project", "your-project", "example.supabase", "placeholder")):
        return False
    host = urllib.parse.urlparse(raw).hostname or ""
    return "." in host and host not in {"localhost", "127.0.0.1"}


def _valid_key(key: str) -> bool:
    raw = str(key or "").strip()
    if len(raw) < 20:
        return False
    lowered = raw.lower()
    if lowered.startswith("your_") or raw in {"your_service_role_key", "changeme"}:
        return False
    return True


def _secrets(env: Mapping[str, str]) -> tuple[str, str] | None:
    url = str(env.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = str(env.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if _valid_url(url) and _valid_key(key):
        return url, key
    return None


def _request(
    opener: Opener,
    *,
    method: str,
    url: str,
    key: str,
    base_host: str,
    payload: dict | None = None,
) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname != base_host or parsed.scheme != "https":
        raise RuntimeError("refusing to send the service key to a different host")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "specialty-tool-room-backup")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        req.add_header("Prefer", "return=minimal")
    try:
        resp = opener(req, timeout=60)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        path = urllib.parse.urlparse(getattr(exc, "url", url) or url).path
        raise RuntimeError(f"HTTP {exc.code} {method} {path}: {body}") from exc
    try:
        raw = resp.read()
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            close()
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _write_artifact(dest: Path, snapshot: dict) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


def backup(env: Mapping[str, str], opener: Opener, dest_dir: Path, *, now: datetime | None = None) -> int:
    """Snapshot specialty_tools. ``opener`` is ``urllib.request.OpenerDirector.open``."""
    stamp = now or _now()
    secrets = _secrets(env)
    if secrets is None:
        print(
            "Backup skipped: set GitHub Actions secrets SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY (the service_role key, not the anon key).",
            file=sys.stderr,
        )
        return 2
    base, key = secrets
    host = urllib.parse.urlparse(base).hostname or ""
    source_url = (
        f"{base}/rest/v1/{SOURCE_TABLE}"
        f"?store_key=eq.{urllib.parse.quote(STORE_KEY)}"
        "&select=store_key,data,updated_at"
    )
    try:
        loaded = _request(opener, method="GET", url=source_url, key=key, base_host=host)
    except Exception as exc:
        print(f"Could not read {STORE_KEY}: {exc}", file=sys.stderr)
        return 1
    if isinstance(loaded, list):
        row = loaded[0] if loaded else None
    elif isinstance(loaded, dict):
        row = loaded
    else:
        row = None
    if not isinstance(row, dict) or not isinstance(row.get("data"), dict):
        print(f"No {STORE_KEY} row to back up.", file=sys.stderr)
        return 1

    data = row["data"]
    snapshot = {
        "store_key": STORE_KEY,
        "source_updated_at": row.get("updated_at"),
        "backed_up_at": stamp.isoformat(),
        "data": data,
    }
    dest = dest_dir / "specialty_tools.json"
    _write_artifact(dest, snapshot)
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    tools = data.get("tools") if isinstance(data.get("tools"), list) else []
    checkouts = data.get("active_checkouts") if isinstance(data.get("active_checkouts"), list) else []
    print(
        f"Wrote {dest} version={data.get('version')} "
        f"tools={len(tools)} checkouts={len(checkouts)} sha256={digest}"
    )

    insert_url = f"{base}/rest/v1/{BACKUP_TABLE}"
    try:
        _request(
            opener,
            method="POST",
            url=insert_url,
            key=key,
            base_host=host,
            payload={
                "store_key": STORE_KEY,
                "data": data,
                "source_updated_at": row.get("updated_at"),
                "backed_up_at": stamp.isoformat(),
            },
        )
    except Exception as exc:
        print(
            f"JSON artifact is at {dest}, but inserting into {BACKUP_TABLE} failed: {exc}. "
            "Run supabase/migrations/20261101223000_app_errors_and_backups.sql "
            "in the Supabase SQL editor if that table does not exist yet.",
            file=sys.stderr,
        )
        return 1
    print(f"Inserted a row into {BACKUP_TABLE}.")

    cutoff = (stamp - timedelta(days=RETAIN_DAYS)).isoformat()
    delete_url = (
        f"{base}/rest/v1/{BACKUP_TABLE}"
        f"?backed_up_at=lt.{urllib.parse.quote(cutoff)}"
    )
    try:
        _request(opener, method="DELETE", url=delete_url, key=key, base_host=host)
    except Exception as exc:
        print(f"warning: snapshot stored but old backups were not pruned: {exc}", file=sys.stderr)
    return 0


def _opener() -> Opener:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError(f"refusing redirect to {newurl}")

    return urllib.request.build_opener(_NoRedirect).open


def main() -> int:
    return backup(os.environ, _opener(), Path("backups"))


if __name__ == "__main__":
    sys.exit(main())
