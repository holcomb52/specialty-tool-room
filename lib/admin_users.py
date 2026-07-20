"""Admin user accounts for full tool-room access."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ADMIN_STORE_KEY = "admin_users"
TABLE = "specialty_tools_store"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ADMIN_PATH = DATA_DIR / "admin_users.json"

_HASH_ROUNDS = 120_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, salt: str | None = None) -> str:
    salt_val = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt_val.encode("utf-8"),
        _HASH_ROUNDS,
    )
    return f"pbkdf2_sha256${salt_val}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, salt, digest = str(stored).split("$", 2)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        _HASH_ROUNDS,
    ).hex()
    return secrets.compare_digest(check, digest)


def _normalize_users(users: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for raw in users or []:
        if not isinstance(raw, dict):
            continue
        username = str(raw.get("username") or "").strip().lower()
        if not username or username in seen:
            continue
        if not str(raw.get("password_hash") or "").strip():
            continue
        seen.add(username)
        cleaned.append(
            {
                "id": str(raw.get("id") or uuid.uuid4()),
                "name": str(raw.get("name") or username).strip() or username,
                "username": username,
                "password_hash": str(raw.get("password_hash")),
                "created_at": str(raw.get("created_at") or _now_iso()),
            }
        )
    cleaned.sort(key=lambda u: (u["name"].split()[0].lower(), u["name"].lower()))
    return cleaned


def _load_local() -> List[Dict[str, Any]]:
    if not ADMIN_PATH.exists():
        return []
    try:
        data = json.loads(ADMIN_PATH.read_text())
        return _normalize_users(data.get("users") if isinstance(data, dict) else data)
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def _save_local(users: List[Dict[str, Any]]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ADMIN_PATH.write_text(
            json.dumps({"users": users}, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def _load_remote() -> List[Dict[str, Any]] | None:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return None
    try:
        result = (
            client.table(TABLE)
            .select("data")
            .eq("store_key", ADMIN_STORE_KEY)
            .limit(1)
            .execute()
        )
        if result.data:
            payload = result.data[0].get("data")
            if isinstance(payload, dict):
                return _normalize_users(payload.get("users"))
            if isinstance(payload, list):
                return _normalize_users(payload)
    except Exception:
        return None
    return None


def _save_remote(users: List[Dict[str, Any]]) -> Tuple[bool, str]:
    from lib.supabase_client import get_supabase

    client = get_supabase()
    if not client:
        return True, ""
    row: Dict[str, Any] = {
        "store_key": ADMIN_STORE_KEY,
        "data": {"users": users},
        "updated_at": _now_iso(),
    }
    try:
        existing = (
            client.table(TABLE)
            .select("store_key")
            .eq("store_key", ADMIN_STORE_KEY)
            .execute()
        )
        if existing.data:
            client.table(TABLE).update(
                {"data": row["data"], "updated_at": row["updated_at"]}
            ).eq("store_key", ADMIN_STORE_KEY).execute()
        else:
            client.table(TABLE).insert(row).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def load_admin_users() -> List[Dict[str, Any]]:
    remote = _load_remote()
    if remote is not None:
        return remote
    return _load_local()


def save_admin_users(users: List[Dict[str, Any]]) -> Tuple[bool, str]:
    cleaned = _normalize_users(users)
    _save_local(cleaned)
    ok, err = _save_remote(cleaned)
    if not ok:
        return True, err or ""
    return True, ""


def find_admin_by_username(
    users: List[Dict[str, Any]], username: str
) -> Optional[Dict[str, Any]]:
    needle = str(username or "").strip().lower()
    if not needle:
        return None
    for user in users:
        if user.get("username") == needle:
            return user
    return None


def authenticate_admin(
    username: str, password: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    users = load_admin_users()
    user = find_admin_by_username(users, username)
    if not user:
        return False, "Incorrect username or password.", None
    if not verify_password(password, str(user.get("password_hash") or "")):
        return False, "Incorrect username or password.", None
    return True, f"Welcome, {user.get('name')}.", user


def add_admin_user(
    users: List[Dict[str, Any]],
    *,
    name: str,
    username: str,
    password: str,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    clean_name = str(name or "").strip()
    clean_user = str(username or "").strip().lower()
    clean_pw = str(password or "")
    if not clean_name:
        return False, "Enter the admin's full name.", users
    if not clean_user:
        return False, "Enter a username.", users
    if " " in clean_user:
        return False, "Username cannot contain spaces.", users
    if len(clean_pw) < 6:
        return False, "Password must be at least 6 characters.", users
    if find_admin_by_username(users, clean_user):
        return False, f"Username '{clean_user}' is already taken.", users

    updated = _normalize_users(
        [
            *users,
            {
                "id": str(uuid.uuid4()),
                "name": clean_name,
                "username": clean_user,
                "password_hash": hash_password(clean_pw),
                "created_at": _now_iso(),
            },
        ]
    )
    ok, err = save_admin_users(updated)
    if not ok:
        return False, err or "Could not save.", users
    return True, f"Added admin {clean_name} ({clean_user}).", updated


def remove_admin_user(
    users: List[Dict[str, Any]], username: str
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    needle = str(username or "").strip().lower()
    if not needle:
        return False, "Select an admin to remove.", users
    if len(users) <= 1:
        return False, "You must keep at least one admin account.", users
    updated = [u for u in users if u.get("username") != needle]
    if len(updated) == len(users):
        return False, "Admin not found.", users
    ok, err = save_admin_users(updated)
    if not ok:
        return False, err or "Could not save.", users
    return True, f"Removed admin '{needle}'.", updated


def ensure_bootstrap_admin(app_password: str) -> None:
    """Create a starter admin from APP_PASSWORD when no admins exist yet."""
    if load_admin_users():
        return
    pw = str(app_password or "").strip()
    if not pw:
        return
    add_admin_user(
        [],
        name="Administrator",
        username="admin",
        password=pw,
    )
