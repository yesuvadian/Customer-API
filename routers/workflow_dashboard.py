"""
workflow_dashboard.py
─────────────────────
GET /workflow-dashboard/

Returns a unified dashboard payload built dynamically from repair_workflow_definitions.
Adding a new workflow type to that table automatically appears in the response.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from utils.db_time import db_naive_to_aware
from models import (
    Equipment,
    OrgDepartment,
    RepairStageAuditLog,
    RepairStageDefinition,
    RepairStageInstance,
    RepairWorkflow,
    RepairWorkflowDefinition,
    User,
)


def _dept_ids(department_id: UUID | None, db: Session) -> set | None:
    if department_id is None:
        return None
    visited: set = set()
    queue = [department_id]
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for (child_id,) in db.query(OrgDepartment.id).filter(
            OrgDepartment.parent_department_id == cur
        ).all():
            queue.append(child_id)
    return visited

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
    department_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    dept_ids = _dept_ids(department_id, db)

    # ── 1. All active workflow definitions ───────────────────────────────────
    definitions = (
        db.query(RepairWorkflowDefinition)
        .filter(RepairWorkflowDefinition.is_active.is_(True))
        .order_by(
            RepairWorkflowDefinition.workflow_code,
            RepairWorkflowDefinition.created_at.desc(),
        )
        .all()
    )

    # Only one dashboard entry per workflow code.
    # Counts are already aggregated by workflow_code, so duplicate
    # active definitions must not cause the same count to be added twice.
    unique_definitions = {}
    for defn in definitions:
        code = defn.workflow_code or ""
        if code and code not in unique_definitions:
            unique_definitions[code] = defn

    definitions = list(unique_definitions.values())

    # ── 2. Per-definition stats ───────────────────────────────────────────────
    # Single aggregation query: (workflow_code, status) → count
    # outerjoin Equipment so org-level workflows (no equipment_id) are included
    def _eq_filter():
        if dept_ids:
            return Equipment.department_id.in_(dept_ids)
        return Equipment.organization_id == org_id

    counts_raw = (
        db.query(
            RepairWorkflow.workflow_code,
            RepairWorkflow.status,
            func.count(RepairWorkflow.id).label("cnt"),
        )
        .outerjoin(
            Equipment,
            Equipment.id == RepairWorkflow.equipment_id,
        )
        .filter(_eq_filter())
        .group_by(
            RepairWorkflow.workflow_code,
            RepairWorkflow.status,
        )
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
            _eq_filter(),
            RepairWorkflow.status == "active",
            RepairWorkflow.assignment_pending.is_(True),
        )
        .group_by(RepairWorkflow.workflow_code)
        .all()
    )
    pending: dict[str, int] = {code: cnt for code, cnt in pending_raw}

    workflow_types = []

    # Use actual workflow codes as the source of truth.
    all_codes = set(counts.keys()) | set(pending.keys())

    # Build definition lookup only for display names.
    definition_by_code = {}

    for defn in definitions:
        code = defn.workflow_code or ""
        if code and code not in definition_by_code:
            definition_by_code[code] = defn

    for code in sorted(all_codes):
        stat = counts.get(code, {})

        active = stat.get("active", 0)
        completed = stat.get("completed", 0)
        cancelled = stat.get("cancelled", 0)
        scheduled = stat.get("scheduled", 0)
        pend = pending.get(code, 0)

        defn = definition_by_code.get(code)

        workflow_types.append({
            "code": code,
            "name": defn.name if defn else code,
            "active": active,
            "completed": completed,
            "cancelled": cancelled,
            "scheduled": scheduled,
            "pending_assignment": pend,
        })

    # Dashboard totals are calculated directly from the same
    # RepairWorkflow aggregation used to build workflow_types.
    totals = {
        "active": sum(
            stat.get("active", 0)
            for stat in counts.values()
        ),
        "completed": sum(
            stat.get("completed", 0)
            for stat in counts.values()
        ),
        "cancelled": sum(
            stat.get("cancelled", 0)
            for stat in counts.values()
        ),
        "scheduled": sum(
            stat.get("scheduled", 0)
            for stat in counts.values()
        ),
        "pending_assignment": sum(
            pending.values()
        ),
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
            _eq_filter(),
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
    def _at_risk_query():
        return (
            db.query(
                RepairWorkflow.id,
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
                _eq_filter(),
                RepairWorkflow.status == "active",
            )
        )

    def _at_risk_rows(rows):
        return [
            {
                "workflow_id":        str(wf_id),
                "workflow_code":      code,
                "workflow_number":    number,
                "equipment_ueic":     ueic,
                "current_stage":      stage,
                "assignment_pending": pending_flag,
            }
            for wf_id, code, number, pending_flag, ueic, stage in rows
        ]

    equipment_at_risk = _at_risk_rows(
        _at_risk_query().order_by(RepairWorkflow.started_at.desc()).limit(20).all()
    )

    # ── 5. Recent activity (last 15 audit log entries) ────────────────────────
    activity_rows = (
        db.query(RepairStageAuditLog)
        .join(RepairWorkflow, RepairWorkflow.id == RepairStageAuditLog.workflow_id)
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .filter(_eq_filter())
        .order_by(RepairStageAuditLog.performed_at.desc())
        .limit(15)
        .all()
    )
    recent_activity = []
    for log in activity_rows:
        wf = log.workflow
        recent_activity.append({
            "workflow_id":     str(log.workflow_id) if log.workflow_id else None,
            "workflow_code":   wf.workflow_code if wf else None,
            "workflow_number": wf.workflow_number if wf else None,
            "equipment_ueic":  wf.equipment.ueic if wf and wf.equipment else None,
            "stage_name":      log.stage.name if log.stage else None,
            "action":          log.action,
            "performed_by":    _user_name(log.performer),
            "performed_at":    log.performed_at.isoformat() if log.performed_at else None,
            "note":            log.note,
        })

    # ── 6. Alerts — Overdue stages across all workflow types ─────────────────
    alerts = []
    stage_deadline: dict[str, datetime] = {}  # workflow_id -> current stage deadline
    now = datetime.now(timezone.utc)

    # Get all active workflows with stage deadlines
    overdue_workflows = (
        db.query(
            RepairWorkflow.id,
            RepairWorkflow.workflow_code,
            RepairWorkflow.workflow_number,
            Equipment.ueic,
            RepairStageDefinition.name.label("stage_name"),
            RepairStageInstance.started_at,
            RepairStageDefinition.default_duration_days,
        )
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .join(
            RepairStageInstance,
            RepairStageInstance.id == RepairWorkflow.current_stage_instance_id,
        )
        .join(
            RepairStageDefinition,
            RepairStageDefinition.id == RepairStageInstance.stage_id,
        )
        .filter(
            _eq_filter(),
            RepairWorkflow.status == "active",
            RepairStageInstance.started_at.isnot(None),
            RepairStageDefinition.default_duration_days.isnot(None),
        )
        .all()
    )

    for (
        wf_id, wf_code, wf_number, ueic, stage_name, started_at, duration_days,
    ) in overdue_workflows:
        # started_at is stored as DB-session-local time, not UTC.
        started_at = db_naive_to_aware(started_at, db)

        deadline = (started_at + timedelta(days=duration_days)).astimezone(timezone.utc)
        late_by = now - deadline
        days_overdue = late_by.days
        stage_deadline[str(wf_id)] = deadline

        # Overdue the moment the deadline passes, not a full day later.
        if late_by.total_seconds() > 0:
            hours_overdue = int(late_by.total_seconds() // 3600)
            late_label = (
                f"{days_overdue} day(s)" if days_overdue > 0 else f"{hours_overdue} hour(s)"
            )
            alerts.append({
                "type": "overdue_stage",
                "severity": "high",
                "workflow_id": str(wf_id),
                "workflow_code": wf_code,
                "workflow_number": wf_number,
                "equipment": ueic,
                "stage_name": stage_name,
                "message": f"{stage_name} overdue by {late_label}",
                "days_overdue": days_overdue,
                "hours_overdue": hours_overdue,
                "deadline": deadline.isoformat(),
            })

    # Sort alerts by days_overdue (most overdue first)
    alerts.sort(key=lambda x: x.get("hours_overdue", 0), reverse=True)

    overdue_by_code: dict[str, int] = {}
    for a in alerts:
        code = a.get("workflow_code") or ""
        overdue_by_code[code] = overdue_by_code.get(code, 0) + 1

    for wt in workflow_types:
        wt["overdue"] = overdue_by_code.get(wt["code"], 0)
    totals["overdue"] = len(alerts)

    # Overdue workflows outside the 20 most recent at-risk rows would be
    # counted on the tile but missing from the list, so append them.
    listed_ids = {e["workflow_id"] for e in equipment_at_risk}
    missing_ids = [UUID(a["workflow_id"]) for a in alerts if a["workflow_id"] not in listed_ids]
    if missing_ids:
        equipment_at_risk.extend(_at_risk_rows(
            _at_risk_query().filter(RepairWorkflow.id.in_(missing_ids)).all()
        ))

    # Deadline fields per at-risk row, so the list can badge overdue items.
    for e in equipment_at_risk:
        deadline = stage_deadline.get(e["workflow_id"])
        e["current_stage_deadline"] = deadline.isoformat() if deadline else None
        overdue = bool(deadline and now > deadline)
        e["is_overdue"] = overdue
        # Whole days left, or -N for N full days late (0 while under a day late).
        e["days_remaining"] = (
            None if not deadline
            else -(now - deadline).days if overdue
            else (deadline - now).days
        )

    # ── 7. Per-department breakdown ───────────────────────────────────────────
    # Get workflow counts grouped by equipment's department + workflow_code + status
    dept_counts_raw = (
        db.query(
            Equipment.department_id,
            RepairWorkflow.workflow_code,
            RepairWorkflow.status,
            func.count(RepairWorkflow.id).label("cnt"),
        )
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .filter(_eq_filter())
        .group_by(
            Equipment.department_id,
            RepairWorkflow.workflow_code,
            RepairWorkflow.status,
        )
        .all()
    )

    # Aggregate: { dept_id: { code: { status: count } } }
    from collections import defaultdict
    dept_agg: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    dept_total: dict = defaultdict(lambda: {"active": 0, "completed": 0, "cancelled": 0, "scheduled": 0, "pending_assignment": 0})
    dept_code_set: dict = defaultdict(set)

    for dept_id, code, status, cnt in dept_counts_raw:
        if dept_id is None:
            continue
        key = str(dept_id)
        dept_agg[key][code or ""][status or ""] += cnt
        if status == "active":
            dept_total[key]["active"] += cnt
        elif status == "completed":
            dept_total[key]["completed"] += cnt
        elif status == "cancelled":
            dept_total[key]["cancelled"] += cnt
        elif status == "scheduled":
            dept_total[key]["scheduled"] += cnt
        dept_code_set[key].add(code or "")

    # Fetch department names
    all_dept_ids_in_result = list(dept_agg.keys())
    dept_name_map = {}
    if all_dept_ids_in_result:
        depts_q = db.query(OrgDepartment.id, OrgDepartment.name).filter(
            OrgDepartment.id.in_([UUID(d) for d in all_dept_ids_in_result])
        ).all()
        dept_name_map = {str(d_id): name for d_id, name in depts_q}

    # Also pending assignment per dept
    dept_pending_raw = (
        db.query(
            Equipment.department_id,
            RepairWorkflow.workflow_code,
            func.count(RepairWorkflow.id).label("cnt"),
        )
        .join(
            Equipment,
            Equipment.id == RepairWorkflow.equipment_id,
        )
        .filter(
            _eq_filter(),
            RepairWorkflow.status == "active",
            RepairWorkflow.assignment_pending.is_(True),
        )
        .group_by(
            Equipment.department_id,
            RepairWorkflow.workflow_code,
        )
        .all()
    )

    dept_pending_by_code = defaultdict(int)

    for dept_id, code, cnt in dept_pending_raw:
        if dept_id:
            key = str(dept_id)

            dept_total[key]["pending_assignment"] += cnt

            dept_pending_by_code[(key, code or "")] += cnt

    by_department = []
    for dept_id_str, totals_d in dept_total.items():
        codes = dept_code_set[dept_id_str]
        by_type = []
        for code in sorted(codes):
            stat = dept_agg[dept_id_str][code]
            by_type.append({
                "code": code,
                "active": stat.get("active", 0),
                "completed": stat.get("completed", 0),
                "cancelled": stat.get("cancelled", 0),
                "scheduled": stat.get("scheduled", 0),
                "pending_assignment": dept_pending_by_code.get(
                    (dept_id_str, code),
                    0,
                ),
            })
        by_department.append({
            "department_id":   dept_id_str,
            "department_name": dept_name_map.get(dept_id_str, "Unknown"),
            "active":          totals_d["active"],
            "completed":       totals_d["completed"],
            "cancelled":       totals_d["cancelled"],
            "scheduled":       totals_d["scheduled"],
            "pending_assignment": totals_d["pending_assignment"],
            "by_type":         by_type,
        })
    by_department.sort(key=lambda x: -(x["active"] + x["completed"]))

    return {
        "workflow_types":    workflow_types,
        "totals":            totals,
        "stage_breakdown":   stage_breakdown,
        "equipment_at_risk": equipment_at_risk,
        "recent_activity":   recent_activity,
        "alerts":            alerts,
        "by_department":     by_department,
    }
