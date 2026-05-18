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
from sqlalchemy import func


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
        Render session data as a single table where:
          - ROWS  = sessions / days (Session cell is merged / spanned across all
                    its readings so the day label appears once on the left)
          - COLS  = template measurement fields (same across all sessions because
                    all sessions share the same template)

        Layout:
          Session / Day  |  R#  |  <measurement columns…>  |  Result  |  Remarks
          ───────────────┼──────┼──────────────────────────┼──────────┼─────────
          Session 1      │  1   │  …                       │  PASS    │  …
          Day 1          │  2   │  …                       │  PASS    │  …
          01/04/2026     │  3   │  …                       │  PASS    │  …
          ───────────────┼──────┼──────────────────────────┼──────────┼─────────
          Session 2      │  1   │  …                       │  PASS    │  …
          …
        """
        sessions = (
            self.db.query(TestSession)
            .filter(TestSession.testing_request_id == request_id)
            .order_by(TestSession.session_number)
            .all()
        )
        if not sessions:
            return

        # Count TestResult rows per session + fetch reading value for cumulative tests
        session_ids = [s.id for s in sessions]
        result_count_rows = (
            self.db.query(TestResult.test_session_id, func.count(TestResult.id))
            .filter(TestResult.test_session_id.in_(session_ids))
            .group_by(TestResult.test_session_id)
            .all()
        )
        result_counts: dict = {str(sid): cnt for sid, cnt in result_count_rows}

        # Fetch latest reading value per session (for cumulative display)
        session_reading_values: dict = {}
        for _sid in session_ids:
            _tr = (
                self.db.query(TestResult)
                .filter(TestResult.test_session_id == _sid)
                .order_by(TestResult.cts.desc())
                .first()
            )
            if _tr and _tr.test_data and "reading" in _tr.test_data:
                session_reading_values[str(_sid)] = _tr.test_data["reading"]

        # Detect cumulative request
        _tr_req = self.db.query(TestingRequest).filter(
            TestingRequest.id == request_id
        ).first()
        is_cumulative = bool(_tr_req and _tr_req.is_cumulative)
        if not is_cumulative and session_reading_values:
            _sample = (
                self.db.query(TestResult)
                .filter(TestResult.test_session_id.in_(session_ids))
                .first()
            )
            if _sample and getattr(_sample, "template_key", None) == "operations_tracking":
                is_cumulative = True

        story.append(PageBreak())
        story.append(Paragraph("Session Data", heading_style))
        story.append(Spacer(1, 0.1 * inch))

        STATUS_COLORS = {
            "completed":   colors.HexColor("#4CAF50"),
            "in_progress": colors.HexColor("#FF9800"),
            "skipped":     colors.HexColor("#F44336"),
            "scheduled":   colors.HexColor("#9E9E9E"),
        }
        RESULT_COLORS = {
            "pass":        colors.HexColor("#4CAF50"),
            "fail":        colors.HexColor("#F44336"),
            "conditional": colors.HexColor("#FF9800"),
            "warning":     colors.HexColor("#FFC107"),
        }

        def _fmt_date(dt):
            return dt.strftime("%d/%m/%Y") if dt else "-"

        def _duration(s):
            if s.started_at and s.completed_at:
                mins = int((s.completed_at - s.started_at).total_seconds() / 60)
                return f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
            return "-"

        # ════════════════════════════════════════════════════════════════
        # PART 1 — Session Summary (one row per session)
        # ════════════════════════════════════════════════════════════════
        story.append(Paragraph("Session Summary", subheading_style))

        _rv_header = "Reading Value" if is_cumulative else "Submissions"
        sum_hdr = ["#", "Session Name", "Date", _rv_header, "Duration", "Status"]
        sum_rows = [sum_hdr]
        for s in sessions:
            if is_cumulative:
                _rv = session_reading_values.get(str(s.id))
                _rv_cell = str(_rv) if _rv is not None else "-"
            else:
                r_count = result_counts.get(str(s.id), len(s.readings or []))
                _rv_cell = str(r_count)
            sum_rows.append([
                str(s.session_number),
                s.session_name or f"Session {s.session_number}",
                _fmt_date(s.session_date),
                _rv_cell,
                _duration(s),
                (s.status or "scheduled").upper(),
            ])

        sum_styles = [
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3C72")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("ALIGN",         (1, 1), (1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
        ]
        for i, s in enumerate(sessions):
            ri_s = i + 1
            sc = STATUS_COLORS.get((s.status or "scheduled").lower(), colors.HexColor("#9E9E9E"))
            sum_styles += [
                ("BACKGROUND", (5, ri_s), (5, ri_s), sc),
                ("TEXTCOLOR",  (5, ri_s), (5, ri_s), colors.white),
                ("FONTNAME",   (5, ri_s), (5, ri_s), "Helvetica-Bold"),
            ]

        sum_table = Table(
            sum_rows,
            colWidths=[0.45*inch, 2.35*inch, 1.10*inch, 0.70*inch, 0.80*inch, 1.10*inch],
            repeatRows=1,
        )
        sum_table.setStyle(TableStyle(sum_styles))
        story.append(sum_table)
        story.append(Spacer(1, 0.25 * inch))

        # ════════════════════════════════════════════════════════════════
        # PART 2 — Merged-cell Readings Table
        # Session / Day column spans vertically across all readings of
        # that session so the day label appears once on the left.
        # Columns = template measurement fields (identical across sessions)
        # ════════════════════════════════════════════════════════════════

        # Collect measurement keys from ALL sessions (template is the same,
        # so keys will be identical — we union just to be safe)
        all_keys: list = []
        for s in sessions:
            for r in sorted(s.readings or [], key=lambda x: x.reading_number):
                for k in (r.reading_data or {}).keys():
                    if k not in all_keys:
                        all_keys.append(k)

        has_readings = any(s.readings for s in sessions)
        if not has_readings:
            story.append(Paragraph("No readings recorded.", normal_style))
            return

        total_readings = sum(len(s.readings or []) for s in sessions)
        story.append(Paragraph(
            f"Detailed Readings  ({total_readings} readings across {len(sessions)} sessions)",
            subheading_style,
        ))

        readable_keys = [" ".join(w.capitalize() for w in k.split("_")) for k in all_keys]

        # Column layout: Session/Day | R# | [measurement cols] | Result | Remarks
        col_headers  = ["Session / Day", "R#"] + readable_keys + ["Result", "Remarks"]
        num_cols     = len(col_headers)
        result_col   = num_cols - 2   # second-to-last
        remarks_col  = num_cols - 1   # last

        # Alternating backgrounds per session group (blue tones vs green tones)
        SESSION_ROW_BG  = [colors.HexColor("#EEF4FF"), colors.HexColor("#F4FFF4")]
        SESSION_CELL_BG = [colors.HexColor("#C8D9F5"), colors.HexColor("#C8EDD5")]

        table_rows = [col_headers]
        ts_list = [
            # ── Header ──────────────────────────────────────────────────────
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1E3C72")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (0, 0), (-1, 0),           "CENTER"),   # header: all centred
            # ── Data column alignment ────────────────────────────────────────
            ("ALIGN",         (0, 1), (0, -1),           "CENTER"),   # Session/Day
            ("ALIGN",         (1, 1), (1, -1),           "CENTER"),   # R#
            ("ALIGN",         (result_col,  1), (result_col,  -1), "CENTER"),  # Result
            ("ALIGN",         (remarks_col, 1), (remarks_col, -1), "LEFT"),    # Remarks
            # ── Global ──────────────────────────────────────────────────────
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            # Thicker right border on the Session/Day column (visual separator)
            ("LINEAFTER",     (0, 0), (0, -1), 1.5, colors.HexColor("#1E3C72")),
        ]

        # Measurement columns alignment (centre), guard against zero keys
        if all_keys:
            ts_list.append(("ALIGN", (2, 1), (result_col - 1, -1), "CENTER"))

        ri = 1   # row index in the table (0 = header)

        for s_idx, s in enumerate(sessions):
            readings = sorted(s.readings or [], key=lambda x: x.reading_number)
            if not readings:
                continue

            n_readings       = len(readings)
            session_start_ri = ri
            session_end_ri   = ri + n_readings - 1

            date_str      = _fmt_date(s.session_date)
            name_label    = s.session_name or f"Session {s.session_number}"
            session_label = f"Session {s.session_number}\n{name_label}\n{date_str}"

            row_bg  = SESSION_ROW_BG[s_idx % 2]
            cell_bg = SESSION_CELL_BG[s_idx % 2]

            # Background for all data cells of this session (cols 1 onward)
            ts_list.append(("BACKGROUND", (1, session_start_ri), (-1, session_end_ri), row_bg))
            # Distinct background + bold for the Session/Day cell
            ts_list += [
                ("BACKGROUND", (0, session_start_ri), (0, session_end_ri), cell_bg),
                ("FONTNAME",   (0, session_start_ri), (0, session_end_ri), "Helvetica-Bold"),
            ]

            # SPAN: merge Session/Day cell vertically across all readings
            if n_readings > 1:
                ts_list.append(("SPAN", (0, session_start_ri), (0, session_end_ri)))

            # Thick blue separator line above each new session block
            if s_idx > 0:
                ts_list.append(
                    ("LINEABOVE", (0, session_start_ri), (-1, session_start_ri),
                     2, colors.HexColor("#1E3C72"))
                )

            for r_idx, r in enumerate(readings):
                row_data = [
                    session_label if r_idx == 0 else "",  # only populate first row of span
                    str(r.reading_number),
                ]
                for k in all_keys:
                    row_data.append(str((r.reading_data or {}).get(k, "-")))
                r_status = (r.result_status or "").lower()
                r_color  = RESULT_COLORS.get(r_status, colors.HexColor("#9E9E9E"))
                row_data.append((r.result_status or "-").upper())
                row_data.append(r.remarks or "-")
                table_rows.append(row_data)

                # Colour the Result cell
                ts_list += [
                    ("BACKGROUND", (result_col, ri), (result_col, ri), r_color),
                    ("TEXTCOLOR",  (result_col, ri), (result_col, ri), colors.white),
                    ("FONTNAME",   (result_col, ri), (result_col, ri), "Helvetica-Bold"),
                ]
                ri += 1

        # ── Column widths ────────────────────────────────────────────────────
        # Session/Day(1.20) | R#(0.30) | [measure cols] | Result(0.70) | Remarks(1.10)
        # Total page content width = 6.5 in  (A4 − 0.75 in margins each side)
        n_measure = len(all_keys)
        fixed_w   = 1.20 + 0.30 + 0.70 + 1.10          # inches (non-measure cols)
        measure_w = max(0.55, (6.5 - fixed_w) / max(n_measure, 1))
        col_widths_r = (
            [1.20*inch, 0.30*inch]
            + [measure_w * inch] * n_measure
            + [0.70*inch, 1.10*inch]
        )

        ctable = Table(table_rows, colWidths=col_widths_r, repeatRows=1)
        ctable.setStyle(TableStyle(ts_list))
        story.append(ctable)
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
