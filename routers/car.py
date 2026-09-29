"""
Corrective Action Request (CAR) API
=====================================
Read-only. A CAR has no manual workflow: it is created, reopened and closed
only by services/car_service.py from Test Request results, and all work on
it (maintenance, repair, retest) is assigned and approved inside each linked
TR's own workflow. This router lists CARs and shows each one's TR chain -
who is working which TR, its status, due date and latest result. The one
write is POST /{id}/void: an admin escape hatch for a CAR raised in error.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from auth_utils import get_current_user
from config import CAR_PAGE_SIZE
from database import get_db
from models import (
    CarStatus,
    CarTestRequest,
    CorrectiveActionRequest,
    Equipment,
    Module,
    OrgDepartment,
    OrgRolePermission,
    OrgUserRole,
    TestResult,
    User,
)
from services import car_service
from utils.common_service import get_dept_subtree_ids

router = APIRouter(
    prefix="/car",
    tags=["corrective-action-requests"],
    dependencies=[Depends(get_current_user)],
)


def _org_id(current_user) -> Optional[UUID]:
    return current_user.organization_id if isinstance(current_user, User) else current_user.get("organization_id")


def _user_display_name(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    return f"{user.firstname or ''} {user.lastname or ''}".strip() or user.email


def _serialize_summary(car: CorrectiveActionRequest, db: Session) -> dict:
    equipment = db.query(Equipment).filter(Equipment.id == car.equipment_id).first() if car.equipment_id else None
    link_count = db.query(CarTestRequest).filter(CarTestRequest.car_id == car.id).count()
    # for the CAR list's "group by" chips: the test that raised it, its department
    trig = car_service.trigger_request(db, car)
    dept_name = (
        db.query(OrgDepartment.name).filter(OrgDepartment.id == car.department_id).scalar()
        if car.department_id else None
    )
    return {
        "id": str(car.id),
        "car_number": car.car_number,
        "equipment_id": str(car.equipment_id) if car.equipment_id else None,
        "equipment_ueic": equipment.ueic if equipment else None,
        "template_key": car.template_key,
        "severity": car.severity,
        "status": car.status,
        "summary": car.summary,
        "due_date": car.due_date.isoformat() if car.due_date else None,
        "test_request_count": link_count,
        "created_at": car.created_at.isoformat() if car.created_at else None,
        "closed_at": car.closed_at.isoformat() if car.closed_at else None,
        "test_type_name": getattr(getattr(trig, "test_type", None), "name", None) if trig else None,
        "department_id": str(car.department_id) if car.department_id else None,
        "department_name": dept_name,
    }


@router.get(
    "/department-summary",
    summary="Department cards with CAR counts — one card per child department, "
            "for the department-drill-down dashboard (mirrors the Asset "
            "Dashboard / Comparison View card-strip UX)",
)
def department_summary(
    parent_department_id: Optional[UUID] = Query(
        None, description="Show this department's direct children. Omit for top-level departments."
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    org_id = _org_id(current_user)
    q = db.query(OrgDepartment).filter(OrgDepartment.is_active.is_(True))
    if org_id:
        q = q.filter(OrgDepartment.organization_id == org_id)
    q = q.filter(OrgDepartment.parent_department_id == parent_department_id) if parent_department_id else \
        q.filter(OrgDepartment.parent_department_id.is_(None))
    children = q.order_by(OrgDepartment.name).all()

    cards = []
    for dept in children:
        dept_ids = get_dept_subtree_ids(db, dept.id)
        has_children = (
            db.query(OrgDepartment.id)
            .filter(OrgDepartment.parent_department_id == dept.id, OrgDepartment.is_active.is_(True))
            .first()
            is not None
        )
        car_q = db.query(CorrectiveActionRequest).filter(
            CorrectiveActionRequest.department_id.in_(dept_ids),
            CorrectiveActionRequest.status != CarStatus.VOIDED,  # raised in error - not counted
        )
        total = car_q.count()
        open_count = car_q.filter(CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES)).count()
        critical_open = car_q.filter(
            CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES),
            CorrectiveActionRequest.severity == "CRITICAL",
        ).count()
        cards.append({
            "department_id": str(dept.id),
            "department_name": dept.name,
            "has_children": has_children,
            "total_count": total,
            "open_count": open_count,
            "critical_open_count": critical_open,
        })

    # Also resolve the current department's own name + parent, for breadcrumb
    current_dept = None
    if parent_department_id:
        d = db.query(OrgDepartment).filter(OrgDepartment.id == parent_department_id).first()
        if d:
            current_dept = {
                "department_id": str(d.id),
                "department_name": d.name,
                "parent_department_id": str(d.parent_department_id) if d.parent_department_id else None,
            }

    return {"current_department": current_dept, "cards": cards}


@router.get(
    "/trend",
    summary="Weekly CARs created vs. closed for a department (or org-wide) — "
            "the backlog trend shown above the CAR table on the dashboard",
)
def car_trend(
    department_id: Optional[UUID] = Query(
        None, description="Scope to this department + all its descendants. Omit for org-wide."
    ),
    weeks: int = Query(12, ge=1, le=52),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func

    org_id = _org_id(current_user)
    dept_ids = get_dept_subtree_ids(db, department_id) if department_id else None

    # Bucket by the Monday of each ISO week, oldest first — `weeks` full
    # weeks back through the current (partial) week, so a CAR opened
    # yesterday shows up in "this week" rather than being cut off.
    now = datetime.now(timezone.utc)
    week_start_of_now = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = week_start_of_now - timedelta(weeks=weeks - 1)

    def _weekly_counts(date_col):
        q = (
            db.query(
                func.date_trunc("week", date_col).label("week"),
                func.count(CorrectiveActionRequest.id),
            )
            .filter(
                CorrectiveActionRequest.organization_id == org_id,
                CorrectiveActionRequest.status != CarStatus.VOIDED,
                date_col.isnot(None),
                date_col >= range_start,
            )
        )
        if dept_ids:
            q = q.filter(CorrectiveActionRequest.department_id.in_(dept_ids))
        return {row[0].date(): row[1] for row in q.group_by("week").all()}

    created_by_week = _weekly_counts(CorrectiveActionRequest.created_at)
    closed_by_week = _weekly_counts(CorrectiveActionRequest.closed_at)

    points = []
    for i in range(weeks):
        week_start = (range_start + timedelta(weeks=i)).date()
        points.append({
            "week_start": week_start.isoformat(),
            "created_count": created_by_week.get(week_start, 0),
            "closed_count": closed_by_week.get(week_start, 0),
        })
    return {"points": points}


@router.get("", summary="List CARs (filterable by status/equipment/department), paginated")
def list_cars(
    status_filter: Optional[str] = Query(None, alias="status"),
    equipment_id: Optional[UUID] = None,
    department_id: Optional[UUID] = Query(
        None, description="Scope to this department + all its descendants (same convention as the analytics dashboards)"
    ),
    open_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=200, description=f"Defaults to CAR_PAGE_SIZE ({CAR_PAGE_SIZE})"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(CorrectiveActionRequest)
    org_id = _org_id(current_user)
    if org_id:
        q = q.filter(CorrectiveActionRequest.organization_id == org_id)
    if department_id:
        dept_ids = get_dept_subtree_ids(db, department_id)
        q = q.filter(CorrectiveActionRequest.department_id.in_(dept_ids))
    if status_filter:
        q = q.filter(CorrectiveActionRequest.status == status_filter)
    elif open_only:
        q = q.filter(CorrectiveActionRequest.status.in_(CarStatus.OPEN_STATUSES))
    else:
        q = q.filter(CorrectiveActionRequest.status != CarStatus.VOIDED)  # only via status=VOIDED
    if equipment_id:
        q = q.filter(CorrectiveActionRequest.equipment_id == equipment_id)

    ps = page_size or CAR_PAGE_SIZE
    skip = (page - 1) * ps

    total = q.count()
    cars = q.order_by(CorrectiveActionRequest.created_at.desc()).offset(skip).limit(ps).all()
    serialized = []
    for c in cars:
        row = _serialize_summary(c, db)
        # badge on the CAR list (ATTENTION / IDLE) - open CARs only, a page at a time
        row["drive_state"] = _drive_state(db, c)["drive_state"] if c.status in CarStatus.OPEN_STATUSES else None
        serialized.append(row)

    return {
        "items": serialized,
        "total": total,
        "page": page,
        "page_size": ps,
        "has_more": (skip + len(serialized)) < total,
    }


def _serialize_link(link: CarTestRequest, db: Session, expecting: set) -> dict:
    """One TR in the CAR's chain, with what its own workflow says: who is
    on it, where it is, when it's due, and what its latest result was.
    is_active = still EXPECTING a result (car_service.expecting_result_ids,
    the same rule the backend decides retests by); awaiting_review = not
    closed but its result is already in (only approval left)."""
    tr = link.test_request
    latest = (
        db.query(TestResult)
        .filter(TestResult.testing_request_id == link.test_request_id)
        .order_by(TestResult.tested_at.desc().nullslast(), TestResult.cts.desc().nullslast())
        .first()
    ) if tr else None
    ev = latest.evaluation_result if latest and isinstance(latest.evaluation_result, dict) else {}
    tester = db.query(User).filter(User.id == tr.assigned_tester_id).first() if tr and tr.assigned_tester_id else None
    status = tr.status if tr else None
    return {
        "test_request_id": str(link.test_request_id),
        "request_number": tr.request_number if tr else None,
        "title": tr.title if tr else None,
        "relationship_type": link.relationship_type,
        "request_category": tr.request_category.value if tr and tr.request_category else None,
        "test_request_type": tr.test_request_type if tr else None,
        "test_type_name": tr.test_type.name if tr and tr.test_type else None,
        "status": status.value if status else None,
        "is_active": tr is not None and tr.id in expecting,
        "awaiting_review": (
            tr is not None and bool(status)
            and status not in car_service._TERMINAL_TR_STATUSES and tr.id not in expecting
        ),
        "assigned_tester_name": _user_display_name(tester),
        "due_date": tr.due_date.date().isoformat() if tr and tr.due_date else None,
        "result": ev.get("overall"),
        "result_remarks": latest.remarks if latest else None,
        "tested_at": latest.tested_at.isoformat() if latest and latest.tested_at else None,
        "linked_at": link.created_at.isoformat() if link.created_at else None,
    }


def _drive_state(db: Session, car: CorrectiveActionRequest) -> dict:
    """car_service.car_drive_state() - the same answer the daily idle check
    acts on - in API form. drive_state: in_progress | attention | idle |
    replacement_pending | replacement_finance | finishing | resolved |
    replacement (None for CLOSED / VOIDED;
    no_trigger shown as idle)."""
    st = car_service.car_drive_state(db, car)
    trig, stopped, repl = st["trigger"], st["stopped"], st["replacement"]
    state = st["state"]
    return {
        "drive_state": "idle" if state == "no_trigger" else state,
        "replacement_request_number": repl.request_number if repl else None,
        # the request that raised this CAR was itself cancelled / rejected
        "trigger_withdrawn": bool(st.get("trigger_withdrawn")),
        # failed test types still needing a passing retest before the CAR closes
        "pending_test_types": [
            getattr(getattr(u["failing"], "test_type", None), "name", None) or f"test_type_id={u['test_type_id']}"
            for u in st["pending_types"]
        ],
        # the same, per type: its retest in flight, or stopped by a person
        "pending_types_detail": [
            {
                "test_type_name": getattr(getattr(u["failing"], "test_type", None), "name", None)
                or f"test_type_id={u['test_type_id']}",
                "in_flight_request_number": u.get("in_flight"),
                "stopped_request_number": u["stopped"].request_number if u.get("stopped") else None,
                "stopped_status": u["stopped"].status.value if u.get("stopped") and u["stopped"].status else None,
            }
            for u in st["pending_types"]
        ],
        # corrective work retests are waiting for (request number / "repair workflow")
        "corrective_work": st.get("corrective_work"),
        # linked requests still open - a CAR closes only when all are finished
        "open_request_numbers": [t.request_number for t in st.get("open_requests") or []],
        # approved replacement's procurement request (replacement_finance / finishing)
        "replacement_pr_number": st.get("replacement_pr"),
        "attention_request_number": stopped.request_number if stopped else None,
        "attention_request_status": stopped.status.value if stopped and stopped.status else None,
        # the test type whose NORMAL retest closes the CAR (the failure that raised it)
        "verifying_test_type_name": getattr(getattr(trig, "test_type", None), "name", None) if trig else None,
    }


@router.get("/{car_id}", summary="CAR detail with its full Test Request lineage")
def get_car(car_id: UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    car = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == car_id).first()
    org_id = _org_id(current_user) if current_user is not None else None
    if not car or (org_id and car.organization_id and car.organization_id != org_id):
        raise HTTPException(status_code=404, detail="CAR not found")  # other orgs' CARs don't exist for you

    links = (
        db.query(CarTestRequest)
        .options(joinedload(CarTestRequest.test_request))
        .filter(CarTestRequest.car_id == car_id)
        .order_by(CarTestRequest.created_at.asc())
        .all()
    )

    expecting = car_service.expecting_result_ids(db, [link.test_request_id for link in links])
    data = _serialize_summary(car, db)
    data["test_requests"] = [_serialize_link(link, db, expecting) for link in links]
    data["active_test_request_count"] = sum(1 for t in data["test_requests"] if t["is_active"])
    data.update(_drive_state(db, car))
    # the findings behind the summary, as tables (one per evaluated table)
    source = db.query(TestResult).filter(TestResult.id == car.source_test_result_id).first()         if car.source_test_result_id else None
    data["summary_tables"] = car_service.summary_tables(source.evaluation_result if source else None)
    source_tr = source.testing_request if source is not None else None
    data["summary_test_name"] = (
        getattr(getattr(source_tr, "test_type", None), "name", None) or getattr(source_tr, "title", None)
    ) if source_tr is not None else None
    # How it was closed: a passing retest, or an approved equipment replacement
    # (close_cars_for_replacement keeps the reason as "REPLACEMENT: ...")
    if car.status == CarStatus.CLOSED:
        note = car.corrective_action or ""
        data["close_reason"] = "replacement" if note.startswith("REPLACEMENT: ") else "verified"
        data["close_note"] = note.removeprefix("REPLACEMENT: ") if note.startswith("REPLACEMENT: ") else None
    if car.status == CarStatus.VOIDED:
        data["void_reason"] = (car.corrective_action or "").removeprefix("VOIDED: ")
        data["voided_by_name"] = _user_display_name(
            db.query(User).filter(User.id == car.modified_by).first() if car.modified_by else None
        )
        data["voided_at"] = car.modified_at.isoformat() if car.modified_at else None
    return data


# Module row seeded by seed_car_module.py; Void needs can_delete on it.
CAR_MODULE_PATH = "corrective-action-requests"


def _has_car_permission(db: Session, current_user, action: str) -> bool:
    """Mirrors the frontend AuthProvider.can('Corrective Action Requests',
    action): super_admin always; otherwise an active role holding `action`
    on the CAR module."""
    if isinstance(current_user, User):
        user_id, usertype = current_user.id, current_user.usertype
    else:
        user_id, usertype = current_user.get("id"), current_user.get("usertype")
    if usertype == "super_admin":
        return True
    module_id = db.query(Module.id).filter(Module.path == CAR_MODULE_PATH).scalar()
    if module_id is None or not user_id:
        return False
    return (
        db.query(OrgUserRole.id)
        .join(OrgRolePermission, OrgRolePermission.org_role_id == OrgUserRole.org_role_id)
        .filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active.is_(True),
            OrgRolePermission.module_id == module_id,
            getattr(OrgRolePermission, action).is_(True),
        )
        .first()
        is not None
    )


class CarVoidRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=1000)


@router.post("/{car_id}/void", summary="Void a CAR raised in error (admin, reason required)")
def void_car(
    car_id: UUID,
    body: CarVoidRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    car = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == car_id).first()
    org_id = _org_id(current_user)
    if not car or (org_id and car.organization_id and car.organization_id != org_id):
        raise HTTPException(status_code=404, detail="CAR not found")
    if not _has_car_permission(db, current_user, "can_delete"):
        raise HTTPException(status_code=403, detail="Your role does not have permission to void CARs")
    if car.status not in CarStatus.OPEN_STATUSES:
        raise HTTPException(status_code=400, detail=f"Only an open CAR can be voided (this one is {car.status})")
    user_id = current_user.id if isinstance(current_user, User) else current_user.get("id")
    car_service.void_car(db, car, reason=body.reason, voided_by=user_id)
    return get_car(car_id, db=db, current_user=current_user)


# Note: there is deliberately no standalone "replace" endpoint here. That
# recommendation is made through the normal Recommendation Wizard on a linked
# TR (picking "Procurement" = next_action replacement). While it awaits
# approval the CAR shows drive_state "replacement_pending" and gets no
# retests; once approved, workflow_dispatch_service.py's replacement branch
# calls car_service.close_cars_for_replacement(), which CLOSES every open CAR
# on that equipment.
