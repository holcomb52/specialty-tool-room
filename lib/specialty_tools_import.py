"""Parse Chrysler special-tool inventory spreadsheets (.xls / .xlsx)."""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Tuple


def _parse_qty(value: Any) -> int:
    if value is None or value == "":
        return 1
    if isinstance(value, (int, float)):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1
    match = re.search(r"(\d+)", str(value).strip())
    return max(1, int(match.group(1))) if match else 1


def _brand_flag(value: Any) -> str:
    token = str(value or "").strip().upper()
    if token == "E":
        return "essential"
    if token == "R":
        return "recommended"
    return ""


def _cell(row: Dict[str, Any], *names: str) -> Any:
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return ""


def _row_to_tool(row: Dict[str, Any], *, status: str) -> Dict[str, Any] | None:
    tool_no = str(_cell(row, "ToolNo", "tool_no", "Tool No", "Tool#") or "").strip()
    description = str(
        _cell(row, "Description", "description", "Tool Description") or ""
    ).strip()
    if not tool_no and not description:
        return None
    location = str(
        _cell(row, "Special Location", "Location", "location", "SpecialLocation") or ""
    ).strip()
    notes = str(_cell(row, "Notes", "notes") or "").strip()
    sort_order = str(_cell(row, "SortOrder", "sort_order", "Sort Order") or "").strip()
    return {
        "id": str(uuid.uuid4()),
        "tool_no": tool_no,
        "description": description,
        "quantity": _parse_qty(_cell(row, "Inv", "ncInv", "Qty", "Quantity", "quantity")),
        "location": location,
        "notes": notes,
        "sort_order": sort_order or tool_no,
        "status": status,
        "brand_flags": {
            "chrysler": _brand_flag(_cell(row, "Cr", "Chrysler")),
            "jeep": _brand_flag(_cell(row, "Jp", "Jeep")),
            "ram": _brand_flag(_cell(row, "Rm", "Ram")),
            "dodge": _brand_flag(_cell(row, "DRT", "Dodge")),
        },
    }


def _read_sheet_rows(path: str, sheet_name: str | None = None) -> Tuple[List[Dict[str, Any]], str]:
    lower = path.lower()
    if lower.endswith(".xls") and not lower.endswith(".xlsx"):
        import xlrd

        wb = xlrd.open_workbook(path)
        name = sheet_name or wb.sheet_names()[0]
        sh = wb.sheet_by_name(name)
        headers = [str(sh.cell_value(0, c) or "").strip() for c in range(sh.ncols)]
        rows: List[Dict[str, Any]] = []
        for r in range(1, sh.nrows):
            row = {headers[c]: sh.cell_value(r, c) for c in range(sh.ncols) if headers[c]}
            rows.append(row)
        return rows, name

    import pandas as pd

    xl = pd.ExcelFile(path)
    name = sheet_name or xl.sheet_names[0]
    df = pd.read_excel(xl, sheet_name=name, dtype=object)
    df = df.where(pd.notnull(df), "")
    return df.to_dict(orient="records"), name


def list_inventory_sheets(path: str) -> List[str]:
    lower = path.lower()
    if lower.endswith(".xls") and not lower.endswith(".xlsx"):
        import xlrd

        return list(xlrd.open_workbook(path).sheet_names())
    import pandas as pd

    return list(pd.ExcelFile(path).sheet_names)


def parse_tool_inventory_file(path: str) -> Tuple[List[Dict[str, Any]], str]:
    sheets = list_inventory_sheets(path)
    tools: List[Dict[str, Any]] = []
    used: List[str] = []

    active_names = [
        s for s in sheets if "ess" in s.lower() or "rec" in s.lower() or "inv" in s.lower()
    ]
    if not active_names:
        active_names = [sheets[0]] if sheets else []

    for name in active_names:
        if "instruction" in name.lower():
            continue
        status = "non_current" if "non" in name.lower() and "current" in name.lower() else "active"
        rows, used_name = _read_sheet_rows(path, name)
        count_before = len(tools)
        for row in rows:
            tool = _row_to_tool(row, status=status)
            if tool:
                tools.append(tool)
        if len(tools) > count_before:
            used.append(f"{used_name} ({len(tools) - count_before})")

    for name in sheets:
        if "non" in name.lower() and "current" in name.lower():
            if any(name in u for u in used):
                continue
            rows, used_name = _read_sheet_rows(path, name)
            count_before = len(tools)
            for row in rows:
                tool = _row_to_tool(row, status="non_current")
                if tool:
                    tools.append(tool)
            if len(tools) > count_before:
                used.append(f"{used_name} ({len(tools) - count_before})")

    if not tools:
        return [], "No tools found in spreadsheet."

    active = sum(1 for t in tools if t["status"] == "active")
    non_current = sum(1 for t in tools if t["status"] == "non_current")
    summary = (
        f"Imported {len(tools)} tools "
        f"({active} active, {non_current} non-current) from: {', '.join(used)}"
    )
    return tools, summary


def empty_inventory(source: str = "") -> Dict[str, Any]:
    return {
        "version": 1,
        "source": source,
        "tools": [],
        "active_checkouts": [],
        "history": [],
    }
