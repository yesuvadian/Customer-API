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


class RecommendationPDFService:
    """Generate PDF reports for recommendations with approver information"""

    def __init__(self, db: Session):
        self.db = db

    def generate_pdf(self, recommendation_id: str) -> BytesIO:
        """Generate PDF for a recommendation"""
        recommendation = self.db.query(Recommendation).filter(
            Recommendation.id == recommendation_id
        ).first()

        if not recommendation:
            raise ValueError(f"Recommendation {recommendation_id} not found")

        # Get related data
        testing_request = recommendation.testing_request
        approver = None
        if recommendation.approved_by:
            approver = self.db.query(User).filter(User.id == recommendation.approved_by).first()

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
        story.append(Paragraph("Testing Recommendation Report", title_style))
        story.append(Spacer(1, 0.2*inch))

        # Document Info Table
        doc_info_data = [
            ['Report Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Recommendation ID:', str(recommendation.id)],
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

        # Testing Request Information
        story.append(Paragraph("Testing Request Information", heading_style))
        request_data = [
            ['Request ID:', str(testing_request.id)],
            ['Request Number:', testing_request.request_number or '-'],
            ['Status:', testing_request.status or '-'],
            ['Title:', testing_request.title or '-'],
            ['Test Type:', testing_request.test_type.name if testing_request.test_type else '-'],
        ]
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

                # Test data details
                test_data_rows = []
                if result.test_data:
                    for key, value in result.test_data.items():
                        # Format key (remove underscores, capitalize)
                        formatted_key = key.replace('_', ' ').title() + ':'
                        formatted_value = str(value) if value is not None else '-'
                        test_data_rows.append([formatted_key, formatted_value])

                # Add remarks if present
                if result.remarks:
                    test_data_rows.append(['Remarks:', result.remarks])

                if test_data_rows:
                    test_data_table = Table(test_data_rows, colWidths=[2*inch, 4*inch])
                    test_data_table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F9F9F9')),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ]))
                    story.append(test_data_table)

                # Add space between tests
                if idx < len(test_results):
                    story.append(Spacer(1, 0.15*inch))

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

        # Submitted By Information
        if submitted_by_user:
            story.append(Paragraph("Submitted By", heading_style))
            submitted_data = [
                ['Name:', f"{submitted_by_user.firstname} {submitted_by_user.lastname}"],
                ['Email:', submitted_by_user.email],
                ['Submitted At:', recommendation.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if recommendation.submitted_at else '-'],
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

        # Approval Information
        story.append(Paragraph("Approval Information", heading_style))
        approval_status_color = self._get_status_color(recommendation.approval_status)

        approval_data = [
            ['Status:', recommendation.approval_status.upper() if recommendation.approval_status else 'PENDING'],
        ]

        if approver:
            approval_data.extend([
                ['Approved By:', f"{approver.firstname} {approver.lastname}"],
                ['Approver Email:', approver.email],
                ['Approved At:', recommendation.approved_at.strftime('%Y-%m-%d %H:%M:%S') if recommendation.approved_at else '-'],
            ])
        else:
            approval_data.append(['Approved By:', 'Pending Approval'])

        if recommendation.approval_notes:
            approval_data.append(['Approval Notes:', recommendation.approval_notes])

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
