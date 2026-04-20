from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from sqlalchemy.orm import Session

from models import Recommendation, User, TestingRequest, TestResult
from sqlalchemy.orm import joinedload


class RecommendationPDFService:
    """Generate PDF reports for recommendations with approver information"""

    def __init__(self, db: Session):
        self.db = db

    def generate_pdf(self, recommendation_id: str) -> BytesIO:
        """Generate PDF for a recommendation with full test report details"""
        recommendation = self.db.query(Recommendation).filter(
            Recommendation.id == recommendation_id
        ).first()

        if not recommendation:
            raise ValueError(f"Recommendation {recommendation_id} not found")

        # Get testing request with all related data
        testing_request = self.db.query(TestingRequest).options(
            joinedload(TestingRequest.equipment_type),
            joinedload(TestingRequest.test_type),
            joinedload(TestingRequest.department),
            joinedload(TestingRequest.originator),
            joinedload(TestingRequest.assigned_tester),
            joinedload(TestingRequest.organization),
            joinedload(TestingRequest.equipment),
        ).filter(TestingRequest.id == recommendation.testing_request_id).first()

        # Get approver
        approver = None
        if recommendation.approved_by:
            approver = self.db.query(User).filter(User.id == recommendation.approved_by).first()

        # Get submitted by user
        submitted_by_user = None
        if recommendation.submitted_by:
            submitted_by_user = self.db.query(User).filter(User.id == recommendation.submitted_by).first()

        # Create PDF buffer
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=colors.HexColor('#003366'),
            alignment=TA_CENTER,
            spaceAfter=20,
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#003366'),
            spaceAfter=10,
        )
        normal_style = styles['Normal']

        # Title
        story.append(Paragraph("Testing Report", title_style))
        story.append(Spacer(1, 0.2*inch))

        # Document Info Table
        doc_info_data = [
            ['Report Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
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

        # Request Information
        story.append(Paragraph("Request Information", heading_style))
        request_data = [
            ['Request Number:', testing_request.request_number or '-'],
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
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0F0F0')),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(equipment_table)
            story.append(Spacer(1, 0.3*inch))

        # Organization and Requester Information
        story.append(Paragraph("Organization & Requester", heading_style))

        requester_name = '-'
        requester_email = '-'
        if testing_request.originator:
            requester_name = f"{testing_request.originator.firstname or ''} {testing_request.originator.lastname or ''}".strip() or testing_request.originator.email
            requester_email = testing_request.originator.email

        org_data = [
            ['Department:', testing_request.department.name if testing_request.department else '-'],
            ['Requested By:', requester_name],
            ['Requester Email:', requester_email],
            ['Submitted On:', testing_request.cts.strftime('%Y-%m-%d %H:%M:%S') if testing_request.cts else '-'],
        ]

        org_table = Table(org_data, colWidths=[2*inch, 4*inch])
        org_table.setStyle(TableStyle([
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
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0F0F0')),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(notes_table)
            story.append(Spacer(1, 0.3*inch))

        # Test Results Section
        test_results = self.db.query(TestResult).filter(
            TestResult.testing_request_id == testing_request.id
        ).order_by(TestResult.cts).all()

        if test_results:
            story.append(Paragraph("Test Results", heading_style))

            for idx, result in enumerate(test_results, 1):
                # Test header with name and overall result
                test_header = [
                    [f"Test {idx}: {result.test_name or result.template_key or 'N/A'}",
                     f"Result: {(result.overall_result or 'N/A').upper()}"]
                ]
                header_table = Table(test_header, colWidths=[4*inch, 2*inch])
                header_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 11),
                    ('TEXTCOLOR', (0, 0), (0, 0), colors.HexColor('#003366')),
                    ('TEXTCOLOR', (1, 0), (1, 0),
                     colors.green if result.overall_result == 'pass' else
                     colors.red if result.overall_result == 'fail' else colors.orange),
                    ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                    ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ]))
                story.append(header_table)

                # ── Build field-label map and column-label map from template ──
                _field_labels = {}   # field_key → friendly label
                _col_labels   = {}   # field_key → {col_key: label}  (for table fields)
                try:
                    from models import OrgTestTemplate
                    _tmpl_row = (
                        self.db.query(OrgTestTemplate)
                        .filter(OrgTestTemplate.template_key == result.template_key)
                        .first()
                    )
                    _tmpl_data = _tmpl_row.template_data if _tmpl_row and _tmpl_row.template_data else {}
                    if not _tmpl_data:
                        from test_templates import get_template_by_key
                        _tmpl_data = get_template_by_key(result.template_key) or {}
                    for _sec in _tmpl_data.get("sections", []):
                        for _f in _sec.get("fields", []):
                            fk = _f.get("key")
                            _field_labels[fk] = _f.get("label", fk)
                            if _f.get("type") == "table":
                                _col_labels[fk] = {
                                    c.get("key", c) if isinstance(c, dict) else c:
                                    c.get("label", c) if isinstance(c, dict) else c
                                    for c in _f.get("columns", [])
                                }
                except Exception:
                    pass

                # Keys already represented elsewhere in the PDF — skip them
                _skip_keys = {'overall_result', 'overall_remarks'}

                # Separate scalar fields from table fields
                _scalar_items = []   # list of (label, display_str)
                _table_items  = []   # list of (label, field_key, list_of_row_dicts)

                if result.test_data:
                    for key, value in result.test_data.items():
                        if key in _skip_keys:
                            continue
                        friendly = _field_labels.get(key, key.replace('_', ' ').title())
                        if isinstance(value, list) and value and isinstance(value[0], dict):
                            _table_items.append((friendly, key, value))
                        else:
                            _scalar_items.append((friendly, str(value) if value is not None else '-'))

                if result.remarks:
                    _scalar_items.append(('Remarks', result.remarks))

                # ── Two-column grid for scalar fields ──────────────────────────
                # Layout: | Label | Value | Label | Value |  (1.2 + 1.8 + 1.2 + 1.8 = 6 in)
                if _scalar_items:
                    _two_col_rows = []
                    for i in range(0, len(_scalar_items), 2):
                        lbl_l, val_l = _scalar_items[i]
                        if i + 1 < len(_scalar_items):
                            lbl_r, val_r = _scalar_items[i + 1]
                        else:
                            lbl_r, val_r = '', ''
                        _two_col_rows.append([f"{lbl_l}:", val_l, f"{lbl_r}:", val_r])

                    _scalar_tbl = Table(_two_col_rows, colWidths=[1.2*inch, 1.8*inch, 1.2*inch, 1.8*inch])
                    _scalar_tbl.setStyle(TableStyle([
                        ('FONTNAME',      (0, 0), (-1, -1), 'Helvetica'),
                        ('FONTNAME',      (0, 0), (0, -1), 'Helvetica-Bold'),   # left labels
                        ('FONTNAME',      (2, 0), (2, -1), 'Helvetica-Bold'),   # right labels
                        ('FONTSIZE',      (0, 0), (-1, -1), 8),
                        ('TEXTCOLOR',     (0, 0), (0, -1), colors.HexColor('#555555')),
                        ('TEXTCOLOR',     (2, 0), (2, -1), colors.HexColor('#555555')),
                        ('BACKGROUND',    (0, 0), (0, -1), colors.HexColor('#F0F0F0')),
                        ('BACKGROUND',    (2, 0), (2, -1), colors.HexColor('#F0F0F0')),
                        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
                        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                        ('GRID',          (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ('TOPPADDING',    (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
                        ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
                    ]))
                    story.append(_scalar_tbl)

                # ── Full-width table for each table-type field ─────────────────
                _sub_heading_style = ParagraphStyle(
                    'SubHeading', parent=normal_style,
                    fontSize=9, fontName='Helvetica-Bold',
                    textColor=colors.HexColor('#003366'),
                    spaceBefore=6, spaceAfter=3,
                )
                for _tbl_label, _fkey, _rows in _table_items:
                    story.append(Paragraph(_tbl_label, _sub_heading_style))
                    _col_map = _col_labels.get(_fkey, {})
                    _col_keys = list(_rows[0].keys()) if _rows else []
                    _header = [
                        _col_map.get(ck, ck.replace('_', ' ').title())
                        for ck in _col_keys
                    ]
                    _body = [
                        [str(row.get(ck, '-')) if row.get(ck) is not None else '-' for ck in _col_keys]
                        for row in _rows
                    ]
                    _n = max(len(_col_keys), 1)
                    _cw = 6.0 * inch / _n
                    _full_tbl = Table([_header] + _body, colWidths=[_cw] * _n)
                    _full_tbl.setStyle(TableStyle([
                        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
                        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
                        ('FONTSIZE',      (0, 0), (-1, -1), 8),
                        ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#D8E4F0')),
                        ('GRID',          (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
                        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                        ('TOPPADDING',    (0, 0), (-1, -1), 3),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
                        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
                    ]))
                    story.append(_full_tbl)

                # Add space between tests
                if idx < len(test_results):
                    story.append(Spacer(1, 0.15*inch))

            story.append(Spacer(1, 0.3*inch))

        # Tested By Information
        if testing_request.assigned_tester:
            story.append(Paragraph("Tested By", heading_style))
            tester = testing_request.assigned_tester
            tester_name = f"{tester.firstname or ''} {tester.lastname or ''}".strip() or tester.email

            tested_data = [
                ['Tester Name:', tester_name],
                ['Tester Email:', tester.email],
            ]

            tested_table = Table(tested_data, colWidths=[2*inch, 4*inch])
            tested_table.setStyle(TableStyle([
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
            story.append(tested_table)
            story.append(Spacer(1, 0.3*inch))

        # Recommendation Details
        story.append(Paragraph("Recommendation", heading_style))
        rec_type_display = recommendation.recommendation_type.value if recommendation.recommendation_type else '-'
        rec_data = [
            ['Type:', rec_type_display.replace('_', ' ').upper()],
            ['Summary:', recommendation.summary or '-'],
        ]
        if recommendation.detailed_notes:
            rec_data.append(['Detailed Notes:', recommendation.detailed_notes])

        rec_table = Table(rec_data, colWidths=[2*inch, 4*inch])
        rec_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0F0F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(rec_table)
        story.append(Spacer(1, 0.3*inch))

        # Reviewed By (Submitted by)
        if submitted_by_user:
            story.append(Paragraph("Reviewed By", heading_style))
            submitted_data = [
                ['Reviewer Name:', f"{submitted_by_user.firstname or ''} {submitted_by_user.lastname or ''}".strip() or submitted_by_user.email],
                ['Reviewer Email:', submitted_by_user.email],
                ['Reviewed At:', recommendation.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if recommendation.submitted_at else '-'],
            ]
            submitted_table = Table(submitted_data, colWidths=[2*inch, 4*inch])
            submitted_table.setStyle(TableStyle([
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
            story.append(submitted_table)
            story.append(Spacer(1, 0.3*inch))

        # Approved/Rejected By
        approval_title = "Approved By" if recommendation.approval_status == 'approved' else "Rejected By" if recommendation.approval_status == 'rejected' else "Approval Status"
        story.append(Paragraph(approval_title, heading_style))

        approval_data = []

        if approver:
            approver_name = f"{approver.firstname or ''} {approver.lastname or ''}".strip() or approver.email
            action_label = "Approved By:" if recommendation.approval_status == 'approved' else "Rejected By:" if recommendation.approval_status == 'rejected' else "Reviewed By:"
            approval_data.extend([
                [action_label, approver_name],
                ['Email:', approver.email],
                ['Date:', recommendation.approved_at.strftime('%Y-%m-%d %H:%M:%S') if recommendation.approved_at else '-'],
            ])
        else:
            approval_data.append(['Status:', 'Pending Approval'])

        if recommendation.approval_notes:
            approval_data.append(['Notes:', recommendation.approval_notes])

        approval_table = Table(approval_data, colWidths=[2*inch, 4*inch])
        approval_table.setStyle(TableStyle([
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
        story.append(approval_table)
        story.append(Spacer(1, 0.3*inch))

        # Status indicator box
        if recommendation.approval_status == 'approved':
            status_text = "APPROVED"
            status_color = colors.green
        elif recommendation.approval_status == 'rejected':
            status_text = "REJECTED"
            status_color = colors.red
        else:
            status_text = "PENDING APPROVAL"
            status_color = colors.orange

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

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def _get_status_color(self, status: str):
        """Get color for status"""
        status_colors = {
            'approved': colors.green,
            'rejected': colors.red,
            'pending': colors.orange,
        }
        return status_colors.get(status, colors.grey)
