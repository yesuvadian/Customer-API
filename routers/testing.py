from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import Recommendation, TestingRequest, TestingRequestStatus, User
from schemas import (
    TestingRequestResponse,
    TestResultResponse,
    TestResultStructuredCreate,
    TestResultStructuredResponse,
    TestResultImageResponse,
    SubmitTestResultsBody,
)
from services.testing_service import TestingService

router = APIRouter(
    prefix="/testing",
    tags=["testing"],
    dependencies=[Depends(get_current_user)],
)


def _enrich(req):
    """Attach computed display names to ORM object for tester workflow."""
    req.equipment_type_name = req.equipment_type.name if req.equipment_type else None
    # Prefer UEIC from linked equipment, fall back to equipment_type name
    if req.equipment:
        req.equipment_ueic = req.equipment.ueic
        req.equipment_name = req.equipment.ueic
    else:
        req.equipment_ueic = None
        req.equipment_name = req.equipment_type.name if req.equipment_type else None
    req.test_type_name = req.test_type.name if req.test_type else None
    req.department_name = req.department.name if req.department else None
    if req.originator:
        req.originator_name = f"{req.originator.firstname or ''} {req.originator.lastname or ''}".strip() or req.originator.email
        req.requester_email = req.originator.email  # For Flutter UI
    else:
        req.originator_name = None
        req.requester_email = None
    if req.assigned_tester:
        req.assigned_tester_name = f"{req.assigned_tester.firstname or ''} {req.assigned_tester.lastname or ''}".strip() or req.assigned_tester.email
    else:
        req.assigned_tester_name = None
    return req


@router.get("/my-assignments", response_model=List[TestingRequestResponse])
def get_my_assignments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    assignments = service.get_my_assignments(tester_id=current_user.id, skip=skip, limit=limit)
    return [_enrich(req) for req in assignments]


