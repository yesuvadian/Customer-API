"""
Notification endpoints — two surfaces:

  A) User-facing in-app notifications
     GET  /notifications              → list in-app notifications (paginated)
     GET  /notifications/unread-count → unread badge count
     PUT  /notifications/{id}/read   → mark one as read
     PUT  /notifications/read-all    → mark all as read

  B) Admin — Notification Template Configuration
     GET  /notifications/templates                → list all templates for the org
     GET  /notifications/templates/event-types   → catalogue of supported event types
     POST /notifications/templates               → create a new template
     PUT  /notifications/templates/{id}          → update template
     DELETE /notifications/templates/{id}        → deactivate / delete template
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import NotificationTemplate, NotificationVariable, OrgRole, OrgUserRole, User, UserNotification

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(get_current_user)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class UserNotificationOut(BaseModel):
    id: UUID
    event_type: str
    title: str
    body: str
    severity: Optional[str] = None       # "critical" | "alert" | "info"
    source_id: Optional[UUID] = None
    source_type: Optional[str] = None
    ueic: Optional[str] = None           # Equipment UEIC for quick display
    is_read: bool
    read_at: Optional[object] = None
    cts: object

    class Config:
        from_attributes = True


class UnreadCountOut(BaseModel):
    count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[UserNotificationOut])
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    severity: Optional[str] = Query(None),   # "critical" | "alert" | "info"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's in-app notifications, newest first.
    Filter by severity (critical/alert/info) or unread_only."""
    q = (
        db.query(UserNotification)
        .filter(UserNotification.user_id == current_user.id)
    )
    if unread_only:
        q = q.filter(UserNotification.is_read.is_(False))
    if severity:
        q = q.filter(UserNotification.severity == severity.lower())
    return q.order_by(UserNotification.cts.desc()).offset(skip).limit(limit).all()


@router.get("/counts", response_model=dict)
def severity_counts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return unread count broken down by severity for the Alerts badge."""
    from sqlalchemy import func as sqlfunc
    rows = (
        db.query(UserNotification.severity, sqlfunc.count(UserNotification.id))
        .filter(
            UserNotification.user_id == current_user.id,
            UserNotification.is_read.is_(False),
        )
        .group_by(UserNotification.severity)
        .all()
    )
    counts = {"critical": 0, "alert": 0, "info": 0, "total": 0}
    for sev, cnt in rows:
        key = (sev or "info").lower()
        if key in counts:
            counts[key] += cnt
        counts["total"] += cnt
    return counts


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return number of unread in-app notifications for the bell badge."""
    count = (
        db.query(UserNotification)
        .filter(
            UserNotification.user_id == current_user.id,
            UserNotification.is_read.is_(False),
        )
        .count()
    )
    return {"count": count}


