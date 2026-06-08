"""
PDF Test Report Generator using ReportLab.

Generates a professional test report PDF from approval/recommendation data,
following the KPTCL CVT test report layout style.
"""

import io
import textwrap
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from sqlalchemy.orm import joinedload
from models import Recommendation, TestingRequest, TestResult, User


class ReportService:

    def __init__(self, db: Session):
        self.db = db

    def _user_name(self, user_id) -> str:
        if not user_id:
            return "-"
        u = self.db.query(User).filter(User.id == user_id).first()
        if u:
            return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email
        return str(user_id)

    def generate_approval_report(self, recommendation_id: UUID) -> bytes:
        """Generate a PDF test report for a recommendation."""
        rec = self.db.query(Recommendation).filter(
            Recommendation.id == recommendation_id
        ).first()
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recommendation not found",
            )

        request = self.db.query(TestingRequest).options(
            joinedload(TestingRequest.equipment_type),
            joinedload(TestingRequest.test_type),
            joinedload(TestingRequest.department),
            joinedload(TestingRequest.equipment),
        ).filter(
            TestingRequest.id == rec.testing_request_id
        ).first()

        results = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == rec.testing_request_id)
            .order_by(TestResult.cts.asc())
            .all()
        )

        # Generate PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
        )

        styles = self._build_styles()
        story = []

        # ─── HEADER ────────────────────────────────────
        story.extend(self._build_header(styles, request))
        story.append(Spacer(1, 4 * mm))

        # ─── REQUEST DETAILS ───────────────────────────
        story.extend(self._build_request_section(styles, request, rec))
        story.append(Spacer(1, 4 * mm))

        # ─── TEST RESULTS ─────────────────────────────
        for idx, result in enumerate(results):
            story.extend(self._build_result_section(styles, result, idx))
            story.append(Spacer(1, 4 * mm))

        # ─── RECOMMENDATION ────────────────────────────
        story.extend(self._build_recommendation_section(styles, rec))
        story.append(Spacer(1, 6 * mm))

        # ─── SIGNATURE BLOCK ──────────────────────────
        story.extend(self._build_signature_block(styles, request, results))

        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    # ───────────────────────────────────────────────────
    # Styles
    # ───────────────────────────────────────────────────
    @staticmethod
    def _build_styles():
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            fontSize=16,
            leading=20,
            alignment=TA_CENTER,
            spaceAfter=2 * mm,
            textColor=colors.HexColor("#1a3c5e"),
        ))
        styles.add(ParagraphStyle(
            "ReportSubTitle",
            parent=styles["Normal"],
            fontSize=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#2c5f8a"),
            spaceAfter=1 * mm,
        ))
        styles.add(ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=11,
            leading=14,
            textColor=colors.white,
            backColor=colors.HexColor("#2c5f8a"),
            spaceBefore=2 * mm,
            spaceAfter=1 * mm,
            leftIndent=4,
            rightIndent=4,
            borderPadding=(4, 6, 4, 6),
        ))
        styles.add(ParagraphStyle(
            "CellLabel",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#555555"),
        ))
        styles.add(ParagraphStyle(
            "CellValue",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.black,
        ))
        styles.add(ParagraphStyle(
            "SmallNote",
            parent=styles["Normal"],
            fontSize=7,
            textColor=colors.grey,
        ))
        return styles

    # ───────────────────────────────────────────────────
    # Header
    # ───────────────────────────────────────────────────
    def _build_header(self, styles, request):
        elements = []
        elements.append(Paragraph("TEST REPORT", styles["ReportTitle"]))

        org_line = "PowerXchange.ai — Procurement Portal"
        elements.append(Paragraph(org_line, styles["ReportSubTitle"]))

        elements.append(HRFlowable(
            width="100%", thickness=1.5,
            color=colors.HexColor("#2c5f8a"),
            spaceAfter=2 * mm,
        ))
        return elements

    # ───────────────────────────────────────────────────
    # Request Details Section
    # ───────────────────────────────────────────────────
    def _build_request_section(self, styles, request, rec):
        elements = []
        elements.append(self._section_header("Section I — Request Details", styles))

        if not request:
            elements.append(Paragraph("No request data available.", styles["Normal"]))
            return elements

        # Gather date of testing from test results or recommendation
        date_of_testing = "-"
        if rec.submitted_at:
            date_of_testing = rec.submitted_at.strftime("%d-%b-%Y %H:%M")

        equip_name = "-"
        if request.equipment_type:
            equip_name = request.equipment_type.name
        test_type_name = "-"
        if request.test_type:
            test_type_name = request.test_type.name

        # UEIC from linked equipment
        ueic = "-"
        if request.equipment and request.equipment.ueic:
            ueic = request.equipment.ueic

        # Department
        dept_name = "-"
        if request.department:
            dept_name = request.department.name

        data = [
            ["Request Number", request.request_number or "-",
             "Date of Testing", date_of_testing],
            ["Title", request.title or "-",
             "Priority", (request.priority or "normal").upper()],
        ]

        if ueic != "-":
            data.append(["UEIC", ueic, "Department", dept_name])

        data.extend([
            ["Equipment Type", equip_name,
             "Test Type", test_type_name],
            ["Transformer Type", request.transformer_type or "-",
             "Transformer Rating", request.transformer_rating or "-"],
            ["Manufacturer", request.manufacturer or "-",
             "Serial Number", request.serial_number or "-"],
            ["Status", (request.status.value if request.status else "-").replace("_", " ").upper(),
             "", ""],
            ["Originator", self._user_name(request.originator_id),
             "Tester", self._user_name(request.assigned_tester_id)],
        ])

        # Location info
        loc_parts = []
        if request.zone:
            loc_parts.append(f"Zone: {request.zone}")
        if request.ce_circle:
            loc_parts.append(f"Circle: {request.ce_circle}")
        if request.se_division:
            loc_parts.append(f"Division: {request.se_division}")
        if request.ee_subdivision:
            loc_parts.append(f"Sub-Division: {request.ee_subdivision}")
        if loc_parts:
            data.append(["Location", ", ".join(loc_parts), "", ""])

        if request.description:
            data.append(["Description", request.description, "", ""])

        table = self._detail_table(data, styles)
        elements.append(table)

        # Bushing details (identity) — from the linked equipment nameplate register
        nd = (request.equipment.nameplate_data or {}) if request.equipment else {}
        bushings = nd.get("bushing_details")
        if isinstance(bushings, list) and bushings:
            elements.append(Spacer(1, 2 * mm))
            elements.extend(self._build_list_table(
                "Bushing Details",
                bushings,
                [
                    {"key": "winding",   "label": "Winding / Level"},
                    {"key": "phase",     "label": "Phase"},
                    {"key": "make",      "label": "Make"},
                    {"key": "serial_no", "label": "Sl. No."},
                    {"key": "yo_mfg",    "label": "Y.O. Mfg."},
                ],
            ))
        return elements

    # ───────────────────────────────────────────────────
    # Individual Test Result Section
    # ───────────────────────────────────────────────────
    def _get_template(self, template_key: str) -> dict:
        """DB-first template lookup: OrgTestTemplate → static test_templates fallback."""
        if not template_key:
            return {}
        try:
            from models import OrgTestTemplate
            tmpl = (
                self.db.query(OrgTestTemplate)
                .filter(OrgTestTemplate.template_key == template_key)
                .first()
            )
            if tmpl and tmpl.template_data:
                return tmpl.template_data
        except Exception:
            pass
        # Fall back to static hardcoded templates
        try:
            from test_templates import get_template_by_key
            t = get_template_by_key(template_key)
            return t or {}
        except Exception:
            return {}

    def _build_result_section(self, styles, result: TestResult, index: int):
        elements = []
        test_name = result.test_name or result.template_key or f"Test {index + 1}"
        overall = (result.overall_result or "").upper()

        # Section header with result badge
        header_text = f"Section {self._roman(index + 2)} — {test_name}"
        if overall:
            header_text += f"  [{overall}]"
        elements.append(self._section_header(header_text, styles))

        # Test metadata row
        tested_at = "-"
        if result.tested_at:
            tested_at = result.tested_at.strftime("%d-%b-%Y %H:%M")

        # Resolve template friendly name
        template_display = result.template_key or "-"
        if result.template_key:
            try:
                tmpl = self._get_template(result.template_key)
                if tmpl:
                    template_display = tmpl.get("name", template_display)
            except Exception:
                pass

        meta_data = [
            ["Tested By", self._user_name(result.tested_by),
             "Date of Testing", tested_at],
            ["Overall Result", overall or "-",
             "Test Type", template_display],
        ]
        # Show remarks — prefer top-level, fall back to test_data overall_remarks
        remarks_text = result.remarks
        if not remarks_text and result.test_data:
            remarks_text = result.test_data.get("overall_remarks")
        if remarks_text:
            meta_data.append(["Remarks", str(remarks_text), "", ""])

        elements.append(self._detail_table(meta_data, styles))
        elements.append(Spacer(1, 2 * mm))

        # Test data from JSONB
        test_data = result.test_data or {}
        if test_data:
            elements.extend(
                self._build_test_data_table(styles, test_data, result.template_key)
            )

        # Cross-session comparison results (calculated deviations vs baseline session)
        ev = result.evaluation_result or {}
        cross_ev = ev.get("cross_session_comparison") or {}
        cross_fields = [
            f for f in cross_ev.get("fields", [])
            if f.get("status") in ("ALERT", "CRITICAL", "NORMAL")
        ]
        if cross_fields:
            elements.extend(self._build_cross_session_section(styles, cross_ev, cross_fields))

        return elements

    # ───────────────────────────────────────────────────
    # Cross-Session Comparison Section
    # ───────────────────────────────────────────────────
    def _build_cross_session_section(self, styles, cross_ev: dict, fields: list):
        """Render cross-session deviation table below the form data for each result section."""
        elements = []
        overall = cross_ev.get("overall", "NORMAL")
        color_map = {"CRITICAL": "#d32f2f", "ALERT": "#f57c00", "NORMAL": "#1a7340"}
        hdr_color = colors.HexColor(color_map.get(overall, "#1E3C72"))

        elements.append(Spacer(1, 3 * mm))
        elements.append(Paragraph(
            f"<b>Cross-Session Comparison vs Baseline  [{overall}]</b>",
            ParagraphStyle("CSHdr", fontSize=9, textColor=hdr_color,
                           spaceBefore=2 * mm, spaceAfter=1 * mm),
        ))

        lbl_style = ParagraphStyle("CSth",  fontSize=8, textColor=colors.white,
                                   fontName="Helvetica-Bold", leading=10)
        val_style = ParagraphStyle("CStd",  fontSize=8, textColor=colors.black, leading=10)

        STATUS_COLOR = {"CRITICAL": "#d32f2f", "ALERT": "#f57c00", "NORMAL": "#1a7340"}

        header = [
            Paragraph("Parameter",       lbl_style),
            Paragraph("Baseline",        lbl_style),
            Paragraph("Current",         lbl_style),
            Paragraph("Deviation",       lbl_style),
            Paragraph("Status",          lbl_style),
        ]
        rows = [header]

        for f in fields:
            dev       = f.get("deviation")
            dev_type  = f.get("deviation_type", "absolute")
            dev_unit  = "%" if dev_type == "relative_percent" else ""
            sign      = "+" if isinstance(dev, (int, float)) and dev > 0 else ""
            dev_str   = f"{sign}{round(dev, 4)}{dev_unit}" if dev is not None else "—"
            status    = f.get("status", "NORMAL")
            sc        = colors.HexColor(STATUS_COLOR.get(status, "#333333"))

            rows.append([
                Paragraph(self._pdf_safe(f.get("label", f.get("key", ""))), val_style),
                Paragraph(self._pdf_safe(str(f.get("baseline_value", "—"))), val_style),
                Paragraph(self._pdf_safe(str(f.get("current_value",  "—"))), val_style),
                Paragraph(self._pdf_safe(dev_str), val_style),
                Paragraph(status, ParagraphStyle("CSst", fontSize=8,
                          textColor=sc, fontName="Helvetica-Bold", leading=10)),
            ])

        page_w = A4[0] - 30 * mm
        col_ws = [page_w * 0.40, page_w * 0.15, page_w * 0.15, page_w * 0.15, page_w * 0.15]
        tbl = Table(rows, colWidths=col_ws, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), hdr_color),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8ff")]),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        elements.append(tbl)
        elements.append(Spacer(1, 2 * mm))
        return elements

    # ───────────────────────────────────────────────────
    # Test Data Table (from JSONB, using template for labels)
    # ───────────────────────────────────────────────────
    def _build_test_data_table(self, styles, test_data: dict, template_key: str = None):
        elements = []

        # Try to get template for field labels and table column metadata
        # DB-first lookup covers fields added via Template Designer
        field_labels = {}
        field_meta = {}  # key -> full field dict (for table columns etc.)
        sections_order = []
        if template_key:
            try:
                template = self._get_template(template_key)
                if template and "sections" in template:
                    for sec in template["sections"]:
                        sec_fields = []
                        for f in sec.get("fields", []):
                            field_labels[f["key"]] = f.get("label", f["key"])
                            field_meta[f["key"]] = f
                            sec_fields.append(f["key"])
                        sections_order.append((sec["title"], sec_fields))
            except Exception:
                pass

        if sections_order:
            # Render by template sections — maintain field order (scalars & tables)
            for sec_title, field_keys in sections_order:
                sec_elements = []
                pending_scalars = []
                _skip_keys = {"overall_result", "overall_remarks"}

                def _flush_scalars():
                    """Flush pending scalars as a 2-column detail table."""
                    if not pending_scalars:
                        return
                    rows = []
                    for i in range(0, len(pending_scalars), 2):
                        row = [pending_scalars[i][0], pending_scalars[i][1]]
                        if i + 1 < len(pending_scalars):
                            row += [pending_scalars[i + 1][0], pending_scalars[i + 1][1]]
                        else:
                            row += ["", ""]
                        rows.append(row)
                    sec_elements.append(self._detail_table_raw(rows))
                    pending_scalars.clear()

                for key in field_keys:
                    if key in _skip_keys or key not in test_data:
                        continue
                    val = test_data[key]
                    label = field_labels.get(key, key.replace("_", " ").title())
                    meta = field_meta.get(key, {})

                    # Table field → flush pending scalars, add table
                    if meta.get("type") == "table" and isinstance(val, list):
                        _flush_scalars()
                        if sec_elements:
                            sec_elements.append(Spacer(1, 2 * mm))
                        columns = meta.get("columns", [])
                        sec_elements.extend(self._build_list_table(label, val, columns))
                    elif isinstance(val, list) and val and isinstance(val[0], dict):
                        # List of dicts without metadata
                        _flush_scalars()
                        if sec_elements:
                            sec_elements.append(Spacer(1, 2 * mm))
                        sec_elements.extend(self._build_list_table(label, val, []))
                    else:
                        # Scalar field → accumulate for next flush
                        pending_scalars.append([label, self._format_value(val)])

                # Flush remaining scalars at end of section
                _flush_scalars()

                # Add section heading + content if any
                if sec_elements:
                    elements.append(Paragraph(
                        f"<b>{sec_title}</b>",
                        ParagraphStyle("SubSection", fontSize=9,
                                       textColor=colors.HexColor("#2c5f8a"),
                                       spaceBefore=2 * mm, spaceAfter=1 * mm),
                    ))
                    elements.extend(sec_elements)
        else:
            # Fallback: render all key-value pairs (use field_labels for friendly names if available)
            rows = []
            list_tables = []
            _skip_keys = {"overall_result", "overall_remarks"}
            items = list(test_data.items())
            for k, v in items:
                if k in _skip_keys:
                    continue
                label = field_labels.get(k, k.replace("_", " ").title())
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    list_tables.append((label, v, field_meta.get(k, {}).get("columns", [])))
                else:
                    val = self._format_value(v)
                    rows.append((label, val))

            if rows:
                table_rows = []
                for i in range(0, len(rows), 2):
                    row = [rows[i][0], rows[i][1]]
                    if i + 1 < len(rows):
                        row += [rows[i + 1][0], rows[i + 1][1]]
                    else:
                        row += ["", ""]
                    table_rows.append(row)
                elements.append(self._detail_table_raw(table_rows))

            for label, data_list, columns in list_tables:
                elements.append(Spacer(1, 2 * mm))
                elements.extend(self._build_list_table(label, data_list, columns))

        # Skip "Additional Fields" — template should cover all relevant data.
        # Any extra keys in test_data are artifacts from old submissions.
        return elements

    # ───────────────────────────────────────────────────
    # Helper: Build a data table from list of dicts
    # ───────────────────────────────────────────────────
    @staticmethod
    def _pdf_safe(text: str) -> str:
        """Replace Unicode chars unsupported by Helvetica with ASCII equivalents."""
        return (str(text)
                .replace("δ", "d").replace("Δ", "D")
                .replace("×", "x").replace("⁻", "-").replace("³", "3").replace("²", "2")
                .replace("°", "deg ").replace("µ", "u").replace("Ω", "Ohm")
                .replace("α", "a").replace("β", "b").replace("γ", "g")
                .replace("⁠", "").replace("​", ""))

    def _build_list_table(self, title: str, data: list, columns: list):
        """Render a list of dicts as a proper table with headers.

        Args:
            title: Table title/label
            data: List of dict rows
            columns: Template column definitions [{"key": ..., "label": ...}, ...]
                     If empty, auto-detect from data keys.
        """
        elements = []
        if not data:
            return elements

        # Determine column keys and labels — skip hidden columns
        if columns:
            visible_cols = [c for c in columns if not c.get("hidden")]
            col_keys   = [c["key"] for c in visible_cols]
            col_labels = [self._pdf_safe(c.get("label", c["key"].replace("_", " ").title())) for c in visible_cols]
            print(f"[PDF DEBUG] {title}: col_keys from template = {col_keys}")
        else:
            # Auto-detect from first row, strip internal keys
            col_keys   = [k for k in data[0].keys() if not k.startswith("__")]
            col_labels = [self._pdf_safe(k.replace("_", " ").title()) for k in col_keys]
            print(f"[PDF DEBUG] {title}: col_keys auto-detected = {col_keys}")

        if not col_keys:
            return elements

        # Build header row — pre-wrap long labels so pdfx doesn't clip them.
        # wordWrap="CJK" lets any long/unbreakable token wrap inside narrow
        # columns, preventing reportlab "flowable too large" crashes.
        lbl_style = ParagraphStyle("tblHdr", fontSize=8, textColor=colors.white,
                                   fontName="Helvetica-Bold", leading=10, wordWrap="CJK")
        val_style = ParagraphStyle("tblVal", fontSize=8, textColor=colors.black,
                                   leading=10, wordWrap="CJK")

        def _wrap_label(text: str, width: int = 12) -> str:
            return '<br/>'.join(textwrap.wrap(text, width=width)) or text

        header_row = [Paragraph(_wrap_label(lbl), lbl_style) for lbl in col_labels]
        table_data = [header_row]

        # Build data rows — skip locked/internal rows
        for row_dict in data:
            if row_dict.get("__locked"):
                continue
            row = []
            for key in col_keys:
                val = self._pdf_safe(self._format_value(row_dict.get(key, "")))
                row.append(Paragraph(val, val_style))
            table_data.append(row)

        # Calculate column widths — weighted by label length, but with a minimum
        # width per column so a short-label column can still hold its data and
        # never collapses to a near-zero width (which crashes reportlab).
        page_width = A4[0] - 30 * mm
        num_cols = len(col_keys)
        weights = [max(1, len(lbl)) for lbl in col_labels]
        total_weight = sum(weights) or 1
        min_w = min(28.0, page_width / num_cols)         # never below 28pt (or even split)
        remaining = max(0.0, page_width - min_w * num_cols)
        col_widths = [min_w + remaining * (w / total_weight) for w in weights]

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header row styling
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5f8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            # Data rows
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (0, 1), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            # Grid
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            # Alternating row colors
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fc")]),
            # Padding
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)
        return elements

    # ───────────────────────────────────────────────────
    # Recommendation Section
    # ───────────────────────────────────────────────────
    def _build_recommendation_section(self, styles, rec):
        elements = []
        elements.append(self._section_header("Recommendation", styles))

        rec_type = rec.recommendation_type.value.upper() if rec.recommendation_type else "-"
        submitted_at = rec.submitted_at.strftime("%d-%b-%Y %H:%M") if rec.submitted_at else "-"

        data = [
            ["Recommendation", rec_type,
             "Submitted By", self._user_name(rec.submitted_by)],
            ["Summary", rec.summary or "-",
             "Submitted At", submitted_at],
        ]
        if rec.detailed_notes:
            data.append(["Detailed Notes", rec.detailed_notes, "", ""])
        if rec.approval_status and rec.approval_status != "pending":
            approved_at = rec.approved_at.strftime("%d-%b-%Y %H:%M") if rec.approved_at else "-"
            data.append([
                "Approval Status", rec.approval_status.upper(),
                "Approved At", approved_at,
            ])
            if rec.approval_notes:
                data.append(["Approval Notes", rec.approval_notes, "", ""])

        table = self._detail_table(data, styles)
        elements.append(table)
        return elements

    # ───────────────────────────────────────────────────
    # Signature Block
    # ───────────────────────────────────────────────────
    def _build_signature_block(self, styles, request, results):
        elements = []
        elements.append(Spacer(1, 10 * mm))

        tester_name = self._user_name(request.assigned_tester_id) if request else "-"
        originator_name = self._user_name(request.originator_id) if request else "-"

        sig_data = [
            ["", "", ""],
            ["_" * 30, "_" * 30, "_" * 30],
            ["Tested By", "Reviewed By", "Approved By"],
            [tester_name, originator_name, ""],
        ]

        sig_table = Table(sig_data, colWidths=[55 * mm, 55 * mm, 55 * mm])
        sig_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 1), (-1, 1), colors.grey),
            ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#2c5f8a")),
            ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 3), (-1, 3), colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(sig_table)
        return elements

    # ───────────────────────────────────────────────────
    # Helper: Section Header
    # ───────────────────────────────────────────────────
    @staticmethod
    def _section_header(text, styles):
        return Paragraph(f"<b>{text}</b>", styles["SectionHeader"])

    # ───────────────────────────────────────────────────
    # Helper: Detail Table (label-value pairs, 4 columns)
    # ───────────────────────────────────────────────────

    def _detail_table(self, data, styles):
        """Build a 4-column label-value table."""
        return self._detail_table_raw(data)

    @staticmethod
    def _detail_table_raw(data):
        """Build a styled 4-column table from raw data."""
        page_width = A4[0] - 30 * mm
        col1 = 35 * mm
        col2 = (page_width - 2 * col1) / 2
        col3 = col1
        col4 = col2

        wrapped_data = []

        for row in data:
            wrapped_row = []

            for i, cell in enumerate(row):
                val = str(cell) if cell else ""

                if i % 2 == 0:
                    # Label column
                    safe_label = escape(ReportService._pdf_safe(val))

                    wrapped_row.append(
                        Paragraph(
                            f"<b>{safe_label}</b>",
                            ParagraphStyle(
                                "lbl",
                                fontSize=8,
                                textColor=colors.HexColor("#555555"),
                                wordWrap="CJK",
                            ),
                        )
                    )
                else:
                    # Value column
                    safe_val = escape(ReportService._pdf_safe(val))

                    wrapped_row.append(
                        Paragraph(
                            safe_val,
                            ParagraphStyle(
                                "val",
                                fontSize=9,
                                textColor=colors.black,
                                wordWrap="CJK",
                            ),
                        )
                    )

            wrapped_data.append(wrapped_row)

        table = Table(
            wrapped_data,
            colWidths=[col1, col2, col3, col4]
        )

        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4f8")),
            ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f0f4f8")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))

        return table

    @staticmethod
    def _format_value(val) -> str:
        if isinstance(val, bool):
            return "Yes" if val else "No"
        if isinstance(val, (dict, list)):
            return str(val)
        if val is None:
            return "-"
        return str(val)

    @staticmethod
    def _roman(num: int) -> str:
        """Convert integer to roman numeral."""
        val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
        syms = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
        result = ""
        for i in range(len(val)):
            while num >= val[i]:
                result += syms[i]
                num -= val[i]
        return result