@router.put("/{request_id}/accept", response_model=TestingRequestResponse)
def accept_assignment(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    req = service.accept_assignment(request_id, tester_id=current_user.id)
    return _enrich(req)


@router.put("/{request_id}/start", response_model=TestingRequestResponse)
def start_testing(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    req = service.start_testing(request_id, tester_id=current_user.id)
    return _enrich(req)


@router.get("/{request_id}/results")
def get_test_results(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    results = service.get_test_results(request_id)
    # Build response with image metadata for each result
    response = []
    for r in results:
        imgs = [
            TestResultImageResponse(
                id=img.id,
                file_name=img.file_name,
                file_type=img.file_type,
                file_size=img.file_size,
                caption=img.caption,
                download_url=f"/testing/results/images/{img.id}",
                cts=img.cts,
            )
            for img in (r.images or [])
        ]
        resp = TestResultResponse(
            id=r.id,
            testing_request_id=r.testing_request_id,
            test_name=r.test_name,
            test_category=r.test_category,
            result_value=r.result_value,
            result_unit=r.result_unit,
            pass_fail=r.pass_fail,
            remarks=r.remarks,
            file_name=r.file_name,
            file_type=r.file_type,
            file_size=r.file_size,
            template_key=r.template_key,
            test_data=r.test_data,
            overall_result=r.overall_result,
            replacement_products=r.replacement_products,
            evaluation_result=r.evaluation_result,
            tested_by=r.tested_by,
            tested_at=r.tested_at,
            image_count=len(imgs),
            images=imgs,
            cts=r.cts,
            mts=r.mts,
        )
        response.append(resp)
    return response


# ─── Test Result Approver Endpoints ──────────────────────────

@router.get("/pending-approval", response_model=List[TestingRequestResponse])
def get_pending_result_approvals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all testing requests in under_approval status for result approver review."""
    requests = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.status == TestingRequestStatus.under_approval,
            TestingRequest.organization_id == current_user.organization_id,
        )
        .order_by(TestingRequest.mts.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_enrich(req) for req in requests]


@router.put("/{request_id}/approve_results", response_model=TestingRequestResponse)
def approve_test_results(
    request_id: UUID,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve submitted test results — delegates to the approval/recommendation workflow.
    Blocked for: originator of the request, assigned tester."""
    from services.approval_service import ApprovalService

    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Testing request not found")

    # Prevent originator from approving their own request
    if req.originator_id == current_user.id:
        raise HTTPException(
            status_code=403,
            detail="The originator of a request cannot approve its results. An independent reviewer must approve.",
        )
    # Prevent assigned tester from approving results they submitted
    if req.assigned_tester_id == current_user.id:
        raise HTTPException(
            status_code=403,
            detail="The assigned tester cannot approve the results they submitted.",
        )

    rec = (
        db.query(Recommendation)
        .filter(Recommendation.testing_request_id == request_id)
        .order_by(Recommendation.cts.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="No recommendation found for this request")
    ApprovalService(db).approve_recommendation(
        recommendation_id=rec.id,
        approver_id=current_user.id,
        notes=body.get("comment"),
    )
    return _enrich(db.query(TestingRequest).filter(TestingRequest.id == request_id).first())


@router.put("/{request_id}/reject_results", response_model=TestingRequestResponse)
def reject_test_results(
    request_id: UUID,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject submitted test results — delegates to the approval/recommendation workflow.
    Blocked for: originator of the request, assigned tester."""
    from services.approval_service import ApprovalService

    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Testing request not found")

    # Prevent originator from rejecting/approving their own request
    if req.originator_id == current_user.id:
        raise HTTPException(
            status_code=403,
            detail="The originator of a request cannot reject its results.",
        )
    if req.assigned_tester_id == current_user.id:
        raise HTTPException(
            status_code=403,
            detail="The assigned tester cannot reject the results they submitted.",
        )

    rec = (
        db.query(Recommendation)
        .filter(Recommendation.testing_request_id == request_id)
        .order_by(Recommendation.cts.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="No recommendation found for this request")
    comment = body.get("comment", "")
    if not comment:
        raise HTTPException(status_code=400, detail="Rejection comment is required")
    ApprovalService(db).reject_recommendation(
        recommendation_id=rec.id,
        approver_id=current_user.id,
        notes=comment,
    )
    return _enrich(db.query(TestingRequest).filter(TestingRequest.id == request_id).first())


@router.put("/{request_id}/submit_results", response_model=TestingRequestResponse)
def submit_test_results(
    request_id: UUID,
    body: Optional[SubmitTestResultsBody] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TestingService(db)
    req = service.submit_test_results(
        request_id,
        tester_id=current_user.id,
        replacement_products=body.replacement_products if body else None,
    )
    return _enrich(req)


# ─── Template & Structured Results ──────────────────────────

@router.get("/templates/by-category/{request_category}")
def get_test_template_by_request_category(
    request_category: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the best-match template for a given request_category
    (maintenance | inspection | repair_lifecycle).
    Falls back to global default when no org-specific row exists.
    """
    from test_templates import REQUEST_CATEGORY_TO_TEMPLATE
    from models import OrgTestTemplate
    import copy
    template_key = REQUEST_CATEGORY_TO_TEMPLATE.get(request_category)
    if not template_key:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"No template mapped for request_category='{request_category}'",
        )
    tmpl = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.template_key == template_key)
        .first()
    )
    if not tmpl:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Template '{template_key}' not seeded — run /org-test-templates/provision/global")
    svc = __import__('services.org_test_template_service', fromlist=['OrgTestTemplateService']).OrgTestTemplateService(db)
    from services.testing_service import _deduplicated_overall_sections
    data = copy.deepcopy(tmpl.template_data or {})
    if "key" not in data:
        data["key"] = tmpl.template_key
    try:
        # Use current user's org_id so org-specific overall assessment edits
        # are picked up even when the main template is a global (org_id=None) one.
        # Deduplicate field keys so fields already in the main template are not
        # repeated from the overall_assessment template (e.g. overall_result).
        overall = svc.get_overall_assessment(org_id=current_user.organization_id)
        overall_sections = (overall.template_data or {}).get("sections", [])
        data.setdefault("sections", [])
        data["sections"].extend(
            _deduplicated_overall_sections(data["sections"], copy.deepcopy(overall_sections))
        )
    except Exception:
        pass
    return data


@router.get("/templates/by-key/{template_key}")
def get_test_template_by_key(
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the dynamic form template looked up by template key (for requests without a test_type_id)."""
    from services.org_test_template_service import OrgTestTemplateService
    import copy
    svc = OrgTestTemplateService(db)
    from services.testing_service import _deduplicated_overall_sections
    tmpl = svc.get_by_template_key(template_key)
    data = copy.deepcopy(tmpl.template_data or {})
    if "key" not in data:
        data["key"] = tmpl.template_key
    # Append Overall Assessment sections (template-driven).
    # Use current user's org_id so org-specific overall assessment edits
    # are picked up even when the main template is global (org_id=None).
    # Deduplicate field keys to prevent a double overall_result dropdown.
    try:
        overall = svc.get_overall_assessment(org_id=current_user.organization_id)
        overall_sections = (overall.template_data or {}).get("sections", [])
        data.setdefault("sections", [])
        data["sections"].extend(
            _deduplicated_overall_sections(data["sections"], copy.deepcopy(overall_sections))
        )
    except Exception:
        pass
    return data


@router.get("/templates/{test_type_id}")
def get_test_template(
    test_type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the dynamic form template for a test type."""
    service = TestingService(db)
    return service.get_template(test_type_id, org_id=current_user.organization_id)


@router.post("/{request_id}/results/structured", response_model=TestResultStructuredResponse)
def create_structured_result(
    request_id: UUID,
    data: TestResultStructuredCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit structured test results with JSONB data. Supports multi-session via test_session_id."""
    service = TestingService(db)
    result = service.create_structured_result(
        request_id=request_id,
        template_key=data.template_key,
        test_data=data.test_data,
        overall_result=data.overall_result,
        remarks=data.remarks,
        tester_id=current_user.id,
        replacement_products=data.replacement_products,
        test_session_id=data.test_session_id,  # Pass session_id for multi-session support
    )
    # Build response with images list
    return _build_structured_response(result)


@router.post("/results/{result_id}/images", response_model=List[TestResultImageResponse])
def upload_result_images(
    result_id: UUID,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload multiple images for a test result."""
    service = TestingService(db)
    images = service.upload_result_images(result_id, files, tester_id=current_user.id)
    return [
        TestResultImageResponse(
            id=img.id,
            file_name=img.file_name,
            file_type=img.file_type,
            file_size=img.file_size,
            caption=img.caption,
            download_url=f"/testing/results/images/{img.id}",
            cts=img.cts,
        )
        for img in images
    ]


@router.get("/results/images/{image_id}")
def download_result_image(
    image_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a single test result image."""
    service = TestingService(db)
    img = service.get_result_image(image_id)
    return Response(
        content=img.file_data,
        media_type=img.file_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{img.file_name}"'},
    )


def _build_structured_response(result) -> TestResultStructuredResponse:
    """Build a structured response with image metadata."""
    images = [
        TestResultImageResponse(
            id=img.id,
            file_name=img.file_name,
            file_type=img.file_type,
            file_size=img.file_size,
            caption=img.caption,
            download_url=f"/testing/results/images/{img.id}",
            cts=img.cts,
        )
        for img in (result.images or [])
    ]
    return TestResultStructuredResponse(
        id=result.id,
        testing_request_id=result.testing_request_id,
        test_name=result.test_name,
        template_key=result.template_key,
        test_data=result.test_data,
        overall_result=result.overall_result,
        remarks=result.remarks,
        replacement_products=result.replacement_products,
        evaluation_result=result.evaluation_result,
        tested_by=result.tested_by,
        tested_at=result.tested_at,
        images=images,
        cts=result.cts,
        mts=result.mts,
    )


@router.get("/results/{result_id}/preview", response_class=HTMLResponse)
def preview_test_result(
    result_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Render test result as styled HTML (browser-friendly preview)."""
    from models import TestResult
    from services.org_test_template_service import OrgTestTemplateService

    service = TestingService(db)
    result = db.query(TestResult).filter(TestResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="Test result not found")

    # Get template definition to render fields properly
    template_service = OrgTestTemplateService(db)
    template = None
    if result.template_key:
        template = template_service.get_by_template_key(result.template_key)

    test_data = result.test_data or {}
    overall_result = result.overall_result or "N/A"
    tested_at = result.tested_at.strftime("%d/%m/%Y %H:%M:%S") if result.tested_at else "N/A"

    # Determine result badge color
    badge_color = "#4CAF50" if overall_result.lower() in ["pass", "ok"] else \
                  "#f44336" if overall_result.lower() in ["fail", "failed"] else \
                  "#ff9800" if overall_result.lower() in ["conditional", "warning"] else \
                  "#9e9e9e"

    # Build field HTML from test_data
    def format_field_name(key: str) -> str:
        """Convert snake_case to Title Case."""
        return " ".join(word.capitalize() for word in key.split("_"))

    def render_value(value) -> str:
        """Render value safely as HTML."""
        if isinstance(value, (list, dict)):
            import json
            return f"<pre>{json.dumps(value, indent=2)}</pre>"
        return str(value) if value is not None else "-"

    def render_test_data_structure(data: dict, depth: int = 0) -> str:
        """
        Intelligently render test data based on structure:
        - List of dicts with consistent keys → Table
        - Dict with simple key-value pairs → Two-column grid
        - Section with nested data → Heading + recursive render
        """
        html = ""

        for key, value in data.items():
            section_name = format_field_name(key)

            if isinstance(value, list) and value and isinstance(value[0], dict):
                # LIST OF DICTS → RENDER AS TABLE
                html += f'<h4 style="color:#2a5298; margin-top:20px; margin-bottom:10px;">{section_name}</h4>'
                html += render_table_from_list(value)

            elif isinstance(value, dict):
                # Check if it's simple key-value or nested
                has_nested = any(isinstance(v, (dict, list)) for v in value.values())

                if has_nested:
                    # NESTED DICT → SECTION HEADING + RECURSIVE
                    html += f'<h4 style="color:#2a5298; margin-top:20px; margin-bottom:10px;">{section_name}</h4>'
                    html += render_test_data_structure(value, depth + 1)
                else:
                    # SIMPLE KEY-VALUE DICT → TWO-COLUMN LAYOUT
                    html += f'<h4 style="color:#2a5298; margin-top:20px; margin-bottom:10px;">{section_name}</h4>'
                    html += render_two_column_layout(value)

            else:
                # SIMPLE VALUE → Add to two-column
                html += render_two_column_layout({key: value})

        return html

    def render_table_from_list(data_list: list) -> str:
        """Render list of dicts as HTML table"""
        if not data_list:
            return ""

        # Extract headers from first dict
        headers = list(data_list[0].keys())

        html = '<table class="data-table"><thead><tr>'
        for header in headers:
            html += f'<th>{format_field_name(header)}</th>'
        html += '</tr></thead><tbody>'

        for row in data_list:
            html += '<tr>'
            for header in headers:
                value = row.get(header, '-')
                html += f'<td>{value}</td>'
            html += '</tr>'

        html += '</tbody></table>'
        return html

    def render_two_column_layout(data_dict: dict) -> str:
        """Render simple key-value pairs in two-column grid"""
        html = '<div class="fields">'
        for key, value in data_dict.items():
            label = format_field_name(key)
            display_value = str(value) if value is not None else '-'
            html += f'''
            <div class="field">
                <label>{label}</label>
                <div class="value">{display_value}</div>
            </div>
            '''
        html += '</div>'
        return html

    fields_html = ""

    if template and template.template_data:
        # Render using template structure for better formatting
        sections = template.template_data.get("sections", [])
        for section in sections:
            section_title = section.get("title", "")
            fields = section.get("fields", [])

            if not fields:
                continue

            fields_html += f'<div class="section"><h3>{section_title}</h3><div class="fields">'

            for field in fields:
                field_key = field.get("key", "")
                field_label = field.get("label", format_field_name(field_key))
                field_value = test_data.get(field_key, "-")
                field_type = field.get("type", "text")
                unit = field.get("unit", "")

                # Format value based on field type
                if field_type == "toggle":
                    display_value = "✓ Yes" if field_value else "✗ No"
                elif field_type == "table":
                    # Render table
                    if isinstance(field_value, list) and field_value:
                        cols = field.get("columns", [])
                        display_value = "<table class='data-table'><thead><tr>"
                        for col in cols:
                            display_value += f"<th>{col.get('label', col.get('key', ''))}</th>"
                        display_value += "</tr></thead><tbody>"
                        for row in field_value:
                            display_value += "<tr>"
                            for col in cols:
                                cell_val = row.get(col.get('key', ''), '-')
                                display_value += f"<td>{cell_val}</td>"
                            display_value += "</tr>"
                        display_value += "</tbody></table>"
                    else:
                        display_value = "-"
                else:
                    display_value = render_value(field_value)
                    if unit and display_value != "-":
                        display_value += f" {unit}"

                fields_html += f'''
                <div class="field">
                    <label>{field_label}</label>
                    <div class="value">{display_value}</div>
                </div>
                '''

            fields_html += '</div></div>'
    else:
        # No template - render raw test_data intelligently
        fields_html += '<div class="section"><h3>Test Data</h3>'
        fields_html += render_test_data_structure(test_data)
        fields_html += '</div>'

    # Add remarks if present
    if result.remarks:
        fields_html += f'''
        <div class="section">
            <h3>Remarks</h3>
            <div class="remarks">{result.remarks}</div>
        </div>
        '''

    # Add evaluation result if present
    if result.evaluation_result:
        eval_data = result.evaluation_result
        overall_eval = eval_data.get("overall", "")
        alerts = eval_data.get("alerts", [])

        if overall_eval or alerts:
            fields_html += '<div class="section"><h3>Evaluation Results</h3>'
            if overall_eval:
                eval_color = "#4CAF50" if overall_eval == "OK" else \
                            "#f44336" if overall_eval == "CRITICAL" else \
                            "#ff9800"
                fields_html += f'<div class="eval-badge" style="background:{eval_color}">{overall_eval}</div>'

            if alerts:
                fields_html += '<ul class="alerts">'
                for alert in alerts:
                    alert_msg = alert.get("message", "")
                    alert_level = alert.get("level", "info")
                    icon = "⚠️" if alert_level in ["warning", "ALERT"] else "🚨" if alert_level == "CRITICAL" else "ℹ️"
                    fields_html += f'<li>{icon} {alert_msg}</li>'
                fields_html += '</ul>'

            fields_html += '</div>'

    # ── Session data section (multi-session testing) ─────────────────────────
    from models import TestSession as _TestSession, TestSessionReading as _TestSessionReading
    from sqlalchemy.orm import joinedload as _jl

    _sessions = (
        db.query(_TestSession)
        .options(_jl(_TestSession.readings))
        .filter(_TestSession.testing_request_id == result.testing_request_id)
        .order_by(_TestSession.session_number)
        .all()
    )

    SESSION_STATUS_COLORS = {
        "completed":  "#4CAF50",
        "in_progress": "#FF9800",
        "skipped":    "#F44336",
        "scheduled":  "#9E9E9E",
    }
    RESULT_STATUS_COLORS = {
        "pass":        "#4CAF50",
        "fail":        "#F44336",
        "conditional": "#FF9800",
        "warning":     "#FFC107",
    }

    def _fmt_dt(dt):
        return dt.strftime("%d/%m/%Y %H:%M") if dt else "-"

    sessions_html = ""
    if _sessions:
        # ── Part 1: Session Summary table ─────────────────────────────────────

        def _dur(sess):
            if sess.started_at and sess.completed_at:
                mins = int((sess.completed_at - sess.started_at).total_seconds() / 60)
                return f"{mins//60}h {mins%60}m" if mins >= 60 else f"{mins}m"
            return "-"

        sessions_html += '<div class="section"><h3>Session Data</h3>'
        sessions_html += '<h4 style="color:#2a5298;margin-bottom:8px">Session Summary</h4>'
        sessions_html += '''<table class="data-table">
          <thead><tr>
            <th>#</th><th>Session Name</th><th>Date</th>
            <th>Readings</th><th>Duration</th><th>Status</th>
          </tr></thead><tbody>'''
        for s in _sessions:
            s_status = (s.status or "scheduled").lower()
            s_color  = SESSION_STATUS_COLORS.get(s_status, "#9E9E9E")
            r_count  = len(s.readings or [])
            sessions_html += f'''<tr>
              <td style="text-align:center">{s.session_number}</td>
              <td>{s.session_name or f"Session {s.session_number}"}</td>
              <td style="text-align:center">{_fmt_dt(s.session_date)[:10]}</td>
              <td style="text-align:center">{r_count}</td>
              <td style="text-align:center">{_dur(s)}</td>
              <td style="text-align:center">
                <span style="background:{s_color};color:#fff;padding:3px 10px;
                  border-radius:10px;font-size:11px;font-weight:700">
                  {s_status.upper()}
                </span>
              </td>
            </tr>'''
        sessions_html += "</tbody></table>"

        # ── Part 2: Consolidated Readings table (all sessions, one table) ──────
        _all_keys: list = []
        _all_pairs: list = []
        for s in _sessions:
            for _r in sorted(s.readings or [], key=lambda r: r.reading_number):
                _all_pairs.append((s, _r))
                for _k in (_r.reading_data or {}).keys():
                    if _k not in _all_keys:
                        _all_keys.append(_k)

        if _all_pairs:
            _readable = [" ".join(w.capitalize() for w in k.split("_")) for k in _all_keys]
            total_r = len(_all_pairs)
            sessions_html += f'<h4 style="color:#2a5298;margin:20px 0 8px">Consolidated Readings ({total_r} total)</h4>'
            sessions_html += '<table class="data-table"><thead><tr>'
            for _h in ["Session", "#", "Date / Time", "Result"] + _readable + ["Remarks"]:
                sessions_html += f"<th>{_h}</th>"
            sessions_html += "</tr></thead><tbody>"

            _prev_snum = None
            for s, _r in _all_pairs:
                # Group header row when session changes
                if s.session_number != _prev_snum:
                    _s_label = s.session_name or f"Session {s.session_number}"
                    _n_cols = 4 + len(_all_keys) + 1
                    sessions_html += f'''<tr>
                      <td colspan="{_n_cols}"
                          style="background:#2a5298;color:#fff;font-weight:700;
                                 font-size:12px;padding:7px 12px;">
                        Session {s.session_number}: {_s_label}
                        &nbsp;·&nbsp; {_fmt_dt(s.session_date)[:10]}
                      </td>
                    </tr>'''
                    _prev_snum = s.session_number

                _rs  = (_r.result_status or "").lower()
                _rc  = RESULT_STATUS_COLORS.get(_rs, "#9E9E9E")
                sessions_html += "<tr>"
                sessions_html += f"<td style='text-align:center;font-weight:600'>{s.session_number}</td>"
                sessions_html += f"<td style='text-align:center'>{_r.reading_number}</td>"
                sessions_html += f"<td style='text-align:center'>{_fmt_dt(_r.reading_time)}</td>"
                sessions_html += (
                    f"<td style='text-align:center'>"
                    f"<span style='background:{_rc};color:#fff;padding:2px 8px;"
                    f"border-radius:10px;font-size:11px;font-weight:600'>"
                    f"{_rs.upper() or '-'}</span></td>"
                )
                for _k in _all_keys:
                    sessions_html += f"<td>{(_r.reading_data or {}).get(_k, '-')}</td>"
                sessions_html += f"<td>{_r.remarks or '-'}</td>"
                sessions_html += "</tr>"

            sessions_html += "</tbody></table>"

        sessions_html += "</div>"

    fields_html += sessions_html

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Result - {result.test_name or result.template_key or 'Preview'}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            padding: 30px;
        }}
        .header h1 {{
            font-size: 24px;
            margin-bottom: 15px;
        }}
        .meta {{
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
            font-size: 14px;
            opacity: 0.95;
        }}
        .meta-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .meta-item strong {{
            font-weight: 600;
        }}
        .result-badge {{
            display: inline-block;
            background: {badge_color};
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .content {{
            padding: 30px;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        .section h3 {{
            color: #333;
            font-size: 18px;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e0e0e0;
        }}
        .fields {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }}
        .field {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border-left: 3px solid #667eea;
        }}
        .field label {{
            display: block;
            color: #555;
            font-weight: 600;
            font-size: 13px;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .field .value {{
            color: #222;
            font-size: 15px;
            word-wrap: break-word;
        }}
        .remarks {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            border-radius: 8px;
            color: #856404;
        }}
        .eval-badge {{
            display: inline-block;
            padding: 10px 20px;
            border-radius: 8px;
            color: white;
            font-weight: 600;
            margin-bottom: 15px;
        }}
        .alerts {{
            list-style: none;
            padding: 0;
        }}
        .alerts li {{
            background: #fff3cd;
            padding: 12px 15px;
            margin-bottom: 8px;
            border-radius: 6px;
            border-left: 3px solid #ff9800;
        }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        .data-table th,
        .data-table td {{
            padding: 10px;
            text-align: left;
            border: 1px solid #ddd;
        }}
        .data-table th {{
            background: #667eea;
            color: white;
            font-weight: 600;
        }}
        .data-table tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        pre {{
            background: #f5f5f5;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 12px;
        }}
        .session-card {{
            margin-bottom: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            overflow: hidden;
        }}
        .session-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
        }}
        .session-title {{
            color: white;
            font-weight: 700;
            font-size: 14px;
        }}
        .session-badge {{
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}
        .session-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            padding: 10px 16px;
            background: #f8f9fa;
            font-size: 12px;
            color: #555;
            border-bottom: 1px solid #e0e0e0;
        }}
        .preview-badge {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 10px 20px;
            border-radius: 25px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 1px;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .preview-badge {{ display: none; }}
            .container {{ box-shadow: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{result.test_name or result.template_key or "Test Result"}</h1>
            <div class="meta">
                <div class="meta-item">
                    <strong>Result:</strong>
                    <span class="result-badge">{overall_result}</span>
                </div>
                <div class="meta-item">
                    <strong>Tested At:</strong> {tested_at}
                </div>
                {f'<div class="meta-item"><strong>Template:</strong> {result.template_key}</div>' if result.template_key else ''}
            </div>
        </div>
        <div class="content">
            {fields_html}
        </div>
    </div>
    <div class="preview-badge">TEST RESULT PREVIEW</div>
</body>
</html>"""

    return HTMLResponse(content=html_page)


@router.get("/results/{result_id}/pdf")
def generate_test_result_pdf(
    result_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate professional PDF report from test result using ReportLab."""
    from fastapi.responses import StreamingResponse
    from services.test_result_pdf_service import TestResultPDFService

    try:
        pdf_service = TestResultPDFService(db)
        pdf_buffer = pdf_service.generate_pdf(result_id)

        # Return PDF as streaming response
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="test_result_{result_id}.pdf"'
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")
