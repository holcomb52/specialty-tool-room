"""Professional PDF reports for Specialty Tool Room."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Print-friendly palette (NSB Chrysler / tool-room amber)
_INK = colors.HexColor("#1c1917")
_MUTED = colors.HexColor("#57534e")
_LINE = colors.HexColor("#d6d3d1")
_HEADER_BG = colors.HexColor("#1c1917")
_HEADER_FG = colors.HexColor("#fafaf9")
_ACCENT = colors.HexColor("#b45309")
_ROW_ALT = colors.HexColor("#f5f5f4")
_SUMMARY_BG = colors.HexColor("#fffbeb")
_FOCUS = colors.HexColor("#fff7ed")


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=_ACCENT,
            spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=_INK,
            spaceBefore=2,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=_MUTED,
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            "SectionHead",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=_INK,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            "ReportMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=_MUTED,
            alignment=TA_RIGHT,
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=_INK,
            leading=11,
        ),
        "cell_bold": ParagraphStyle(
            "CellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=_INK,
            leading=11,
        ),
        "cell_focus": ParagraphStyle(
            "CellFocus",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_INK,
            leading=12,
        ),
        "empty": ParagraphStyle(
            "Empty",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=_MUTED,
            alignment=TA_CENTER,
            spaceBefore=8,
            spaceAfter=8,
        ),
        "hint": ParagraphStyle(
            "Hint",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=_MUTED,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    raw = "" if text is None else str(text)
    safe = (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return Paragraph(safe or "—", style)


def _summary_table(
    summary: Sequence[tuple[str, str]], styles: Dict[str, ParagraphStyle]
) -> Table:
    data = [
        [_p(label, styles["cell"]), _p(value, styles["cell_bold"])]
        for label, value in summary
    ]
    table = Table(data, colWidths=[2.2 * inch, 1.4 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _SUMMARY_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, _ACCENT),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, _LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _detail_table(
    rows: List[Dict[str, Any]], styles: Dict[str, ParagraphStyle]
) -> Table:
    """Detail table led by who / when signed out / how long held."""
    headers = [
        "Technician",
        "Tool #",
        "Description",
        "Signed out",
        "How long out",
        "Signed in",
        "RO #",
    ]
    data = [[_p(h, styles["cell_bold"]) for h in headers]]

    if not rows:
        data.append(
            [
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
                _p("No tools signed out", styles["empty"]),
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
            ]
        )
    else:
        for row in rows:
            data.append(
                [
                    _p(row.get("tech_name"), styles["cell_focus"]),
                    _p(row.get("tool_no"), styles["cell_bold"]),
                    _p(row.get("description"), styles["cell"]),
                    _p(row.get("signed_out"), styles["cell_focus"]),
                    _p(row.get("duration"), styles["cell_focus"]),
                    _p(row.get("signed_in"), styles["cell"]),
                    _p(row.get("ro_number") or "—", styles["cell"]),
                ]
            )

    col_widths = [
        1.25 * inch,  # Technician (who)
        0.8 * inch,   # Tool #
        1.85 * inch,  # Description
        1.2 * inch,   # Signed out (when)
        1.0 * inch,   # How long out
        0.95 * inch,  # Signed in
        0.65 * inch,  # RO
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, _LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.8, _INK),
        # Highlight who / when / duration columns
        ("BACKGROUND", (0, 1), (0, -1), _FOCUS),
        ("BACKGROUND", (3, 1), (4, -1), _FOCUS),
    ]
    for i in range(1, len(data)):
        if rows and i % 2 == 0:
            style_cmds.append(("BACKGROUND", (1, i), (2, i), _ROW_ALT))
            style_cmds.append(("BACKGROUND", (5, i), (6, i), _ROW_ALT))
    table.setStyle(TableStyle(style_cmds))
    return table


def build_checkout_report_pdf(
    *,
    title: str,
    subtitle: str = "",
    rows: List[Dict[str, Any]],
    summary: Optional[Sequence[tuple[str, str]]] = None,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """Return PDF bytes for a specialty tool checkout report."""
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title=title,
        author="Specialty Tool Room",
    )

    when = (generated_at or datetime.now()).astimezone()
    stamp = when.strftime("%m/%d/%Y %I:%M %p")

    story: List[Any] = [
        Paragraph("NEW SMYRNA BEACH CHRYSLER", styles["brand"]),
        Paragraph("Specialty Tool Room", styles["title"]),
        Paragraph(title, styles["subtitle"]),
    ]
    if subtitle:
        story.append(Paragraph(subtitle, styles["subtitle"]))
    story.append(Paragraph(f"Generated {stamp}", styles["meta"]))
    story.append(Spacer(1, 0.12 * inch))

    if summary:
        story.append(_summary_table(summary, styles))
        story.append(Spacer(1, 0.18 * inch))

    story.append(
        Paragraph(
            "Checkout detail — who has the tool, when it was signed out, and how long it has been out",
            styles["section"],
        )
    )
    story.append(_detail_table(rows, styles))

    if not rows:
        story.append(Spacer(1, 0.1 * inch))
        story.append(
            Paragraph(
                "Nothing is signed out right now. Check a tool out under Check Out, "
                "then export this report again to see technician, signed-out time, and duration.",
                styles["hint"],
            )
        )

    def _footer(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_LINE)
        canvas.setLineWidth(0.5)
        canvas.line(0.5 * inch, 0.45 * inch, letter[0] - 0.5 * inch, 0.45 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_MUTED)
        canvas.drawString(
            0.5 * inch,
            0.28 * inch,
            "Specialty Tool Room · Confidential shop use",
        )
        canvas.drawRightString(
            letter[0] - 0.5 * inch,
            0.28 * inch,
            f"Page {_doc.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def build_inventory_report_pdf(
    *,
    title: str,
    subtitle: str = "",
    rows: List[Dict[str, Any]],
    summary: Optional[Sequence[tuple[str, str]]] = None,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """PDF for physical inventory count status."""
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title=title,
        author="Specialty Tool Room",
    )

    when = (generated_at or datetime.now()).astimezone()
    stamp = when.strftime("%m/%d/%Y %I:%M %p")

    story: List[Any] = [
        Paragraph("NEW SMYRNA BEACH CHRYSLER", styles["brand"]),
        Paragraph("Specialty Tool Room", styles["title"]),
        Paragraph(title, styles["subtitle"]),
    ]
    if subtitle:
        story.append(Paragraph(subtitle, styles["subtitle"]))
    story.append(Paragraph(f"Generated {stamp}", styles["meta"]))
    story.append(Spacer(1, 0.12 * inch))

    if summary:
        story.append(_summary_table(summary, styles))
        story.append(Spacer(1, 0.18 * inch))

    story.append(
        Paragraph(
            "Inventory status — located, missing/unaccounted, signed out, or returned to place",
            styles["section"],
        )
    )

    header = [
        _p("Tool #", styles["cell_bold"]),
        _p("Description", styles["cell_bold"]),
        _p("Location", styles["cell_bold"]),
        _p("Status", styles["cell_bold"]),
        _p("Detail", styles["cell_bold"]),
    ]
    data = [header]
    if not rows:
        data.append(
            [
                _p("No tools in this filter", styles["empty"]),
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
                _p("—", styles["cell"]),
            ]
        )
    else:
        for row in rows:
            if row.get("is_signed_out"):
                status = "Signed out"
                detail = f"To {row.get('signed_out_to') or '—'} · {row.get('signed_out_at') or ''}"
            else:
                result = str(row.get("inventory_result") or "")
                if result == "missing":
                    status = "Missing / Unaccounted"
                    detail = "Not found during inventory"
                elif result == "returned":
                    status = "Returned to place"
                    detail = "Found wrong place — put back"
                elif result == "located":
                    status = "Located"
                    detail = "Found at assigned location"
                else:
                    status = "Needs count"
                    detail = "Not checked yet"
            data.append(
                [
                    _p(row.get("tool_no"), styles["cell_bold"]),
                    _p(row.get("description"), styles["cell"]),
                    _p(row.get("location") or "—", styles["cell"]),
                    _p(status, styles["cell_focus"]),
                    _p(detail, styles["cell"]),
                ]
            )

    col_widths = [
        0.9 * inch,
        2.1 * inch,
        1.4 * inch,
        1.35 * inch,
        1.95 * inch,
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, _LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.8, _INK),
        ("BACKGROUND", (3, 1), (3, -1), _FOCUS),
    ]
    for i in range(1, len(data)):
        if rows and i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (2, i), _ROW_ALT))
            style_cmds.append(("BACKGROUND", (4, i), (4, i), _ROW_ALT))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    def _footer(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_LINE)
        canvas.setLineWidth(0.5)
        canvas.line(0.5 * inch, 0.45 * inch, letter[0] - 0.5 * inch, 0.45 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_MUTED)
        canvas.drawString(
            0.5 * inch,
            0.28 * inch,
            "Specialty Tool Room · Confidential shop use",
        )
        canvas.drawRightString(
            letter[0] - 0.5 * inch,
            0.28 * inch,
            f"Page {_doc.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def build_labor_rate_grid_pdf(
    *,
    title: str,
    subtitle: str = "",
    grid_rows: List[Dict[str, Any]],
    summary: Optional[Sequence[tuple[str, str]]] = None,
    strong_lo: float = 0.0,
    strong_hi: float = 0.0,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """Printable customer-pay labor grid for warranty rate submissions."""
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title=title,
        author="Specialty Tool Room",
    )

    when = (generated_at or datetime.now()).astimezone()
    stamp = when.strftime("%m/%d/%Y %I:%M %p")

    story: List[Any] = [
        Paragraph("NEW SMYRNA BEACH CHRYSLER", styles["brand"]),
        Paragraph("Specialty Tool Room", styles["title"]),
        Paragraph(title, styles["subtitle"]),
    ]
    if subtitle:
        story.append(Paragraph(subtitle, styles["subtitle"]))
    story.append(Paragraph(f"Generated {stamp}", styles["meta"]))
    story.append(Spacer(1, 0.12 * inch))

    if summary:
        story.append(_summary_table(summary, styles))
        story.append(Spacer(1, 0.18 * inch))

    story.append(
        Paragraph(
            f"Customer-pay labor grid · strong band {strong_lo:.1f}–{strong_hi:.1f} hrs",
            styles["section"],
        )
    )

    header = [
        _p("HOUR", styles["cell_bold"]),
        _p("+.0", styles["cell_bold"]),
        _p("+.1", styles["cell_bold"]),
        _p("+.2", styles["cell_bold"]),
        _p("+.3", styles["cell_bold"]),
        _p("+.4", styles["cell_bold"]),
    ]
    data = [header]
    strong_row_indexes: List[int] = []
    for idx, row in enumerate(grid_rows, start=1):
        data.append(
            [
                _p(row.get("HOUR", ""), styles["cell_bold"]),
                _p(row.get("+.0", "") or "—", styles["cell"]),
                _p(row.get("+.1", "") or "—", styles["cell"]),
                _p(row.get("+.2", "") or "—", styles["cell"]),
                _p(row.get("+.3", "") or "—", styles["cell"]),
                _p(row.get("+.4", "") or "—", styles["cell"]),
            ]
        )
        if row.get("_strong"):
            strong_row_indexes.append(idx)

    col_widths = [
        0.75 * inch,
        1.15 * inch,
        1.15 * inch,
        1.15 * inch,
        1.15 * inch,
        1.15 * inch,
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, _LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.8, _INK),
        ("BACKGROUND", (0, 1), (0, -1), _FOCUS),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (1, i), (-1, i), _ROW_ALT))
    for i in strong_row_indexes:
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), _SUMMARY_BG))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 0.12 * inch))
    story.append(
        Paragraph(
            "Highlighted rows intersect the hour range where most of your work falls. "
            "Use this customer-pay schedule to support a Stellantis warranty labor rate request.",
            styles["hint"],
        )
    )

    def _footer(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_LINE)
        canvas.setLineWidth(0.5)
        canvas.line(0.5 * inch, 0.45 * inch, letter[0] - 0.5 * inch, 0.45 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_MUTED)
        canvas.drawString(
            0.5 * inch,
            0.28 * inch,
            "Specialty Tool Room · Confidential shop use",
        )
        canvas.drawRightString(
            letter[0] - 0.5 * inch,
            0.28 * inch,
            f"Page {_doc.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
