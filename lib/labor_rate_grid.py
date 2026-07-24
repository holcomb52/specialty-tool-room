"""Customer-pay labor rate grid builder for warranty ELR submissions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

TENTHS = (0.0, 0.1, 0.2, 0.3, 0.4)
TENTH_LABELS = ("+.0", "+.1", "+.2", "+.3", "+.4")


@dataclass(frozen=True)
class LaborGridResult:
    target_elr: float
    strong_lo: float
    strong_hi: float
    max_hours: float
    strength_boost: float
    # Display rows: base hour -> amounts for +.0 .. +.4
    matrix: Dict[float, Dict[float, float]]
    # Flat list of (hours, amount, elr, in_strong)
    cells: List[Dict[str, float | bool]]
    strong_avg_elr: float
    strong_min_elr: float
    strong_max_elr: float
    overall_avg_elr: float
    scale_factor: float


def parse_hour_range(text: str) -> Tuple[float, float]:
    """Parse ranges like '1.0-3.5', '1 to 4', '2.5 – 5'."""
    raw = str(text or "").strip().lower()
    if not raw:
        raise ValueError("Enter an hour range, e.g. 1.0-3.5")
    raw = raw.replace("–", "-").replace("—", "-").replace("to", "-")
    parts = re.split(r"\s*-\s*", raw)
    if len(parts) != 2:
        raise ValueError("Use a range like 1.0-3.5")
    try:
        lo = float(parts[0].strip())
        hi = float(parts[1].strip())
    except ValueError as exc:
        raise ValueError("Hour range must be numbers, e.g. 1.0-3.5") from exc
    if lo < 0 or hi < 0:
        raise ValueError("Hours cannot be negative.")
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        hi = lo + 0.5
    return round(lo, 1), round(hi, 1)


def _round_money(value: float) -> float:
    """Dealer grids usually land on whole dollars or half-dollars."""
    if value <= 0:
        return 0.0
    return round(value * 2.0) / 2.0


def _strength(
    hours: float,
    strong_lo: float,
    strong_hi: float,
    boost: float,
) -> float:
    """
    Multiplier peaking inside the strong hour band.

    Inside the band: 1.0 at the edges → (1 + boost) at the center.
    Outside: gently lower so the submission ELR is carried by your real mix.
    """
    if hours <= 0:
        return 1.0
    mid = (strong_lo + strong_hi) / 2.0
    half = max((strong_hi - strong_lo) / 2.0, 0.25)
    if strong_lo <= hours <= strong_hi:
        proximity = 1.0 - min(abs(hours - mid) / half, 1.0)
        return 1.0 + max(0.0, boost) * proximity
    if hours < strong_lo:
        gap = strong_lo - hours
        return max(0.80, 1.0 - 0.045 * gap)
    gap = hours - strong_hi
    return max(0.84, 1.0 - 0.028 * gap)


def _iter_hours(max_hours: float) -> List[float]:
    """All billable times on the classic +.0 … +.4 grid through max_hours."""
    max_h = max(0.5, float(max_hours))
    # Cap at the last tenth column on the final half-hour row
    out: List[float] = []
    base = 0.0
    while base <= max_h + 1e-9:
        for tenth in TENTHS:
            hours = round(base + tenth, 1)
            if hours <= max_h + 1e-9:
                out.append(hours)
        base = round(base + 0.5, 1)
    return out


def build_labor_grid(
    target_elr: float,
    strong_lo: float,
    strong_hi: float,
    *,
    max_hours: float = 16.0,
    strength_boost: float = 0.10,
) -> LaborGridResult:
    """
    Build a customer-pay labor matrix aimed at `target_elr`.

    Amounts are scaled so the average ELR across times in the strong hour
    range matches the target (what you want Stellantis to see from your mix).
    """
    elr = float(target_elr)
    if elr <= 0:
        raise ValueError("Target ELR must be greater than zero.")
    lo = float(strong_lo)
    hi = float(strong_hi)
    if hi < lo:
        lo, hi = hi, lo
    boost = max(0.0, min(0.25, float(strength_boost)))
    max_h = max(hi + 1.0, float(max_hours))

    hours_list = _iter_hours(max_h)
    raw_amounts: Dict[float, float] = {}
    for hours in hours_list:
        if hours <= 0:
            raw_amounts[hours] = 0.0
            continue
        raw_amounts[hours] = hours * elr * _strength(hours, lo, hi, boost)

    # Scale so strong-band average ELR == target
    strong_pairs = [
        (h, raw_amounts[h])
        for h in hours_list
        if h > 0 and lo - 1e-9 <= h <= hi + 1e-9
    ]
    if not strong_pairs:
        # Fallback: nearest hour cells around the requested band
        strong_pairs = [(h, raw_amounts[h]) for h in hours_list if h > 0][:10]

    strong_elrs = [amt / h for h, amt in strong_pairs if h > 0]
    avg_raw = sum(strong_elrs) / len(strong_elrs) if strong_elrs else elr
    scale = elr / avg_raw if avg_raw else 1.0

    cells: List[Dict[str, float | bool]] = []
    matrix: Dict[float, Dict[float, float]] = {}
    for hours in hours_list:
        amount = _round_money(raw_amounts[hours] * scale)
        tenths_int = int(round(hours * 10))
        base_tenths = (tenths_int // 5) * 5
        tenth_tenths = tenths_int - base_tenths
        base_row = round(base_tenths / 10.0, 1)
        tenth_col = round(tenth_tenths / 10.0, 1)

        matrix.setdefault(base_row, {})
        matrix[base_row][tenth_col] = amount
        cell_elr = (amount / hours) if hours > 0 else 0.0
        in_strong = bool(hours > 0 and lo - 1e-9 <= hours <= hi + 1e-9)
        cells.append(
            {
                "hours": hours,
                "amount": amount,
                "elr": round(cell_elr, 2),
                "in_strong": in_strong,
            }
        )

    strong_cells = [c for c in cells if c["in_strong"] and float(c["hours"]) > 0]
    strong_elr_vals = [float(c["elr"]) for c in strong_cells]
    all_elr_vals = [float(c["elr"]) for c in cells if float(c["hours"]) > 0]

    return LaborGridResult(
        target_elr=elr,
        strong_lo=lo,
        strong_hi=hi,
        max_hours=max_h,
        strength_boost=boost,
        matrix=matrix,
        cells=cells,
        strong_avg_elr=round(sum(strong_elr_vals) / len(strong_elr_vals), 2)
        if strong_elr_vals
        else 0.0,
        strong_min_elr=round(min(strong_elr_vals), 2) if strong_elr_vals else 0.0,
        strong_max_elr=round(max(strong_elr_vals), 2) if strong_elr_vals else 0.0,
        overall_avg_elr=round(sum(all_elr_vals) / len(all_elr_vals), 2)
        if all_elr_vals
        else 0.0,
        scale_factor=round(scale, 4),
    )


def grid_to_dataframe_rows(result: LaborGridResult) -> List[Dict[str, str]]:
    """Rows for a Streamlit/CSV table matching the classic HOUR / +.0…+.4 layout."""
    rows: List[Dict[str, str]] = []
    for base in sorted(result.matrix.keys()):
        row: Dict[str, str] = {"HOUR": f"{base:.1f}"}
        for tenth, label in zip(TENTHS, TENTH_LABELS):
            amount = result.matrix.get(base, {}).get(tenth)
            row[label] = f"{amount:.2f}" if amount is not None else ""
        # Mark if this half-hour row intersects the strong band
        row_hours = [round(base + t, 1) for t in TENTHS]
        row["_strong"] = any(
            result.strong_lo - 1e-9 <= h <= result.strong_hi + 1e-9 for h in row_hours if h > 0
        )
        rows.append(row)
    return rows


def lookup_amount(result: LaborGridResult, hours: float) -> Optional[float]:
    h = round(float(hours), 1)
    for cell in result.cells:
        if abs(float(cell["hours"]) - h) < 1e-9:
            return float(cell["amount"])
    return None
