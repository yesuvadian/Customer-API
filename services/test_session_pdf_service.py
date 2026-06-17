from io import BytesIO

from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from models import TestSession, TestSessionReading, TestingRequest, TestResult

_NAVY  = rl_colors.HexColor("#1B3A6B")
_TEAL  = rl_colors.HexColor("#006D7E")
_LIGHT = rl_colors.HexColor("#E8F0FE")
_KIT_BLUE = rl_colors.HexColor("#1A5276")
_KIT_ROW  = rl_colors.HexColor("#EBF5FB")
_KIT_GRID = rl_colors.HexColor("#AED6F1")


class TestSessionPDFService:
    """Renders a single test session as a PDF byte stream."""

    def generate_pdf(
        self,
        session: TestSession,
        readings: list[TestSessionReading],
        request: TestingRequest,
        test_result: TestResult | None = None,
    ) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        title_s = ParagraphStyle("T",    parent=styles["Title"],   fontSize=16, textColor=_NAVY, spaceAfter=6,  alignment=TA_LEFT)
        sub_s   = ParagraphStyle("Sub",  parent=styles["Normal"],  fontSize=10, textColor=rl_colors.grey, spaceAfter=12)
        h2_s    = ParagraphStyle("H2",   parent=styles["Heading2"],fontSize=12, textColor=_NAVY, spaceBefore=14, spaceAfter=6)
        body_s  = ParagraphStyle("Body", parent=styles["Normal"],  fontSize=10, spaceAfter=4)
        th_s    = ParagraphStyle("TH",   fontSize=9,  textColor=rl_colors.white, fontName="Helvetica-Bold")
        key_s   = ParagraphStyle("Key",  fontSize=9,  fontName="Helvetica-Bold")
        cel_s   = ParagraphStyle("Cel",  fontSize=9)
        sub_th  = ParagraphStyle("STH",  fontSize=8,  textColor=rl_colors.white, fontName="Helvetica-Bold")
        sub_td  = ParagraphStyle("STD",  fontSize=8)

        req_num      = getattr(request, "request_number", "") or ""
        eq_name      = (request.equipment_type.name if request and request.equipment_type else "") or ""
        session_name = session.session_name or f"Session {session.session_number}"
        date_str     = session.session_date.strftime("%d %b %Y") if session.session_date else "-"

        story = [
            Paragraph(f"Session Report — {session_name}", title_s),
            Paragraph(f"Request: {req_num}   |   Equipment: {eq_name}   |   Date: {date_str}", sub_s),
            Spacer(1, 0.1 * inch),
            self._meta_table(session, date_str, body_s),
            Spacer(1, 0.15 * inch),
        ]

        story += self._form_section(test_result, h2_s, th_s, key_s, cel_s, sub_th, sub_td)
        story += self._kit_section(test_result, h2_s)
        story += self._readings_section(readings, h2_s, body_s)

        doc.build(story)
        buf.seek(0)
        return buf.read()

    # ── private helpers ────────────────────────────────────────────────────────

    def _kv_style(self, hdr_color=None):
        hdr_color = hdr_color or _NAVY
        return TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), hdr_color),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f5f8ff")]),
            ("BOX",           (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CCCCCC")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#DDDDDD")),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ])

    def _meta_table(self, session: TestSession, date_str: str, body_s) -> Table:
        def row(label, value):
            return [Paragraph(label, body_s), Paragraph(str(value or "-"), body_s)]

        data = [
            row("Session Number", session.session_number),
            row("Status", (session.status or "-").replace("_", " ").upper()),
            row("Session Date", date_str),
            row("Started At",   session.started_at.strftime("%d/%m/%Y %H:%M")   if session.started_at   else "-"),
            row("Completed At", session.completed_at.strftime("%d/%m/%Y %H:%M") if session.completed_at else "-"),
            row("Weather Conditions", session.weather_conditions),
            row("Conducted By", session.conducted_by),
            row("Witnessed By", session.witnessed_by),
        ]
        if session.notes:
            data.append(row("Notes", session.notes))

        t = Table(data, colWidths=[2.2 * inch, 4.6 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), _LIGHT),
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f5f8ff")]),
            ("BOX",           (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CCCCCC")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#DDDDDD")),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]))
        return t

    def _form_section(self, test_result, h2_s, th_s, key_s, cel_s, sub_th, sub_td) -> list:
        if not (test_result and test_result.test_data):
            return []
        td = test_result.test_data
        overall = (td.get("overall_result") or "").upper()

        scalar_rows  = [[Paragraph("Field", th_s), Paragraph("Value", th_s)]]
        table_fields = []

        for k, v in td.items():
            if k == "overall_result":
                continue
            if isinstance(v, list) and v and isinstance(v[0], dict):
                table_fields.append((k, v))
            else:
                scalar_rows.append([
                    Paragraph(k.replace("_", " ").title(), key_s),
                    Paragraph(str(v) if v is not None else "—", cel_s),
                ])

        if overall:
            res_color = (
                rl_colors.HexColor("#1A7340") if overall == "PASS"
                else rl_colors.HexColor("#B71C1C") if overall == "FAIL"
                else rl_colors.black
            )
            scalar_rows.append([
                Paragraph("Overall Result", key_s),
                Paragraph(overall, ParagraphStyle("Res", fontSize=9, textColor=res_color, fontName="Helvetica-Bold")),
            ])

        items = [Paragraph("Form Submission", h2_s)]
        if len(scalar_rows) > 1:
            t = Table(scalar_rows, colWidths=[2.2 * inch, 4.6 * inch])
            t.setStyle(self._kv_style())
            items += [t, Spacer(1, 0.1 * inch)]

        for field_key, rows in table_fields:
            items.append(Paragraph(
                field_key.replace("_", " ").title(),
                ParagraphStyle("SubH", parent=h2_s, fontSize=10, spaceBefore=8, spaceAfter=4),
            ))
            cols  = list(rows[0].keys())
            col_w = (6.8 * inch) / max(len(cols), 1)
            sub_rows = [[Paragraph(c.replace("_", " ").title(), sub_th) for c in cols]] + [
                [Paragraph(str(row.get(c, "—")) if row.get(c) is not None else "—", sub_td) for c in cols]
                for row in rows
            ]
            sub_t = Table(sub_rows, colWidths=[col_w] * len(cols), repeatRows=1)
            sub_t.setStyle(self._kv_style(hdr_color=_TEAL))
            items += [sub_t, Spacer(1, 0.12 * inch)]

        return items

    def _kit_section(self, test_result, h2_s) -> list:
        if not (test_result and test_result.testing_kit_id and test_result.testing_kit):
            return []
        kit = test_result.testing_kit
        np  = kit.nameplate_data or {}
        kit_type = (
            np.get("kit_subtype")
            or kit.bay_number
            or (kit.equipment_type.name if kit.equipment_type else "Testing Kit")
        )
        th_s  = ParagraphStyle("KTH", fontSize=9, textColor=rl_colors.white, fontName="Helvetica-Bold")
        key_s = ParagraphStyle("KK",  fontSize=9, fontName="Helvetica-Bold")
        cel_s = ParagraphStyle("KC",  fontSize=9)

        kit_rows = [
            [Paragraph("Field",         th_s),  Paragraph("Value",                                         th_s)],
            [Paragraph("UEIC",          key_s), Paragraph(kit.ueic or "—",                                 cel_s)],
            [Paragraph("Kit Type",      key_s), Paragraph(kit_type,                                        cel_s)],
            [Paragraph("Manufacturer",  key_s), Paragraph(kit.manufacturer or "—",                         cel_s)],
            [Paragraph("Model Number",  key_s), Paragraph(kit.model_number or "—",                         cel_s)],
            [Paragraph("Serial Number", key_s), Paragraph(kit.factory_serial_number or "—",                cel_s)],
            [Paragraph("Location",      key_s), Paragraph(kit.department.name if kit.department else "—",  cel_s)],
        ]
        t = Table(kit_rows, colWidths=[2.2 * inch, 4.6 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _KIT_BLUE),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_KIT_ROW, rl_colors.white]),
            ("BOX",           (0, 0), (-1, -1), 0.5, _KIT_GRID),
            ("INNERGRID",     (0, 0), (-1, -1), 0.25, _KIT_GRID),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]))
        return [Paragraph("Testing Kit Used", h2_s), t, Spacer(1, 0.15 * inch)]

    def _readings_section(self, readings: list, h2_s, body_s) -> list:
        items = [Paragraph(f"Readings ({len(readings)})", h2_s)]
        if not readings:
            items.append(Paragraph("No readings recorded for this session.", body_s))
            return items

        all_keys: list = []
        for r in readings:
            if r.reading_data and isinstance(r.reading_data, dict):
                for k in r.reading_data:
                    if k not in all_keys:
                        all_keys.append(k)

        th_s  = ParagraphStyle("RTH", fontSize=9, textColor=rl_colors.white, fontName="Helvetica-Bold")
        cel_s = ParagraphStyle("RC",  fontSize=9)
        res_bold = lambda color: ParagraphStyle("Res", fontSize=9, textColor=color, fontName="Helvetica-Bold")

        headers    = ["#", "Time", *[k.replace("_", " ").title() for k in all_keys], "Serial", "Result", "Remarks"]
        header_row = [Paragraph(h, th_s) for h in headers]
        rows = [header_row]

        for r in readings:
            rd = r.reading_data or {}
            res_s = (r.result_status or "").lower()
            res_color = (
                rl_colors.HexColor("#1A7340") if res_s == "pass"
                else rl_colors.HexColor("#B71C1C") if res_s == "fail"
                else rl_colors.black
            )
            rows.append([
                Paragraph(str(r.reading_number), cel_s),
                Paragraph(str(r.reading_time or "-"), cel_s),
                *[Paragraph(str(rd.get(k, "-")), cel_s) for k in all_keys],
                Paragraph(str(r.equipment_serial or "-"), cel_s),
                Paragraph((r.result_status or "-").upper(), res_bold(res_color)),
                Paragraph(str(r.remarks or "-"), cel_s),
            ])

        fixed_w  = 0.4 * inch
        time_w   = 1.0 * inch
        serial_w = 1.0 * inch
        result_w = 0.7 * inch
        remark_w = 1.0 * inch
        remaining = (6.8 * inch) - fixed_w - time_w - serial_w - result_w - remark_w
        data_w    = remaining / max(len(all_keys), 1) if all_keys else 0
        col_widths = [fixed_w, time_w, *[data_w] * len(all_keys), serial_w, result_w, remark_w]

        t = Table(rows, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f5f8ff")]),
            ("BOX",           (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CCCCCC")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#DDDDDD")),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        items.append(t)
        return items
