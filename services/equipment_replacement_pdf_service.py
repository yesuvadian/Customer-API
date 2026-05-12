from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from sqlalchemy.orm import Session, joinedload
from uuid import UUID

from models import Equipment, EquipmentStatus, User


class EquipmentReplacementPDFService:
    """Generate formatted PDF Replacement Report for a retire-and-replace event (SRS §3.3.1)."""

    def __init__(self, db: Session):
        self.db = db

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt_date(self, dt) -> str:
        if not dt:
            return "-"
        if isinstance(dt, str):
            return dt[:10]
        return dt.strftime("%d/%m/%Y")

    def _kv_table(self, rows: list, story: list) -> None:
        """Render a list of [label, value] pairs as a styled two-column table."""
        table = Table(rows, colWidths=[2.2 * inch, 4.3 * inch])
        table.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (0, -1),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1),  9),
            ("TEXTCOLOR",     (0, 0), (0, -1),   colors.HexColor("#333333")),
            ("ALIGN",         (0, 0), (0, -1),   "LEFT"),
            ("ALIGN",         (1, 0), (1, -1),   "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1),  "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1),  6),
            ("BOTTOMPADDING", (0, 0), (-1, -1),  6),
            ("LEFTPADDING",   (0, 0), (-1, -1),  10),
            ("RIGHTPADDING",  (0, 0), (-1, -1),  10),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
            ("GRID",          (0, 0), (-1, -1),  0.75, colors.HexColor("#DDDDDD")),
        ]))
        story.append(table)

    def _section_heading(self, text: str, story: list, heading_style) -> None:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(text, heading_style))

    # ── Main generator ────────────────────────────────────────────────────────

    def generate_pdf(self, old_equipment_id: UUID, new_equipment_id: UUID) -> BytesIO:
        """
        Generate a Replacement Event Report PDF.
        Returns a BytesIO buffer positioned at 0.
        """
        old = (
            self.db.query(Equipment)
            .options(
                joinedload(Equipment.equipment_type),
                joinedload(Equipment.department),
                joinedload(Equipment.organization),
                joinedload(Equipment.creator),
            )
            .filter(Equipment.id == old_equipment_id)
            .first()
        )
        new = (
            self.db.query(Equipment)
            .options(
                joinedload(Equipment.equipment_type),
                joinedload(Equipment.department),
                joinedload(Equipment.organization),
            )
            .filter(Equipment.id == new_equipment_id)
            .first()
        )
        if not old or not new:
            raise ValueError("Equipment records not found for PDF generation.")

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )
        story = []

        # ── Styles ────────────────────────────────────────────────────────────
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReplTitle",
            parent=styles["Heading1"],
            fontSize=20,
            textColor=colors.HexColor("#1E3C72"),
            alignment=TA_CENTER,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        )
        sub_title_style = ParagraphStyle(
            "ReplSubTitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#555555"),
            alignment=TA_CENTER,
            spaceAfter=16,
        )
        heading_style = ParagraphStyle(
            "ReplHeading",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#1E3C72"),
            spaceAfter=8,
            spaceBefore=12,
            fontName="Helvetica-Bold",
        )
        normal_style = styles["Normal"]
        normal_style.fontSize = 9

        # ── Title ─────────────────────────────────────────────────────────────
        story.append(Paragraph("EQUIPMENT REPLACEMENT REPORT", title_style))
        story.append(Paragraph(
            f"SEACMS — SubStation Equipment &amp; Asset Condition Monitoring System",
            sub_title_style,
        ))

        # Report metadata
        meta_rows = [
            ["Report Generated:", datetime.now().strftime("%d/%m/%Y  %H:%M:%S")],
            ["Report Reference:", f"REPL-{str(new.id)[:8].upper()}"],
            ["Organisation:", new.organization.name if new.organization else "-"],
            ["Substation / Bay:", f"{new.department.name if new.department else '-'}"],
        ]
        meta_table = Table(meta_rows, colWidths=[2.2 * inch, 4.3 * inch])
        meta_table.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (0, -1),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1),  8),
            ("TEXTCOLOR",     (0, 0), (0, -1),   colors.HexColor("#666666")),
            ("ALIGN",         (0, 0), (-1, -1),  "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1),  "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1),  4),
            ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 0.2 * inch))

        # Divider
        story.append(Table(
            [[""]],
            colWidths=[6.5 * inch],
            style=TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 2, colors.HexColor("#1E3C72")),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]),
        ))

        # ── Replacement Summary Badge ──────────────────────────────────────────
        reason_type_label = (
            "Compliance with Software Recommendation"
            if new.replacement_reason_type == "recommendation_compliance"
            else "Other Reason (Failure / Age / Policy)"
        )
        badge_table = Table(
            [["REPLACEMENT TYPE", reason_type_label]],
            colWidths=[2.2 * inch, 4.3 * inch],
        )
        badge_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0),   colors.HexColor("#1E3C72")),
            ("BACKGROUND",    (1, 0), (1, 0),   colors.HexColor("#E8F0FE")),
            ("TEXTCOLOR",     (0, 0), (0, 0),   colors.white),
            ("TEXTCOLOR",     (1, 0), (1, 0),   colors.HexColor("#1E3C72")),
            ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 10),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(Spacer(1, 0.15 * inch))
        story.append(badge_table)
        story.append(Spacer(1, 0.1 * inch))

        # ── Replacement Reason ────────────────────────────────────────────────
        if old.retirement_reason:
            self._section_heading("Replacement Reason", story, heading_style)
            reason_data = [[old.retirement_reason or "-"]]
            reason_table = Table(reason_data, colWidths=[6.5 * inch])
            reason_table.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FFF8E1")),
                ("TEXTCOLOR",     (0, 0), (-1, -1), colors.HexColor("#5D4037")),
                ("FONTSIZE",      (0, 0), (-1, -1), 10),
                ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING",   (0, 0), (-1, -1), 14),
                ("BOX",           (0, 0), (-1, -1), 1.5, colors.HexColor("#FFC107")),
            ]))
            story.append(reason_table)

        if new.analysis_report_path:
            story.append(Spacer(1, 0.08 * inch))
            story.append(Paragraph(
                f"<b>Analysis Report:</b> {new.analysis_report_path}",
                normal_style,
            ))

        # ── Section 1 — Retired Equipment ─────────────────────────────────────
        story.append(PageBreak())
        self._section_heading("Retired Equipment (UEIC Preserved)", story, heading_style)

        old_rows = [
            ["UEIC",               old.ueic or "-"],
            ["Equipment Type",     old.equipment_type.name if old.equipment_type else "-"],
            ["Substation / Bay",   old.department.name if old.department else "-"],
            ["Voltage Class",      f"{old.voltage_class} kV" if old.voltage_class else "-"],
            ["Bay Number",         old.bay_number or "-"],
            ["Manufacturer",       old.manufacturer or "-"],
            ["Model Number",       old.model_number or "-"],
            ["Factory Serial No.", old.factory_serial_number or "-"],
            ["Year of Manufacture", str(old.year_of_manufacture) if old.year_of_manufacture else "-"],
            ["Commissioned Date",  self._fmt_date(old.commissioned_date)],
            ["Retired Date",       self._fmt_date(old.retired_date)],
            ["Retirement Reason",  old.retirement_reason or "-"],
        ]
        self._kv_table(old_rows, story)

        # Retired status badge
        story.append(Spacer(1, 0.1 * inch))
        retired_badge = Table([["STATUS: RETIRED"]], colWidths=[3 * inch])
        retired_badge.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#E53935")),
            ("TEXTCOLOR",     (0, 0), (-1, -1), colors.white),
            ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 11),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(retired_badge)

        # Nameplate data for old equipment
        if old.nameplate_data:
            story.append(Spacer(1, 0.15 * inch))
            story.append(Paragraph("Nameplate Data (Retired Unit)", ParagraphStyle(
                "SubHead", parent=styles["Normal"],
                fontSize=10, fontName="Helvetica-Bold",
                textColor=colors.HexColor("#2A5298"), spaceAfter=6,
            )))
            np_rows = [
                [" ".join(w.capitalize() for w in k.split("_")), str(v) if v is not None else "-"]
                for k, v in old.nameplate_data.items()
            ]
            if np_rows:
                self._kv_table(np_rows, story)

        # ── Section 2 — New (Replacement) Equipment ────────────────────────────
        story.append(PageBreak())
        self._section_heading("Replacement Equipment (New UEIC Commissioned)", story, heading_style)

        new_rows = [
            ["UEIC (New)",         new.ueic or "-"],
            ["Equipment Type",     new.equipment_type.name if new.equipment_type else "-"],
            ["Substation / Bay",   new.department.name if new.department else "-"],
            ["Voltage Class",      f"{new.voltage_class} kV" if new.voltage_class else "-"],
            ["Bay Number",         new.bay_number or "-"],
            ["Manufacturer",       new.manufacturer or "-"],
            ["Model Number",       new.model_number or "-"],
            ["Factory Serial No.", new.factory_serial_number or "-"],
            ["Year of Manufacture", str(new.year_of_manufacture) if new.year_of_manufacture else "-"],
            ["Commissioned Date",  self._fmt_date(new.commissioned_date)],
            ["Replaces UEIC",      old.ueic or "-"],
        ]
        if new.replacement_recommendation_id:
            new_rows.append(["Linked Recommendation", str(new.replacement_recommendation_id)[:8] + "…"])

        self._kv_table(new_rows, story)

        # Active status badge
        story.append(Spacer(1, 0.1 * inch))
        active_badge = Table([["STATUS: ACTIVE"]], colWidths=[3 * inch])
        active_badge.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#43A047")),
            ("TEXTCOLOR",     (0, 0), (-1, -1), colors.white),
            ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 11),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(active_badge)

        # Nameplate data for new equipment
        if new.nameplate_data:
            story.append(Spacer(1, 0.15 * inch))
            story.append(Paragraph("Nameplate Data (New Unit)", ParagraphStyle(
                "SubHead2", parent=styles["Normal"],
                fontSize=10, fontName="Helvetica-Bold",
                textColor=colors.HexColor("#2A5298"), spaceAfter=6,
            )))
            np_rows = [
                [" ".join(w.capitalize() for w in k.split("_")), str(v) if v is not None else "-"]
                for k, v in new.nameplate_data.items()
            ]
            if np_rows:
                self._kv_table(np_rows, story)

        # ── Historical Data Note ───────────────────────────────────────────────
        story.append(Spacer(1, 0.3 * inch))
        note_data = [[
            "Historical Records Notice: All test results, maintenance records, and audit "
            "observations linked to the retired UEIC (" + (old.ueic or "-") + ") remain "
            "permanently retrievable in the system under the retired UEIC."
        ]]
        note_table = Table(note_data, colWidths=[6.5 * inch])
        note_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#E3F2FD")),
            ("TEXTCOLOR",     (0, 0), (-1, -1), colors.HexColor("#1565C0")),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("BOX",           (0, 0), (-1, -1), 1.5, colors.HexColor("#1565C0")),
        ]))
        story.append(note_table)

        # ── Footer ────────────────────────────────────────────────────────────
        story.append(Spacer(1, 0.4 * inch))
        footer_style = ParagraphStyle(
            "Footer",
            parent=normal_style,
            fontSize=8,
            textColor=colors.HexColor("#999999"),
            alignment=TA_CENTER,
        )
        story.append(Paragraph(
            f"Generated by SEACMS — Equipment Replacement Workflow  |  {datetime.now().strftime('%d %B %Y')}",
            footer_style,
        ))
        story.append(Paragraph(
            "This is a computer-generated document. No signature required.",
            footer_style,
        ))

        doc.build(story)
        buffer.seek(0)
        return buffer
