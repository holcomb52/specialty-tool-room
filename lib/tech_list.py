"""Technician name list for check-out dropdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

TECH_STORE_KEY = "technicians"
TABLE = "specialty_tools_store"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TECH_PATH = DATA_DIR / "technicians.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_name_sort_key(name: str) -> tuple[str, str]:
    """Sort by first name, then full name (case-insensitive)."""
    cleaned = str(name).strip()
    parts = cleaned.split()
    first = parts[0].lower() if parts else ""
    return (first, cleaned.lower())


def _normalize(names: List[str] | None) -> List[str]:
    cleaned = sorted(
        {str(n).strip() for n in (names or []) if str(n).strip()},
        key=_first_name_sort_key,
    )
    return cleaned


def _load_local() -> List[str]:
    if not TECH_PATH.exists():
        return []
    try:
        data = json.loads(TECH_PATH.read_text())
        return _normalize(data.get("technicians") if isinstance(data, dict) else data)
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def _save_local(names: List[str]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TECH_PATH.write_text(json.dumps({"technicians": names}, indent=2) + "\n")
    except OSError:
        pass


def _load_remote() -> List[str] | None:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return None
    try:
        result = (
            client.table(TABLE)
            .select("data")
            .eq("store_key", TECH_STORE_KEY)
            .limit(1)
            .execute()
        )
        if result.data:
            payload = result.data[0].get("data")
            if isinstance(payload, dict):
                return _normalize(payload.get("technicians"))
            if isinstance(payload, list):
                return _normalize(payload)
    except Exception:
        return None
    return None


def _save_remote(names: List[str]) -> Tuple[bool, str]:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return True, ""
    row: Dict[str, Any] = {
        "store_key": TECH_STORE_KEY,
        "data": {"technicians": names},
        "updated_at": _now_iso(),
    }
    try:
        existing = (
            client.table(TABLE)
            .select("store_key")
            .eq("store_key", TECH_STORE_KEY)
            .execute()
        )
        if existing.data:
            client.table(TABLE).update(
                {"data": row["data"], "updated_at": row["updated_at"]}
            ).eq("store_key", TECH_STORE_KEY).execute()
        else:
            client.table(TABLE).insert(row).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def load_technicians() -> List[str]:
    remote = _load_remote()
    if remote is not None:
        return remote
    return _load_local()


def save_technicians(names: List[str]) -> Tuple[bool, str]:
    cleaned = _normalize(names)
    _save_local(cleaned)
    ok, err = _save_remote(cleaned)
    if not ok:
        # Local save already succeeded — keep working offline / without Supabase
        return True, err or ""
    return True, ""


def add_technician(names: List[str], name: str) -> Tuple[bool, str, List[str]]:
    clean = str(name or "").strip()
    if not clean:
        return False, "Enter a technician name.", names
    existing = {n.lower() for n in names}
    if clean.lower() in existing:
        return False, f"{clean} is already on the list.", names
    updated = _normalize([*names, clean])
    ok, err = save_technicians(updated)
    if not ok:
        return False, err or "Could not save.", names
    return True, f"Added {clean}.", updated


def remove_technician(names: List[str], name: str) -> Tuple[bool, str, List[str]]:
    updated = [n for n in names if n != name]
    ok, err = save_technicians(updated)
    if not ok:
        return False, err or "Could not save.", names
    return True, f"Removed {name}.", updated
