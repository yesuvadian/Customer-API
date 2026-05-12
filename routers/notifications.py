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
from models import (
    NotificationEventCatalogue,
    NotificationRoutingRule,
    NotificationTemplate,
    NotificationVariable,
    OrgRole,
    OrgRolePermission,
    OrgUserRole,
    Module,
    User,
    UserNotification,
)

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
    # ── Fixed: was "request_assigned" but service fires "tester_assigned" ──────
    {
        "event_type": "tester_assigned",
        "label": "Tester Assigned to Request",
        "group": "Test Workflow",
        "description": "Fired when a test request is assigned to a field/lab tester.",
        "context_vars": ["request.number", "request.title", "request.assigned_to",
                         "request.due_date", "equipment.ueic"],
        "default_roles": ["Tester", "AEE Maintenance"],
    },
    {
        "event_type": "tester_declined",
        "label": "Tester Declined Assignment",
        "group": "Test Workflow",
        "description": "Fired when a tester declines an assignment — notifies the Test Assigner.",
        "context_vars": ["request.number", "tester_name", "reason"],
        "default_roles": ["TestAssigner", "EE TLSS"],
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
        "event_type": "recommendation_approved",
        "label": "Recommendation Approved",
        "group": "Test Workflow",
        "description": "Fired when a technical approver approves a recommendation.",
        "context_vars": ["request.number", "recommendation_type", "product_count"],
        "default_roles": ["Originator", "AEE Maintenance"],
    },
    {
        "event_type": "recommendation_rejected",
        "label": "Recommendation Rejected",
        "group": "Test Workflow",
        "description": "Fired when a technical approver rejects a recommendation — notifies the tester.",
        "context_vars": ["request.number", "reason"],
        "default_roles": ["Tester", "Originator"],
    },
    # ── Scheduling ────────────────────────────────────────────────────────────
    {
        "event_type": "due_reminder",
        "label": "Test Due Soon Reminder (15 days)",
        "group": "Scheduling",
        "description": "Fired 15 days before a scheduled test is due (SRS §8.2 #1).",
        "context_vars": ["equipment.ueic", "request.title", "request.due_date",
                         "equipment.department", "days_remaining"],
        "default_roles": ["AEE Maintenance", "EE TLSS"],
    },
    {
        "event_type": "due_reminder_final",
        "label": "Test Due Final Reminder (7 days)",
        "group": "Scheduling",
        "description": "Final reminder fired 7 days before a scheduled test is due (SRS §8.2 #2).",
        "context_vars": ["equipment.ueic", "request.title", "request.due_date",
                         "equipment.department", "days_remaining"],
        "default_roles": ["AEE Maintenance", "EE TLSS", "Department Head"],
    },
    # ── Fixed: was "test_overdue" but service fires "overdue_alert" ───────────
    {
        "event_type": "overdue_alert",
        "label": "Test Overdue",
        "group": "Scheduling",
        "description": "Fired when a scheduled test passes its due date without completion (SRS §8.2 #3).",
        "context_vars": ["equipment.ueic", "request.title", "request.due_date",
                         "equipment.department"],
        "default_roles": ["EE TLSS", "AEE Maintenance", "SEE W&M"],
    },
    {
        "event_type": "overdue_escalation",
        "label": "Test Overdue Escalation (>7 days)",
        "group": "Scheduling",
        "description": "Escalation fired when a test is more than 7 days overdue (SRS §8.2 #4).",
        "context_vars": ["equipment.ueic", "request.title", "request.due_date",
                         "days_overdue", "equipment.department"],
        "default_roles": ["SEE W&M", "CEE Transmission Zone"],
    },
    # ── Procurement ───────────────────────────────────────────────────────────
    {
        "event_type": "procurement_pending",
        "label": "Procurement Request Raised",
        "group": "Recommendations",
        "description": "Fired when a procurement request is created — notifies Finance Approvers.",
        "context_vars": ["request.number", "pr_number", "title"],
        "default_roles": ["FinanceApprover", "Department Head"],
    },
    {
        "event_type": "procurement_decision",
        "label": "Procurement Decision (Approved / Rejected)",
        "group": "Recommendations",
        "description": "Fired when Finance approves or rejects a procurement request.",
        "context_vars": ["request.number", "pr_number", "decision", "notes"],
        "default_roles": ["Originator", "TechApprover", "EE TLSS"],
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
    attachment_vars: List = []
    """
    Attachment variable entries for the email channel.
    Each entry is either a simple string or a typed dict:
      Simple : "report.retriepdf"
      Typed  : {"var_key": "report.retriepdf", "type": "pdf"}
    Supported types: pdf | excel | xlsx | docx | json | csv | txt | zip
    """
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
    attachment_vars: List = Field(
        default=[],
        description=(
            "Attachment variable entries for email channel. Each entry is either "
            "a simple string ('report.retriepdf') or a typed dict "
            "({'var_key': 'report.retriepdf', 'type': 'pdf'}). "
            "Supported types: pdf | excel | xlsx | docx | json | csv | txt | zip"
        ),
    )
    is_active: bool = True


class TemplateUpdate(BaseModel):
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    recipient_roles: Optional[List[str]] = None
    extra_recipient_emails: Optional[List[str]] = None
    attachment_vars: Optional[List] = Field(
        default=None,
        description=(
            "Attachment variable entries for email channel. Pass [] to clear. "
            "Each entry: simple string or {'var_key': '...', 'type': 'pdf|excel|docx|json|...'}"
        ),
    )
    is_active: Optional[bool] = None


# ── Helper ────────────────────────────────────────────────────────────────────

def _require_admin(db: Session, user: User) -> None:
    """Raise 403 unless the user's role has can_view on any notification module
    OR the role carries is_org_admin / is_dept_admin — no hardcoded flag required.
    """
    # Check module-permission: any of the three notification admin modules
    _NOTIF_MODULE_PATHS = [
        "org_notification_templates",
        "org_notification_routing",
        "org_notification_schedules",
    ]
    has_perm = (
        db.query(OrgUserRole)
        .join(OrgRole, OrgRole.id == OrgUserRole.org_role_id)
        .join(OrgRolePermission, OrgRolePermission.org_role_id == OrgRole.id)
        .join(Module, Module.id == OrgRolePermission.module_id)
        .filter(
            OrgUserRole.user_id == user.id,
            OrgUserRole.is_active.is_(True),
            OrgRolePermission.can_view.is_(True),
            Module.path.in_(_NOTIF_MODULE_PATHS),
        )
        .first()
    )
    if not has_perm:
        # Fallback: accept is_org_admin or is_dept_admin role flags
        has_role_flag = (
            db.query(OrgUserRole)
            .join(OrgRole, OrgRole.id == OrgUserRole.org_role_id)
            .filter(
                OrgUserRole.user_id == user.id,
                OrgUserRole.is_active.is_(True),
                (OrgRole.is_org_admin.is_(True) | OrgRole.is_dept_admin.is_(True)),
            )
            .first()
        )
        if not has_role_flag:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: insufficient permissions for notification management.",
            )


