from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from sqlalchemy.orm import Session, joinedload

from models import TestingRequest, User


class TestingRequestPDFService:
    """Generate PDF reports for testing requests"""

    def __init__(self, db: Session):
        self.db = db

    def generate_pdf(self, request_id: str) -> BytesIO:
        """Generate PDF for a testing request"""
        testing_request = self.db.query(TestingRequest).options(
            joinedload(TestingRequest.equipment_type),
            joinedload(TestingRequest.test_type),
            joinedload(TestingRequest.department),
            joinedload(TestingRequest.originator),
            joinedload(TestingRequest.assigned_tester),
            joinedload(TestingRequest.organization),
        ).filter(TestingRequest.id == request_id).first()

        if not testing_request:
            raise ValueError(f"Testing request {request_id} not found")

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
        story.append(Paragraph("Testing Request Form", title_style))
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
            ['Request ID:', str(testing_request.id)],
            ['Title:', testing_request.title or '-'],
            ['Priority:', (testing_request.priority or '-').upper()],
        ]

        if testing_request.description:
            request_data.append(['Description:', testing_request.description])

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

        # Status indicator box
        status_text, status_color = self._get_status_display(testing_request.status)

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
