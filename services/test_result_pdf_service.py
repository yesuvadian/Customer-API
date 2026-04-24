from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from sqlalchemy.orm import Session
from uuid import UUID

from models import TestResult, TestSession, TestSessionReading, TestingRequest, User
from sqlalchemy.orm import joinedload


class TestResultPDFService:
    """Generate PDF reports for test results with full details"""

    def __init__(self, db: Session):
        self.db = db

    def _render_test_data_structure(self, data, story, heading_style, subheading_style, normal_style):
        """
        Intelligently render test data based on structure:
        - List of dicts with consistent keys → Table
        - Dict with simple key-value pairs → Two-column layout
        - Section with nested data → Heading + recursive render
        """
        for key, value in data.items():
            # Format section name
            section_name = ' '.join(word.capitalize() for word in key.split('_'))

            if isinstance(value, list) and value and isinstance(value[0], dict):
                # LIST OF DICTS → RENDER AS TABLE
                story.append(Paragraph(section_name, subheading_style))
                self._render_table_from_list(value, story)
                story.append(Spacer(1, 0.15*inch))

            elif isinstance(value, dict):
                # Check if it's a simple key-value dict or nested structure
                has_nested = any(isinstance(v, (dict, list)) for v in value.values())

                if has_nested:
                    # NESTED DICT → SECTION HEADING + RECURSIVE
                    story.append(Paragraph(section_name, subheading_style))
                    self._render_test_data_structure(value, story, heading_style, subheading_style, normal_style)
                else:
                    # SIMPLE KEY-VALUE DICT → TWO-COLUMN LAYOUT
                    story.append(Paragraph(section_name, subheading_style))
                    self._render_two_column_layout(value, story)
                    story.append(Spacer(1, 0.15*inch))

            else:
                # SIMPLE VALUE → TWO-COLUMN ROW
                self._render_two_column_layout({key: value}, story)
                story.append(Spacer(1, 0.1*inch))

    def _render_table_from_list(self, data_list, story):
        """Render a list of dicts as a table (e.g., test readings)"""
        if not data_list:
            return

        # Extract headers from first dict
        headers = list(data_list[0].keys())
        formatted_headers = [' '.join(word.capitalize() for word in h.split('_')) for h in headers]

        # Build table rows
        table_rows = [formatted_headers]
        for item in data_list:
            row = [str(item.get(h, '-')) for h in headers]
            table_rows.append(row)

        # Calculate column widths dynamically
        num_cols = len(headers)
        col_width = 6.5 / num_cols
        col_widths = [col_width * inch] * num_cols

        table = Table(table_rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3C72')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            # Data rows
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),

            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),

            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#DDDDDD')),
        ]))
        story.append(table)

    def _render_two_column_layout(self, data_dict, story):
        """Render simple key-value pairs in two columns"""
        rows = []
        for key, value in data_dict.items():
            field_name = ' '.join(word.capitalize() for word in key.split('_'))
            formatted_value = str(value) if value is not None else '-'
            rows.append([field_name, formatted_value])

        table = Table(rows, colWidths=[2.5*inch, 4*inch])
        table.setStyle(TableStyle([
            # Field names (left column)
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),

            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),

            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#DDDDDD')),
        ]))
        story.append(table)

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION DATA SECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _render_session_data(self, request_id, story, heading_style, subheading_style, normal_style):
        """
        Append a 'Session Data' section to the PDF story for all TestSessions
        linked to request_id.  Each session is rendered with a header row
        (name + status badge) followed by a readings table.
        """
        sessions = (
            self.db.query(TestSession)
            .options(joinedload(TestSession.readings))
            .filter(TestSession.testing_request_id == request_id)
            .order_by(TestSession.session_number)
            .all()
        )
        if not sessions:
            return

        story.append(PageBreak())
        story.append(Paragraph("Session Data", heading_style))
        story.append(Spacer(1, 0.1 * inch))

        STATUS_COLORS = {
            "completed":  colors.HexColor("#4CAF50"),
            "in_progress": colors.HexColor("#FF9800"),
            "skipped":    colors.HexColor("#F44336"),
            "scheduled":  colors.HexColor("#9E9E9E"),
        }
        RESULT_COLORS = {
            "pass":        colors.HexColor("#4CAF50"),
            "fail":        colors.HexColor("#F44336"),
            "conditional": colors.HexColor("#FF9800"),
            "warning":     colors.HexColor("#FFC107"),
        }

        def _fmt(dt):
            return dt.strftime("%d/%m/%Y %H:%M") if dt else "-"

        for session in sessions:
            status = (session.status or "scheduled").lower()
            status_color = STATUS_COLORS.get(status, colors.HexColor("#9E9E9E"))
            session_label = (
                session.session_name
                or f"Session {session.session_number}"
            )

            # ── Session header bar ──────────────────────────────────────────
            hdr = Table(
                [[f"Session {session.session_number}:  {session_label}", status.upper()]],
                colWidths=[5.0 * inch, 1.5 * inch],
            )
            hdr.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (0, 0), colors.HexColor("#1E3C72")),
                ("BACKGROUND",   (1, 0), (1, 0), status_color),
                ("TEXTCOLOR",    (0, 0), (-1, -1), colors.white),
                ("FONTNAME",     (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 11),
                ("ALIGN",        (0, 0), (0, 0), "LEFT"),
                ("ALIGN",        (1, 0), (1, 0), "CENTER"),
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",   (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
                ("LEFTPADDING",  (0, 0), (0, 0), 12),
            ]))
            story.append(hdr)

            # ── Session metadata ────────────────────────────────────────────
            meta_rows = [
                ["Date",       _fmt(session.session_date)],
                ["Started",    _fmt(session.started_at)],
                ["Completed",  _fmt(session.completed_at)],
            ]
            if session.notes:
                meta_rows.append(["Notes", session.notes])
            if session.weather_conditions:
                meta_rows.append(["Weather", session.weather_conditions])
            if session.witnessed_by:
                meta_rows.append(["Witnessed By", session.witnessed_by])

            meta = Table(meta_rows, colWidths=[1.5 * inch, 5.0 * inch])
            meta.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#F8F9FA")),
                ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 9),
                ("TEXTCOLOR",    (0, 0), (0, -1), colors.HexColor("#555555")),
                ("ALIGN",        (0, 0), (-1, -1), "LEFT"),
                ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
                ("LEFTPADDING",  (0, 0), (-1, -1), 10),
                ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            ]))
            story.append(meta)
            story.append(Spacer(1, 0.1 * inch))

            # ── Readings table ──────────────────────────────────────────────
            readings = sorted(session.readings or [], key=lambda r: r.reading_number)
            if not readings:
                story.append(Paragraph("No readings recorded for this session.", normal_style))
                story.append(Spacer(1, 0.2 * inch))
                continue

            story.append(Paragraph(f"Readings  ({len(readings)})", subheading_style))

            # Collect all measurement keys across readings (preserving insertion order)
            all_keys: list[str] = []
            for r in readings:
                for k in (r.reading_data or {}).keys():
                    if k not in all_keys:
                        all_keys.append(k)

            # Header: #  |  Time  |  Result  |  <measurement cols>  |  Remarks
            col_headers = (
                ["#", "Time", "Result"]
                + [" ".join(w.capitalize() for w in k.split("_")) for k in all_keys]
                + ["Remarks"]
            )
            table_rows = [col_headers]
            for r in readings:
                result_label = (r.result_status or "-").upper()
                row = [
                    str(r.reading_number),
                    _fmt(r.reading_time),
                    result_label,
                ]
                for k in all_keys:
                    row.append(str((r.reading_data or {}).get(k, "-")))
                row.append(r.remarks or "-")
                table_rows.append(row)

            # Dynamic column widths (total 6.5 in)
            n_measure = len(all_keys)
            fixed_w = 0.35 + 0.90 + 0.70 + 1.10  # #, Time, Result, Remarks
            measure_w = max(0.5, (6.5 - fixed_w) / max(n_measure, 1))
            col_widths_r = (
                [0.35 * inch, 0.90 * inch, 0.70 * inch]
                + [measure_w * inch] * n_measure
                + [1.10 * inch]
            )

            rtable = Table(table_rows, colWidths=col_widths_r, repeatRows=1)
            rtable.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#2A5298")),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 8),
                ("ALIGN",        (0, 0), (2, -1), "CENTER"),
                ("ALIGN",        (3, 0), (-1, -1), "LEFT"),
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1),
                    [colors.white, colors.HexColor("#EEF2FF")]),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ]))
            story.append(rtable)
            story.append(Spacer(1, 0.3 * inch))

    def generate_pdf(self, result_id: UUID) -> BytesIO:
        """Generate PDF for a test result with all test data"""
        result = self.db.query(TestResult).filter(
            TestResult.id == result_id
        ).first()

        if not result:
            raise ValueError(f"Test Result {result_id} not found")

        # Get testing request with all related data
        testing_request = self.db.query(TestingRequest).options(
            joinedload(TestingRequest.equipment_type),
            joinedload(TestingRequest.test_type),
            joinedload(TestingRequest.department),
            joinedload(TestingRequest.originator),
            joinedload(TestingRequest.assigned_tester),
            joinedload(TestingRequest.organization),
            joinedload(TestingRequest.equipment),
        ).filter(TestingRequest.id == result.testing_request_id).first()

        # Get tester
        tester = None
        if result.tested_by:
            tester = self.db.query(User).filter(User.id == result.tested_by).first()

        # Create PDF buffer
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch,
            leftMargin=0.75*inch,
            rightMargin=0.75*inch
        )
        story = []

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=22,
            textColor=colors.HexColor('#1E3C72'),
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName='Helvetica-Bold',
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#1E3C72'),
            spaceAfter=12,
            spaceBefore=16,
            fontName='Helvetica-Bold',
        )
        subheading_style = ParagraphStyle(
            'CustomSubHeading',
            parent=styles['Heading3'],
            fontSize=13,
            textColor=colors.HexColor('#2A5298'),
            spaceAfter=8,
            fontName='Helvetica-Bold',
        )
        normal_style = styles['Normal']
        normal_style.fontSize = 10

        # ============================================================
        # HEADER - TITLE
        # ============================================================
        story.append(Paragraph("TEST RESULT REPORT", title_style))
        story.append(Spacer(1, 0.1*inch))

        # Result Badge
        result_color = colors.HexColor('#4CAF50') if result.overall_result and result.overall_result.lower() == 'pass' else \
                      colors.HexColor('#f44336') if result.overall_result and result.overall_result.lower() == 'fail' else \
                      colors.HexColor('#ff9800')

        result_badge = Table(
            [[result.overall_result or 'N/A']],
            colWidths=[2*inch]
        )
        result_badge.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), result_color),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('ROUNDEDCORNERS', [10, 10, 10, 10]),
        ]))
        story.append(result_badge)
        story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # DOCUMENT INFO
        # ============================================================
        doc_info_data = [
            ['Report Generated:', datetime.now().strftime('%d/%m/%Y %H:%M:%S')],
            ['Report ID:', str(result.id)[:8] + '...'],
        ]
        doc_info_table = Table(doc_info_data, colWidths=[2*inch, 4.5*inch])
        doc_info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(doc_info_table)
        story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # TEST INFORMATION
        # ============================================================
        story.append(Paragraph("Test Information", heading_style))

        test_info_data = [
            ['Test Name:', result.test_name or result.template_key or '-'],
            ['Template Key:', result.template_key or '-'],
            ['Test Category:', result.test_category or '-'],
            ['Tested At:', result.tested_at.strftime('%d/%m/%Y %H:%M:%S') if result.tested_at else '-'],
            ['Tested By:', f"{tester.firstname} {tester.lastname}" if tester else '-'],
        ]

        test_info_table = Table(test_info_data, colWidths=[2*inch, 4.5*inch])
        test_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8F9FA')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
        ]))
        story.append(test_info_table)
        story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # REQUEST INFORMATION
        # ============================================================
        if testing_request:
            story.append(Paragraph("Testing Request Details", heading_style))

            request_data = [
                ['Request Number:', testing_request.request_number or '-'],
                ['Title:', testing_request.title or '-'],
                ['Equipment Type:', testing_request.equipment_type.name if testing_request.equipment_type else '-'],
                ['Test Type:', testing_request.test_type.name if testing_request.test_type else '-'],
                ['Organization:', testing_request.organization.name if testing_request.organization else '-'],
                ['Status:', testing_request.status.value if testing_request.status else '-'],
            ]

            request_table = Table(request_data, colWidths=[2*inch, 4.5*inch])
            request_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8F9FA')),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
            ]))
            story.append(request_table)
            story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # TEST DATA
        # ============================================================
        story.append(Paragraph("Test Data", heading_style))

        test_data = result.test_data or {}

        if test_data:
            self._render_test_data_structure(test_data, story, heading_style, subheading_style, normal_style)
        else:
            story.append(Paragraph("No test data available.", normal_style))

        story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # SESSION DATA  (multi-session testing — all sessions + readings)
        # ============================================================
        self._render_session_data(
            result.testing_request_id, story, heading_style, subheading_style, normal_style
        )

        # ============================================================
        # REMARKS
        # ============================================================
        if result.remarks:
            story.append(Paragraph("Remarks", heading_style))

            remarks_data = [[result.remarks]]
            remarks_table = Table(remarks_data, colWidths=[6.5*inch])
            remarks_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF3CD')),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#856404')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('LEFTPADDING', (0, 0), (-1, -1), 15),
                ('RIGHTPADDING', (0, 0), (-1, -1), 15),
                ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#FFC107')),
            ]))
            story.append(remarks_table)
            story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # EVALUATION RESULTS
        # ============================================================
        if result.evaluation_result:
            story.append(Paragraph("Evaluation Results", heading_style))

            eval_data = result.evaluation_result
            overall_eval = eval_data.get('overall', 'N/A')
            alerts = eval_data.get('alerts', [])

            # Overall evaluation badge
            eval_color = colors.HexColor('#4CAF50') if overall_eval == 'OK' else \
                        colors.HexColor('#f44336') if overall_eval == 'CRITICAL' else \
                        colors.HexColor('#ff9800')

            eval_badge_data = [['Overall Evaluation', overall_eval]]
            eval_badge = Table(eval_badge_data, colWidths=[3*inch, 3.5*inch])
            eval_badge.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#F8F9FA')),
                ('BACKGROUND', (1, 0), (1, 0), eval_color),
                ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('TEXTCOLOR', (0, 0), (0, 0), colors.HexColor('#333333')),
                ('TEXTCOLOR', (1, 0), (1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
            ]))
            story.append(eval_badge)
            story.append(Spacer(1, 0.15*inch))

            # Alerts
            if alerts:
                story.append(Paragraph("Alerts & Warnings:", subheading_style))

                alert_rows = []
                for alert in alerts:
                    level = alert.get('level', 'info')
                    message = alert.get('message', '')

                    icon = '⚠' if level in ['warning', 'ALERT'] else '🚨' if level == 'CRITICAL' else 'ℹ'
                    alert_rows.append([icon, message])

                if alert_rows:
                    alerts_table = Table(alert_rows, colWidths=[0.5*inch, 6*inch])
                    alerts_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF3CD')),
                        ('FONTSIZE', (0, 0), (-1, -1), 10),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#856404')),
                        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('TOPPADDING', (0, 0), (-1, -1), 8),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                        ('LEFTPADDING', (0, 0), (-1, -1), 10),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#FFC107')),
                    ]))
                    story.append(alerts_table)

            story.append(Spacer(1, 0.3*inch))

        # ============================================================
        # FOOTER
        # ============================================================
        story.append(Spacer(1, 0.5*inch))
        footer_style = ParagraphStyle(
            'Footer',
            parent=normal_style,
            fontSize=8,
            textColor=colors.HexColor('#999999'),
            alignment=TA_CENTER,
        )
        story.append(Paragraph(
            f"Generated by SEACMS Test Management System | {datetime.now().strftime('%d %B %Y')}",
            footer_style
        ))
        story.append(Paragraph("This is a computer-generated document. No signature is required.", footer_style))

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
