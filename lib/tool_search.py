"""Cached catalog index for tool search and location lists.

The live catalog is about 1,700 tools. Streamlit reruns the script on every
keystroke and reloads the inventory dict, so each search used to rebuild
lowercase haystacks and rescan open checkouts per tool. This module builds
that once per inventory contents and reuses it until a tool or checkout changes.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, NamedTuple

from lib.specialty_tools_storage import (
    ACCOUNTABILITY_BOXES,
    ACCOUNTABILITY_PART_ORDERED,
    ACCOUNTABILITY_UNACCOUNTED,
    normalize_accountability,
)

BRANDS = ("chrysler", "jeep", "ram", "dodge")
BRAND_LEVELS = ("essential", "recommended")
BRAND_LABELS = {
    "chrysler": "Chrysler",
    "jeep": "Jeep",
    "ram": "Ram",
    "dodge": "Dodge",
}
BRAND_LEVEL_LABELS = {
    "essential": "Essential",
    "recommended": "Recommended",
}

_CACHE: Dict[bytes, List["IndexedTool"]] = {}
_CACHE_ORDER: List[bytes] = []
_CACHE_MAX = 4
_BUILDS = 0
_HITS = 0


class IndexedTool(NamedTuple):
    tool: Dict[str, Any]
    hay: str
    status: Any
    loc: str
    loc_l: str
    acct: str
    brand_levels: Dict[str, str]
    qty_out: int
    qty_available: int
    is_out: bool


def clear_search_cache() -> None:
    """Drop the process cache. Tests use this so counts start at zero."""
    global _BUILDS, _HITS
    _CACHE.clear()
    _CACHE_ORDER.clear()
    _BUILDS = 0
    _HITS = 0


def search_index_stats() -> Dict[str, int]:
    return {"builds": _BUILDS, "hits": _HITS, "size": len(_CACHE)}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _fingerprint(tools: List[Any], checkouts: List[Any]) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    for tool in tools:
        digest.update(b"\x1e")
        if not isinstance(tool, dict):
            continue
        flags = tool.get("brand_flags") if isinstance(tool.get("brand_flags"), dict) else {}
        for key in (
            "id",
            "tool_no",
            "description",
            "location",
            "notes",
            "status",
            "accountability",
            "quantity",
            "sort_order",
        ):
            digest.update(str(tool.get(key) or "").encode())
            digest.update(b"\x1f")
        for name in BRANDS:
            digest.update(str(flags.get(name) or "").encode())
            digest.update(b"\x1f")
    digest.update(b"\x1d")
    for checkout in checkouts:
        digest.update(b"\x1e")
        if not isinstance(checkout, dict):
            continue
        digest.update(str(checkout.get("tool_id") or "").encode())
        digest.update(b"\x1f")
        digest.update(str(checkout.get("qty") if checkout.get("qty") is not None else "").encode())
        digest.update(b"\x1f")
    return digest.digest()


def _qty_total(tool: Dict[str, Any]) -> int:
    try:
        return max(1, int(tool.get("quantity") or 1))
    except (TypeError, ValueError):
        return 1


def _brand_levels(tool: Dict[str, Any]) -> Dict[str, str]:
    flags = tool.get("brand_flags")
    if not isinstance(flags, dict):
        return {}
    levels: Dict[str, str] = {}
    for name in BRANDS:
        level = str(flags.get(name) or "").strip().lower()
        if level:
            levels[name] = level
    return levels


def _build_index(tools: List[Any], checkouts: List[Any]) -> List[IndexedTool]:
    qty_by_id: Dict[Any, int] = {}
    out_ids = set()
    for checkout in checkouts:
        if not isinstance(checkout, dict):
            continue
        tool_id = checkout.get("tool_id")
        out_ids.add(tool_id)
        try:
            qty_by_id[tool_id] = qty_by_id.get(tool_id, 0) + int(checkout.get("qty") or 1)
        except (TypeError, ValueError):
            qty_by_id[tool_id] = qty_by_id.get(tool_id, 0) + 1

    records: List[IndexedTool] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        acct = normalize_accountability(tool.get("accountability"))
        loc = str(tool.get("location") or "").strip()
        hay = " ".join(
            [
                str(tool.get("tool_no") or ""),
                str(tool.get("description") or ""),
                loc,
                str(tool.get("notes") or ""),
                acct,
            ]
        ).lower()
        tool_id = tool.get("id")
        qty_out = int(qty_by_id.get(tool_id, 0))
        records.append(
            IndexedTool(
                tool=tool,
                hay=hay,
                status=tool.get("status"),
                loc=loc,
                loc_l=loc.lower(),
                acct=acct,
                brand_levels=_brand_levels(tool),
                qty_out=qty_out,
                qty_available=max(0, _qty_total(tool) - qty_out),
                is_out=tool_id in out_ids,
            )
        )
    return records


def get_search_index(data: Dict[str, Any] | None) -> List[IndexedTool]:
    """Return the cached index for this inventory, building it when contents change."""
    global _BUILDS, _HITS
    payload = data if isinstance(data, dict) else {}
    tools = _as_list(payload.get("tools"))
    checkouts = _as_list(payload.get("active_checkouts"))
    stamp = _fingerprint(tools, checkouts)
    cached = _CACHE.get(stamp)
    if cached is not None:
        _HITS += 1
        return cached
    records = _build_index(tools, checkouts)
    _CACHE[stamp] = records
    _CACHE_ORDER.append(stamp)
    while len(_CACHE_ORDER) > _CACHE_MAX:
        old = _CACHE_ORDER.pop(0)
        if old != stamp:
            _CACHE.pop(old, None)
    _BUILDS += 1
    return records


def _brand_ok(levels: Dict[str, str], brand: str, level: str) -> bool:
    if not brand and not level:
        return True
    if brand and brand not in BRANDS:
        return False
    if level and level not in BRAND_LEVELS:
        return False
    if brand and level:
        return levels.get(brand) == level
    if brand:
        return bool(levels.get(brand))
    return any(flag == level for flag in levels.values())


def search_indexed_tools(
    data: Dict[str, Any] | None,
    query: str = "",
    *,
    status: str = "active",
    location: str = "",
    only_out: bool = False,
    only_with_location: bool = False,
    only_without_location: bool = False,
    only_unaccounted: bool = False,
    only_part_ordered: bool = False,
    brand: str = "",
    brand_level: str = "",
) -> List[Dict[str, Any]]:
    records = get_search_index(data)
    q = str(query or "").strip().lower()
    loc_filter = str(location or "").strip().lower()
    brand_name = str(brand or "").strip().lower()
    level = str(brand_level or "").strip().lower()
    results: List[Dict[str, Any]] = []
    for record in records:
        if status != "all" and record.status != status:
            continue
        if only_out and not record.is_out:
            continue
        if only_part_ordered:
            if record.acct != ACCOUNTABILITY_PART_ORDERED:
                continue
        elif only_unaccounted:
            if record.acct != ACCOUNTABILITY_UNACCOUNTED:
                continue
        else:
            if only_with_location and (
                not record.loc or record.acct in ACCOUNTABILITY_BOXES
            ):
                continue
            if only_without_location and (
                record.loc or record.acct in ACCOUNTABILITY_BOXES
            ):
                continue
        if loc_filter and loc_filter not in record.loc_l:
            continue
        if not _brand_ok(record.brand_levels, brand_name, level):
            continue
        if q and q not in record.hay:
            continue
        enriched = dict(record.tool)
        enriched["qty_out"] = record.qty_out
        enriched["qty_available"] = record.qty_available
        enriched["accountability"] = record.acct
        results.append(enriched)
    results.sort(key=lambda t: str(t.get("sort_order") or t.get("tool_no") or ""))
    return results


def indexed_locations(data: Dict[str, Any] | None) -> List[str]:
    return sorted(
        {record.loc for record in get_search_index(data) if record.loc},
        key=str.lower,
    )
