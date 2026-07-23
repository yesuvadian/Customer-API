from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from sqlalchemy.orm import Session, joinedload

from models import TestingRequest, TestResult, User, OrgDepartment
from services.nameplate_helper import resolve_capacity, resolve_voltage_ratio


class TestingRequestPDFService:
    """Generate PDF reports for testing requests"""

    def __init__(self, db: Session):
        self.db = db

    def generate_pdf(self, request_id: str) -> BytesIO:
        """Generate PDF for a testing request"""
        print(f"[DEBUG] Starting PDF generation for request_id: {request_id}")

        testing_request = self.db.query(TestingRequest).options(
            joinedload(TestingRequest.equipment_type),
            joinedload(TestingRequest.test_type),
            joinedload(TestingRequest.department),
            joinedload(TestingRequest.originator),
            joinedload(TestingRequest.assigned_tester),
            joinedload(TestingRequest.completed_by),
            joinedload(TestingRequest.organization),
            joinedload(TestingRequest.equipment),
        ).filter(TestingRequest.id == request_id).first()

        if not testing_request:
            print(f"[ERROR] Testing request not found: {request_id}")
            raise ValueError(f"Testing request {request_id} not found")

        print(f"[DEBUG] Testing request found: {testing_request.request_number}")

        # Create PDF buffer
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []

        NAVY      = colors.HexColor('#0F2B6B')
        BLUE      = colors.HexColor('#1A56DB')
        PANEL_BG  = colors.HexColor('#EFF4FF')
        BORDER    = colors.HexColor('#CBD5E1')
        TEXT_DARK = colors.HexColor('#1E293B')

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=20,
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=NAVY,
            spaceAfter=10,
        )
        normal_style = styles['Normal']

        # Title
        story.append(Paragraph("Testing Request Form", title_style))
        story.append(Spacer(1, 0.1*inch))

        # Latest test result — used both as a fallback source for nameplate
        # fields the Equipment register never got populated with, and later
        # for the "Test Data" section.
        result = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == testing_request.id)
            .order_by(TestResult.cts.desc())
            .first()
        )

        # Equipment Nameplate Header
        eq = testing_request.equipment
        np_data = (eq.nameplate_data or {}) if eq else {}
        voltage = (eq.voltage_class if eq else '') or '-'
        capacity_str = resolve_capacity(np_data, result.test_data if result else {})
        voltage_ratio = resolve_voltage_ratio(
            np_data, result.test_data if result else {},
            voltage_class=eq.voltage_class if eq else None,
        )
        station = (testing_request.department.name if testing_request.department else '') or '-'
        serial  = (eq.factory_serial_number if eq else '') or '-'
        make    = (eq.manufacturer if eq else '') or '-'
        yom     = str(eq.year_of_manufacture) if eq and eq.year_of_manufacture else '-'
        doc_date = '-'
        if eq and eq.commissioned_date:
            doc_date = eq.commissioned_date.strftime('%d-%b-%y')

        ssmd = zone = '-'
        if testing_request.department and testing_request.department.parent_department_id:
            _parent = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == testing_request.department.parent_department_id).first()
            if _parent:
                ssmd = _parent.name or '-'
                if _parent.parent_department_id:
                    _gp = self.db.query(OrgDepartment).filter(
                        OrgDepartment.id == _parent.parent_department_id).first()
                    zone = (_gp.name if _gp else '-') or '-'

        np_table_data = [
            ['Name Of Station', station,     'Capacity',      capacity_str, 'Serial Number', serial],
            ['SSMD',           ssmd,         'Voltage Class', voltage,      'Date Of Commission', doc_date],
            ['Zone',           zone,         'Make',          make,         'YOM',           yom],
            ['Voltage Ratio',  voltage_ratio, '',              '',           '',                ''],
        ]
        col_w = [1.0*inch, 1.4*inch, 1.0*inch, 1.0*inch, 1.3*inch, 0.8*inch]
        np_tbl = Table(np_table_data, colWidths=col_w)
        np_tbl.setStyle(TableStyle([
            ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica'),
            ('FONTNAME',   (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME',   (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTNAME',   (4, 0), (4, -1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#dde6f5')),
            ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#dde6f5')),
            ('BACKGROUND', (4, 0), (4, -1), colors.HexColor('#dde6f5')),
            ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#f0f4ff')),
            ('BACKGROUND', (3, 0), (3, -1), colors.HexColor('#f0f4ff')),
            ('BACKGROUND', (5, 0), (5, -1), colors.HexColor('#f0f4ff')),
            ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#c5d3f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('TEXTCOLOR',  (0, 0), (0, -1), colors.HexColor('#1b3a6b')),
            ('TEXTCOLOR',  (2, 0), (2, -1), colors.HexColor('#1b3a6b')),
            ('TEXTCOLOR',  (4, 0), (4, -1), colors.HexColor('#1b3a6b')),
        ]))
        story.append(np_tbl)
        story.append(Spacer(1, 0.2*inch))

        # Document Info Table
        doc_info_data = [
            ['Report Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Request Number:', testing_request.request_number or '-'],
        ]
        doc_info_table = Table(doc_info_data, colWidths=[2*inch, 4*inch])
        doc_info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(doc_info_table)
        story.append(Spacer(1, 0.3*inch))

        # Basic Information
        story.append(Paragraph("Request Information", heading_style))

        request_data = [
            ['Title:', testing_request.title or '-'],
            ['Priority:', (testing_request.priority or '-').upper() if isinstance(testing_request.priority, str) else (testing_request.priority.value.upper() if testing_request.priority else '-')],
        ]

        if testing_request.description:
            request_data.append(['Description:', testing_request.description])

        if testing_request.equipment and testing_request.equipment.ueic:
            request_data.append(['UEIC:', testing_request.equipment.ueic])

        request_data.extend([
            ['Equipment Type:', testing_request.equipment_type.name if testing_request.equipment_type else '-'],
            ['Test Type:', testing_request.test_type.name if testing_request.test_type else '-'],
        ])

        request_table = Table(request_data, colWidths=[2*inch, 4*inch])
        request_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0F0F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(request_table)
        story.append(Spacer(1, 0.3*inch))

        # Equipment Details (if available)
        equipment_details = []
        if testing_request.transformer_type:
            equipment_details.append(['Transformer Type:', testing_request.transformer_type])
        if testing_request.transformer_rating:
            equipment_details.append(['Transformer Rating:', testing_request.transformer_rating])
        if testing_request.manufacturer:
            equipment_details.append(['Manufacturer:', testing_request.manufacturer])
        if testing_request.serial_number:
            equipment_details.append(['Serial Number:', testing_request.serial_number])

        if equipment_details:
            story.append(Paragraph("Equipment Details", heading_style))
            equipment_table = Table(equipment_details, colWidths=[2*inch, 4*inch])
            equipment_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), NAVY),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
                ('BACKGROUND', (0, 0), (0, -1), PANEL_BG),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(equipment_table)
            story.append(Spacer(1, 0.3*inch))

        # Organization and Requester Information
        story.append(Paragraph("Organization & Requester", heading_style))

        def _pdf_user_name(u) -> str:
            if not u:
                return '-'
            return (f"{u.firstname or ''} {u.lastname or ''}".strip()) or u.email or '-'

        requester_name = _pdf_user_name(testing_request.originator)
        requester_email = testing_request.originator.email if testing_request.originator else '-'
        tester_name = _pdf_user_name(testing_request.assigned_tester)
        completed_by_name = _pdf_user_name(testing_request.completed_by) if testing_request.completed_by_id else None

        org_data = [
            ['Department:', testing_request.department.name if testing_request.department else '-'],
            ['Requested By:', requester_name],
            ['Requester Email:', requester_email],
            ['Assigned Tester:', tester_name],
            ['Submitted On:', testing_request.cts.strftime('%Y-%m-%d %H:%M:%S') if testing_request.cts else '-'],
        ]
        if completed_by_name:
            org_data.append(['Tested By:', completed_by_name])

        org_table = Table(org_data, colWidths=[2*inch, 4*inch])
        org_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), NAVY),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('BACKGROUND', (0, 0), (0, -1), PANEL_BG),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(org_table)
        story.append(Spacer(1, 0.3*inch))

        # Additional Notes (if available)
        if testing_request.notes:
            story.append(Paragraph("Additional Notes", heading_style))
            notes_data = [['Notes:', testing_request.notes]]
            notes_table = Table(notes_data, colWidths=[2*inch, 4*inch])
            notes_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), NAVY),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
                ('BACKGROUND', (0, 0), (0, -1), PANEL_BG),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(notes_table)
            story.append(Spacer(1, 0.3*inch))

        # Status indicator box
        status_text, status_color = self._get_status_display(testing_request.status.value if testing_request.status else 'draft')

        status_table = Table([[status_text]], colWidths=[6*inch])
        status_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, -1), status_color),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(status_table)

        # ── Test Result Data (generic — works for any template) ──────────────
        if result and result.test_data:
            story.append(Spacer(1, 0.2 * inch))
            story.append(Paragraph("Test Data", heading_style))

            td = result.test_data
            navy   = colors.HexColor("#1B3A6B")
            teal   = colors.HexColor("#006D7E")
            light  = colors.HexColor("#f5f8ff")

            cell_s = ParagraphStyle("C",  fontSize=9)
            key_s  = ParagraphStyle("K",  fontSize=9, fontName="Helvetica-Bold")
            th_s   = ParagraphStyle("TH", fontSize=9, textColor=colors.white, fontName="Helvetica-Bold")
            sub_th = ParagraphStyle("STH",fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")
            sub_td = ParagraphStyle("STD",fontSize=8)

            def _tbl(hdr_color=navy):
                return TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0), hdr_color),
                    ("FONTSIZE",      (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, light]),
                    ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                    ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING",    (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ])

            scalar_rows  = [[Paragraph("Field", th_s), Paragraph("Value", th_s)]]
            table_fields = []
            overall      = None

            for k, v in td.items():
                if k == "overall_result":
                    overall = str(v).upper() if v else None
                    continue
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    table_fields.append((k, v))
                else:
                    scalar_rows.append([
                        Paragraph(k.replace("_", " ").title(), key_s),
                        Paragraph(str(v) if v is not None else "—", cell_s),
                    ])

            if overall:
                res_color = colors.HexColor("#1A7340") if overall == "PASS" \
                    else colors.HexColor("#B71C1C") if overall == "FAIL" \
                    else colors.black
                scalar_rows.append([
                    Paragraph("Overall Result", key_s),
                    Paragraph(overall, ParagraphStyle("R", fontSize=9,
                              textColor=res_color, fontName="Helvetica-Bold")),
                ])

            if len(scalar_rows) > 1:
                t = Table(scalar_rows, colWidths=[2.2 * inch, 4.6 * inch])
                t.setStyle(_tbl())
                story += [t, Spacer(1, 0.1 * inch)]

            for field_key, rows in table_fields:
                story.append(Paragraph(
                    field_key.replace("_", " ").title(),
                    ParagraphStyle("SubH", parent=heading_style, fontSize=10, spaceBefore=8, spaceAfter=4)
                ))
                cols  = list(rows[0].keys())
                col_w = (6.8 * inch) / max(len(cols), 1)
                sub_header = [Paragraph(c.replace("_", " ").title(), sub_th) for c in cols]
                sub_rows = [sub_header] + [
                    [Paragraph(str(row.get(c, "—")) if row.get(c) is not None else "—", sub_td)
                     for c in cols]
                    for row in rows
                ]
                sub_t = Table(sub_rows, colWidths=[col_w] * len(cols), repeatRows=1)
                sub_t.setStyle(_tbl(hdr_color=teal))
                story += [sub_t, Spacer(1, 0.12 * inch)]

        # ── Testing Kit Used ────────────────────────────────────────────────
        if result and result.testing_kit_id and result.testing_kit:
            kit = result.testing_kit
            np = kit.nameplate_data or {}
            kit_type = (
                np.get("kit_subtype")
                or kit.bay_number
                or (kit.equipment_type.name if kit.equipment_type else "Testing Kit")
            )
            _th_s  = ParagraphStyle("KTH", fontSize=9, textColor=colors.white, fontName="Helvetica-Bold")
            _key_s = ParagraphStyle("KK",  fontSize=9, fontName="Helvetica-Bold")
            _cel_s = ParagraphStyle("KC",  fontSize=9)
            story.append(Spacer(1, 0.1 * inch))
            story.append(Paragraph("Testing Kit Used", heading_style))
            kit_rows = [
                [Paragraph("Field", _th_s), Paragraph("Value", _th_s)],
                [Paragraph("UEIC", _key_s), Paragraph(kit.ueic or "—", _cel_s)],
                [Paragraph("Kit Type", _key_s), Paragraph(kit_type, _cel_s)],
                [Paragraph("Manufacturer", _key_s), Paragraph(kit.manufacturer or "—", _cel_s)],
                [Paragraph("Model Number", _key_s), Paragraph(kit.model_number or "—", _cel_s)],
                [Paragraph("Serial Number", _key_s), Paragraph(kit.factory_serial_number or "—", _cel_s)],
                [Paragraph("Location", _key_s), Paragraph(kit.department.name if kit.department else "—", _cel_s)],
            ]
            kit_t = Table(kit_rows, colWidths=[2.2 * inch, 4.6 * inch])
            kit_t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1A5276")),
                ("FONTSIZE",      (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#EBF5FB"), colors.white]),
                ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#AED6F1")),
                ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#AED6F1")),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ]))
            story += [kit_t, Spacer(1, 0.12 * inch)]

        # ── Evaluation ──────────────────────────────────────────────────────
        if result and result.evaluation_result:
            ev_fields = (result.evaluation_result or {}).get("fields", [])
            if ev_fields:
                story.append(Spacer(1, 0.1 * inch))
                story.append(Paragraph("Evaluation", heading_style))

                STATUS_CLR = {
                    "normal":   colors.HexColor("#1A7340"),
                    "alert":    colors.HexColor("#C75B00"),
                    "critical": colors.HexColor("#B71C1C"),
                }

                ev_th  = ParagraphStyle("EvTH", fontSize=9, textColor=colors.white, fontName="Helvetica-Bold")
                ev_key = ParagraphStyle("EvK",  fontSize=9)
                ev_val = ParagraphStyle("EvV",  fontSize=9)

                ev_rows = [[
                    Paragraph("Parameter", ev_th),
                    Paragraph("Value",     ev_th),
                    Paragraph("Status",    ev_th),
                ]]
                for f in ev_fields:
                    s = (f.get("status") or "").lower()
                    s_clr = STATUS_CLR.get(s, colors.HexColor("#555555"))
                    if f.get("type") == "table":
                        agg = f.get("aggregate_result")
                        if agg is not None:
                            val_str = str(agg)
                        else:
                            col_results = f.get("column_results") or []
                            flagged = [r for r in col_results if r.get("status") in ("ALERT", "CRITICAL")]
                            source = flagged if flagged else col_results
                            by_col: dict = {}
                            for r in source:
                                col = r.get("column", "")
                                val = r.get("value")
                                if val is not None:
                                    by_col.setdefault(col, []).append(val)
                            if by_col:
                                parts = []
                                for col, vals in by_col.items():
                                    lbl = " ".join(w.capitalize() for w in col.split("_"))
                                    parts.append(f"{lbl}: {', '.join(str(v) for v in vals)}")
                                val_str = " | ".join(parts)
                            else:
                                val_str = "—"
                    else:
                        raw = f.get("value")
                        unit = (f.get("unit") or "").strip()
                        val_str = f"{raw} {unit}".strip() if raw is not None else "—"

                    ev_rows.append([
                        Paragraph(f.get("label", f.get("key", "")), ev_key),
                        Paragraph(val_str, ev_val),
                        Paragraph(s.upper() if s else "—",
                                  ParagraphStyle("EvS", fontSize=9, fontName="Helvetica-Bold",
                                                 textColor=s_clr)),
                    ])

                ev_t = Table(ev_rows, colWidths=[3.2 * inch, 2.0 * inch, 1.6 * inch], repeatRows=1)
                ev_t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1B3A6B")),
                    ("FONTSIZE",      (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8ff")]),
                    ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                    ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING",    (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ]))
                story += [ev_t, Spacer(1, 0.15 * inch)]

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def _get_status_display(self, status: str):
        """Get status display text and color"""
        status_map = {
            'draft': ('DRAFT', colors.grey),
            'submitted': ('PENDING APPROVAL', colors.orange),
            'pending_approval': ('PENDING APPROVAL', colors.orange),
            'approved': ('APPROVED', colors.green),
            'rejected': ('REJECTED', colors.red),
            'assigned': ('ASSIGNED', colors.blue),
            'accepted': ('ACCEPTED', colors.HexColor('#4CAF50')),
            'in_progress': ('IN PROGRESS', colors.HexColor('#2196F3')),
            'test_submitted': ('TEST SUBMITTED', colors.HexColor('#9C27B0')),
            'under_approval': ('UNDER APPROVAL', colors.HexColor('#FF9800')),
            'completed': ('COMPLETED', colors.HexColor('#4CAF50')),
            'cancelled': ('CANCELLED', colors.HexColor('#F44336')),
        }
        return status_map.get(status, (status.upper(), colors.grey))
