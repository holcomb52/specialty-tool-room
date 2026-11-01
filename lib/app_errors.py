"""Durable record of a failed save to the shop database.

The on-screen message stays "Not saved…". This module is the copy Bruce can
look up later. It never raises: a logging failure must not hide the original
save error or turn into a second traceback on the shop PC.

Where the row goes, in order:

1. ``public.app_errors`` after ``supabase/migrations/*app_errors*.sql`` has
   been run in the SQL editor.
2. Until that table exists, a jsonb row in the existing
   ``specialty_tools_store`` table under ``store_key = 'app_errors'``.
   That table is already in production, so a failed save is still recorded
   before the migration is applied. This never writes ``specialty_tools``.
3. ``data/app_errors.jsonl`` if both cloud writes fail. Streamlit Cloud's
   disk is wiped on restart, so this file is only a last resort.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

STORE_TABLE = "specialty_tools_store"
APP_ERRORS_TABLE = "app_errors"
APP_ERRORS_STORE_KEY = "app_errors"
STORE_ERROR_LIMIT = 200

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_LOG = DATA_DIR / "app_errors.jsonl"

_MAX_ERROR_CHARS = 4000
_MAX_ACTION_CHARS = 200
_MAX_USER_CHARS = 200


def current_actor() -> str:
    """Signed-in person, or ``unknown`` outside a Streamlit run."""
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            get_script_run_ctx,
        )

        if get_script_run_ctx(suppress_warning=True) is None:
            return "unknown"
        import streamlit as st

        role = str(st.session_state.get("tool_room_role") or "")
        tech = str(st.session_state.get("shop_tech_name") or "").strip()
        admin_name = str(st.session_state.get("tool_room_admin_name") or "").strip()
        admin_user = str(st.session_state.get("tool_room_admin_username") or "").strip()
    except Exception:
        return "unknown"
    return _format_actor(role, tech, admin_name, admin_user)


def _format_actor(role: str, tech: str, admin_name: str, admin_user: str) -> str:
    if role == "tech":
        return tech or "Technician"
    if role == "admin":
        if admin_name and admin_user:
            return f"{admin_name} ({admin_user})"
        return admin_name or admin_user or "Admin"
    if role == "manager":
        return "Manager"
    return tech or admin_name or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_row(
    *,
    action: str,
    error: str,
    user: str,
    detail: Dict[str, Any] | None,
) -> Dict[str, Any]:
    extra = detail if isinstance(detail, dict) else {}
    safe_detail: Dict[str, Any] = {}
    for key, value in extra.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe_detail[str(key)] = value
        else:
            safe_detail[str(key)] = str(value)
    actor = str(user or "").strip() or current_actor()
    return {
        "occurred_at": _now_iso(),
        "action": str(action or "save")[:_MAX_ACTION_CHARS],
        "error": str(error or "")[:_MAX_ERROR_CHARS],
        "user_name": (actor or "unknown")[:_MAX_USER_CHARS],
        "detail": safe_detail,
    }


def record_save_failure(
    *,
    action: str,
    error: str,
    user: str = "",
    detail: Dict[str, Any] | None = None,
) -> str:
    """Persist one failed save. Returns ``table``, ``store``, ``local``, or ``unrecorded``."""
    row = _error_row(action=action, error=error, user=user, detail=detail)
    try:
        if _insert_error_table(row):
            return "table"
        if _append_error_store(row):
            return "store"
    except Exception:
        pass
    try:
        _append_local(row)
    except Exception:
        return "unrecorded"
    return "local"


def prepend_errors(
    existing: List[Any] | None, row: Dict[str, Any], *, limit: int = STORE_ERROR_LIMIT
) -> List[Dict[str, Any]]:
    """Newest first, capped, dropping non-dict leftovers."""
    out: List[Dict[str, Any]] = [row]
    for item in existing or []:
        if len(out) >= limit:
            break
        if isinstance(item, dict):
            out.append(item)
    return out[:limit]


def _insert_error_table(row: Dict[str, Any]) -> bool:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return False
    try:
        client.table(APP_ERRORS_TABLE).insert(
            {
                "occurred_at": row["occurred_at"],
                "action": row["action"],
                "error": row["error"],
                "user_name": row["user_name"],
                "detail": row["detail"],
            }
        ).execute()
    except Exception:
        return False
    return True


def _append_error_store(row: Dict[str, Any]) -> bool:
    """Append to store_key ``app_errors`` only. Never touches ``specialty_tools``."""
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return False
    if APP_ERRORS_STORE_KEY == "specialty_tools":
        return False
    try:
        existing = (
            client.table(STORE_TABLE)
            .select("data")
            .eq("store_key", APP_ERRORS_STORE_KEY)
            .limit(1)
            .execute()
        )
        previous: List[Any] = []
        found = bool(getattr(existing, "data", None))
        if found:
            payload = existing.data[0].get("data")
            if isinstance(payload, dict) and isinstance(payload.get("errors"), list):
                previous = payload["errors"]
        body = {
            "data": {"errors": prepend_errors(previous, row)},
            "updated_at": row["occurred_at"],
        }
        if found:
            (
                client.table(STORE_TABLE)
                .update(body)
                .eq("store_key", APP_ERRORS_STORE_KEY)
                .execute()
            )
        else:
            client.table(STORE_TABLE).insert(
                {"store_key": APP_ERRORS_STORE_KEY, **body}
            ).execute()
    except Exception:
        return False
    return True


def _append_local(row: Dict[str, Any]) -> None:
    LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")
