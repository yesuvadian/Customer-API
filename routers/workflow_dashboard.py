"""
workflow_dashboard.py
─────────────────────
GET /workflow-dashboard/

Returns a unified dashboard payload built dynamically from repair_workflow_definitions.
Adding a new workflow type to that table automatically appears in the response.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    Equipment,
    RepairStageAuditLog,
    RepairStageDefinition,
    RepairWorkflow,
    RepairWorkflowDefinition,
    User,
)

router = APIRouter(
    prefix="/workflow-dashboard",
    tags=["workflow-dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _user_name(user: User | None) -> str | None:
    if not user:
        return None
    full = f"{user.firstname or ''} {user.lastname or ''}".strip()
    return full or user.email or None


@router.get("/")
def get_workflow_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id

    # ── 1. All active workflow definitions ───────────────────────────────────
    definitions = (
        db.query(RepairWorkflowDefinition)
        .filter(RepairWorkflowDefinition.is_active.is_(True))
        .order_by(RepairWorkflowDefinition.created_at)
        .all()
    )

    # ── 2. Per-definition stats ───────────────────────────────────────────────
    # Single aggregation query: (workflow_code, status) → count
    # outerjoin Equipment so org-level workflows (no equipment_id) are included
    counts_raw = (
        db.query(
            RepairWorkflow.workflow_code,
            RepairWorkflow.status,
            func.count(RepairWorkflow.id).label("cnt"),
        )
        .outerjoin(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .filter(
            or_(
                Equipment.organization_id == org_id,
                RepairWorkflow.organization_id == org_id,
            )
        )
        .group_by(RepairWorkflow.workflow_code, RepairWorkflow.status)
        .all()
    )
    # Build lookup: { code: { status: count } }
    counts: dict[str, dict[str, int]] = {}
    for code, status, cnt in counts_raw:
        counts.setdefault(code or "", {})[status or ""] = cnt

    # Pending assignment counts per code
    pending_raw = (
        db.query(
            RepairWorkflow.workflow_code,
            func.count(RepairWorkflow.id).label("cnt"),
        )
        .outerjoin(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .filter(
            or_(
                Equipment.organization_id == org_id,
                RepairWorkflow.organization_id == org_id,
            ),
            RepairWorkflow.status == "active",
            RepairWorkflow.assignment_pending.is_(True),
        )
        .group_by(RepairWorkflow.workflow_code)
        .all()
    )
    pending: dict[str, int] = {code: cnt for code, cnt in pending_raw}

    workflow_types = []
    total_active = total_completed = total_cancelled = total_pending = 0

    for defn in definitions:
        code = defn.workflow_code or ""
        stat = counts.get(code, {})
        active    = stat.get("active", 0)
        completed = stat.get("completed", 0)
        cancelled = stat.get("cancelled", 0)
        pend      = pending.get(code, 0)

        total_active    += active
        total_completed += completed
        total_cancelled += cancelled
        total_pending   += pend

        workflow_types.append({
            "code":               code,
            "name":               defn.name,
            "active":             active,
            "completed":          completed,
            "cancelled":          cancelled,
            "pending_assignment": pend,
        })

    totals = {
        "active":             total_active,
        "completed":          total_completed,
        "cancelled":          total_cancelled,
        "pending_assignment": total_pending,
    }

    # ── 3. Stage breakdown — active workflows only ────────────────────────────
    stage_breakdown_raw = (
        db.query(
            RepairWorkflow.workflow_code,
            RepairStageDefinition.name,
            func.count(RepairWorkflow.id).label("cnt"),
        )
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .join(
            RepairStageDefinition,
            RepairStageDefinition.id == RepairWorkflow.current_stage_id,
        )
        .filter(
            Equipment.organization_id == org_id,
            RepairWorkflow.status == "active",
        )
        .group_by(RepairWorkflow.workflow_code, RepairStageDefinition.name)
        .order_by(RepairWorkflow.workflow_code, func.count(RepairWorkflow.id).desc())
        .all()
    )
    stage_breakdown = [
        {"workflow_code": code, "stage_name": stage, "count": cnt}
        for code, stage, cnt in stage_breakdown_raw
    ]

    # ── 4. Equipment at risk (active workflows) ───────────────────────────────
    at_risk_rows = (
        db.query(
            RepairWorkflow.workflow_code,
            RepairWorkflow.workflow_number,
            RepairWorkflow.assignment_pending,
            Equipment.ueic,
            RepairStageDefinition.name.label("stage_name"),
        )
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .outerjoin(
            RepairStageDefinition,
            RepairStageDefinition.id == RepairWorkflow.current_stage_id,
        )
        .filter(
            Equipment.organization_id == org_id,
            RepairWorkflow.status == "active",
        )
        .order_by(RepairWorkflow.started_at.desc())
        .limit(20)
        .all()
    )
    equipment_at_risk = [
        {
            "workflow_code":      code,
            "workflow_number":    number,
            "equipment_ueic":     ueic,
            "current_stage":      stage,
            "assignment_pending": pending_flag,
        }
        for code, number, pending_flag, ueic, stage in at_risk_rows
    ]

    # ── 5. Recent activity (last 15 audit log entries) ────────────────────────
    activity_rows = (
        db.query(RepairStageAuditLog)
        .join(RepairWorkflow, RepairWorkflow.id == RepairStageAuditLog.workflow_id)
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .filter(Equipment.organization_id == org_id)
        .order_by(RepairStageAuditLog.performed_at.desc())
        .limit(15)
        .all()
    )
    recent_activity = []
    for log in activity_rows:
        wf = log.workflow
        recent_activity.append({
            "workflow_code":   wf.workflow_code if wf else None,
            "workflow_number": wf.workflow_number if wf else None,
            "equipment_ueic":  wf.equipment.ueic if wf and wf.equipment else None,
            "stage_name":      log.stage.name if log.stage else None,
            "action":          log.action,
            "performed_by":    _user_name(log.performer),
            "performed_at":    log.performed_at.isoformat() if log.performed_at else None,
            "note":            log.note,
        })

    return {
        "workflow_types":   workflow_types,
        "totals":           totals,
        "stage_breakdown":  stage_breakdown,
        "equipment_at_risk": equipment_at_risk,
        "recent_activity":  recent_activity,
    }
