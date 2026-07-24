"""Labor rate grid builder tests."""

from __future__ import annotations

from lib.labor_rate_grid import (
    build_labor_grid,
    grid_to_dataframe_rows,
    lookup_amount,
    parse_hour_range,
)
from lib.reports_pdf import build_labor_rate_grid_pdf


def test_parse_hour_range():
    assert parse_hour_range("1.0-3.5") == (1.0, 3.5)
    assert parse_hour_range("2 to 4") == (2.0, 4.0)
    assert parse_hour_range("3.5 – 1.0") == (1.0, 3.5)


def test_strong_band_hits_target_elr():
    result = build_labor_grid(300.0, 1.0, 3.5, max_hours=12.0, strength_boost=0.10)
    assert abs(result.strong_avg_elr - 300.0) < 2.0  # rounding tolerance
    assert result.strong_max_elr >= result.strong_min_elr
    # Center of band should be at least as strong as a short fringe cell outside
    amt_2 = lookup_amount(result, 2.0)
    amt_8 = lookup_amount(result, 8.0)
    assert amt_2 is not None and amt_8 is not None
    assert (amt_2 / 2.0) >= (amt_8 / 8.0) - 5.0


def test_grid_layout_and_pdf():
    result = build_labor_grid(295.0, 1.5, 4.0, max_hours=10.0)
    rows = grid_to_dataframe_rows(result)
    assert rows[0]["HOUR"] == "0.0"
    assert "+.0" in rows[0] and "+.4" in rows[0]
    assert lookup_amount(result, 0.0) == 0.0
    assert lookup_amount(result, 1.3) is not None

    pdf = build_labor_rate_grid_pdf(
        title="Test Labor Grid",
        grid_rows=rows,
        summary=[("Target ELR", "$295.00")],
        strong_lo=1.5,
        strong_hi=4.0,
    )
    assert pdf.startswith(b"%PDF")
