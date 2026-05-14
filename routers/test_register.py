"""
test_register.py
────────────────
REST API for the Test Register module.

Endpoints
─────────
  GET    /test-register/                             list templates
  POST   /test-register/                             create template
  GET    /test-register/{template_id}                get template
  PUT    /test-register/{template_id}                update template
  DELETE /test-register/{template_id}                deactivate template

  POST   /test-register/commission/{equipment_id}    commission equipment
         (clones all matching templates into live TestingRequests)

  POST   /test-register/alert-reschedule/{schedule_id}
         (update next_run_date after ALERT evaluation)

  GET    /test-register/equipment/{equipment_id}/schedules
         (live schedule view for one equipment unit)

Access
──────
  All endpoints require authentication.
  Create / Update / Deactivate require EE TLSS, Department Head, or Admin role.
  Read endpoints are open to any authenticated org user.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import CategoryDetails, CategoryMaster, User
from services.test_register_service import TestRegisterService

router = APIRouter(
    prefix="/test-register",
    tags=["test-register"],
    dependencies=[Depends(get_current_user)],
)


# ── Request schemas ────────────────────────────────────────────────────────────

class TemplateCreateBody(BaseModel):
    equipment_type_id: int
    organization_id: Optional[UUID] = None   # falls back to current_user.organization_id
    frequency: str                       # ScheduleFrequency value

    title: Optional[str] = None          # auto-generated from test_type if omitted
    test_type_id: Optional[int] = None   # CategoryDetails PK
    description: Optional[str] = None
    department_id: Optional[UUID] = None
    template_key: Optional[str] = None
    priority: str = "normal"
    notes: Optional[str] = None
    advance_days: int = 15

    revised_periodicity_days: Optional[int] = None
    oem_reference: Optional[str] = None


class TemplateUpdateBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    equipment_type_id: Optional[int] = None
    department_id: Optional[UUID] = None

    frequency: Optional[str] = None
    advance_days: Optional[int] = None
    revised_periodicity_days: Optional[int] = None
    oem_reference: Optional[str] = None
    is_active: Optional[bool] = None


# ── List templates ─────────────────────────────────────────────────────────────

@router.get("/", summary="List test register templates")
def list_templates(
    organization_id: Optional[UUID] = Query(None),
    equipment_type_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all test register templates, optionally filtered by org and/or equipment type.
    """
    svc = TestRegisterService(db)
    return svc.list_templates(
        organization_id=organization_id,
        equipment_type_id=equipment_type_id,
        skip=skip,
        limit=limit,
    )


# ── Test types lookup ──────────────────────────────────────────────────────────

@router.get("/test-types", summary="List test types grouped by equipment type")
def list_test_types(db: Session = Depends(get_db)):
    rows = (
        db.query(CategoryDetails, CategoryMaster)
        .join(CategoryMaster, CategoryMaster.id == CategoryDetails.category_master_id)
        .filter(
            CategoryDetails.category_type == "test",
            CategoryDetails.is_active.is_(True),
            CategoryMaster.is_active.is_(True),
        )
        .order_by(CategoryMaster.name, CategoryDetails.name)
        .all()
    )
    return [
        {
            "id": detail.id,
            "name": detail.name,
            "equipment_type_id": detail.category_master_id,
            "equipment_type_name": master.name,
        }
        for detail, master in rows
    ]


@router.get("/maintenance-types", summary="List maintenance types grouped by equipment type")
def list_maintenance_types(db: Session = Depends(get_db)):
    rows = (
        db.query(CategoryDetails, CategoryMaster)
        .join(CategoryMaster, CategoryMaster.id == CategoryDetails.category_master_id)
        .filter(
            CategoryDetails.category_type == "maintenance",
            CategoryDetails.is_active.is_(True),
            CategoryMaster.is_active.is_(True),
        )
        .order_by(CategoryMaster.name, CategoryDetails.name)
        .all()
    )
    return [
        {
            "id": detail.id,
            "name": detail.name,
            "equipment_type_id": detail.category_master_id,
            "equipment_type_name": master.name,
        }
        for detail, master in rows
    ]


# ── Create template ────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a test register template")
def create_template(
    body: TemplateCreateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new register template entry.
    Generates a TestingRequest (is_schedule_template=True) + linked TestRequestSchedule.
    Role required: EE TLSS, Department Head, Admin, or SuperAdmin.
    """
    svc = TestRegisterService(db)
    data = body.model_dump()
    if not data.get('organization_id'):
        data['organization_id'] = current_user.organization_id
    return svc.create_template(data, current_user)


# ── Get single template ────────────────────────────────────────────────────────

@router.get("/{template_id}", summary="Get a single test register template")
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TestRegisterService(db)
    return svc.get_template(template_id)


# ── Update template ────────────────────────────────────────────────────────────

@router.put("/{template_id}", summary="Update a test register template")
def update_template(
    template_id: UUID,
    body: TemplateUpdateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Partial update of a register template and/or its schedule config.
    Role required: EE TLSS, Department Head, Admin, or SuperAdmin.
    """
    svc = TestRegisterService(db)
    return svc.update_template(
        template_id,
        body.model_dump(exclude_none=True),
        current_user,
    )


# ── Deactivate template ────────────────────────────────────────────────────────

@router.delete("/{template_id}", summary="Deactivate a test register template")
def deactivate_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft-delete: sets the template's schedule is_active=False.
    The TestingRequest row is retained for audit.
    Role required: EE TLSS, Department Head, Admin, or SuperAdmin.
    """
    svc = TestRegisterService(db)
    return svc.deactivate_template(template_id, current_user)


# ── Commission equipment ───────────────────────────────────────────────────────

@router.post(
    "/commission/{equipment_id}",
    summary="Commission equipment — instantiate operational schedules for one unit",
)
def commission_equipment(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services.test_request_schedule_service import TestRequestScheduleService
    from models import Equipment
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found.")
    TestRequestScheduleService.instantiate_equipment_schedules(db, equipment, current_user.id)
    return {"message": "Operational schedules instantiated.", "equipment_id": str(equipment_id)}


@router.post(
    "/run-scheduler",
    summary="Run the daily scheduler — generate due tickets for all equipment",
)
def run_scheduler(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services.test_request_schedule_service import TestRequestScheduleService
    return TestRequestScheduleService.run_daily_scheduler(db)


# ── ALERT reschedule ───────────────────────────────────────────────────────────

@router.post(
    "/alert-reschedule/{schedule_id}",
    summary="Update schedule after ALERT evaluation result",
)
def alert_reschedule(
    schedule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    After EvaluationService returns ALERT, call this to advance next_run_date
    using revised_periodicity_days (if set) or normal frequency otherwise.
    """
    svc = TestRegisterService(db)
    return svc.apply_alert_reschedule(schedule_id)


# ── Equipment schedule view ────────────────────────────────────────────────────

@router.get(
    "/equipment/{equipment_id}/schedules",
    summary="List all live test schedules for one equipment unit",
)
def equipment_schedules(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns all active TestRequestSchedule rows linked to live (non-template)
    TestingRequests for the given equipment. Ordered by next_run_date ascending.
    """
    svc = TestRegisterService(db)
    return svc.list_equipment_schedules(equipment_id)
