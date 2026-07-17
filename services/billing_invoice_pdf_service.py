from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_RUPEE = "Rs."

PAGE_W, PAGE_H = A4
MARGIN = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

NAVY = colors.HexColor("#0F2B6B")
LIGHT_GREY = colors.HexColor("#f8fafc")
BORDER = colors.HexColor("#e2e8f0")
GREEN = colors.HexColor("#16a34a")
TEXT = colors.HexColor("#1e293b")
MUTED = colors.HexColor("#64748b")

_title = ParagraphStyle("title", fontSize=22, fontName=_FONT_BOLD, textColor=NAVY)
_sub   = ParagraphStyle("sub",   fontSize=10, fontName=_FONT,      textColor=MUTED)
_label = ParagraphStyle("label", fontSize=9,  fontName=_FONT_BOLD, textColor=MUTED, spaceAfter=2)
_val   = ParagraphStyle("val",   fontSize=12, fontName=_FONT_BOLD, textColor=TEXT)
_val_s = ParagraphStyle("val_s", fontSize=10, fontName=_FONT,      textColor=TEXT)
_th    = ParagraphStyle("th",    fontSize=10, fontName=_FONT_BOLD, textColor=colors.white)
_td    = ParagraphStyle("td",    fontSize=11, fontName=_FONT,      textColor=TEXT)
_td_r  = ParagraphStyle("td_r",  fontSize=11, fontName=_FONT,      textColor=TEXT, alignment=TA_RIGHT)
_foot  = ParagraphStyle("foot",  fontSize=9,  fontName=_FONT,      textColor=MUTED, alignment=TA_CENTER)
_badge = ParagraphStyle("badge", fontSize=10, fontName=_FONT_BOLD, textColor=GREEN)
_total_r = ParagraphStyle("tot_r", fontSize=12, fontName=_FONT_BOLD, textColor=NAVY, alignment=TA_RIGHT)
_total_l = ParagraphStyle("tot_l", fontSize=12, fontName=_FONT_BOLD, textColor=NAVY)


def _p(text, style):
    safe = str(text or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def generate_invoice_pdf(
    invoice_no: str,
    org_name: str,
    org_email: str,
    plan_name: str,
    billing_cycle: str,
    amount_paise: int,
    paid_date: datetime,
    razorpay_payment_id: str,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    amount_rupees = (amount_paise or 0) / 100
    paid_str = paid_date.strftime("%d %b %Y") if paid_date else "—"
    cycle_str = billing_cycle.capitalize() if billing_cycle else "—"

    story = []

    # ── Header: Brand left, Invoice right ────────────────────────────────
    header_table = Table(
        [[
            [_p("CogniWatt", _title), _p("AI Based Substation Maintenance Software", _sub)],
            [_p("INVOICE", _title), _p(invoice_no, _sub)],
        ]],
        colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN",  (1, 0), (1, 0),  "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width=CONTENT_W, thickness=2, color=NAVY))
    story.append(Spacer(1, 0.25 * inch))

    # ── Billing info row ─────────────────────────────────────────────────
    info_table = Table(
        [[
            [_p("BILLED TO", _label), _p(org_name, _val), _p(org_email, _val_s)],
            [_p("INVOICE DATE", _label), _p(paid_str, _val)],
            [_p("PAYMENT ID", _label), _p(razorpay_payment_id or "—", _val_s)],
            [_p("STATUS", _label), _p("✓  PAID", _badge)],
        ]],
        colWidths=[CONTENT_W * 0.32, CONTENT_W * 0.20, CONTENT_W * 0.28, CONTENT_W * 0.20],
    )
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.35 * inch))

    # ── Line items table ─────────────────────────────────────────────────
    col_desc = CONTENT_W * 0.55
    col_cycle = CONTENT_W * 0.22
    col_amt = CONTENT_W * 0.23

    items_data = [
        [_p("DESCRIPTION", _th), _p("BILLING CYCLE", _th), _p("AMOUNT", _th)],
        [
            _p(f"{plan_name} Plan", _td),
            _p(cycle_str, _td),
            _p(f"{_RUPEE}{amount_rupees:,.0f}", _td_r),
        ],
        [
            _p("Total", _total_l),
            _p("", _td),
            _p(f"{_RUPEE}{amount_rupees:,.0f}", _total_r),
        ],
    ]

    items_table = Table(items_data, colWidths=[col_desc, col_cycle, col_amt])
    items_table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND",   (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, 1), [LIGHT_GREY]),
        ("TOPPADDING",   (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ("LEFTPADDING",  (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        # Total row top border
        ("LINEABOVE",    (0, 2), (-1, 2), 1.5, NAVY),
        ("LINEBELOW",    (0, 0), (-1, 0), 0,   colors.transparent),
        # Outer border
        ("BOX",          (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",    (0, 1), (-1, 1), 0.5, BORDER),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.5 * inch))

    # ── Footer ───────────────────────────────────────────────────────────
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=BORDER))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_p(
        "Thank you for your payment. This is a computer-generated invoice and does not require a signature.",
        _foot,
    ))
    story.append(_p("CogniWatt · support@cogniwatt.com", _foot))

    doc.build(story)
    return buf.getvalue()
