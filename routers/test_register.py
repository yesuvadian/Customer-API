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

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from services.test_register_service import TestRegisterService

router = APIRouter(
    prefix="/test-register",
    tags=["test-register"],
    dependencies=[Depends(get_current_user)],
)


# ── Request schemas ────────────────────────────────────────────────────────────

class TemplateCreateBody(BaseModel):
    title: str
    equipment_type_id: int
    organization_id: UUID
    frequency: str                       # ScheduleFrequency value

    description: Optional[str] = None
    department_id: Optional[UUID] = None
    template_key: Optional[str] = None
    priority: str = "normal"
    notes: Optional[str] = None
    advance_days: int = 15

    responsible_role_id: Optional[UUID] = None
    reviewing_role_id: Optional[UUID] = None
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
    responsible_role_id: Optional[UUID] = None
    reviewing_role_id: Optional[UUID] = None
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
    return svc.create_template(body.model_dump(), current_user)


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
    status_code=status.HTTP_201_CREATED,
    summary="Commission equipment — clone templates to live requests",
)
def commission_equipment(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger commissioning for an equipment unit.
    Finds all active register templates matching equipment.equipment_type_id
    and creates a live TestingRequest + TestRequestSchedule for each.

    This is also called automatically from the equipment creation endpoint.
    """
    svc = TestRegisterService(db)
    return svc.commission_equipment(equipment_id, current_user)


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
