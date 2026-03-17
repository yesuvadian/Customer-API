"""
PDF Test Report Generator using ReportLab.

Generates a professional test report PDF from approval/recommendation data,
following the KPTCL CVT test report layout style.
"""

import io
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

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

        request = self.db.query(TestingRequest).filter(
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

        data = [
            ["Request Number", request.request_number or "-",
             "Date of Testing", date_of_testing],
            ["Title", request.title or "-",
             "Priority", (request.priority or "normal").upper()],
            ["Equipment Type", equip_name,
             "Test Type", test_type_name],
            ["Transformer Rating", request.transformer_rating or "-",
             "Manufacturer", request.manufacturer or "-"],
            ["Serial Number", request.serial_number or "-",
             "Status", (request.status.value if request.status else "-").replace("_", " ").upper()],
            ["Originator", self._user_name(request.originator_id),
             "Tester", self._user_name(request.assigned_tester_id)],
        ]

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
        return elements

    # ───────────────────────────────────────────────────
    # Individual Test Result Section
    # ───────────────────────────────────────────────────
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

        meta_data = [
            ["Tested By", self._user_name(result.tested_by),
             "Date of Testing", tested_at],
            ["Overall Result", overall or "-",
             "Template", result.template_key or "-"],
        ]
        if result.remarks:
            meta_data.append(["Remarks", result.remarks, "", ""])

        elements.append(self._detail_table(meta_data, styles))
        elements.append(Spacer(1, 2 * mm))

        # Test data from JSONB
        test_data = result.test_data or {}
        if test_data:
            elements.extend(
                self._build_test_data_table(styles, test_data, result.template_key)
            )

        return elements

    # ───────────────────────────────────────────────────
    # Test Data Table (from JSONB, using template for labels)
    # ───────────────────────────────────────────────────
    def _build_test_data_table(self, styles, test_data: dict, template_key: str = None):
        elements = []

        # Try to get template for field labels
        field_labels = {}
        sections_order = []
        if template_key:
            try:
                from test_templates import get_template_by_key
                template = get_template_by_key(template_key)
                if template and "sections" in template:
                    for sec in template["sections"]:
                        sec_fields = []
                        for f in sec.get("fields", []):
                            field_labels[f["key"]] = f.get("label", f["key"])
                            sec_fields.append(f["key"])
                        sections_order.append((sec["title"], sec_fields))
            except Exception:
                pass

        if sections_order:
            # Render by template sections
            for sec_title, field_keys in sections_order:
                sec_data = []
                for key in field_keys:
                    if key in test_data:
                        val = test_data[key]
                        label = field_labels.get(key, key.replace("_", " ").title())
                        display_val = self._format_value(val)
                        sec_data.append([label, display_val])

                if sec_data:
                    elements.append(Paragraph(
                        f"<b>{sec_title}</b>",
                        ParagraphStyle(
                            "SubSection", fontSize=9,
                            textColor=colors.HexColor("#2c5f8a"),
                            spaceBefore=2 * mm, spaceAfter=1 * mm,
                        ),
                    ))
                    # Build 2-column key-value table
                    rows = []
                    for i in range(0, len(sec_data), 2):
                        row = [sec_data[i][0], sec_data[i][1]]
                        if i + 1 < len(sec_data):
                            row += [sec_data[i + 1][0], sec_data[i + 1][1]]
                        else:
                            row += ["", ""]
                        rows.append(row)

                    table = self._detail_table_raw(rows)
                    elements.append(table)
        else:
            # Fallback: render all key-value pairs
            rows = []
            items = list(test_data.items())
            for i in range(0, len(items), 2):
                k1, v1 = items[i]
                label1 = k1.replace("_", " ").title()
                val1 = self._format_value(v1)
                if i + 1 < len(items):
                    k2, v2 = items[i + 1]
                    label2 = k2.replace("_", " ").title()
                    val2 = self._format_value(v2)
                else:
                    label2, val2 = "", ""
                rows.append([label1, val1, label2, val2])

            if rows:
                table = self._detail_table_raw(rows)
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
        page_width = A4[0] - 30 * mm  # minus margins
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
                    wrapped_row.append(Paragraph(
                        f"<b>{val}</b>",
                        ParagraphStyle("lbl", fontSize=8, textColor=colors.HexColor("#555555")),
                    ))
                else:
                    # Value column
                    wrapped_row.append(Paragraph(
                        val,
                        ParagraphStyle("val", fontSize=9, textColor=colors.black),
                    ))
            wrapped_data.append(wrapped_row)

        table = Table(wrapped_data, colWidths=[col1, col2, col3, col4])
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
