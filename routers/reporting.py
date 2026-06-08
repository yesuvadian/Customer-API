"""
Reporting Suite Endpoints
=========================
GET  /reports/definitions              List all report definitions
POST /reports/definitions              Create ad-hoc definition
GET  /reports/definitions/{id}         Get one definition
PUT  /reports/definitions/{id}         Update definition
GET  /reports/definitions/query-keys   List available query keys

POST /reports/definitions/{id}/run     Generate report -> returns binary file
GET  /reports/logs                     List generation history
GET  /reports/logs/{id}                Get one log entry
"""

from typing import Optional
from uuid import UUID

import os

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, ReportQueryKey
from services.reporting_service import ReportingService

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(get_current_user)],
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _svc(db: Session, current_user: User,
         org_id: Optional[UUID] = None) -> ReportingService:
    """Resolve org from user's OrgUserRole if not supplied."""
    resolved = org_id
    if resolved is None:
        from models import OrgUserRole, OrgRole
        row = (
            db.query(OrgUserRole)
            .filter(OrgUserRole.user_id == current_user.id,
                    OrgUserRole.is_active.is_(True))
            .first()
        )
        if row:
            role = db.query(OrgRole).filter(OrgRole.id == row.org_role_id).first()
            if role:
                resolved = role.organization_id
    return ReportingService(db, org_id=resolved)


def _defn_to_dict(defn) -> dict:
    return {
        "id":               str(defn.id),
        "name":             defn.name,
        "description":      defn.description,
        "query_key":        defn.query_key,
        "parameters":       defn.parameters,
        "output_format":    defn.output_format,
        "frequency":        defn.frequency,
        "recipient_roles":  defn.recipient_roles,
        "is_active":        defn.is_active,
        "is_system":        defn.is_system,
        "last_generated_at": defn.last_generated_at.isoformat()
                              if defn.last_generated_at else None,
        "cts":              defn.cts.isoformat() if defn.cts else None,
    }


def _log_to_dict(log) -> dict:
    return {
        "id":             str(log.id),
        "definition_id":  str(log.definition_id),
        "output_format":  log.output_format,
        "file_name":      log.file_name,
        "file_size":      log.file_size,
        "row_count":      log.row_count,
        "status":         log.status,
        "error_message":  log.error_message,
        "started_at":     log.started_at.isoformat()   if log.started_at   else None,
        "completed_at":   log.completed_at.isoformat() if log.completed_at else None,
        "cts":            log.cts.isoformat()           if log.cts          else None,
    }


# ── Pydantic schemas ───────────────────────────────────────────────────────

class DefinitionCreate(BaseModel):
    name:            str
    description:     Optional[str] = None
    query_key:       str
    parameters:      dict = {}
    output_format:   str  = "excel"
    frequency:       str  = "on_demand"
    recipient_roles: list = []


class DefinitionUpdate(BaseModel):
    name:            Optional[str]  = None
    description:     Optional[str]  = None
    parameters:      Optional[dict] = None
    output_format:   Optional[str]  = None
    frequency:       Optional[str]  = None
    recipient_roles: Optional[list] = None
    is_active:       Optional[bool] = None


class RunRequest(BaseModel):
    parameters:    dict = {}
    output_format: str  = "excel"   # excel | pdf


class ConsolidatedReportRequest(BaseModel):
    department_id:     UUID
    equipment_type_id: int
    test_type_ids:     list[int] = []
    date_from:         Optional[str] = None   # "YYYY-MM-DD"
    date_to:           Optional[str] = None
    equipment_ids:     Optional[list[UUID]] = None
    delivery:          str = "on_demand"      # on_demand | email
    output_format:     str = "pdf"            # on_demand: pdf | excel  (email always sends both)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/definitions/query-keys")
def get_query_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return available report query keys from the database."""
    keys = (
        db.query(ReportQueryKey)
        .filter(ReportQueryKey.is_active.is_(True))
        .order_by(ReportQueryKey.group_name, ReportQueryKey.sort_order)
        .all()
    )
    return [
        {
            "key":               k.key,
            "label":             k.label,
            "description":       k.description,
            "group_name":        k.group_name,
            "parameters_schema": k.parameters_schema,
        }
        for k in keys
    ]


@router.get("/definitions")
def list_definitions(
    active_only: bool = Query(True),
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc   = _svc(db, current_user, org_id)
    defs  = svc.list_definitions(active_only=active_only)
    return [_defn_to_dict(d) for d in defs]


@router.post("/definitions", status_code=201)
def create_definition(
    body: DefinitionCreate,
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc  = _svc(db, current_user, org_id)
    defn = svc.create_definition(body.dict(), user_id=current_user.id)
    return _defn_to_dict(defn)


@router.get("/definitions/{definition_id}")
def get_definition(
    definition_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc  = _svc(db, current_user)
    defn = svc.get_definition(definition_id)
    if not defn:
        raise HTTPException(404, "Report definition not found")
    return _defn_to_dict(defn)


@router.put("/definitions/{definition_id}")
def update_definition(
    definition_id: UUID,
    body: DefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = _svc(db, current_user)
    try:
        defn = svc.update_definition(
            definition_id,
            {k: v for k, v in body.dict().items() if v is not None},
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _defn_to_dict(defn)


@router.post("/definitions/{definition_id}/run")
def run_report(
    definition_id: UUID,
    body: RunRequest,
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate report and return the file as binary.
    Content-Disposition header carries the filename.
    """
    svc = _svc(db, current_user, org_id)
    try:
        raw, filename, content_type = svc.generate(
            definition_id=definition_id,
            parameters=body.parameters,
            output_format=body.output_format,
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(422, str(e))

    return Response(
        content=raw,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Filename":   filename,
            "X-Row-Count":         str(len(raw)),   # approximate
        },
    )


