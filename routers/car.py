"""
Corrective Action Request (CAR) API
=====================================
CARs are never created through this router — creation is implicit, driven
by services/car_service.process_evaluation_for_car() when a test result
evaluates CRITICAL (see services/testing_service.py). This router only
exposes read/list and the status-transition actions a user takes once a
CAR already exists.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from auth_utils import get_current_user
from config import CAR_PAGE_SIZE
from database import get_db
from models import (
    CarStatus,
    CarTestRequest,
    CorrectiveActionRequest,
    Equipment,
    OrgDepartment,
    TestingRequest,
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


def _serialize_summary(car: CorrectiveActionRequest, db: Session) -> dict:
    equipment = db.query(Equipment).filter(Equipment.id == car.equipment_id).first() if car.equipment_id else None
    link_count = db.query(CarTestRequest).filter(CarTestRequest.car_id == car.id).count()
    return {
        "id": str(car.id),
        "car_number": car.car_number,
        "equipment_id": str(car.equipment_id) if car.equipment_id else None,
        "equipment_ueic": equipment.ueic if equipment else None,
        "template_key": car.template_key,
        "severity": car.severity,
        "status": car.status,
        "summary": car.summary,
        "assigned_to": str(car.assigned_to) if car.assigned_to else None,
        "due_date": car.due_date.isoformat() if car.due_date else None,
        "test_request_count": link_count,
        "created_at": car.created_at.isoformat() if car.created_at else None,
        "closed_at": car.closed_at.isoformat() if car.closed_at else None,
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
        car_q = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.department_id.in_(dept_ids))
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
    if equipment_id:
        q = q.filter(CorrectiveActionRequest.equipment_id == equipment_id)

    ps = page_size or CAR_PAGE_SIZE
    skip = (page - 1) * ps

    total = q.count()
    cars = q.order_by(CorrectiveActionRequest.created_at.desc()).offset(skip).limit(ps).all()
    serialized = [_serialize_summary(c, db) for c in cars]

    return {
        "items": serialized,
        "total": total,
        "page": page,
        "page_size": ps,
        "has_more": (skip + len(serialized)) < total,
    }


@router.get("/{car_id}", summary="CAR detail with its full Test Request lineage")
def get_car(car_id: UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    car = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="CAR not found")

    links = (
        db.query(CarTestRequest)
        .options(joinedload(CarTestRequest.test_request))
        .filter(CarTestRequest.car_id == car_id)
        .order_by(CarTestRequest.created_at.asc())
        .all()
    )

    data = _serialize_summary(car, db)
    data["corrective_action"] = car.corrective_action
    data["test_requests"] = [
        {
            "test_request_id": str(link.test_request_id),
            "request_number": link.test_request.request_number if link.test_request else None,
            "relationship_type": link.relationship_type,
            "status": link.test_request.status.value if link.test_request and link.test_request.status else None,
            "linked_at": link.created_at.isoformat() if link.created_at else None,
        }
        for link in links
    ]
    return data


class CarAssignRequest(BaseModel):
    assigned_to: UUID
    due_date: Optional[date] = None


@router.post("/{car_id}/assign", summary="Assign the CAR to a user")
def assign_car(car_id: UUID, body: CarAssignRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    car = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="CAR not found")
    car_service.assign_car(db, car, body.assigned_to)
    if body.due_date:
        car.due_date = body.due_date
        # A new deadline gets its own fresh overdue check — clear the marker
        # so car_overdue can fire again if this new date also passes.
        car.overdue_notified_at = None
        db.commit()
        db.refresh(car)
    return _serialize_summary(car, db)


@router.post("/{car_id}/start", summary="Mark the CAR as in progress")
def start_car(car_id: UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    car = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="CAR not found")
    car_service.start_progress(db, car)
    return _serialize_summary(car, db)


class CarSubmitVerificationRequest(BaseModel):
    corrective_action: str


@router.post("/{car_id}/submit-verification", summary="Submit corrective action text, awaiting retest verification")
def submit_verification(
    car_id: UUID,
    body: CarSubmitVerificationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    car = db.query(CorrectiveActionRequest).filter(CorrectiveActionRequest.id == car_id).first()
    if not car:
        raise HTTPException(status_code=404, detail="CAR not found")
    car_service.submit_for_verification(db, car, body.corrective_action)
    return _serialize_summary(car, db)

# Note: there is deliberately no standalone "recommend replacement" endpoint
# here. That recommendation is made through the normal Recommendation Wizard
# on the CAR's linked TR (picking "Procurement", which is next_action=
# replacement under the hood) - once approved, workflow_dispatch_service.py's
# NextActionType.replacement branch calls car_service.recommend_replacement()
# automatically for any CAR in that TR's lineage. See
# _recommend_replacement_for_linked_car() there.