def _get_org(user: User) -> UUID:
    if not user.organization_id:
        raise HTTPException(status_code=403, detail="User has no organization.")
    return user.organization_id


# ── Endpoints — template catalogue ───────────────────────────────────────────

@router.get("/templates/event-types")
def list_event_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the merged event-type catalogue for the caller's organisation.

    Resolution (same pattern as templates):
      1. Start with all global entries (organization_id IS NULL).
      2. Overlay org-specific entries — they can override labels/descriptions
         or add entirely new event types custom to this org.
    Falls back to the hardcoded _EVENT_CATALOGUE if the table is empty.
    """
    org_id = getattr(current_user, "organization_id", None)

    # Fetch global rows
    global_rows = (
        db.query(NotificationEventCatalogue)
        .filter(
            NotificationEventCatalogue.organization_id.is_(None),
            NotificationEventCatalogue.is_active.is_(True),
        )
        .all()
    )

    # Fetch org-specific rows (override / extend)
    org_rows = (
        db.query(NotificationEventCatalogue)
        .filter(
            NotificationEventCatalogue.organization_id == org_id,
            NotificationEventCatalogue.is_active.is_(True),
        )
        .all()
    ) if org_id else []

    if not global_rows and not org_rows:
        # Pre-seed fallback
        return _EVENT_CATALOGUE

    # Merge: org-specific entries override global ones for the same event_type
    merged: dict = {r.event_type: r for r in global_rows}
    for r in org_rows:
        merged[r.event_type] = r   # org-specific wins

    return [
        {
            "event_type":    r.event_type,
            "label":         r.label,
            "group":         r.group_name,
            "description":   r.description or "",
            "context_vars":  r.context_vars or [],
            "default_roles": r.default_roles or [],
        }
        for r in sorted(merged.values(), key=lambda x: (x.group_name, x.label))
    ]


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
        attachment_vars=data.attachment_vars,
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
            attachment_vars=data.attachment_vars if data.attachment_vars is not None else list(getattr(tmpl, 'attachment_vars', None) or []),
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
    if data.attachment_vars is not None:
        tmpl.attachment_vars = data.attachment_vars
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
    attachment_vars: List = Field(
        default=[],
        description=(
            "Email attachment variable entries. Each entry is either a simple string "
            "('report.retriepdf') or a typed dict {'var_key': '...', 'type': 'pdf|excel|docx|json'}."
            " Only meaningful for the email channel."
        ),
    )


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

        # Carry over attachment_vars from global default if caller didn't supply any
        effective_attachment_vars = cfg.attachment_vars
        if not effective_attachment_vars and channel == "email":
            global_tmpl_av = db.query(NotificationTemplate).filter(
                NotificationTemplate.event_type == data.event_type,
                NotificationTemplate.channel == "email",
                NotificationTemplate.organization_id.is_(None),
            ).first()
            if global_tmpl_av:
                effective_attachment_vars = list(getattr(global_tmpl_av, 'attachment_vars', None) or [])

        new_tmpl = NotificationTemplate(
            id=uuid4(),
            organization_id=org_id,
            event_type=data.event_type,
            channel=channel,
            subject_template=cfg.subject_template,
            body_template=cfg.body_template or "",
            recipient_roles=data.recipient_roles,
            extra_recipient_emails=data.extra_recipient_emails,
            attachment_vars=effective_attachment_vars,
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
    attachment_vars: List = []
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
            attachment_vars=list(getattr(row, 'attachment_vars', None) or []),
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


# ══════════════════════════════════════════════════════════════════════════════
# D)  ADMIN — Notification Routing Rules
# ══════════════════════════════════════════════════════════════════════════════
#
# Routing rules decide: for a given event_type, which CHANNELS are activated
# depending on the workflow type, equipment type, test category, and status
# transition of the triggering request.
#
# Global rules (organization_id=NULL) are the system defaults seeded by seed.py.
# Org-specific rules override globals — higher priority value wins.
#
# Adding a new workflow (e.g. "preventive_maintenance"):
#   POST /notifications/routing-rules  { event_type: "...", applicable_workflow_types: ["preventive_maintenance"], ... }
#   Zero code change required.
# ══════════════════════════════════════════════════════════════════════════════

# ── Constants exposed for UI dropdowns ────────────────────────────────────────

WORKFLOW_TYPES = [
    {"value": "direct_test",       "label": "Direct Test"},
    {"value": "failure_register",  "label": "Failure Register"},
    {"value": "taqc",              "label": "TA&QC Inspection"},
    {"value": "multisession",      "label": "Multi-Session Test"},
    {"value": "schedule",          "label": "Scheduled / Periodic Test"},
    {"value": "repair_cycle",      "label": "Repair Cycle"},
]

def _get_test_types(db: Session = None) -> list:
    """
    Return distinct test category types from CategoryDetails — the real source of truth.
    Falls back to a hardcoded list if db is not provided.
    """
    _LABELS = {
        "test":             "Test",
        "maintenance":      "Maintenance",
        "inspection":       "Inspection",
        "repair_lifecycle": "Repair Cycle",
        "nameplate":        "Nameplate",
    }
    if db is not None:
        from models import CategoryDetails
        from sqlalchemy import distinct as sa_distinct
        rows = (
            db.query(sa_distinct(CategoryDetails.category_type))
            .filter(
                CategoryDetails.category_type.isnot(None),
                CategoryDetails.is_active.is_(True),
            )
            .all()
        )
        return [
            {"value": r[0], "label": _LABELS.get(r[0], r[0].replace("_", " ").title())}
            for r in rows if r[0]
        ]
    # static fallback (used at module load time for TEST_TYPES constant)
    return [{"value": k, "label": v} for k, v in _LABELS.items()]

TEST_TYPES = _get_test_types()

CHANNELS = ["email", "sms", "inapp"]


# ── Schemas ────────────────────────────────────────────────────────────────────

class RoutingRuleOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    event_type: str
    label: Optional[str] = None
    applicable_workflow_types:  List[str] = []
    applicable_equipment_types: List[str] = []
    applicable_test_types:      List[str] = []
    applicable_status_from: Optional[str] = None
    applicable_status_to:   Optional[str] = None
    channels_enabled:           List[str] = []
    recipient_roles_override:   Optional[List[str]] = None
    priority:  int = 0
    is_active: bool
    is_global: bool = False   # True if organization_id is None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoutingRuleCreate(BaseModel):
    event_type: str
    label: Optional[str] = None
    applicable_workflow_types:  List[str] = Field(default=[], description="Empty = all workflows")
    applicable_equipment_types: List[str] = Field(default=[], description="Empty = all equipment types")
    applicable_test_types:      List[str] = Field(default=[], description="Empty = all test categories")
    applicable_status_from: Optional[str] = None
    applicable_status_to:   Optional[str] = None
    channels_enabled:    List[str] = Field(default=["email", "sms", "inapp"])
    recipient_roles_override: Optional[List[str]] = None
    priority: int = Field(default=10, description="Higher priority wins. Default 10 for org rules.")
    is_active: bool = True


class RoutingRuleUpdate(BaseModel):
    label: Optional[str] = None
    applicable_workflow_types:  Optional[List[str]] = None
    applicable_equipment_types: Optional[List[str]] = None
    applicable_test_types:      Optional[List[str]] = None
    applicable_status_from: Optional[str] = None
    applicable_status_to:   Optional[str] = None
    channels_enabled:    Optional[List[str]] = None
    recipient_roles_override: Optional[List[str]] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


# ── Helper: serialise a rule row ──────────────────────────────────────────────

def _rule_out(rule: NotificationRoutingRule) -> dict:
    return {
        "id":            rule.id,
        "organization_id": rule.organization_id,
        "event_type":    rule.event_type,
        "label":         rule.label,
        "applicable_workflow_types":  rule.applicable_workflow_types or [],
        "applicable_equipment_types": rule.applicable_equipment_types or [],
        "applicable_test_types":      rule.applicable_test_types or [],
        "applicable_status_from":     rule.applicable_status_from,
        "applicable_status_to":       rule.applicable_status_to,
        "channels_enabled":           rule.channels_enabled or [],
        "recipient_roles_override":   rule.recipient_roles_override,
        "priority":  rule.priority,
        "is_active": rule.is_active,
        "is_global": rule.organization_id is None,
        "cts": rule.cts,
        "mts": rule.mts,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _get_stages_by_workflow(db: Session) -> dict:
    """
    Return {workflow_type: [{value, label}]} for use in status_from/status_to dropdowns.
    - Workflow-based types share the testing_request status lifecycle.
    - repair_lifecycle uses RepairStageDefinition names from DB.
    - Equipment and standalone types get their own fixed event stages.
    """
    from models import RepairStageDefinition

    tr_statuses = [
        {"value": "submitted",       "label": "Submitted"},
        {"value": "assigned",        "label": "Assigned"},
        {"value": "accepted",        "label": "Accepted"},
        {"value": "in_progress",     "label": "In Progress"},
        {"value": "under_review",    "label": "Under Review"},
        {"value": "test_submitted",  "label": "Test Submitted"},
        {"value": "under_approval",  "label": "Under Approval"},
        {"value": "approved",        "label": "Approved"},
        {"value": "rejected",        "label": "Rejected"},
        {"value": "completed",       "label": "Completed"},
    ]

    repair_stages = [
        {"value": s.name, "label": s.name}
        for s in db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.is_active.is_(True))
            .order_by(RepairStageDefinition.sequence)
            .all()
    ]
    if not repair_stages:
        repair_stages = [{"value": f"S{i}", "label": f"Stage {i}"} for i in range(1, 11)]

    equipment_stages = [
        {"value": "registered",  "label": "Registered"},
        {"value": "retired",     "label": "Retired"},
        {"value": "replaced",    "label": "Replaced"},
    ]

    return {
        "testing_request":   tr_statuses,
        "taqc_inspection":   tr_statuses,
        "failure_registry":  [
            {"value": "submitted",       "label": "Submitted"},
            {"value": "under_approval",  "label": "Under Approval"},
            {"value": "approved",        "label": "Approved"},
            {"value": "rejected",        "label": "Rejected"},
        ],
        "repair_lifecycle":  repair_stages,
        "equipment":         equipment_stages,
    }


def _get_org_roles(db: Session, organization_id=None) -> list:
    """Return [{value, label}] of active OrgRole names for the org (or all global roles)."""
    q = db.query(OrgRole.name).filter(OrgRole.is_active.is_(True))
    if organization_id:
        q = q.filter(OrgRole.organization_id == organization_id)
    rows = q.order_by(OrgRole.name).distinct().all()
    return [{"value": r[0], "label": r[0]} for r in rows]


def _get_equipment_types(db: Session) -> list:
    """Return [{value, label}] of active equipment categories from CategoryMaster."""
    from models import CategoryMaster
    rows = (
        db.query(CategoryMaster.name)
        .filter(CategoryMaster.is_active.is_(True))
        .order_by(CategoryMaster.name)
        .all()
    )
    return [{"value": r[0], "label": r[0]} for r in rows]


@router.get("/routing-rules/meta")
def routing_rules_meta(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return dropdown values for the routing rules configuration UI.
    Includes workflow types, test types, channels, stages per workflow,
    org roles, and equipment types.
    """
    from models import Workflow as WorkflowModel
    org_id = _get_org(current_user)
    wf_rows = db.query(WorkflowModel.workflow_type, WorkflowModel.name).distinct().order_by(WorkflowModel.name).all()
    workflow_types = [{"value": r.workflow_type, "label": r.name} for r in wf_rows] or WORKFLOW_TYPES
    return {
        "workflow_types":      workflow_types,
        "test_types":          _get_test_types(db),
        "channels":            CHANNELS,
        "stages_by_workflow":  _get_stages_by_workflow(db),
        "org_roles":           _get_org_roles(db, org_id),
        "equipment_types":     _get_equipment_types(db),
    }


