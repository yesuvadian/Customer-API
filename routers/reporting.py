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

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from services.reporting_service import ReportingService

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(get_current_user)],
)

# ── Available query keys (ad-hoc builder uses this) ────────────────────────

QUERY_KEYS = [
    {"key": "equipment_condition_summary",    "label": "Equipment Condition Summary",
     "description": "All active equipment with latest test condition (CRITICAL/ALERT/NORMAL/NOT_TESTED)"},
    {"key": "overdue_tests_report",           "label": "Overdue Tests",
     "description": "Testing requests past their due date"},
    {"key": "active_alerts_report",           "label": "Active Alerts",
     "description": "Test results with CRITICAL or ALERT evaluation"},
    {"key": "flagged_equipment_report",       "label": "Flagged Equipment",
     "description": "Equipment with CRITICAL or ALERT status (deduplicated)"},
    {"key": "repair_progress_report",         "label": "Repair Lifecycle Progress",
     "description": "Repair lifecycle requests with session progress"},
    {"key": "maintenance_overdue_report",     "label": "Maintenance Overdue",
     "description": "Preventive maintenance requests past due date"},
    {"key": "procurement_pipeline_report",    "label": "Procurement Pipeline",
     "description": "All procurement requests with status"},
    {"key": "open_remediation_report",        "label": "Open Remediation Records",
     "description": "Pending recommendations awaiting approval"},
    {"key": "testing_request_status_report",  "label": "Testing Request Status",
     "description": "All testing requests with current status and assignment"},
    {"key": "test_results_summary_report",    "label": "Test Results Summary",
     "description": "Test results with evaluation outcomes"},
    {"key": "recommendation_approval_report", "label": "Recommendation Approvals",
     "description": "Recommendations with approval status and notes"},
    {"key": "compliance_status_report",       "label": "Compliance Status by Substation",
     "description": "Equipment testing compliance rates grouped by substation"},
    {"key": "tester_performance_report",      "label": "Tester Performance",
     "description": "Tester completion rates and average turnaround times"},
    {"key": "monthly_kpi_report",             "label": "Monthly KPI Summary",
     "description": "Monthly aggregated KPIs: requests, completions, alerts, findings"},
]


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


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/definitions/query-keys")
def get_query_keys():
    """Return the list of built-in query keys for the ad-hoc builder."""
    return QUERY_KEYS


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