@router.get("/logs")
def list_logs(
    definition_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc  = _svc(db, current_user, org_id)
    logs = svc.list_logs(definition_id=definition_id, limit=limit)
    return [_log_to_dict(lg) for lg in logs]


# ── Reporting Center endpoints ─────────────────────────────────────────────────

@router.get("/groups")
def get_report_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return distinct group_name values for Reporting Center filter chips."""
    from sqlalchemy import distinct
    from models import ReportDefinition
    rows = db.query(distinct(ReportDefinition.group_name)).filter(
        ReportDefinition.group_name.isnot(None)
    ).all()
    return sorted([r[0] for r in rows if r[0]])


@router.get("/download/{filename:path}")
def download_report_file(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Serve a previously generated scheduled report file."""
    # Sanitise: strip any path traversal
    safe_name = os.path.basename(filename)
    path = os.path.join("uploads", "reports", safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report file not found or expired")
    if filename.endswith(".xlsx"):
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media = "application/pdf"
    return FileResponse(
        path,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ── Consolidated Test Report (multi-equipment, multi-test PDF) ──────────────────

@router.post("/consolidated-test-report")
def consolidated_test_report(
    body: ConsolidatedReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a single combined PDF spanning every equipment of the chosen type
    within the user's department subtree, including the selected test types
    completed in the given date range. Grouped per equipment.
    """
    from datetime import date as _date
    from services.consolidated_report_service import ConsolidatedReportService

    def _parse(d: Optional[str]) -> Optional[_date]:
        if not d:
            return None
        try:
            return _date.fromisoformat(d[:10])
        except Exception:
            return None

    svc = ConsolidatedReportService(db)
    _df, _dt = _parse(body.date_from), _parse(body.date_to)
    _args = dict(
        department_id=body.department_id,
        equipment_type_id=body.equipment_type_id,
        test_type_ids=body.test_type_ids,
        date_from=_df,
        date_to=_dt,
        equipment_ids=body.equipment_ids,
    )
    _stamp = f"{(body.date_from or 'all')}_{(body.date_to or 'all')}"

    # ── EMAIL delivery: send PDF + Excel to the requesting user ────────────────
    if body.delivery == "email":
        if not current_user.email:
            raise HTTPException(400, "Your account has no email address on file.")
        pdf_bytes = svc.generate(**_args)
        xls_bytes = svc.generate_excel(**_args)
        from utils.email_service import EmailService
        try:
            EmailService().send_multi_attachment_email_starttls_bcc(
                bcc_emails=[current_user.email],
                subject=f"[Consolidated Test Report] {_stamp}",
                body_html=(
                    "<h3 style='color:#1565C0'>Consolidated Test Report</h3>"
                    "<p>Your requested consolidated test report is attached "
                    "in <strong>PDF</strong> and <strong>Excel</strong> formats.</p>"
                    "<p style='color:#888;font-size:12px'>Generated by CogniWatt SEACMS</p>"
                ),
                attachments=[
                    {"content": pdf_bytes, "filename": f"consolidated_report_{_stamp}.pdf",
                     "mime_type": "application/pdf"},
                    {"content": xls_bytes, "filename": f"consolidated_report_{_stamp}.xlsx",
                     "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                ],
            )
        except Exception as e:
            raise HTTPException(502, f"Failed to send email: {e}")
        return {"status": "sent", "message": f"Report emailed to {current_user.email}"}

    # ── ON-DEMAND delivery: return the file directly ───────────────────────────
    if body.output_format == "excel":
        raw = svc.generate_excel(**_args)
        filename = f"consolidated_report_{_stamp}.xlsx"
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raw = svc.generate(**_args)
        filename = f"consolidated_report_{_stamp}.pdf"
        media = "application/pdf"

    return Response(
        content=raw,
        media_type=media,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Report-Filename": filename,
        },
    )