@router.get("/routing-rules", response_model=List[RoutingRuleOut])
def list_routing_rules(
    event_type: Optional[str] = Query(None),
    workflow_type: Optional[str] = Query(None),
    include_global: bool = Query(True, description="Include system-wide global rules"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List routing rules for the caller's org.
    Returns org-specific rules + (optionally) global defaults merged/labelled.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    q = db.query(NotificationRoutingRule).filter(
        (NotificationRoutingRule.organization_id == org_id) |
        (NotificationRoutingRule.organization_id.is_(None) if include_global else False),
    )
    if event_type:
        q = q.filter(NotificationRoutingRule.event_type == event_type)
    if workflow_type:
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        q = q.filter(
            NotificationRoutingRule.applicable_workflow_types.contains([workflow_type])
        )

    rules = q.order_by(
        NotificationRoutingRule.organization_id.is_(None).asc(),   # org-specific first
        NotificationRoutingRule.priority.desc(),
        NotificationRoutingRule.event_type,
    ).all()

    return [_rule_out(r) for r in rules]


@router.post("/routing-rules", status_code=status.HTTP_201_CREATED)
def create_routing_rule(
    data: RoutingRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create an org-specific routing rule.
    This overrides any global rule that matches the same scope.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = NotificationRoutingRule(
        organization_id=org_id,
        event_type=data.event_type,
        label=data.label,
        applicable_workflow_types=data.applicable_workflow_types,
        applicable_equipment_types=data.applicable_equipment_types,
        applicable_test_types=data.applicable_test_types,
        applicable_status_from=data.applicable_status_from,
        applicable_status_to=data.applicable_status_to,
        channels_enabled=data.channels_enabled,
        recipient_roles_override=data.recipient_roles_override,
        priority=data.priority,
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.put("/routing-rules/{rule_id}")
def update_routing_rule(
    rule_id: UUID,
    data: RoutingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update an org-specific routing rule.
    Global (system) rules cannot be edited — create an org-specific override instead.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = db.query(NotificationRoutingRule).filter(
        NotificationRoutingRule.id == rule_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found.")
    if rule.organization_id is None:
        raise HTTPException(
            status_code=403,
            detail="Global system rules cannot be edited. Create an org-specific rule instead.",
        )
    if rule.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Cannot edit another org's routing rule.")

    if data.label is not None:
        rule.label = data.label
    if data.applicable_workflow_types is not None:
        rule.applicable_workflow_types = data.applicable_workflow_types
    if data.applicable_equipment_types is not None:
        rule.applicable_equipment_types = data.applicable_equipment_types
    if data.applicable_test_types is not None:
        rule.applicable_test_types = data.applicable_test_types
    if data.applicable_status_from is not None:
        rule.applicable_status_from = data.applicable_status_from
    if data.applicable_status_to is not None:
        rule.applicable_status_to = data.applicable_status_to
    if data.channels_enabled is not None:
        rule.channels_enabled = data.channels_enabled
    if data.recipient_roles_override is not None:
        rule.recipient_roles_override = data.recipient_roles_override
    if data.priority is not None:
        rule.priority = data.priority
    if data.is_active is not None:
        rule.is_active = data.is_active

    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.delete("/routing-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routing_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deactivate (soft-delete) an org-specific routing rule.
    Global rules cannot be deleted.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = db.query(NotificationRoutingRule).filter(
        NotificationRoutingRule.id == rule_id,
        NotificationRoutingRule.organization_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(
            status_code=404,
            detail="Rule not found or is a global default (cannot delete global rules).",
        )
    rule.is_active = False
    db.commit()


@router.post("/routing-rules/{rule_id}/clone")
def clone_routing_rule_as_org_override(
    rule_id: UUID,
    data: RoutingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Clone a global routing rule as an org-specific override, then apply updates.

    Use this when you want to customise a global default rule:
    1. GET /routing-rules  → find the global rule id
    2. POST /routing-rules/{id}/clone  { channels_enabled: ["email"] }
       → creates org-specific copy with your changes applied, priority=10
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    source = db.query(NotificationRoutingRule).filter(
        NotificationRoutingRule.id == rule_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source routing rule not found.")

    clone = NotificationRoutingRule(
        organization_id=org_id,
        event_type=source.event_type,
        label=data.label or (f"[Override] {source.label or source.event_type}"),
        applicable_workflow_types=data.applicable_workflow_types
            if data.applicable_workflow_types is not None
            else list(source.applicable_workflow_types or []),
        applicable_equipment_types=data.applicable_equipment_types
            if data.applicable_equipment_types is not None
            else list(source.applicable_equipment_types or []),
        applicable_test_types=data.applicable_test_types
            if data.applicable_test_types is not None
            else list(source.applicable_test_types or []),
        applicable_status_from=data.applicable_status_from or source.applicable_status_from,
        applicable_status_to=data.applicable_status_to or source.applicable_status_to,
        channels_enabled=data.channels_enabled
            if data.channels_enabled is not None
            else list(source.channels_enabled or ["email", "sms", "inapp"]),
        recipient_roles_override=data.recipient_roles_override or source.recipient_roles_override,
        priority=data.priority if data.priority is not None else 10,
        is_active=True,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _rule_out(clone)


# ══════════════════════════════════════════════════════════════════════════════
# E)  ADMIN — Notification Schedule Rules  (configurable trigger events)
# ══════════════════════════════════════════════════════════════════════════════
#
# Schedule rules define WHEN a notification is triggered:
#   • time-based  : N days before/after a due date
#   • status-based: when workflow reaches a specific status
#   • both        : time AND status condition must both be true
#
# Org admins can override global defaults (e.g. change 15-day reminder to 10).
# Global rules (organization_id=NULL) are read-only for org admins.
# ──────────────────────────────────────────────────────────────────────────────

from models import NotificationScheduleRule as _NSR

TRIGGER_TYPES = [
    {"value": "due_soon",          "label": "N days before due date"},
    {"value": "overdue",           "label": "When test is overdue"},
    {"value": "escalation",        "label": "When overdue > N days"},
    {"value": "status_transition", "label": "When workflow status changes"},
    {"value": "both",              "label": "Time-based AND status-based"},
]

SEVERITY_LEVELS = ["info", "alert", "critical"]

WORKFLOW_STATUSES = [
    "submitted", "pending_approval", "approved", "assigned", "in_progress",
    "completed", "rejected", "overdue", "escalated", "cancelled",
    "pending_review", "pending_dispatch", "dispatched", "result_uploaded",
    "compliance_pending", "compliance_uploaded",
    # Repair cycle statuses
    "dismantling", "inspection_stage", "rewinding", "testing", "reassembly",
    "oil_filling", "final_test", "dispatched_for_commissioning", "commissioned",
    "delayed",
]


class ScheduleRuleOut(BaseModel):
    id:                       str
    organization_id:          Optional[str]
    is_global:                bool
    event_type:               str
    label:                    str
    trigger_type:             str
    offset_days:              int
    trigger_on_status:        Optional[str]
    applicable_workflow_types: List[str]
    applicable_categories:    List[str]
    advanced_conditions:      Optional[dict]
    severity:                 str
    is_active:                bool
    cts:                      Optional[str]
    mts:                      Optional[str]

    class Config:
        from_attributes = True


class ScheduleRuleCreate(BaseModel):
    event_type:               str
    label:                    str
    trigger_type:             str
    offset_days:              int = 0
    trigger_on_status:        Optional[str] = None
    applicable_workflow_types: Optional[List[str]] = None
    applicable_categories:    Optional[List[str]] = None
    advanced_conditions:      Optional[dict] = None
    severity:                 str = "info"
    is_active:                bool = True


class ScheduleRuleUpdate(BaseModel):
    label:                    Optional[str] = None
    trigger_type:             Optional[str] = None
    offset_days:              Optional[int] = None
    trigger_on_status:        Optional[str] = None
    applicable_workflow_types: Optional[List[str]] = None
    applicable_categories:    Optional[List[str]] = None
    advanced_conditions:      Optional[dict] = None
    severity:                 Optional[str] = None
    is_active:                Optional[bool] = None


def _srule_out(r: _NSR) -> dict:
    return {
        "id":                       str(r.id),
        "organization_id":          str(r.organization_id) if r.organization_id else None,
        "is_global":                r.organization_id is None,
        "event_type":               r.event_type,
        "label":                    r.label,
        "trigger_type":             r.trigger_type,
        "offset_days":              r.offset_days,
        "trigger_on_status":        r.trigger_on_status,
        "applicable_workflow_types": list(r.applicable_workflow_types or []),
        "applicable_categories":    list(r.applicable_categories or []),
        "advanced_conditions":      r.advanced_conditions,
        "severity":                 r.severity,
        "is_active":                r.is_active,
        "cts":                      r.cts.isoformat() if r.cts else None,
        "mts":                      r.mts.isoformat() if r.mts else None,
    }


@router.get("/schedule-rules/meta")
def get_schedule_rule_meta(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns dropdown options for the schedule rule editor.
    Workflow types from the Workflow table; test categories from RequestCategory enum.
    """
    from models import Workflow as WorkflowModel
    org_id = _get_org(current_user)
    wf_rows = db.query(WorkflowModel.workflow_type, WorkflowModel.name).distinct().order_by(WorkflowModel.name).all()
    workflow_types = [{"value": r.workflow_type, "label": r.name} for r in wf_rows] or WORKFLOW_TYPES
    return {
        "trigger_types":      TRIGGER_TYPES,
        "severity_levels":    SEVERITY_LEVELS,
        "workflow_statuses":  WORKFLOW_STATUSES,
        "workflow_types":     workflow_types,
        "test_types":         _get_test_types(db),
        "stages_by_workflow": _get_stages_by_workflow(db),
        "org_roles":          _get_org_roles(db, org_id),
        "equipment_types":    _get_equipment_types(db),
    }


@router.get("/schedule-rules", response_model=List[ScheduleRuleOut])
def list_schedule_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns all schedule rules: global defaults + org-specific overrides for
    the caller's organisation.  Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rules = db.query(_NSR).filter(
        (_NSR.organization_id.is_(None)) | (_NSR.organization_id == org_id),
        _NSR.is_active.is_(True),
    ).order_by(
        _NSR.organization_id.is_(None).desc(),  # globals first
        _NSR.event_type,
    ).all()
    return [_srule_out(r) for r in rules]


@router.post("/schedule-rules", status_code=status.HTTP_201_CREATED)
def create_schedule_rule(
    data: ScheduleRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new org-specific schedule rule.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = _NSR(
        organization_id=org_id,
        event_type=data.event_type,
        label=data.label,
        trigger_type=data.trigger_type,
        offset_days=data.offset_days,
        trigger_on_status=data.trigger_on_status,
        applicable_workflow_types=data.applicable_workflow_types or [],
        applicable_categories=data.applicable_categories or [],
        advanced_conditions=data.advanced_conditions,
        severity=data.severity,
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _srule_out(rule)


@router.put("/schedule-rules/{rule_id}")
def update_schedule_rule(
    rule_id: UUID,
    data: ScheduleRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update an org-specific schedule rule.
    Org admins only — cannot edit global defaults.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = db.query(_NSR).filter(
        _NSR.id == rule_id,
        _NSR.organization_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(
            status_code=404,
            detail="Rule not found or is a global default (override it using /clone).",
        )

    if data.label             is not None: rule.label             = data.label
    if data.trigger_type      is not None: rule.trigger_type      = data.trigger_type
    if data.offset_days       is not None: rule.offset_days       = data.offset_days
    if data.trigger_on_status is not None: rule.trigger_on_status = data.trigger_on_status
    if data.applicable_workflow_types is not None:
        rule.applicable_workflow_types = data.applicable_workflow_types
    if data.applicable_categories is not None:
        rule.applicable_categories = data.applicable_categories
    if data.advanced_conditions is not None:
        rule.advanced_conditions = data.advanced_conditions
    if data.severity          is not None: rule.severity          = data.severity
    if data.is_active         is not None: rule.is_active         = data.is_active

    db.commit()
    db.refresh(rule)
    return _srule_out(rule)


@router.delete("/schedule-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft-delete (deactivate) an org-specific schedule rule.
    Global defaults cannot be deleted — clone and deactivate the clone instead.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = db.query(_NSR).filter(
        _NSR.id == rule_id,
        _NSR.organization_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(
            status_code=404,
            detail="Rule not found or is a global default (cannot delete global defaults).",
        )
    rule.is_active = False
    db.commit()


@router.post("/schedule-rules/{rule_id}/clone")
def clone_schedule_rule_as_org_override(
    rule_id: UUID,
    data: ScheduleRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Clone a global schedule rule as an org-specific override.

    Use this to customise the trigger days (e.g. change global 15-day reminder
    to 10 days for your org):
      POST /schedule-rules/{global_rule_id}/clone  { "offset_days": 10 }
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    source = db.query(_NSR).filter(_NSR.id == rule_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source schedule rule not found.")

    clone = _NSR(
        organization_id=org_id,
        event_type=source.event_type,
        label=data.label or f"[Override] {source.label}",
        trigger_type=data.trigger_type       or source.trigger_type,
        offset_days=data.offset_days         if data.offset_days is not None else source.offset_days,
        trigger_on_status=data.trigger_on_status or source.trigger_on_status,
        applicable_workflow_types=(
            data.applicable_workflow_types
            if data.applicable_workflow_types is not None
            else list(source.applicable_workflow_types or [])
        ),
        applicable_categories=(
            data.applicable_categories
            if data.applicable_categories is not None
            else list(source.applicable_categories or [])
        ),
        advanced_conditions=data.advanced_conditions or source.advanced_conditions,
        severity=data.severity or source.severity,
        is_active=True,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _srule_out(clone)
