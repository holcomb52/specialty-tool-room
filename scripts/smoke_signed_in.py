#!/usr/bin/env python3
"""Opt-in signed-in smoke test. Read-only.

Logs in through the real sign-in form and opens every tab that role can see.
Any exception is printed with the page name. The process exits 1 when a page
raises, when a checkout appears or disappears, or when the app tries to write
to Supabase.

It does not click Check out, Check in, Save, Import, Add, or Delete.

This does not run in the default test workflow. Set TOOL_ROOM_SMOKE=1.

Environment variables
---------------------
TOOL_ROOM_SMOKE
    Set to ``1`` to run. Anything else prints a skip line and exits 0.

TOOL_ROOM_SMOKE_ROLE
    ``technician`` (or ``tech``), ``admin``, or ``manager``.

TOOL_ROOM_SMOKE_PASSWORD
    Password typed into the sign-in form. For technician this is the shared
    TECH_PASSWORD. For manager it is APP_PASSWORD. For admin it is that
    admin account's password. The script sets TECH_PASSWORD or APP_PASSWORD
    in this process only so the local app accepts it. It does not change
    Streamlit Cloud secrets.

TOOL_ROOM_SMOKE_USERNAME
    Required when the role is admin.

SUPABASE_URL and SUPABASE_KEY
    Optional. When they are the real project values, each tab reads the live
    catalog. Writes are refused. Leave them unset to open tabs against the
    local / seed catalog instead.

Exit codes: 0 passed or skipped, 2 configuration error, 1 a page failed,
a checkout list changed, or a cloud write was attempted.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROLE_ALIASES = {
    "tech": "tech",
    "technician": "tech",
    "admin": "admin",
    "manager": "manager",
}


class SmokeWriteBlocked(RuntimeError):
    """A cloud write was refused."""


class ReadOnlyTable:
    def __init__(self, inner: Any, log: list, name: str) -> None:
        self._inner = inner
        self._log = log
        self._name = name

    def _block(self, op: str) -> None:
        self._log.append({"op": op, "table": self._name})
        raise SmokeWriteBlocked(f"{op} {self._name}")

    def insert(self, *args: Any, **kwargs: Any) -> None:
        self._block("insert")

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._block("update")

    def upsert(self, *args: Any, **kwargs: Any) -> None:
        self._block("upsert")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        self._block("delete")

    def select(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.select(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)


class ReadOnlyClient:
    """Passes ``select`` through and refuses every other table write."""

    def __init__(self, inner: Any, log: list) -> None:
        self._inner = inner
        self._log = log

    def table(self, name: str) -> ReadOnlyTable:
        return ReadOnlyTable(self._inner.table(name), self._log, name)

    def __getattr__(self, item: str) -> Any:
        if item in {"rpc", "postgrest"}:
            self._log.append({"op": item, "table": ""})
            raise SmokeWriteBlocked(item)
        return getattr(self._inner, item)


def install_write_fence(log: list) -> dict:
    """Block Supabase writes and local inventory files for this process.

    Returns the originals so ``restore_write_fence`` can put them back.
    The smoke test used to leave those replacements in place and the next
    test in the same process could not save.
    """
    import lib.admin_users as admin_users
    import lib.app_errors as app_errors
    import lib.specialty_tools_storage as storage
    import lib.supabase_client as supabase_client
    import lib.tech_list as tech_list

    originals = {
        "modules": {
            "supabase_client": supabase_client,
            "storage": storage,
            "admin_users": admin_users,
            "tech_list": tech_list,
            "app_errors": app_errors,
        },
        "get_supabase": supabase_client.get_supabase,
        "storage_local": storage._save_local,
        "admin_local": admin_users._save_local,
        "tech_local": tech_list._save_local,
        "local_log": app_errors.LOCAL_LOG,
    }
    real_get = supabase_client.get_supabase
    clear = getattr(real_get, "clear", None)
    if callable(clear):
        try:
            clear()
        except Exception:
            pass

    def guarded() -> Any:
        client = real_get()
        if client is None:
            return None
        return ReadOnlyClient(client, log)

    def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    supabase_client.get_supabase = guarded
    storage._save_local = _noop
    admin_users._save_local = _noop
    tech_list._save_local = _noop
    app_errors.LOCAL_LOG = Path(tempfile.mkdtemp(prefix="tool-room-smoke-")) / "app_errors.jsonl"
    return originals


def restore_write_fence(originals: dict | None) -> None:
    if not originals:
        return
    modules = originals["modules"]
    modules["supabase_client"].get_supabase = originals["get_supabase"]
    modules["storage"]._save_local = originals["storage_local"]
    modules["admin_users"]._save_local = originals["admin_local"]
    modules["tech_list"]._save_local = originals["tech_local"]
    modules["app_errors"].LOCAL_LOG = originals["local_log"]


def _exception_text(at: Any) -> str:
    chunks = []
    for exc in at.exception:
        chunks.append(str(getattr(exc.proto, "message", "") or ""))
        chunks.extend(list(exc.stack_trace or []))
    return "\n".join(chunks)


def _alert_text(at: Any) -> str:
    return "\n".join(item.value for item in at.error)


def _state(at: Any, key: str, default: Any = None) -> Any:
    """AppTest session state has no ``dict.get``."""
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def _checkout_signature(at: Any) -> tuple:
    data = _state(at, "specialty_tools_data") or {}
    rows = []
    for checkout in data.get("active_checkouts") or []:
        if isinstance(checkout, dict):
            rows.append(
                (
                    str(checkout.get("id") or ""),
                    str(checkout.get("tool_no") or ""),
                    str(checkout.get("tech_name") or ""),
                    str(checkout.get("ro_number") or ""),
                )
            )
    return tuple(rows)


def _click_label(at: Any, label: str) -> bool:
    for button in at.button:
        if button.label == label:
            button.click()
            return True
    return False


def _login(at: Any, role: str, username: str) -> str:
    if role == "tech":
        password_key = "tool_room_tech_password"
        label = "Sign in as Technician"
    elif role == "admin":
        password_key = "tool_room_admin_password_input"
        label = "Sign in as Admin"
        at.text_input(key="tool_room_admin_username_input").set_value(username)
    else:
        password_key = "tool_room_manager_password"
        label = "Sign in as Manager"
    at.text_input(key=password_key).set_value(os.environ["TOOL_ROOM_SMOKE_PASSWORD"])
    at.run()
    if not _click_label(at, label):
        return f"Could not find the {label!r} button."
    at.run()
    if at.exception:
        return _exception_text(at)
    if not _state(at, "tool_room_authenticated"):
        visible = _alert_text(at) or "Sign-in did not complete."
        return visible
    return ""


def _prepare_role_env(role: str) -> str:
    """Return an error string, or empty when the process env is ready."""
    password = str(os.environ.get("TOOL_ROOM_SMOKE_PASSWORD") or "")
    if not password:
        return "TOOL_ROOM_SMOKE_PASSWORD is required."
    if role == "tech":
        os.environ["TECH_PASSWORD"] = password
        return ""
    if role == "manager":
        os.environ["APP_PASSWORD"] = password
        return ""
    if role == "admin":
        if not str(os.environ.get("TOOL_ROOM_SMOKE_USERNAME") or "").strip():
            return "TOOL_ROOM_SMOKE_USERNAME is required for an admin smoke test."
        return ""
    return "TOOL_ROOM_SMOKE_ROLE must be technician, admin, or manager."


def _run_signed_in(role: str, write_log: list) -> int:
    from streamlit.testing.v1 import AppTest

    username = str(os.environ.get("TOOL_ROOM_SMOKE_USERNAME") or "").strip()
    app_path = ROOT / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=180)
    at.run()
    if at.exception:
        print("App failed before sign-in.")
        print(_exception_text(at))
        return 1

    login_error = _login(at, role, username)
    if login_error:
        print("Sign-in failed.")
        print(login_error)
        return 1

    try:
        pages = list(at.radio(key="nav_page").options)
    except Exception as exc:
        print(f"Signed in, but the page list was not available: {exc}")
        return 1
    if not pages:
        print("Signed in, but there are no pages for this role.")
        return 1

    print(f"Signed in as {role}. Opening {len(pages)} tab(s).")
    baseline = _checkout_signature(at)
    failures: list[str] = []
    for page in pages:
        at.radio(key="nav_page").set_value(page)
        at.run()
        problem_text = _exception_text(at)
        if at.exception or "Traceback" in problem_text:
            print(f"FAIL  {page}")
            print(problem_text or "(exception with no message)")
            failures.append(page)
            continue
        signature = _checkout_signature(at)
        if signature != baseline:
            print(f"FAIL  {page} changed the checkout list")
            failures.append(page)
            continue
        print(f"OK    {page}")

    if write_log:
        print("Cloud writes were attempted and blocked:")
        for item in write_log:
            print(f"  {item.get('op')} {item.get('table')}")
        failures.append("cloud write")

    if failures:
        print(f"{len(failures)} problem(s). No checkout was created.")
        return 1
    print("Smoke test passed. No exceptions, no checkout changes, no cloud writes.")
    return 0


def main() -> int:
    if os.getenv("TOOL_ROOM_SMOKE") != "1":
        print("Signed-in smoke test skipped. Set TOOL_ROOM_SMOKE=1 to run it.")
        return 0

    role = ROLE_ALIASES.get(str(os.getenv("TOOL_ROOM_SMOKE_ROLE") or "").strip().lower(), "")
    saved_env = {
        name: os.environ.get(name) for name in ("TECH_PASSWORD", "APP_PASSWORD")
    }
    originals = None
    try:
        problem = _prepare_role_env(role)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        write_log: list = []
        originals = install_write_fence(write_log)
        return _run_signed_in(role, write_log)
    finally:
        restore_write_fence(originals)
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    sys.exit(main())
