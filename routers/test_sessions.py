"""
Test Session Router - API endpoints for multi-day, multi-session testing.

Endpoints:
- Create/update/delete test sessions
- Record multiple readings per session
- Start/complete sessions
- Auto-generate sessions based on schedule
- Get session statistics
"""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import TestSession, TestSessionReading, TestingRequest, User
from schemas import (
    TestSessionCreate,
    TestSessionUpdate,
    TestSessionResponse,
    TestSessionReadingCreate,
    TestSessionReadingUpdate,
    TestSessionReadingResponse,
)
from services.test_session_service import TestSessionService

router = APIRouter(
    prefix="/testing_requests/{request_id}/sessions",
    tags=["test_sessions"],
    dependencies=[Depends(get_current_user)],
)


# ═══════════════════════════════════════════════════════════
# TEST SESSION ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.post("/", response_model=TestSessionResponse, status_code=201)
def create_session(
    request_id: UUID,
    data: TestSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new test session for a testing request."""
    svc = TestSessionService(db)
    return svc.create_session(
        testing_request_id=request_id,
        session_number=data.session_number,
        session_name=data.session_name,
        session_date=data.session_date,
        scheduled_date=data.scheduled_date,
        template_key=data.template_key,
        notes=data.notes,
        weather_conditions=data.weather_conditions,
        environmental_factors=data.environmental_factors,
        organization_id=data.organization_id,
        created_by=current_user.id,
    )


@router.post("/auto-generate", response_model=List[TestSessionResponse], status_code=201)
def auto_generate_sessions(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Auto-generate all sessions for a multi-session testing request.
    Creates sessions based on total_sessions_planned and session_interval_days.
    """
    svc = TestSessionService(db)
    return svc.auto_generate_sessions(
        testing_request_id=request_id,
        created_by=current_user.id,
    )


@router.get("/", response_model=List[TestSessionResponse])
def list_sessions(
    request_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all sessions for a testing request."""
    svc = TestSessionService(db)
    return svc.list_sessions(
        testing_request_id=request_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{session_id}", response_model=TestSessionResponse)
def get_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Get a specific test session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return session


@router.put("/{session_id}", response_model=TestSessionResponse)
def update_session(
    request_id: UUID,
    session_id: UUID,
    data: TestSessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a test session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")

    return svc.update_session(
        session_id=session_id,
        session_name=data.session_name,
        session_date=data.session_date,
        status=data.status,
        notes=data.notes,
        weather_conditions=data.weather_conditions,
        environmental_factors=data.environmental_factors,
        conducted_by=data.conducted_by,
        witnessed_by=data.witnessed_by,
        started_at=data.started_at,
        completed_at=data.completed_at,
        modified_by=current_user.id,
    )


@router.delete("/{session_id}", status_code=204)
def delete_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a test session and all its readings."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    svc.delete_session(session_id)


@router.post("/{session_id}/start", response_model=TestSessionResponse)
def start_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a session as in progress and set start time."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return svc.start_session(session_id, conducted_by=current_user.id)


@router.post("/{session_id}/complete", response_model=TestSessionResponse)
def complete_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Mark a session as completed and set completion time."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return svc.complete_session(session_id)


@router.get("/{session_id}/statistics")
def get_session_statistics(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Get statistics for a session (reading count, pass/fail, duration)."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")
    return svc.get_session_statistics(session_id)


# ═══════════════════════════════════════════════════════════
# TEST SESSION READING ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.post("/{session_id}/readings", response_model=TestSessionReadingResponse, status_code=201)
def create_reading(
    request_id: UUID,
    session_id: UUID,
    data: TestSessionReadingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new reading for a test session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")

    return svc.create_reading(
        session_id=session_id,
        reading_number=data.reading_number,
        reading_time=data.reading_time,
        reading_data=data.reading_data,
        equipment_serial=data.equipment_serial,
        calibration_date=data.calibration_date,
        remarks=data.remarks,
        result_status=data.result_status,
        recorded_by=current_user.id,
    )


@router.get("/{session_id}/readings", response_model=List[TestSessionReadingResponse])
def list_readings(
    request_id: UUID,
    session_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all readings for a session."""
    svc = TestSessionService(db)
    session = svc.get_session(session_id)
    if session.testing_request_id != request_id:
        raise HTTPException(status_code=404, detail="Session not found for this testing request")

    return svc.list_readings(
        session_id=session_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{session_id}/readings/{reading_id}", response_model=TestSessionReadingResponse)
def get_reading(
    request_id: UUID,
    session_id: UUID,
    reading_id: UUID,
    db: Session = Depends(get_db),
):
    """Get a specific reading."""
    svc = TestSessionService(db)
    reading = svc.get_reading(reading_id)
    if reading.test_session_id != session_id:
        raise HTTPException(status_code=404, detail="Reading not found for this session")
    return reading


@router.put("/{session_id}/readings/{reading_id}", response_model=TestSessionReadingResponse)
def update_reading(
    request_id: UUID,
    session_id: UUID,
    reading_id: UUID,
    data: TestSessionReadingUpdate,
    db: Session = Depends(get_db),
):
    """Update a reading."""
    svc = TestSessionService(db)
    reading = svc.get_reading(reading_id)
    if reading.test_session_id != session_id:
        raise HTTPException(status_code=404, detail="Reading not found for this session")

    return svc.update_reading(
        reading_id=reading_id,
        reading_time=data.reading_time,
        reading_data=data.reading_data,
        equipment_serial=data.equipment_serial,
        calibration_date=data.calibration_date,
        remarks=data.remarks,
        result_status=data.result_status,
    )


@router.delete("/{session_id}/readings/{reading_id}", status_code=204)
def delete_reading(
    request_id: UUID,
    session_id: UUID,
    reading_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a reading."""
    svc = TestSessionService(db)
    reading = svc.get_reading(reading_id)
    if reading.test_session_id != session_id:
        raise HTTPException(status_code=404, detail="Reading not found for this session")
    svc.delete_reading(reading_id)


# ═══════════════════════════════════════════════════════════
# SESSION REPORT — HTML PREVIEW & PDF DOWNLOAD
# ═══════════════════════════════════════════════════════════

def _build_session_html(session: TestSession, readings: list, request: TestingRequest) -> str:
    """Build a styled HTML report for a single test session."""

    def fmt(v):
        if v is None:
            return "-"
        if isinstance(v, dict):
            import json
            return f"<pre style='margin:0;font-size:12px'>{json.dumps(v, indent=2)}</pre>"
        return str(v)

    def status_badge(s):
        colors = {
            "completed":   ("#1a7340", "#e8f5e9"),
            "in_progress": ("#c75b00", "#fff3e0"),
            "scheduled":   ("#1b3a6b", "#e8f0fe"),
        }
        fg, bg = colors.get(s, ("#555", "#f5f5f5"))
        return f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600">{s.replace("_"," ").upper()}</span>'

    # Reading rows
    reading_rows = ""
    for r in readings:
        rd = r.reading_data or {}
        data_cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #e0e0e0'><b>{k.replace('_',' ').title()}</b>: {fmt(v)}</td>"
            for k, v in rd.items()
        )
        result_color = "#1a7340" if (r.result_status or "").lower() == "pass" else \
                       "#b71c1c" if (r.result_status or "").lower() == "fail" else "#555"
        reading_rows += f"""
        <tr>
          <td style='padding:6px 10px;border:1px solid #e0e0e0;text-align:center'>{r.reading_number}</td>
          <td style='padding:6px 10px;border:1px solid #e0e0e0'>{fmt(r.reading_time)}</td>
          <td style='padding:6px 10px;border:1px solid #e0e0e0'>{data_cells}</td>
          <td style='padding:6px 10px;border:1px solid #e0e0e0'>{fmt(r.equipment_serial)}</td>
          <td style='padding:6px 10px;border:1px solid #e0e0e0;color:{result_color};font-weight:600'>{(r.result_status or '-').upper()}</td>
          <td style='padding:6px 10px;border:1px solid #e0e0e0'>{fmt(r.remarks)}</td>
        </tr>"""

    no_readings = '<tr><td colspan="6" style="padding:20px;text-align:center;color:#888">No readings recorded for this session</td></tr>' if not readings else ""

    req_num = getattr(request, "request_number", "") or ""
    eq_name = ""
    if hasattr(request, "equipment_type") and request.equipment_type:
        eq_name = request.equipment_type.name or ""

    session_date_str = session.session_date.strftime("%d %b %Y") if session.session_date else "-"
    started_str = session.started_at.strftime("%d/%m/%Y %H:%M") if session.started_at else "-"
    completed_str = session.completed_at.strftime("%d/%m/%Y %H:%M") if session.completed_at else "-"
    env_str = fmt(session.environmental_factors) if session.environmental_factors else "-"
    weather_str = session.weather_conditions or "-"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Session Report — {session.session_name or f'Session {session.session_number}'}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; color: #333; background:#f9f9f9 }}
    .header {{ background:#1b3a6b; color:white; padding:20px 24px; border-radius:10px 10px 0 0 }}
    .header h1 {{ margin:0; font-size:20px }}
    .header p  {{ margin:6px 0 0; font-size:13px; opacity:.8 }}
    .body  {{ background:white; padding:20px 24px; border-radius:0 0 10px 10px; box-shadow:0 2px 8px rgba(0,0,0,.1) }}
    .meta-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:20px }}
    .meta-item label {{ color:#666; font-size:12px; display:block; margin-bottom:3px }}
    .meta-item span  {{ font-size:14px; font-weight:600 }}
    .section-title {{ font-size:15px; font-weight:700; color:#1b3a6b; border-bottom:2px solid #e8f0fe; padding-bottom:6px; margin:20px 0 12px }}
    table.readings {{ width:100%; border-collapse:collapse; font-size:13px }}
    table.readings th {{ background:#1b3a6b; color:white; padding:8px 10px; text-align:left }}
    table.readings tr:nth-child(even) {{ background:#f5f8ff }}
    .footer {{ margin-top:24px; font-size:11px; color:#aaa; text-align:center }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Session Report — {session.session_name or f'Session {session.session_number}'}</h1>
    <p>Request: {req_num} &nbsp;|&nbsp; Equipment: {eq_name}</p>
  </div>
  <div class="body">
    <div style="margin-bottom:16px">{status_badge(session.status or 'scheduled')}</div>

    <div class="meta-grid">
      <div class="meta-item"><label>Session Number</label><span>{session.session_number}</span></div>
      <div class="meta-item"><label>Session Date</label><span>{session_date_str}</span></div>
      <div class="meta-item"><label>Started At</label><span>{started_str}</span></div>
      <div class="meta-item"><label>Completed At</label><span>{completed_str}</span></div>
      <div class="meta-item"><label>Weather Conditions</label><span>{weather_str}</span></div>
      <div class="meta-item"><label>Environmental Factors</label><span>{env_str}</span></div>
      {"<div class='meta-item'><label>Conducted By</label><span>" + fmt(session.conducted_by) + "</span></div>" if session.conducted_by else ""}
      {"<div class='meta-item'><label>Witnessed By</label><span>" + fmt(session.witnessed_by) + "</span></div>" if session.witnessed_by else ""}
    </div>

    {"<p><b>Notes:</b> " + (session.notes or "") + "</p>" if session.notes else ""}

    <div class="section-title">Readings ({len(readings)})</div>
    <table class="readings">
      <thead>
        <tr>
          <th>#</th><th>Time</th><th>Measurement Data</th>
          <th>Equipment Serial</th><th>Result</th><th>Remarks</th>
        </tr>
      </thead>
      <tbody>
        {reading_rows}
        {no_readings}
      </tbody>
    </table>

    <div class="footer">
      Generated by SEACMS &nbsp;|&nbsp; KPTCL &nbsp;|&nbsp; {__import__('datetime').datetime.now().strftime("%d %b %Y %H:%M")}
    </div>
  </div>
</body>
</html>"""


@router.get("/{session_id}/preview", response_class=HTMLResponse)
def preview_session(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Render a single test session as a styled HTML report (browser preview)."""
    session = db.query(TestSession).filter(
        TestSession.id == session_id,
        TestSession.testing_request_id == request_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    readings = (
        db.query(TestSessionReading)
        .filter(TestSessionReading.test_session_id == session_id)
        .order_by(TestSessionReading.reading_number)
        .all()
    )
    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    return _build_session_html(session, readings, req)


@router.get("/{session_id}/pdf")
def download_session_pdf(
    request_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """Generate and return a PDF report for a single test session."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    session = db.query(TestSession).filter(
        TestSession.id == session_id,
        TestSession.testing_request_id == request_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    readings = (
        db.query(TestSessionReading)
        .filter(TestSessionReading.test_session_id == session_id)
        .order_by(TestSessionReading.reading_number)
        .all()
    )
    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()

    # ── Build PDF ──────────────────────────────────────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)

    styles = getSampleStyleSheet()
    navy = rl_colors.HexColor("#1B3A6B")
    teal = rl_colors.HexColor("#006D7E")
    light = rl_colors.HexColor("#E8F0FE")

    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=16,
                                 textColor=navy, spaceAfter=6, alignment=TA_LEFT)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10,
                               textColor=rl_colors.grey, spaceAfter=12)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12,
                              textColor=navy, spaceBefore=14, spaceAfter=6)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, spaceAfter=4)

    req_num = getattr(req, "request_number", "") or ""
    eq_name = (req.equipment_type.name if req and req.equipment_type else "") or ""
    session_name = session.session_name or f"Session {session.session_number}"
    session_date_str = session.session_date.strftime("%d %b %Y") if session.session_date else "-"

    story = [
        Paragraph(f"Session Report — {session_name}", title_style),
        Paragraph(f"Request: {req_num}   |   Equipment: {eq_name}   |   Date: {session_date_str}", sub_style),
        Spacer(1, 0.1 * inch),
    ]

    # Metadata table
    def meta_row(label, value):
        return [Paragraph(label, body_style), Paragraph(str(value or "-"), body_style)]

    meta_data = [
        meta_row("Session Number", session.session_number),
        meta_row("Status", (session.status or "-").replace("_", " ").upper()),
        meta_row("Session Date", session_date_str),
        meta_row("Started At", session.started_at.strftime("%d/%m/%Y %H:%M") if session.started_at else "-"),
        meta_row("Completed At", session.completed_at.strftime("%d/%m/%Y %H:%M") if session.completed_at else "-"),
        meta_row("Weather Conditions", session.weather_conditions),
        meta_row("Conducted By", session.conducted_by),
        meta_row("Witnessed By", session.witnessed_by),
    ]
    if session.notes:
        meta_data.append(meta_row("Notes", session.notes))

    meta_table = Table(meta_data, colWidths=[2.2 * inch, 4.6 * inch])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), light),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f5f8ff")]),
        ("BOX", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CCCCCC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [meta_table, Spacer(1, 0.15 * inch)]

    # Readings section
    story.append(Paragraph(f"Readings ({len(readings)})", h2_style))

    if not readings:
        story.append(Paragraph("No readings recorded for this session.", body_style))
    else:
        # Collect all unique reading_data keys across readings
        all_keys: list = []
        for r in readings:
            if r.reading_data and isinstance(r.reading_data, dict):
                for k in r.reading_data:
                    if k not in all_keys:
                        all_keys.append(k)

        headers = ["#", "Time", *[k.replace("_", " ").title() for k in all_keys], "Serial", "Result", "Remarks"]
        header_row = [Paragraph(h, ParagraphStyle("TH", fontSize=9, textColor=rl_colors.white, fontName="Helvetica-Bold"))
                      for h in headers]

        rows = [header_row]
        for r in readings:
            rd = r.reading_data or {}
            result_color = rl_colors.HexColor("#1A7340") if (r.result_status or "").lower() == "pass" \
                else rl_colors.HexColor("#B71C1C") if (r.result_status or "").lower() == "fail" \
                else rl_colors.black
            result_para = Paragraph(
                (r.result_status or "-").upper(),
                ParagraphStyle("Res", fontSize=9, textColor=result_color, fontName="Helvetica-Bold")
            )
            row = [
                Paragraph(str(r.reading_number), ParagraphStyle("Cell", fontSize=9)),
                Paragraph(str(r.reading_time or "-"), ParagraphStyle("Cell", fontSize=9)),
                *[Paragraph(str(rd.get(k, "-")), ParagraphStyle("Cell", fontSize=9)) for k in all_keys],
                Paragraph(str(r.equipment_serial or "-"), ParagraphStyle("Cell", fontSize=9)),
                result_para,
                Paragraph(str(r.remarks or "-"), ParagraphStyle("Cell", fontSize=9)),
            ]
            rows.append(row)

        col_count = len(headers)
        fixed = 3  # #, Time, Result
        fixed_w = 0.4 * inch  # #
        time_w = 1.0 * inch
        serial_w = 1.0 * inch
        result_w = 0.7 * inch
        remarks_w = 1.0 * inch
        remaining = (6.8 * inch) - fixed_w - time_w - serial_w - result_w - remarks_w
        data_w = remaining / max(len(all_keys), 1) if all_keys else 0
        col_widths = [fixed_w, time_w, *[data_w] * len(all_keys), serial_w, result_w, remarks_w]

        readings_table = Table(rows, colWidths=col_widths, repeatRows=1)
        readings_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f5f8ff")]),
            ("BOX", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CCCCCC")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#DDDDDD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(readings_table)

    doc.build(story)
    buf.seek(0)
    safe_name = f"session_{session.session_number}_{req_num or 'report'}.pdf".replace(" ", "_")
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
