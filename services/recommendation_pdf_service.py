"""
RecommendationPDFService — fixed version.

Key fixes vs original:
  1. _render_table_from_list   — Paragraph-wrapped headers + values; smart
                                 column-width distribution (weight by label length);
                                 long text wraps instead of overflowing.
  2. _render_two_column_layout — Paragraph-wrapped cells so long values wrap
                                 gracefully; LEFT-align values.
  3. Scalar two-column grid    — unchanged in layout but now uses Paragraph cells
                                 so long values never spill outside the cell.
  4. Table-type field renderer — same Paragraph-wrapping applied to the full-width
                                 table bodies; summary row preserved.
"""

from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from services.nameplate_helper import resolve_capacity, resolve_voltage_ratio

# ── Shared paragraph styles used inside table cells ─────────────────────────
_HDR_STYLE  = ParagraphStyle("_TblHdr",  fontSize=9,  fontName="Helvetica-Bold",
                              textColor=colors.white,  leading=11, wordWrap="CJK")
_VAL_STYLE  = ParagraphStyle("_TblVal",  fontSize=9,  fontName="Helvetica",
                              textColor=colors.black,  leading=11, wordWrap="CJK")
_LBL_STYLE  = ParagraphStyle("_TblLbl",  fontSize=9,  fontName="Helvetica-Bold",
                              textColor=colors.HexColor("#333333"), leading=11, wordWrap="CJK")
_CELL_STYLE = ParagraphStyle("_TblCell", fontSize=9,  fontName="Helvetica",
                              textColor=colors.black,  leading=11, wordWrap="CJK")