@router.put("/{notification_id}/read", response_model=UserNotificationOut)
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    from datetime import datetime, timezone
    from fastapi import HTTPException, status

    notif = (
        db.query(UserNotification)
        .filter(
            UserNotification.id == notification_id,
            UserNotification.user_id == current_user.id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    notif.is_read = True
    notif.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(notif)
    return notif


@router.put("/read-all", response_model=UnreadCountOut)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    from sqlalchemy import update

    now = datetime.now(timezone.utc)
    db.query(UserNotification).filter(
        UserNotification.user_id == current_user.id,
        UserNotification.is_read.is_(False),
    ).update({"is_read": True, "read_at": now})
    db.commit()
    return {"count": 0}


# ══════════════════════════════════════════════════════════════════════════════
# B)  ADMIN — Notification Template Configuration
# ══════════════════════════════════════════════════════════════════════════════

# ── System variable registry ──────────────────────────────────────────────────
# Variables the user can embed in subject/body templates using {{var}} syntax.
# Grouped by category for the UI variable picker.
SYSTEM_VARIABLES: List[Dict[str, Any]] = [
    # Report attachment links
    {"var": "{{report.retriexls}}",  "label": "Report — Excel Download URL",  "group": "Reports"},
    {"var": "{{report.retriepdf}}",  "label": "Report — PDF Download URL",    "group": "Reports"},
    {"var": "{{report.ref}}",        "label": "Report Reference Number",      "group": "Reports"},
    {"var": "{{report.generated_on}}","label": "Report Generated Date/Time",  "group": "Reports"},
    # Equipment
    {"var": "{{equipment.ueic}}",       "label": "Equipment UEIC",             "group": "Equipment"},
    {"var": "{{equipment.type}}",       "label": "Equipment Type",             "group": "Equipment"},
    {"var": "{{equipment.department}}", "label": "Substation / Department",    "group": "Equipment"},
    {"var": "{{equipment.status}}",     "label": "Equipment Status",           "group": "Equipment"},
    {"var": "{{equipment.manufacturer}}","label": "Manufacturer",              "group": "Equipment"},
    # Replacement event
    {"var": "{{old_ueic}}",         "label": "Retired UEIC",                  "group": "Replacement"},
    {"var": "{{new_ueic}}",         "label": "New Replacement UEIC",          "group": "Replacement"},
    {"var": "{{replaced_by}}",      "label": "Replaced By (User)",            "group": "Replacement"},
    {"var": "{{replaced_on}}",      "label": "Replacement Date",              "group": "Replacement"},
    {"var": "{{reason}}",           "label": "Replacement Reason",            "group": "Replacement"},
    # Test request workflow
    {"var": "{{request.number}}",   "label": "Test Request Number",           "group": "Test Request"},
    {"var": "{{request.title}}",    "label": "Test Request Title",            "group": "Test Request"},
    {"var": "{{request.status}}",   "label": "Request Status",               "group": "Test Request"},
    {"var": "{{request.priority}}", "label": "Priority",                      "group": "Test Request"},
    {"var": "{{request.due_date}}", "label": "Due Date",                      "group": "Test Request"},
    {"var": "{{request.submitted_by}}","label": "Submitted By",              "group": "Test Request"},
    {"var": "{{request.assigned_to}}","label": "Assigned To (Tester)",       "group": "Test Request"},
    # Evaluation / test result
    {"var": "{{eval.overall}}",     "label": "Overall Result (NORMAL/ALERT/CRITICAL)", "group": "Evaluation"},
    {"var": "{{eval.test_type}}",   "label": "Test Type",                     "group": "Evaluation"},
    {"var": "{{eval.evaluated_at}}","label": "Evaluation Date/Time",          "group": "Evaluation"},
    # Organisation / system
    {"var": "{{org.name}}",         "label": "Organisation Name",             "group": "Organisation"},
    {"var": "{{org.id}}",           "label": "Organisation ID",               "group": "Organisation"},
    {"var": "{{system.date}}",      "label": "Today's Date",                  "group": "System"},
    {"var": "{{system.time}}",      "label": "Current Time",                  "group": "System"},
    {"var": "{{system.app_name}}",  "label": "Application Name (SEACMS)",     "group": "System"},
]


# ── Known event types catalogue ───────────────────────────────────────────────
_EVENT_CATALOGUE: List[Dict[str, Any]] = [
    # ── Equipment lifecycle ───────────────────────────────────────────────────
    {
        "event_type": "equipment_replacement",
        "label": "Equipment Replacement",
        "group": "Equipment",
        "description": "Fired when equipment is retired and a replacement unit is commissioned.",
        "context_vars": ["old_ueic", "new_ueic", "equipment_type", "department",
                         "reason_type", "reason", "replaced_by", "replaced_on"],
        "default_roles": ["EE TLSS", "SEE W&M", "CEE Transmission Zone"],
    },
    # ── Test result evaluation ────────────────────────────────────────────────
    {
        "event_type": "eval_critical",
        "label": "Critical Test Result",
        "group": "Evaluation",
        "description": "Fired when a test evaluation result is CRITICAL (per test template thresholds).",
        "context_vars": ["equipment", "ueic", "test_type", "result", "dept",
                         "eval.overall", "eval.evaluated_at", "report.retriepdf"],
        "default_roles": ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "AEE Maintenance"],
    },
    {
        "event_type": "eval_alert",
        "label": "Alert Test Result",
        "group": "Evaluation",
        "description": "Fired when a test evaluation result is ALERT (per test template thresholds).",
        "context_vars": ["equipment", "ueic", "test_type", "result", "dept",
                         "eval.overall", "eval.evaluated_at", "report.retriepdf"],
        "default_roles": ["EE TLSS", "AEE Maintenance"],
    },
    # ── Test request workflow status changes ──────────────────────────────────
    {
        "event_type": "request_submitted",
        "label": "Test Request Submitted",
        "group": "Test Workflow",
        "description": "Fired when an originator submits a new test request.",
        "context_vars": ["request.number", "request.title", "request.priority",
                         "request.submitted_by", "equipment.ueic", "equipment.department"],
        "default_roles": ["EE TLSS", "Department Head"],
    },
    {
        "event_type": "request_assigned",
        "label": "Test Request Assigned to Tester",
        "group": "Test Workflow",
        "description": "Fired when a test request is assigned to a field/lab tester.",
        "context_vars": ["request.number", "request.title", "request.assigned_to",
                         "request.due_date", "equipment.ueic"],
        "default_roles": ["Field Tester", "Lab Tester"],
    },
    {
        "event_type": "test_submitted",
        "label": "Test Results Submitted",
        "group": "Test Workflow",
        "description": "Fired when a tester submits test results for review.",
        "context_vars": ["request.number", "request.title", "request.submitted_by",
                         "equipment.ueic", "eval.overall", "report.retriepdf"],
        "default_roles": ["EE TLSS", "Department Head"],
    },
    {
        "event_type": "request_approved",
        "label": "Test Request Approved",
        "group": "Test Workflow",
        "description": "Fired when a test request/result is approved by the reviewer.",
        "context_vars": ["request.number", "request.title", "request.submitted_by",
                         "equipment.ueic", "report.retriepdf", "report.retriexls"],
        "default_roles": ["Originator", "AEE Maintenance"],
    },
    {
        "event_type": "request_rejected",
        "label": "Test Request Rejected / Returned",
        "group": "Test Workflow",
        "description": "Fired when a test request is rejected or returned for rework.",
        "context_vars": ["request.number", "request.title", "request.submitted_by",
                         "equipment.ueic", "reason"],
        "default_roles": ["Originator", "Field Tester", "Lab Tester"],
    },
    # ── Scheduling ────────────────────────────────────────────────────────────
    {
        "event_type": "due_reminder",
        "label": "Test Due Soon Reminder",
        "group": "Scheduling",
        "description": "Fired N days before a scheduled test is due.",
        "context_vars": ["equipment.ueic", "request.title", "request.due_date", "equipment.department"],
        "default_roles": ["AEE Maintenance", "EE TLSS"],
    },
    {
        "event_type": "test_overdue",
        "label": "Test Overdue",
        "group": "Scheduling",
        "description": "Fired when a scheduled test passes its due date without completion.",
        "context_vars": ["equipment.ueic", "request.title", "request.due_date", "equipment.department"],
        "default_roles": ["EE TLSS", "AEE Maintenance"],
    },
    # ── Recommendations ───────────────────────────────────────────────────────
    {
        "event_type": "recommendation_approved",
        "label": "Recommendation Approved",
        "group": "Recommendations",
        "description": "Fired when an equipment recommendation is approved.",
        "context_vars": ["equipment.ueic", "recommendation_type", "approved_by", "summary"],
        "default_roles": ["Originator", "AEE Maintenance"],
    },
]


# ── Schemas ───────────────────────────────────────────────────────────────────

class TemplateOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    event_type: str
    channel: str                            # "email" | "sms" | "inapp"
    subject_template: Optional[str] = None
    body_template: str
    recipient_roles: List[str]
    extra_recipient_emails: List[str] = []
    is_active: bool
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


class TemplateCreate(BaseModel):
    event_type: str = Field(..., description="e.g. 'equipment_replacement'")
    channel: str = Field(..., description="'email' | 'sms' | 'inapp'")
    subject_template: Optional[str] = Field(None, description="Subject line (email only)")
    body_template: str = Field(..., description="Message body. Use {{var}} placeholders.")
    recipient_roles: List[str] = Field(
        default=[], description="OrgRole names — all users under these roles get notified"
    )
    extra_recipient_emails: List[str] = Field(
        default=[], description="Individual email addresses (outside role membership)"
    )
    is_active: bool = True


class TemplateUpdate(BaseModel):
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    recipient_roles: Optional[List[str]] = None
    extra_recipient_emails: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ── Helper ────────────────────────────────────────────────────────────────────

def _require_admin(db: Session, user: User) -> None:
    """Raise 403 unless the user is an org admin."""
    from models import OrgRole, OrgUserRole
    is_admin = (
        db.query(OrgUserRole)
        .join(OrgRole)
        .filter(
            OrgUserRole.user_id == user.id,
            OrgRole.is_org_admin.is_(True),
            OrgUserRole.is_active.is_(True),
        )
        .first()
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only org admins can manage notification templates.",
        )


def _get_org(user: User) -> UUID:
    if not user.organization_id:
        raise HTTPException(status_code=403, detail="User has no organization.")
    return user.organization_id


# ── Endpoints — template catalogue ───────────────────────────────────────────

@router.get("/templates/event-types")
def list_event_types(
    current_user: User = Depends(get_current_user),
):
    """
    Return the catalogue of all supported event types with their available
    context variables and default recipient roles — grouped by feature area.
    """
    return _EVENT_CATALOGUE


@router.get("/templates/system-variables")
def list_system_variables(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the variable registry for the template designer variable picker.
    Merges global system variables with any org-specific custom variables.
    Grouped by group_name for the UI accordion/chips.
    """
    org_id = getattr(current_user, "organization_id", None)

    rows = (
        db.query(NotificationVariable)
        .filter(
            NotificationVariable.is_active.is_(True),
            (NotificationVariable.organization_id.is_(None)) |
            (NotificationVariable.organization_id == org_id),
        )
        .order_by(NotificationVariable.group_name, NotificationVariable.var_key)
        .all()
    )

    if rows:
        return [
            {
                "var":          "{{" + r.var_key + "}}",
                "var_key":      r.var_key,
                "label":        r.label,
                "group":        r.group_name,
                "description":  r.description,
                "sample_value": r.sample_value,
                "is_system":    r.is_system,
                "id":           str(r.id),
            }
            for r in rows
        ]

    # Fallback to hardcoded list if DB not seeded yet
    return SYSTEM_VARIABLES


# ── Endpoints — template CRUD ─────────────────────────────────────────────────

@router.get("/templates", response_model=List[TemplateOut])
def list_templates(
    event_type: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List notification templates for the current org.
    Returns org-specific templates merged with global defaults (org-specific takes priority).
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    # Fetch org-specific + global templates
    q = db.query(NotificationTemplate).filter(
        (NotificationTemplate.organization_id == org_id) |
        (NotificationTemplate.organization_id.is_(None))
    )
    if event_type:
        q = q.filter(NotificationTemplate.event_type == event_type)
    if channel:
        q = q.filter(NotificationTemplate.channel == channel)

    templates = q.order_by(
        # org-specific first, then global
        NotificationTemplate.organization_id.desc().nulls_last(),
        NotificationTemplate.event_type,
        NotificationTemplate.channel,
    ).all()

    # De-duplicate: if org has its own for (event_type, channel), hide the global one
    seen: set = set()
    result = []
    for t in templates:
        key = (t.event_type, t.channel)
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new org-specific notification template.
    If a template for (org, event_type, channel) already exists it is overwritten
    by deactivating the old one and inserting the new one.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    # Deactivate any existing org-level template for same event/channel
    db.query(NotificationTemplate).filter(
        NotificationTemplate.organization_id == org_id,
        NotificationTemplate.event_type == data.event_type,
        NotificationTemplate.channel == data.channel,
    ).update({"is_active": False})

    tmpl = NotificationTemplate(
        id=uuid4(),
        organization_id=org_id,
        event_type=data.event_type,
        channel=data.channel,
        subject_template=data.subject_template,
        body_template=data.body_template,
        recipient_roles=data.recipient_roles,
        extra_recipient_emails=data.extra_recipient_emails,
        is_active=data.is_active,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return tmpl


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: UUID,
    data: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a notification template.
    Only org-specific templates can be updated — if the template_id belongs
    to a global (org=NULL) template, a org-specific override copy is created.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    tmpl = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # If it's a global template, create an org-specific override
    if tmpl.organization_id is None:
        override = NotificationTemplate(
            id=uuid4(),
            organization_id=org_id,
            event_type=tmpl.event_type,
            channel=tmpl.channel,
            subject_template=data.subject_template if data.subject_template is not None else tmpl.subject_template,
            body_template=data.body_template if data.body_template is not None else tmpl.body_template,
            recipient_roles=data.recipient_roles if data.recipient_roles is not None else list(tmpl.recipient_roles or []),
            extra_recipient_emails=data.extra_recipient_emails if data.extra_recipient_emails is not None else list(getattr(tmpl, 'extra_recipient_emails', None) or []),
            is_active=data.is_active if data.is_active is not None else tmpl.is_active,
        )
        db.add(override)
        db.commit()
        db.refresh(override)
        return override

    # It's an org-owned template — update in place
    if tmpl.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Cannot edit another org's template")

    if data.subject_template is not None:
        tmpl.subject_template = data.subject_template
    if data.body_template is not None:
        tmpl.body_template = data.body_template
    if data.recipient_roles is not None:
        tmpl.recipient_roles = data.recipient_roles
    if data.extra_recipient_emails is not None:
        tmpl.extra_recipient_emails = data.extra_recipient_emails
    if data.is_active is not None:
        tmpl.is_active = data.is_active

    db.commit()
    db.refresh(tmpl)
    return tmpl


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deactivate (soft-delete) an org-specific notification template.
    Global templates cannot be deleted — only overridden per org.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    tmpl = db.query(NotificationTemplate).filter(
        NotificationTemplate.id == template_id,
        NotificationTemplate.organization_id == org_id,
    ).first()
    if not tmpl:
        raise HTTPException(
            status_code=404,
            detail="Template not found or is a global default (cannot delete global templates).",
        )
    tmpl.is_active = False
    db.commit()


# ── Bulk channel upsert ───────────────────────────────────────────────────────

class ChannelConfig(BaseModel):
    """Per-channel body/subject config inside a bulk upsert payload."""
    enabled: bool = True
    subject_template: Optional[str] = None
    body_template: Optional[str] = None


class BulkTemplateUpsert(BaseModel):
    """
    Upsert all channel configs for one event_type in a single call.
    Used by the UI template form where channels are multi-select toggles.
    Channels not listed are left untouched.
    """
    event_type: str
    recipient_roles: List[str] = []
    extra_recipient_emails: List[str] = []
    email: Optional[ChannelConfig] = None
    sms:   Optional[ChannelConfig] = None
    inapp: Optional[ChannelConfig] = None


@router.post("/templates/bulk-upsert", response_model=List[TemplateOut], status_code=status.HTTP_200_OK)
def bulk_upsert_templates(
    data: BulkTemplateUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create or update all channel templates for one event_type atomically.
    The UI sends this when the admin clicks Save on the template form which
    shows [● Email] [○ SMS] [○ In-App] channel toggles.

    For each channel supplied:
    - enabled=True  → upsert (deactivate old org row, insert new)
    - enabled=False → deactivate org-level template (falls back to global default)
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    channel_map = {
        "email": data.email,
        "sms":   data.sms,
        "inapp": data.inapp,
    }

    results: List[NotificationTemplate] = []
    for channel, cfg in channel_map.items():
        if cfg is None:
            continue  # not supplied — leave existing rows untouched

        # Deactivate any existing org-level row for this event/channel
        db.query(NotificationTemplate).filter(
            NotificationTemplate.organization_id == org_id,
            NotificationTemplate.event_type == data.event_type,
            NotificationTemplate.channel == channel,
        ).update({"is_active": False})

        if not cfg.enabled:
            continue  # just disabled — no new row needed

        # Look up global default body if caller didn't supply one
        if not cfg.body_template:
            global_tmpl = db.query(NotificationTemplate).filter(
                NotificationTemplate.event_type == data.event_type,
                NotificationTemplate.channel == channel,
                NotificationTemplate.organization_id.is_(None),
            ).first()
            cfg.body_template = global_tmpl.body_template if global_tmpl else ""
            if not cfg.subject_template and global_tmpl:
                cfg.subject_template = global_tmpl.subject_template

        new_tmpl = NotificationTemplate(
            id=uuid4(),
            organization_id=org_id,
            event_type=data.event_type,
            channel=channel,
            subject_template=cfg.subject_template,
            body_template=cfg.body_template or "",
            recipient_roles=data.recipient_roles,
            extra_recipient_emails=data.extra_recipient_emails,
            is_active=True,
        )
        db.add(new_tmpl)
        results.append(new_tmpl)

    db.commit()
    for r in results:
        db.refresh(r)
    return results


# ── Grouped template view by event_type ───────────────────────────────────────

class ChannelConfigOut(BaseModel):
    id: Optional[UUID] = None
    enabled: bool
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    is_global: bool = False   # True if showing global default (no org override)

class EventTemplateGroupOut(BaseModel):
    event_type: str
    recipient_roles: List[str] = []
    extra_recipient_emails: List[str] = []
    email: Optional[ChannelConfigOut] = None
    sms:   Optional[ChannelConfigOut] = None
    inapp: Optional[ChannelConfigOut] = None


@router.get("/templates/event/{event_type}", response_model=EventTemplateGroupOut)
def get_event_template_group(
    event_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all channel configs for a single event_type, merged (org overrides global).
    Used by the template form to populate the [● Email] [○ SMS] [○ In-App] toggles.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    all_rows = (
        db.query(NotificationTemplate)
        .filter(
            NotificationTemplate.event_type == event_type,
            NotificationTemplate.is_active.is_(True),
            (NotificationTemplate.organization_id == org_id) |
            (NotificationTemplate.organization_id.is_(None)),
        )
        .order_by(NotificationTemplate.organization_id.desc().nulls_last())
        .all()
    )

    # Build channel map: org-specific wins over global
    channels: Dict[str, NotificationTemplate] = {}
    is_global: Dict[str, bool] = {}
    for row in all_rows:
        ch = row.channel
        if ch not in channels:  # first = org-specific (ordered above)
            channels[ch] = row
            is_global[ch] = row.organization_id is None

    def _ch_out(channel: str) -> Optional[ChannelConfigOut]:
        row = channels.get(channel)
        if not row:
            return None
        return ChannelConfigOut(
            id=row.id,
            enabled=True,
            subject_template=row.subject_template,
            body_template=row.body_template,
            is_global=is_global.get(channel, False),
        )

    # Common fields: prefer org row, fall back to any row
    sample = next(iter(channels.values()), None)
    return EventTemplateGroupOut(
        event_type=event_type,
        recipient_roles=list(sample.recipient_roles or []) if sample else [],
        extra_recipient_emails=list(getattr(sample, "extra_recipient_emails", None) or []) if sample else [],
        email=_ch_out("email"),
        sms=_ch_out("sms"),
        inapp=_ch_out("inapp"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# C)  ADMIN — Notification Variable CRUD
# ══════════════════════════════════════════════════════════════════════════════

class VariableOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    var_key: str
    label: str
    group_name: str
    description: Optional[str] = None
    sample_value: Optional[str] = None
    resolver_key: Optional[str] = None
    is_system: bool
    is_active: bool
    cts: Optional[datetime] = None

    class Config:
        from_attributes = True


class VariableCreate(BaseModel):
    var_key: str = Field(..., description="Key used in templates: {{var_key}}")
    label: str
    group_name: str = Field(..., description="UI group/category label")
    description: Optional[str] = None
    sample_value: Optional[str] = Field(None, description="Preview value shown in template designer")
    resolver_key: Optional[str] = Field(None, description="Context key used during rendering (defaults to var_key)")


class VariableUpdate(BaseModel):
    label: Optional[str] = None
    group_name: Optional[str] = None
    description: Optional[str] = None
    sample_value: Optional[str] = None
    resolver_key: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/variables", response_model=List[VariableOut])
def list_variables(
    group_name: Optional[str] = Query(None),
    include_system: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all notification variables (system + org-specific).
    System variables have organization_id=NULL and is_system=True.
    """
    org_id = getattr(current_user, "organization_id", None)

    q = db.query(NotificationVariable).filter(
        (NotificationVariable.organization_id.is_(None)) |
        (NotificationVariable.organization_id == org_id),
        NotificationVariable.is_active.is_(True),
    )
    if not include_system:
        q = q.filter(NotificationVariable.is_system.is_(False))
    if group_name:
        q = q.filter(NotificationVariable.group_name == group_name)

    return q.order_by(NotificationVariable.group_name, NotificationVariable.var_key).all()


@router.post("/variables", response_model=VariableOut, status_code=status.HTTP_201_CREATED)
def create_variable(
    data: VariableCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a custom org-specific notification variable.
    Use {{var_key}} in your template bodies to reference it.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    # Prevent duplicate var_key within the org
    existing = db.query(NotificationVariable).filter(
        NotificationVariable.var_key == data.var_key,
        NotificationVariable.organization_id == org_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Variable '{data.var_key}' already exists for this organisation.",
        )

    var = NotificationVariable(
        id=uuid4(),
        organization_id=org_id,
        var_key=data.var_key,
        label=data.label,
        group_name=data.group_name,
        description=data.description,
        sample_value=data.sample_value,
        resolver_key=data.resolver_key or data.var_key,
        is_system=False,
        is_active=True,
    )
    db.add(var)
    db.commit()
    db.refresh(var)
    return var


@router.put("/variables/{variable_id}", response_model=VariableOut)
def update_variable(
    variable_id: UUID,
    data: VariableUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a notification variable.
    System variables: only sample_value, description, and is_active can be changed.
    Custom org variables: all fields editable.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    var = db.query(NotificationVariable).filter(
        NotificationVariable.id == variable_id,
    ).first()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found.")

    # System variables: limit editable fields
    if var.is_system:
        if data.sample_value is not None:
            var.sample_value = data.sample_value
        if data.description is not None:
            var.description = data.description
        if data.is_active is not None:
            var.is_active = data.is_active
    else:
        # Org custom variable — must belong to caller's org
        if var.organization_id != org_id:
            raise HTTPException(status_code=403, detail="Cannot edit another org's variable.")
        if data.label is not None:
            var.label = data.label
        if data.group_name is not None:
            var.group_name = data.group_name
        if data.description is not None:
            var.description = data.description
        if data.sample_value is not None:
            var.sample_value = data.sample_value
        if data.resolver_key is not None:
            var.resolver_key = data.resolver_key
        if data.is_active is not None:
            var.is_active = data.is_active

    db.commit()
    db.refresh(var)
    return var


@router.delete("/variables/{variable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variable(
    variable_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deactivate (soft-delete) an org-specific custom variable.
    System variables (is_system=True) cannot be deleted — use PUT to disable.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    var = db.query(NotificationVariable).filter(
        NotificationVariable.id == variable_id,
    ).first()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found.")
    if var.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System variables cannot be deleted. Use PUT to set is_active=false.",
        )
    if var.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Cannot delete another org's variable.")

    var.is_active = False
    db.commit()
