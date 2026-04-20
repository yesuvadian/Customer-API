"""
Admin notification management endpoints.

Notification Templates
  GET    /admin/notifications/templates             → list templates
  POST   /admin/notifications/templates             → create template
  PUT    /admin/notifications/templates/{id}        → update template
  DELETE /admin/notifications/templates/{id}        → deactivate template

Notification Log
  GET    /admin/notifications/logs                  → paginated log view

Seed & Test
  POST   /admin/notifications/seed-defaults         → seed global default templates
  POST   /admin/notifications/test-fire             → manual trigger for any event_type
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import NotificationLog, NotificationTemplate, User

router = APIRouter(
    prefix="/admin/notifications",
    tags=["admin-notifications"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class TemplateCreate(BaseModel):
    event_type: str
    channel: str                       # "email" | "sms" | "inapp"
    subject_template: Optional[str] = None
    body_template: str
    recipient_roles: List[str] = []
    organization_id: Optional[UUID] = None
    is_active: bool = True


class TemplateUpdate(BaseModel):
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    recipient_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None


class TemplateOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID]
    event_type: str
    channel: str
    subject_template: Optional[str]
    body_template: str
    recipient_roles: list
    is_active: bool
    cts: object

    class Config:
        from_attributes = True


class LogOut(BaseModel):
    id: UUID
    event_type: str
    channel: str
    recipient_email: Optional[str]
    status: str
    retry_count: int
    error_message: Optional[str]
    sent_at: Optional[object]
    source_type: Optional[str]
    source_id: Optional[UUID]
    cts: object

    class Config:
        from_attributes = True


class TestFireBody(BaseModel):
    event_type: str
    context: dict = {}
    organization_id: Optional[UUID] = None


# ── Template CRUD ─────────────────────────────────────────────────────────────

@router.get("/templates", response_model=List[TemplateOut])
def list_templates(
    event_type: Optional[str] = None,
    channel: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(NotificationTemplate)
    if event_type:
        q = q.filter(NotificationTemplate.event_type == event_type)
    if channel:
        q = q.filter(NotificationTemplate.channel == channel)
    return q.order_by(NotificationTemplate.event_type, NotificationTemplate.channel).all()


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tmpl = NotificationTemplate(**body.model_dump())
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return tmpl


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tmpl = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    for key, val in body.model_dump(exclude_none=True).items():
        setattr(tmpl, key, val)
    db.commit()
    db.refresh(tmpl)
    return tmpl


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tmpl = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    tmpl.is_active = False
    db.commit()


# ── Notification Log ──────────────────────────────────────────────────────────

@router.get("/logs", response_model=List[LogOut])
def list_logs(
    event_type: Optional[str] = None,
    channel: Optional[str] = None,
    log_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(NotificationLog)
    if event_type:
        q = q.filter(NotificationLog.event_type == event_type)
    if channel:
        q = q.filter(NotificationLog.channel == channel)
    if log_status:
        q = q.filter(NotificationLog.status == log_status)
    return q.order_by(NotificationLog.cts.desc()).offset(skip).limit(limit).all()


# ── Seed & Test ───────────────────────────────────────────────────────────────

@router.post("/seed-defaults")
def seed_defaults(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Insert global default notification templates (idempotent)."""
    from services.notification_service import seed_default_templates
    inserted = seed_default_templates(db)
    return {"inserted": inserted, "message": f"Seeded {inserted} new default templates."}


@router.post("/test-fire")
def test_fire(
    body: TestFireBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger any notification event for testing.
    Useful for verifying templates and recipient resolution without
    waiting for a real event.
    """
    from services.notification_service import NotificationService
    svc = NotificationService(db)
    svc.fire(
        event_type=body.event_type,
        context=body.context,
        organization_id=body.organization_id,
        extra_recipients=[current_user],  # always send to caller so they can verify
    )
    return {"status": "fired", "event_type": body.event_type}