def _p(text, style) -> Paragraph:
    """Safe Paragraph: escapes & and < so ReportLab XML parser doesn't choke."""
    safe = str(text or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def _smart_col_widths(labels: list, total_width: float, min_w: float = 0.65) -> list:
    """
    Distribute *total_width* (inches) among columns proportionally to label
    length, with a per-column floor of *min_w* inches so narrow columns still
    fit short values without forced mid-word line-breaks.
    """
    # Weight = label chars, but never less than 8 (guarantees ~0.65 in minimum)
    weights = [max(8, len(str(lbl))) for lbl in labels]
    total   = sum(weights)
    raw     = [total_width * w / total for w in weights]
    # First pass: clamp to floor
    clamped = [max(min_w, r) for r in raw]
    # Re-scale so total stays at total_width
    scale   = total_width / sum(clamped)
    return [c * scale * inch for c in clamped]


# ─────────────────────────────────────────────────────────────────────────────

class RecommendationPDFService:
    """Generate PDF reports for recommendations with approver information."""

    def __init__(self, db):
        self.db = db

    # ── Public entry point ────────────────────────────────────────────────────

    def generate_pdf(self, recommendation_id: str) -> BytesIO:
        """Generate PDF for a recommendation with full test report details."""
        from models import Recommendation, User, TestingRequest, TestResult
        from sqlalchemy.orm import joinedload

        recommendation = self.db.query(Recommendation).filter(
            Recommendation.id == recommendation_id
        ).first()
        if not recommendation:
            raise ValueError(f"Recommendation {recommendation_id} not found")

        testing_request = self.db.query(TestingRequest).options(
            joinedload(TestingRequest.equipment_type),
            joinedload(TestingRequest.test_type),
            joinedload(TestingRequest.department),
            joinedload(TestingRequest.originator),
            joinedload(TestingRequest.assigned_tester),
            joinedload(TestingRequest.organization),
            joinedload(TestingRequest.equipment),
        ).filter(TestingRequest.id == recommendation.testing_request_id).first()

        approver = None
        if recommendation.approved_by:
            approver = self.db.query(User).filter(
                User.id == recommendation.approved_by
            ).first()

        submitted_by_user = None
        if recommendation.submitted_by:
            submitted_by_user = self.db.query(User).filter(
                User.id == recommendation.submitted_by
            ).first()

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        )
        story  = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "CustomTitle", parent=styles["Heading1"],
            fontSize=20, textColor=colors.HexColor("#003366"),
            alignment=TA_CENTER, spaceAfter=20,
        )
        heading_style = ParagraphStyle(
            "CustomHeading", parent=styles["Heading2"],
            fontSize=14, textColor=colors.HexColor("#003366"), spaceAfter=10,
        )
        normal_style = styles["Normal"]

        # ── Title ─────────────────────────────────────────────────────────────
        story.append(Paragraph("Testing Report", title_style))
        story.append(Spacer(1, 0.2 * inch))

        # ── Doc info ──────────────────────────────────────────────────────────
        story.append(self._kv_table([
            ["Report Generated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ]))
        story.append(Spacer(1, 0.3 * inch))

        # ── Request Information ───────────────────────────────────────────────
        story.append(Paragraph("Request Information", heading_style))
        request_data = [
            ["Request Number:", testing_request.request_number or "-"],
            ["Title:",          testing_request.title or "-"],
            ["Priority:",       (
                testing_request.priority.upper()
                if isinstance(testing_request.priority, str)
                else (testing_request.priority.value.upper()
                      if testing_request.priority else "-")
            )],
        ]
        if testing_request.description:
            request_data.append(["Description:", testing_request.description])
        if testing_request.equipment and testing_request.equipment.ueic:
            request_data.append(["UEIC:", testing_request.equipment.ueic])
        request_data.extend([
            ["Equipment Type:", testing_request.equipment_type.name
             if testing_request.equipment_type else "-"],
            ["Test Type:", testing_request.test_type.name
             if testing_request.test_type else "-"],
        ])
        story.append(self._kv_table(request_data))
        story.append(Spacer(1, 0.3 * inch))

        # Fetch test results now — used both as a fallback source for
        # equipment fields the register never got populated with, and later
        # for the "Test Results" section.
        test_results = self.db.query(TestResult).filter(
            TestResult.testing_request_id == testing_request.id
        ).order_by(TestResult.cts).all()

        # ── Equipment Details ─────────────────────────────────────────────────
        equip_details = []
        for label, attr in [
            ("Transformer Type:",   "transformer_type"),
            ("Transformer Rating:", "transformer_rating"),
            ("Manufacturer:",       "manufacturer"),
            ("Serial Number:",      "serial_number"),
        ]:
            val = getattr(testing_request, attr, None)
            if val:
                equip_details.append([label, val])

        # Capacity / Voltage Class / Voltage Ratio / YOM — pulled from the
        # Equipment register, falling back to the submitted test's own form
        # data when the register itself was never populated with them.
        eq = testing_request.equipment
        if eq:
            eq_nd = eq.nameplate_data or {}
            fallback_sources = [r.test_data for r in test_results if r.test_data]
            capacity = resolve_capacity(eq_nd, *fallback_sources)
            voltage_ratio = resolve_voltage_ratio(eq_nd, *fallback_sources, voltage_class=eq.voltage_class)
            equip_details.append(["Capacity:", capacity])
            equip_details.append(["Voltage Class:", eq.voltage_class or "-"])
            equip_details.append(["Voltage Ratio:", voltage_ratio])
            if eq.year_of_manufacture:
                equip_details.append(["Year of Mfg:", str(eq.year_of_manufacture)])

        if equip_details:
            story.append(Paragraph("Equipment Details", heading_style))
            story.append(self._kv_table(equip_details))
            story.append(Spacer(1, 0.3 * inch))

        # ── Organisation & Requester ──────────────────────────────────────────
        story.append(Paragraph("Organization & Requester", heading_style))
        requester_name  = "-"
        requester_email = "-"
        if testing_request.originator:
            requester_name = (
                f"{testing_request.originator.firstname or ''} "
                f"{testing_request.originator.lastname or ''}"
            ).strip() or testing_request.originator.email
            requester_email = testing_request.originator.email

        org_data = [
            ["Department:",    testing_request.department.name
             if testing_request.department else "-"],
            ["Requested By:",  requester_name],
            ["Requester Email:", requester_email],
            ["Submitted On:",  testing_request.cts.strftime("%Y-%m-%d %H:%M:%S")
             if testing_request.cts else "-"],
        ]
        story.append(self._kv_table(org_data))
        story.append(Spacer(1, 0.3 * inch))

        # ── Additional Notes ──────────────────────────────────────────────────
        if getattr(testing_request, "notes", None):
            story.append(Paragraph("Additional Notes", heading_style))
            story.append(self._kv_table([["Notes:", testing_request.notes]]))
            story.append(Spacer(1, 0.3 * inch))

        # ── Test Results ──────────────────────────────────────────────────────
        if test_results:
            story.append(Paragraph("Test Results", heading_style))

            for idx, result in enumerate(test_results, 1):
                story.extend(
                    self._render_single_test_result(
                        result, idx, len(test_results), normal_style
                    )
                )

            story.append(Spacer(1, 0.3 * inch))

        # ── Tested By ─────────────────────────────────────────────────────────
        if testing_request.assigned_tester:
            story.append(Paragraph("Tested By", heading_style))
            t = testing_request.assigned_tester
            tester_name = (
                f"{t.firstname or ''} {t.lastname or ''}".strip() or t.email
            )
            story.append(self._kv_table([
                ["Tester Name:",  tester_name],
                ["Tester Email:", t.email],
            ]))
            story.append(Spacer(1, 0.3 * inch))

        # ── Recommendation ────────────────────────────────────────────────────
        story.append(Paragraph("Recommendation", heading_style))
        rec_type = (
            recommendation.recommendation_type.value
            if recommendation.recommendation_type else "-"
        )
        rec_data = [
            ["Type:",    rec_type.replace("_", " ").upper()],
            ["Summary:", recommendation.summary or "-"],
        ]
        if recommendation.detailed_notes:
            rec_data.append(["Detailed Notes:", recommendation.detailed_notes])
        story.append(self._kv_table(rec_data))
        story.append(Spacer(1, 0.3 * inch))

        # ── Reviewed By ───────────────────────────────────────────────────────
        if submitted_by_user:
            story.append(Paragraph("Reviewed By", heading_style))
            story.append(self._kv_table([
                ["Reviewer Name:", (
                    f"{submitted_by_user.firstname or ''} "
                    f"{submitted_by_user.lastname or ''}"
                ).strip() or submitted_by_user.email],
                ["Reviewer Email:", submitted_by_user.email],
                ["Reviewed At:", recommendation.submitted_at.strftime("%Y-%m-%d %H:%M:%S")
                 if recommendation.submitted_at else "-"],
            ]))
            story.append(Spacer(1, 0.3 * inch))

        # ── Approved / Rejected By ────────────────────────────────────────────
        approval_title = (
            "Approved By" if recommendation.approval_status == "approved" else
            "Rejected By" if recommendation.approval_status == "rejected" else
            "Approval Status"
        )
        story.append(Paragraph(approval_title, heading_style))
        approval_data = []
        if approver:
            approver_name = (
                f"{approver.firstname or ''} {approver.lastname or ''}".strip()
                or approver.email
            )
            action_label = (
                "Approved By:" if recommendation.approval_status == "approved" else
                "Rejected By:" if recommendation.approval_status == "rejected" else
                "Reviewed By:"
            )
            approval_data.extend([
                [action_label, approver_name],
                ["Email:",      approver.email],
                ["Date:",       recommendation.approved_at.strftime("%Y-%m-%d %H:%M:%S")
                 if recommendation.approved_at else "-"],
            ])
        else:
            approval_data.append(["Status:", "Pending Approval"])
        if recommendation.approval_notes:
            approval_data.append(["Notes:", recommendation.approval_notes])
        story.append(self._kv_table(approval_data))
        story.append(Spacer(1, 0.3 * inch))

        # ── Status badge ──────────────────────────────────────────────────────
        if recommendation.approval_status == "approved":
            status_text, status_color = "APPROVED", colors.HexColor("#4CAF50")
        elif recommendation.approval_status == "rejected":
            status_text, status_color = "REJECTED", colors.HexColor("#F44336")
        else:
            status_text, status_color = "PENDING APPROVAL", colors.HexColor("#FF9800")

        badge = Table([[status_text]], colWidths=[6.5 * inch])
        badge.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 14),
            ("TEXTCOLOR",     (0, 0), (-1, -1), colors.white),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND",    (0, 0), (-1, -1), status_color),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(badge)

        doc.build(story)
        buffer.seek(0)
        return buffer

    # ── Single test result block ──────────────────────────────────────────────

    def _render_single_test_result(self, result, idx, total, normal_style):
        """Return a list of flowables for one TestResult."""
        story = []

        # ── Header row with test name + result colour ─────────────────────────
        res_str = (result.overall_result or "N/A").upper()
        if res_str == "PASS":
            res_color = colors.HexColor("#4CAF50")
        elif res_str == "FAIL":
            res_color = colors.HexColor("#F44336")
        else:
            res_color = colors.HexColor("#FF9800")

        hdr_lbl = ParagraphStyle("_HL", fontSize=11, fontName="Helvetica-Bold",
                                 textColor=colors.HexColor("#003366"))
        hdr_res = ParagraphStyle("_HR", fontSize=11, fontName="Helvetica-Bold",
                                 textColor=res_color, alignment=1)  # TA_RIGHT

        hdr_tbl = Table(
            [[
                _p(f"Test {idx}: {result.test_name or result.template_key or 'N/A'}", hdr_lbl),
                _p(f"Result: {res_str}", hdr_res),
            ]],
            colWidths=[4.5 * inch, 2.0 * inch],
        )
        hdr_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(hdr_tbl)

        # ── Build field label / column metadata from template ─────────────────
        _field_labels  = {}
        _col_labels    = {}
        _col_summaries = {}
        try:
            from models import OrgTestTemplate
            _tmpl_row = (
                self.db.query(OrgTestTemplate)
                .filter(OrgTestTemplate.template_key == result.template_key)
                .first()
            )
            _tmpl_data = (
                _tmpl_row.template_data
                if _tmpl_row and _tmpl_row.template_data
                else {}
            )
            if not _tmpl_data:
                from test_templates import get_template_by_key
                _tmpl_data = get_template_by_key(result.template_key) or {}
            for _sec in _tmpl_data.get("sections", []):
                for _f in _sec.get("fields", []):
                    fk = _f.get("key")
                    _field_labels[fk] = _f.get("label", fk)
                    if _f.get("type") == "table":
                        _col_labels[fk] = {
                            (c.get("key", c) if isinstance(c, dict) else c):
                            (c.get("label", c) if isinstance(c, dict) else c)
                            for c in _f.get("columns", [])
                        }
                        raw = _f.get("column_summaries", {})
                        if isinstance(raw, dict) and raw:
                            _col_summaries[fk] = {
                                k: v for k, v in raw.items() if v and v != "none"
                            }
        except Exception:
            pass

        _skip_keys    = {"overall_result", "overall_remarks"}
        _scalar_items = []
        _table_items  = []

        if result.test_data:
            for key, value in result.test_data.items():
                if key in _skip_keys:
                    continue
                friendly = _field_labels.get(
                    key, key.replace("_", " ").title()
                )
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    _table_items.append((friendly, key, value))
                else:
                    _scalar_items.append((friendly, str(value) if value is not None else "-"))

        if result.remarks:
            _scalar_items.append(("Remarks", result.remarks))

        # ── Scalar two-column grid ─────────────────────────────────────────────
        # Layout: | Label | Value | Label | Value |  (1.2 + 1.8 + 1.2 + 1.8 = 6 in)
        if _scalar_items:
            lbl_s = ParagraphStyle("_SL", fontSize=8, fontName="Helvetica-Bold",
                                   textColor=colors.HexColor("#555555"),
                                   backColor=colors.HexColor("#F0F0F0"), wordWrap="CJK")
            val_s = ParagraphStyle("_SV", fontSize=8, fontName="Helvetica",
                                   textColor=colors.black, wordWrap="CJK")
            rows = []
            for i in range(0, len(_scalar_items), 2):
                lbl_l, val_l = _scalar_items[i]
                lbl_r, val_r = (_scalar_items[i + 1] if i + 1 < len(_scalar_items)
                                else ("", ""))
                rows.append([
                    _p(f"{lbl_l}:", lbl_s), _p(val_l, val_s),
                    _p(f"{lbl_r}:", lbl_s) if lbl_r else _p("", lbl_s),
                    _p(val_r,       val_s),
                ])

            scalar_tbl = Table(rows, colWidths=[1.3*inch, 1.9*inch, 1.3*inch, 1.9*inch])
            scalar_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (0, -1), colors.HexColor("#F0F0F0")),
                ("BACKGROUND",    (2, 0), (2, -1), colors.HexColor("#F0F0F0")),
                ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("GRID",          (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ]))
            story.append(scalar_tbl)

        # ── Full-width tables for table-type fields ───────────────────────────
        sub_hdr_s = ParagraphStyle(
            "_SubHdr", parent=normal_style,
            fontSize=9, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#003366"),
            spaceBefore=6, spaceAfter=3,
        )

        for _tbl_label, _fkey, _rows in _table_items:
            story.append(Paragraph(_tbl_label, sub_hdr_s))
            story.append(
                self._render_data_table(_rows, _col_labels.get(_fkey, {}),
                                        _col_summaries.get(_fkey, {}))
            )

        if idx < total:
            story.append(Spacer(1, 0.2 * inch))

        return story

    # ── Key-value table (2-column, label on left) ─────────────────────────────

    def _kv_table(self, rows: list) -> Table:
        """
        Build a simple 2-column key-value table.
        Column widths: 2 in (label) + 4.5 in (value).  Cells wrapped with Paragraph.
        """
        lbl_s = ParagraphStyle("_KL", fontSize=10, fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#333333"), wordWrap="CJK")
        val_s = ParagraphStyle("_KV", fontSize=10, fontName="Helvetica",
                               textColor=colors.black, wordWrap="CJK")

        wrapped = [[_p(r[0], lbl_s), _p(r[1], val_s)] for r in rows]

        tbl = Table(wrapped, colWidths=[2.0 * inch, 4.5 * inch])
        tbl.setStyle(TableStyle([
            ("FONTSIZE",      (0, 0), (-1, -1), 10),
            ("BACKGROUND",    (0, 0), (0, -1), colors.HexColor("#F0F0F0")),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("GRID",          (0, 0), (-1, -1), 0.5, colors.grey),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ]))
        return tbl

    # ── Data table from list of dicts ─────────────────────────────────────────

    def _render_data_table(self, data_list: list, col_label_map: dict,
                           col_summaries: dict) -> Table:
        """
        Render a list of row-dicts as a proper table.

        - Headers wrapped in Paragraph with word-wrap
        - Column widths distributed proportionally to header label length
        - Optional summary row appended when col_summaries is set
        """
        if not data_list:
            return Table([[_p("(no data)", _VAL_STYLE)]])

        col_keys   = list(data_list[0].keys())
        col_labels = [
            col_label_map.get(k, k.replace("_", " ").title())
            for k in col_keys
        ]

        # Total usable width = A4 − margins (0.75 in each side) = 6.5 in
        total_w = 6.5
        col_widths = _smart_col_widths(col_labels, total_w)

        # Header row
        hdr_row = [_p(lbl, _HDR_STYLE) for lbl in col_labels]
        table_data = [hdr_row]

        # Data rows
        for row_dict in data_list:
            table_data.append([
                _p(str(row_dict.get(k, "") if row_dict.get(k) is not None else "-"),
                   _VAL_STYLE)
                for k in col_keys
            ])

        # Optional summary row
        summary_row = None
        if col_summaries:
            cells, has_any = [], False
            for k in col_keys:
                fn = col_summaries.get(k)
                if fn:
                    vals = []
                    for row in data_list:
                        try:
                            vals.append(float(row.get(k, "")))
                        except (TypeError, ValueError):
                            pass
                    if vals:
                        has_any = True
                        agg = (
                            sum(vals) / len(vals) if fn == "avg" else
                            sum(vals)             if fn == "sum" else
                            min(vals)             if fn == "min" else
                            max(vals)             if fn == "max" else None
                        )
                        if agg is not None:
                            disp = str(int(agg)) if agg == int(agg) else f"{agg:.2f}"
                            cells.append(_p(f"{fn.upper()}: {disp}", _HDR_STYLE))
                        else:
                            cells.append(_p("-", _HDR_STYLE))
                    else:
                        cells.append(_p("-", _HDR_STYLE))
                else:
                    cells.append(_p("Summary" if k == col_keys[0] else "", _HDR_STYLE))
            if has_any:
                summary_row = cells

        if summary_row:
            table_data.append(summary_row)

        n_data = len(data_list)  # rows between header and optional summary

        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        cmds = [
            # Header
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3C72")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
            # Data
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (0, 1), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, n_data),
             [colors.white, colors.HexColor("#F8F9FA")]),
            # Grid
            ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            # Padding
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]
        if summary_row:
            cmds += [
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDE7F6")),
                ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR",  (0, -1), (-1, -1), colors.HexColor("#4A148C")),
            ]
        tbl.setStyle(TableStyle(cmds))
        return tbl

    # ── Legacy helpers kept for backward compat ───────────────────────────────

    def _render_test_data_structure(self, data, story, heading_style,
                                    subheading_style, normal_style):
        """Render arbitrary test_data dict. Uses fixed helpers below."""
        for key, value in data.items():
            section_name = " ".join(w.capitalize() for w in key.split("_"))
            if isinstance(value, list) and value and isinstance(value[0], dict):
                story.append(Paragraph(section_name, subheading_style))
                story.append(self._render_data_table(value, {}, {}))
                story.append(Spacer(1, 0.15 * inch))
            elif isinstance(value, dict):
                has_nested = any(isinstance(v, (dict, list)) for v in value.values())
                if has_nested:
                    story.append(Paragraph(section_name, subheading_style))
                    self._render_test_data_structure(
                        value, story, heading_style, subheading_style, normal_style
                    )
                else:
                    story.append(Paragraph(section_name, subheading_style))
                    story.append(self._render_two_column_layout(value))
                    story.append(Spacer(1, 0.15 * inch))
            else:
                story.append(self._render_two_column_layout({key: value}))
                story.append(Spacer(1, 0.1 * inch))

    def _render_two_column_layout(self, data_dict: dict) -> Table:
        """
        Render simple key-value pairs in two columns.
        NOW uses Paragraph cells so long values wrap instead of overflowing.
        """
        lbl_s = ParagraphStyle("_2CL", fontSize=9, fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#333333"), wordWrap="CJK")
        val_s = ParagraphStyle("_2CV", fontSize=9, fontName="Helvetica",
                               textColor=colors.black, wordWrap="CJK")

        rows = [
            [_p(" ".join(w.capitalize() for w in k.split("_")), lbl_s),
             _p(str(v) if v is not None else "-", val_s)]
            for k, v in data_dict.items()
        ]

        tbl = Table(rows, colWidths=[2.0 * inch, 4.5 * inch])
        tbl.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("TEXTCOLOR",     (0, 0), (0, -1), colors.HexColor("#333333")),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1),
             [colors.white, colors.HexColor("#F8F9FA")]),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("GRID",          (0, 0), (-1, -1), 0.75, colors.HexColor("#DDDDDD")),
        ]))
        return tbl

    def _get_status_color(self, status: str):
        return {
            "approved": colors.HexColor("#4CAF50"),
            "rejected": colors.HexColor("#F44336"),
            "pending":  colors.HexColor("#FF9800"),
        }.get(status, colors.grey)