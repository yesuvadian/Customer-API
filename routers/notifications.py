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

import asyncio as _asyncio
import json as _json

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from category_labels import NotificationRoutingCategoryLabels
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
    extra_data: Optional[dict] = None    # Structured payload (e.g. download_url for reports)

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


@router.get("/stream")
async def notification_stream(
    current_user: User = Depends(get_current_user),
):
    """
    Server-Sent Events stream — real-time unread notification badge counts.

    Emits a JSON payload every 5 s when the unread count changes:
        data: {"critical": 2, "alert": 3, "info": 5, "total": 10}

    Emits `: ping` keepalives between unchanged ticks (prevents proxy / nginx
    idle-connection timeouts at 60 s).

    The Flutter client reconnects automatically on any disconnect — standard
    SSE browser/http-client behaviour.  Fall-back 30-second polling in the
    Flutter provider keeps the badge updated even if SSE is blocked by a proxy.

    Notes
    -----
    • Does NOT inject db via Depends — creates a fresh session per poll tick
      inside asyncio.to_thread() so the connection holds no long-lived session.
    • The endpoint itself is async; the DB query runs in a thread-pool worker.
    • X-Accel-Buffering: no — disables nginx response buffering so each SSE
      chunk is flushed to the client immediately.
    """
    from fastapi.responses import StreamingResponse
    from database import SessionLocal
    from sqlalchemy import func as _sqlfunc

    user_id = current_user.id

    async def _gen():
        last_total = -1
        while True:
            def _counts():
                _db = SessionLocal()
                try:
                    rows = (
                        _db.query(
                            UserNotification.severity,
                            _sqlfunc.count(UserNotification.id),
                        )
                        .filter(
                            UserNotification.user_id == user_id,
                            UserNotification.is_read.is_(False),
                        )
                        .group_by(UserNotification.severity)
                        .all()
                    )
                    c = {"critical": 0, "alert": 0, "info": 0, "total": 0}
                    for sev, cnt in rows:
                        k = (sev or "info").lower()
                        if k in c:
                            c[k] += cnt
                        c["total"] += cnt
                    return c
                finally:
                    _db.close()

            try:
                counts = await _asyncio.to_thread(_counts)
            except Exception as _exc:
                # yield a comment so the connection stays alive, then back off
                yield f": db-error {str(_exc)[:80]}\n\n"
                await _asyncio.sleep(15)
                continue

            if counts["total"] != last_total:
                last_total = counts["total"]
                yield f"data: {_json.dumps(counts)}\n\n"
            else:
                yield ": ping\n\n"   # keepalive — no data change

            await _asyncio.sleep(5)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# B)  ADMIN — Notification Template Configuration
# ══════════════════════════════════════════════════════════════════════════════

# ── System variable registry ──────────────────────────────────────────────────
# Variables the user can embed in subject/body templates using {{var}} syntax.
# Grouped by category for the UI variable picker.
# ── Schemas ───────────────────────────────────────────────────────────────────

class TemplateOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    event_type: str
    channel: str                            # "email" | "sms" | "inapp"
    name: Optional[str] = None             # NULL = default; named variants have a user label
    subject_template: Optional[str] = None
    body_template: str
    recipient_roles: List[str]
    extra_recipient_emails: List[str] = []
    # ── CC / BCC (email only) ────────────────────────────────────────────────
    cc_roles:   List[str] = []   # OrgRole UUIDs
    cc_emails:  List[str] = []   # individual addresses
    bcc_roles:  List[str] = []   # OrgRole UUIDs
    bcc_emails: List[str] = []   # individual addresses
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
    name: Optional[str] = Field(None, description="NULL = default template; named variants have a user label, e.g. 'Admin Alert'")
    subject_template: Optional[str] = Field(None, description="Subject line (email only)")
    body_template: str = Field(..., description="Message body. Use {{var}} placeholders.")
    recipient_roles: List[UUID] = Field(
        default=[], description="OrgRole UUIDs — all users under these roles get notified"
    )
    extra_recipient_emails: List[str] = Field(
        default=[], description="Individual email addresses (outside role membership)"
    )
    # ── CC / BCC (email channel only) ────────────────────────────────────────
    cc_roles:   List[UUID] = Field(default=[], description="OrgRole UUIDs to CC (email only)")
    cc_emails:  List[str]  = Field(default=[], description="Individual CC addresses (email only)")
    bcc_roles:  List[UUID] = Field(default=[], description="OrgRole UUIDs to BCC (email only)")
    bcc_emails: List[str]  = Field(default=[], description="Individual BCC addresses (email only)")
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
    name: Optional[str] = None    # Pass to rename a variant; pass "" to clear name (make default)
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    recipient_roles: Optional[List[UUID]] = None   # OrgRole UUIDs
    extra_recipient_emails: Optional[List[str]] = None
    # ── CC / BCC (email channel only) ────────────────────────────────────────
    cc_roles:   Optional[List[UUID]] = None   # Pass [] to clear
    cc_emails:  Optional[List[str]]  = None   # Pass [] to clear
    bcc_roles:  Optional[List[UUID]] = None   # Pass [] to clear
    bcc_emails: Optional[List[str]]  = None   # Pass [] to clear
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
    """
    Raise 403 unless the user's role has can_view on any notification module
    OR the role carries is_org_admin / is_dept_admin.

    Called internally by the `require_notif_admin` FastAPI dependency below.
    Direct callers outside this module should use `Depends(require_notif_admin)`.
    """
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


def require_notif_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency — checks notification admin permission once per request.
    FastAPI caches this result when the same Depends(...) instance is referenced
    multiple times in a single call chain, avoiding redundant DB queries.

    Usage in endpoint:
        @router.get("/...")
        def my_endpoint(admin: User = Depends(require_notif_admin)):
            org_id = _get_org(admin)
    """
    _require_admin(db, current_user)
    return current_user


def _get_org(user: User) -> UUID:
    # 400 Bad Request: missing org is a data/config issue, not an authorisation issue
    if not user.organization_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no organization.")
    return user.organization_id


# ── Endpoints — template catalogue ───────────────────────────────────────────

@router.get("/templates/event-types")
def list_event_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the merged event-type catalogue for the caller's organisation.

    Resolution:
      1. Start with all global entries (organization_id IS NULL) — seeded by seed.py.
      2. Overlay org-specific entries — they can override labels/descriptions
         or add entirely new event types custom to this org.

    The catalogue is populated exclusively by seed.py (_seed_notification_event_catalogue).
    If the table is empty (seed has not been run) an empty list is returned.
    """
    org_id = getattr(current_user, "organization_id", None)

    # Global platform-wide entries
    global_rows = (
        db.query(NotificationEventCatalogue)
        .filter(
            NotificationEventCatalogue.organization_id.is_(None),
            NotificationEventCatalogue.is_active.is_(True),
        )
        .all()
    )

    # Org-specific overrides / extensions
    org_rows = (
        db.query(NotificationEventCatalogue)
        .filter(
            NotificationEventCatalogue.organization_id == org_id,
            NotificationEventCatalogue.is_active.is_(True),
        )
        .all()
    ) if org_id else []

    if not global_rows and not org_rows:
        import logging
        logging.getLogger(__name__).warning(
            "NotificationEventCatalogue table is empty — run seed.py to populate it."
        )
        return []

    # Merge: org-specific entries override global ones for the same event_type
    merged: dict = {r.event_type: r for r in global_rows}
    for r in org_rows:
        merged[r.event_type] = r   # org-specific wins

    return [
        {
            "event_type":      r.event_type,
            "label":           r.label,
            "group":           r.group_name,
            "description":     r.description or "",
            "context_vars":    r.context_vars or [],
            "default_roles":   r.default_roles or [],
            # Flutter uses this to show the "Built-in" badge on global events
            "organization_id": str(r.organization_id) if r.organization_id else None,
            "is_global":       r.organization_id is None,
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

    Merges global system variables (organization_id IS NULL, seeded by seed.py)
    with any org-specific custom variables for the caller's organisation.
    Ordered by group then key; grouped by group_name for the UI accordion/chips.

    Each entry includes role_template_id (UUID | null) — the Flutter designer
    uses this to highlight variables relevant to the template's recipient role.
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

    if not rows:
        import logging
        logging.getLogger(__name__).warning(
            "NotificationVariable table is empty — run seed.py to populate it."
        )
        return []

    return [
        {
            "id":                str(r.id),
            "var":               "{{" + r.var_key + "}}",
            "var_key":           r.var_key,
            "label":             r.label,
            "group":             r.group_name,
            "description":       r.description,
            "sample_value":      r.sample_value,
            "resolver_key":      r.resolver_key,
            "is_system":         r.is_system,
            "role_template_ids": r.role_template_ids or [],
        }
        for r in rows
    ]


# ── Endpoint — Org roles ──────────────────────────────────────────────────────

@router.get("/org-roles")
def list_org_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all active OrgRole records for the current user's organisation.

    Includes both org-specific roles and global/platform roles (org_id IS NULL).
    When a name exists in both, the org-specific row is returned and the global
    one is suppressed (org wins).

    Used by:
      • Notification routing rule editor  → Recipient Roles picker
      • Notification template editor      → Recipient Roles picker

    Response shape per item:
        {
          "id":           "<uuid>",
          "name":         "EE TLSS",
          "value":        "EE TLSS",   # chip value
          "label":        "EE TLSS",   # chip label
          "is_org_admin":  false,
          "is_dept_admin": false,
        }
    """
    org_id = _get_org(current_user)
    return _get_org_roles(db, org_id)


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

    # Fetch active org-specific + global templates
    q = db.query(NotificationTemplate).filter(
        NotificationTemplate.is_active.is_(True),
        (NotificationTemplate.organization_id == org_id) |
        (NotificationTemplate.organization_id.is_(None))
    )
    if event_type:
        q = q.filter(NotificationTemplate.event_type == event_type)
    if channel:
        q = q.filter(NotificationTemplate.channel == channel)

    templates = q.order_by(
        # org-specific first (is_(None) → True/1 sorts last when asc)
        NotificationTemplate.organization_id.is_(None).asc(),
        NotificationTemplate.event_type,
        NotificationTemplate.channel,
    ).all()

    # De-duplicate:
    # • Default templates (name IS NULL): org-specific wins; suppress the global row
    #   for the same (event_type, channel).
    # • Named variants (name IS NOT NULL): each (event_type, channel, name) is unique;
    #   an org-specific named variant suppresses a global one with the same name.
    seen: set = set()
    result = []
    for t in templates:
        key = (t.event_type, t.channel, t.name)   # name=None → default de-dup
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

    # Deactivate any existing org-level template for same event/channel/name combo.
    # (Allows multiple named variants to coexist for the same event+channel.)
    db.query(NotificationTemplate).filter(
        NotificationTemplate.organization_id == org_id,
        NotificationTemplate.event_type == data.event_type,
        NotificationTemplate.channel == data.channel,
        NotificationTemplate.name == data.name,   # None deactivates the default; named targets its own slot
    ).update({"is_active": False})

    tmpl = NotificationTemplate(
        id=uuid4(),
        organization_id=org_id,
        event_type=data.event_type,
        channel=data.channel,
        name=data.name or None,
        subject_template=data.subject_template,
        body_template=data.body_template,
        recipient_roles=data.recipient_roles,
        extra_recipient_emails=data.extra_recipient_emails,
        cc_roles=[str(r) for r in (data.cc_roles or [])],
        cc_emails=data.cc_emails or [],
        bcc_roles=[str(r) for r in (data.bcc_roles or [])],
        bcc_emails=data.bcc_emails or [],
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
            name=data.name if data.name is not None else getattr(tmpl, 'name', None),
            subject_template=data.subject_template if data.subject_template is not None else tmpl.subject_template,
            body_template=data.body_template if data.body_template is not None else tmpl.body_template,
            recipient_roles=data.recipient_roles if data.recipient_roles is not None else list(tmpl.recipient_roles or []),
            extra_recipient_emails=data.extra_recipient_emails if data.extra_recipient_emails is not None else list(getattr(tmpl, 'extra_recipient_emails', None) or []),
            cc_roles=[str(r) for r in data.cc_roles] if data.cc_roles is not None else list(getattr(tmpl, 'cc_roles', None) or []),
            cc_emails=data.cc_emails if data.cc_emails is not None else list(getattr(tmpl, 'cc_emails', None) or []),
            bcc_roles=[str(r) for r in data.bcc_roles] if data.bcc_roles is not None else list(getattr(tmpl, 'bcc_roles', None) or []),
            bcc_emails=data.bcc_emails if data.bcc_emails is not None else list(getattr(tmpl, 'bcc_emails', None) or []),
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

    if data.name is not None:
        tmpl.name = data.name or None   # empty string → None (default)
    if data.subject_template is not None:
        tmpl.subject_template = data.subject_template
    if data.body_template is not None:
        tmpl.body_template = data.body_template
    if data.recipient_roles is not None:
        tmpl.recipient_roles = data.recipient_roles
    if data.extra_recipient_emails is not None:
        tmpl.extra_recipient_emails = data.extra_recipient_emails
    if data.cc_roles is not None:
        tmpl.cc_roles = [str(r) for r in data.cc_roles]
    if data.cc_emails is not None:
        tmpl.cc_emails = data.cc_emails
    if data.bcc_roles is not None:
        tmpl.bcc_roles = [str(r) for r in data.bcc_roles]
    if data.bcc_emails is not None:
        tmpl.bcc_emails = data.bcc_emails
    if data.attachment_vars is not None:
        tmpl.attachment_vars = data.attachment_vars
    if data.is_active is not None:
        tmpl.is_active = data.is_active

    db.commit()
    db.refresh(tmpl)
    return tmpl


@router.delete("/templates/event/{event_type}", status_code=status.HTTP_204_NO_CONTENT)
def reset_event_templates(
    event_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_notif_admin),
):
    """
    Hard-delete ALL org-specific template rows for this event_type.

    After deletion the GET /templates/event/{event_type} endpoint will return
    the global seed template (is_global=True) so the editor falls back to the
    platform default — no SQL patch required.

    Global templates (organization_id IS NULL) are never touched.
    """
    org_id = _get_org(current_user)
    rows = (
        db.query(NotificationTemplate)
        .filter(
            NotificationTemplate.event_type   == event_type,
            NotificationTemplate.organization_id == org_id,
        )
        .all()
    )
    for row in rows:
        db.delete(row)
    db.commit()


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
    # ── CC / BCC — email channel only; ignored for sms/inapp ────────────────
    cc_roles:   List[str] = []   # OrgRole UUIDs
    cc_emails:  List[str] = []   # individual addresses
    bcc_roles:  List[str] = []   # OrgRole UUIDs
    bcc_emails: List[str] = []   # individual addresses
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

    name=None  → creates/updates the default template (existing behaviour).
    name="..."  → creates/updates a named variant; multiple variants per event allowed.
    """
    event_type: str
    name: Optional[str] = Field(None, description="NULL = default template; provide a name for a variant, e.g. 'Admin Alert'")
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

        # Deactivate existing org-level row for this event/channel/name slot
        db.query(NotificationTemplate).filter(
            NotificationTemplate.organization_id == org_id,
            NotificationTemplate.event_type == data.event_type,
            NotificationTemplate.channel == channel,
            NotificationTemplate.name == (data.name or None),
        ).update({"is_active": False})

        if not cfg.enabled:
            # Insert a disabled-marker row so this org's preference blocks the
            # global fallback.  The row is_active=True so it wins in the query,
            # but org_channel_disabled=True tells the UI and dispatcher to skip it.
            disabled_marker = NotificationTemplate(
                id=uuid4(),
                organization_id=org_id,
                event_type=data.event_type,
                channel=channel,
                name=data.name or None,
                subject_template="",
                body_template="",
                recipient_roles=[],
                extra_recipient_emails=[],
                cc_roles=[], cc_emails=[], bcc_roles=[], bcc_emails=[],
                attachment_vars=[],
                org_channel_disabled=True,
                is_active=True,
            )
            db.add(disabled_marker)
            continue

        # Look up global default once; reuse for body, subject, and attachment_vars
        global_tmpl = None
        if not cfg.body_template or (not cfg.attachment_vars and channel == "email"):
            global_tmpl = db.query(NotificationTemplate).filter(
                NotificationTemplate.event_type == data.event_type,
                NotificationTemplate.channel == channel,
                NotificationTemplate.organization_id.is_(None),
            ).first()

        if not cfg.body_template:
            cfg.body_template = global_tmpl.body_template if global_tmpl else ""
            if not cfg.subject_template and global_tmpl:
                cfg.subject_template = global_tmpl.subject_template

        # Carry over attachment_vars from global default if caller didn't supply any
        effective_attachment_vars = cfg.attachment_vars
        if not effective_attachment_vars and channel == "email" and global_tmpl:
            effective_attachment_vars = list(getattr(global_tmpl, 'attachment_vars', None) or [])

        # Inherit recipient_roles from global when not explicitly provided.
        # Prevents org override from silently clearing recipients → no notifications sent.
        effective_recipient_roles = data.recipient_roles
        if not effective_recipient_roles and global_tmpl:
            effective_recipient_roles = list(global_tmpl.recipient_roles or [])

        new_tmpl = NotificationTemplate(
            id=uuid4(),
            organization_id=org_id,
            event_type=data.event_type,
            channel=channel,
            name=data.name or None,
            subject_template=cfg.subject_template,
            body_template=cfg.body_template or "",
            recipient_roles=effective_recipient_roles,
            extra_recipient_emails=data.extra_recipient_emails,
            # CC / BCC are email-only; set to empty for sms/inapp
            cc_roles=cfg.cc_roles   if channel == "email" else [],
            cc_emails=cfg.cc_emails if channel == "email" else [],
            bcc_roles=cfg.bcc_roles  if channel == "email" else [],
            bcc_emails=cfg.bcc_emails if channel == "email" else [],
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
    # CC / BCC (email channel only — empty for sms/inapp)
    cc_emails:  List[str] = []
    bcc_emails: List[str] = []
    cc_roles:   List[str] = []
    bcc_roles:  List[str] = []
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
        # Org explicitly disabled this channel — report it as absent so the
        # Flutter toggle shows OFF (same as if there were no template at all).
        if getattr(row, 'org_channel_disabled', False):
            return None
        return ChannelConfigOut(
            id=row.id,
            enabled=True,
            subject_template=row.subject_template,
            body_template=row.body_template,
            attachment_vars=list(getattr(row, 'attachment_vars', None) or []),
            # CC / BCC addresses and roles stored on the template row
            cc_emails =list(getattr(row, 'cc_emails',  None) or []),
            bcc_emails=list(getattr(row, 'bcc_emails', None) or []),
            cc_roles  =list(getattr(row, 'cc_roles',   None) or []),
            bcc_roles =list(getattr(row, 'bcc_roles',  None) or []),
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
    role_template_ids: List[str] = []   # RoleTemplate UUIDs (multi-role)
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
    role_template_ids: List[UUID] = Field(
        default=[], description="RoleTemplate UUIDs — variables relevant only to these roles"
    )


class VariableUpdate(BaseModel):
    label: Optional[str] = None
    group_name: Optional[str] = None
    description: Optional[str] = None
    sample_value: Optional[str] = None
    resolver_key: Optional[str] = None
    is_active: Optional[bool] = None
    role_template_ids: Optional[List[UUID]] = Field(
        default=None, description="Replace the full list of RoleTemplate UUIDs. Pass [] to clear."
    )


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
        role_template_ids=[str(r) for r in data.role_template_ids],
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

    # System variables: allow sample_value, description, is_active, and role_template_ids
    if var.is_system:
        if data.sample_value is not None:
            var.sample_value = data.sample_value
        if data.description is not None:
            var.description = data.description
        if data.is_active is not None:
            var.is_active = data.is_active
        if data.role_template_ids is not None:
            var.role_template_ids = [str(r) for r in data.role_template_ids]
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
        if data.role_template_ids is not None:
            var.role_template_ids = [str(r) for r in data.role_template_ids]

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
            {"value": r[0], "label": NotificationRoutingCategoryLabels.get(r[0])}
            for r in rows if r[0]
        ]
    # static fallback (used at module load time for TEST_TYPES constant)
    return [{"value": k, "label": v} for k, v in NotificationRoutingCategoryLabels.as_dict().items()]

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
    template_recipient_roles:   Optional[List[str]] = None  # template defaults (no override set)
    advanced_conditions:        Optional[dict] = None
    followup_action:            Optional[dict] = None  # auto follow-up ticket config
    priority:  int = 0
    # Per-channel template overrides (NULL = use default template)
    email_template_id: Optional[UUID] = None
    sms_template_id:   Optional[UUID] = None
    inapp_template_id: Optional[UUID] = None
    is_active: bool
    is_global: bool = False   # True if organization_id is None
    has_org_override: bool = False  # True if an org-specific rule covers the same event_type
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
    channels_enabled:    List[str] = Field(default=["inapp"])
    recipient_roles_override: Optional[List[str]] = None
    priority: int = Field(default=10, description="Higher priority wins. Default 10 for org rules.")
    followup_action: Optional[dict] = None  # auto follow-up ticket on alert/critical
    # Per-channel template overrides — NULL = use default template for that channel
    email_template_id: Optional[UUID] = None
    sms_template_id:   Optional[UUID] = None
    inapp_template_id: Optional[UUID] = None
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
    advanced_conditions: Optional[dict] = None
    followup_action: Optional[dict] = None  # auto follow-up ticket on alert/critical
    priority: Optional[int] = None
    # Per-channel template overrides — pass null to clear back to default
    email_template_id: Optional[UUID] = None
    sms_template_id:   Optional[UUID] = None
    inapp_template_id: Optional[UUID] = None
    is_active: Optional[bool] = None


# ── Helper: serialise a rule row ──────────────────────────────────────────────

def _rule_out(rule: NotificationRoutingRule, db: Optional[Session] = None) -> dict:
    # When no override is set, look up the global template's default recipient_roles
    # so the UI can show them as a read-only hint (e.g. on global-default cards).
    template_recipient_roles: Optional[list] = None
    if db is not None and not rule.recipient_roles_override:
        from models import NotificationTemplate as _NTmpl
        _tmpl = (
            db.query(_NTmpl)
            .filter(
                _NTmpl.event_type == rule.event_type,
                _NTmpl.organization_id.is_(None),
                _NTmpl.channel == "email",
            )
            .first()
        )
        if _tmpl and _tmpl.recipient_roles:
            template_recipient_roles = list(_tmpl.recipient_roles)

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
        "template_recipient_roles":   template_recipient_roles,
        "priority":  rule.priority,
        # Per-channel template overrides (None = use default)
        "email_template_id": getattr(rule, 'email_template_id', None),
        "sms_template_id":   getattr(rule, 'sms_template_id', None),
        "inapp_template_id": getattr(rule, 'inapp_template_id', None),
        "advanced_conditions": getattr(rule, 'advanced_conditions', None),
        "followup_action":     getattr(rule, 'followup_action', None),
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
    from models import RepairStageDefinition, TrWfStatus

    # Load live statuses from all active TR workflow definitions (deduplicated by status_code)
    seen_codes: set = set()
    tr_statuses = []
    for s in (
        db.query(TrWfStatus)
        .filter(TrWfStatus.is_active.is_(True))
        .order_by(TrWfStatus.sequence)
        .all()
    ):
        if s.status_code not in seen_codes:
            seen_codes.add(s.status_code)
            tr_statuses.append({"value": s.status_code, "label": s.status_name})

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
    """
    Return active OrgRole records for the given org.

    Includes:
      • Org-specific roles  (organization_id == org_id)  — defined by the org admin
      • Global/system roles (organization_id IS NULL)     — seeded platform-wide

    When two roles share the same name, the org-specific row wins (shown once).

    Each entry includes role_template_id (RoleTemplate.id, looked up by name).
    The Flutter template editor uses this to bridge:
      NotificationEventCatalogue.default_roles  (RoleTemplate UUIDs)
        → OrgRole.id  (what recipient_roles in NotificationTemplate stores)
    by matching role_template_id from this list against the default_roles UUIDs
    from the catalogue endpoint.
    """
    from sqlalchemy import or_ as _or_
    from models import RoleTemplate

    # Build name → RoleTemplate.id map for the role_template_id bridge field.
    rt_map: dict = {
        rt.name: str(rt.id)
        for rt in db.query(RoleTemplate).all()
    }

    if not organization_id:
        # No org context — return global roles only
        rows = (
            db.query(OrgRole)
            .filter(
                OrgRole.is_active.is_(True),
                OrgRole.organization_id.is_(None),
            )
            .order_by(OrgRole.name)
            .all()
        )
    else:
        rows = (
            db.query(OrgRole)
            .filter(
                OrgRole.is_active.is_(True),
                _or_(
                    OrgRole.organization_id == organization_id,
                    OrgRole.organization_id.is_(None),
                ),
            )
            # Org-specific rows first so they win the dedup below
            .order_by(
                OrgRole.organization_id.is_(None).asc(),  # False (0) = org-specific first
                OrgRole.name,
            )
            .all()
        )

    # Deduplicate by name — org-specific beats global for the same name
    seen: set = set()
    result = []
    for r in rows:
        if r.name not in seen:
            seen.add(r.name)
            result.append({
                "id":               str(r.id),
                "name":             r.name,
                "value":            r.name,   # chip/dropdown value
                "label":            r.name,   # chip/dropdown label
                "is_org_admin":     getattr(r, "is_org_admin",  False) or False,
                "is_dept_admin":    getattr(r, "is_dept_admin", False) or False,
                # Bridge field: RoleTemplate.id for this role name.
                # Lets Flutter map catalogue default_roles (RoleTemplate UUIDs)
                # to OrgRole.id values when pre-filling the template editor.
                "role_template_id": rt_map.get(r.name),
                "is_system_token":  False,
            })

    # Prepend system recipient tokens at the top so they appear first in the
    # Recipient Roles chip selector in the Flutter Notification Center UI.
    # ``is_system_token: True`` lets the UI render them with distinct styling.
    from services.notification_tokens import all_token_entries
    return all_token_entries() + result


def _get_equipment_types(db: Session) -> list:
    """
    Return equipment types with their test types grouped by activity category.
    Uses the same rich structure as the testing request form for consistency.

    Returns:
        [{
            "id": int,
            "name": str,
            "value": str,  # For backwards compatibility
            "label": str,  # For backwards compatibility
            "types_by_category": {
                "test": [{id, name, category_type, enable_cumulative, enable_calibration}, ...],
                "maintenance": [...],
                "inspection": [...],
                "repair_lifecycle": [...]
            }
        }]
    """
    from services.testing_request_service import TestingRequestService

    # Reuse the testing request service logic to get equipment types with tests
    service = TestingRequestService(db)
    equipment_types = service.list_equipment_types()

    # Add backwards-compatible value/label fields
    for eq in equipment_types:
        eq['value'] = eq['name']
        eq['label'] = eq['name']

    return equipment_types


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
        NotificationRoutingRule.is_active.is_(True),
        (NotificationRoutingRule.organization_id == org_id) |
        (NotificationRoutingRule.organization_id.is_(None) if include_global else False),
    )
    if event_type:
        q = q.filter(NotificationRoutingRule.event_type == event_type)
    if workflow_type:
        q = q.filter(
            NotificationRoutingRule.applicable_workflow_types.contains([workflow_type])
        )

    rules = q.order_by(
        NotificationRoutingRule.organization_id.is_(None).asc(),   # org-specific first
        NotificationRoutingRule.priority.desc(),
        NotificationRoutingRule.event_type,
    ).all()

    # event_types that have at least one org-specific rule in this result set
    org_overridden_event_types: set = {
        r.event_type for r in rules if r.organization_id is not None
    }

    rule_dicts = [_rule_out(r, db) for r in rules]

    # Mark global default rules that are (at least partially) superseded by an org rule
    for rd in rule_dicts:
        if rd.get("is_global") and rd["event_type"] in org_overridden_event_types:
            rd["has_org_override"] = True

    return rule_dicts


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
        email_template_id=data.email_template_id,
        sms_template_id=data.sms_template_id,
        inapp_template_id=data.inapp_template_id,
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule, db)


@router.put("/routing-rules/{rule_id}")
def update_routing_rule(
    rule_id: UUID,
    data: RoutingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update an org-specific routing rule.
    If rule_id belongs to a global (org=NULL) rule, an org-specific override copy
    is created automatically — the global default is left untouched.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = db.query(NotificationRoutingRule).filter(
        NotificationRoutingRule.id == rule_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found.")

    # ── Global rule → create org-specific override (same pattern as update_template) ──
    if rule.organization_id is None:
        override = NotificationRoutingRule(
            id=uuid4(),
            organization_id=org_id,
            event_type=rule.event_type,
            label=(
                data.label if data.label is not None else rule.label
            ),
            applicable_workflow_types=(
                data.applicable_workflow_types
                if data.applicable_workflow_types is not None
                else list(rule.applicable_workflow_types or [])
            ),
            applicable_equipment_types=(
                data.applicable_equipment_types
                if data.applicable_equipment_types is not None
                else list(rule.applicable_equipment_types or [])
            ),
            applicable_test_types=(
                data.applicable_test_types
                if data.applicable_test_types is not None
                else list(rule.applicable_test_types or [])
            ),
            applicable_status_from=(
                data.applicable_status_from
                if data.applicable_status_from is not None
                else rule.applicable_status_from
            ),
            applicable_status_to=(
                data.applicable_status_to
                if data.applicable_status_to is not None
                else rule.applicable_status_to
            ),
            channels_enabled=(
                data.channels_enabled
                if data.channels_enabled is not None
                else list(rule.channels_enabled or ["inapp"])
            ),
            recipient_roles_override=(
                data.recipient_roles_override
                if data.recipient_roles_override is not None
                else rule.recipient_roles_override
            ),
            advanced_conditions=(
                data.advanced_conditions
                if data.advanced_conditions is not None
                else rule.advanced_conditions
            ),
            followup_action=(
                data.followup_action
                if data.followup_action is not None
                else getattr(rule, 'followup_action', None)
            ),
            priority=(
                data.priority if data.priority is not None else rule.priority
            ),
            email_template_id=(
                data.email_template_id
                if data.email_template_id is not None
                else getattr(rule, 'email_template_id', None)
            ),
            sms_template_id=(
                data.sms_template_id
                if data.sms_template_id is not None
                else getattr(rule, 'sms_template_id', None)
            ),
            inapp_template_id=(
                data.inapp_template_id
                if data.inapp_template_id is not None
                else getattr(rule, 'inapp_template_id', None)
            ),
            is_active=(
                data.is_active if data.is_active is not None else True
            ),
        )
        db.add(override)
        db.commit()
        db.refresh(override)
        return _rule_out(override, db)

    # ── Org-specific rule: verify ownership then update in-place ──────────────
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
    if data.advanced_conditions is not None:
        rule.advanced_conditions = data.advanced_conditions
    if data.followup_action is not None:
        rule.followup_action = data.followup_action
    if data.priority is not None:
        rule.priority = data.priority
    # Template overrides — explicitly passed null clears back to default
    if 'email_template_id' in (data.model_fields_set or set()):
        rule.email_template_id = data.email_template_id
    if 'sms_template_id' in (data.model_fields_set or set()):
        rule.sms_template_id = data.sms_template_id
    if 'inapp_template_id' in (data.model_fields_set or set()):
        rule.inapp_template_id = data.inapp_template_id
    if data.is_active is not None:
        rule.is_active = data.is_active

    db.commit()
    db.refresh(rule)
    return _rule_out(rule, db)


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
            else list(source.channels_enabled or ["inapp"]),
        recipient_roles_override=data.recipient_roles_override or source.recipient_roles_override,
        advanced_conditions=data.advanced_conditions if data.advanced_conditions is not None else source.advanced_conditions,
        followup_action=data.followup_action if data.followup_action is not None else source.followup_action,
        priority=data.priority if data.priority is not None else 10,
        is_active=True,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _rule_out(clone, db)


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

from models import NotificationScheduleRule as _NSR, ScheduleFrequency as _SF

TRIGGER_TYPES = [
    {"value": "due_soon",          "label": "N days before due date"},
    {"value": "overdue",           "label": "When test is overdue"},
    {"value": "escalation",        "label": "When overdue > N days"},
    {"value": "status_transition", "label": "When workflow status changes"},
    {"value": "both",              "label": "Time-based AND status-based"},
    {"value": "recurring",         "label": "Recurring — fire on a set frequency"},
]

SEVERITY_LEVELS = ["info", "alert", "critical"]

# Days are derived from ScheduleFrequency.days — single source of truth in models.py.
FREQUENCY_OPTIONS = [
    {"value": _SF.daily.value,       "label": "Daily",          "days": _SF.daily.days},
    {"value": _SF.weekly.value,      "label": "Weekly",         "days": _SF.weekly.days},
    {"value": _SF.biweekly.value,    "label": "Every 2 weeks",  "days": _SF.biweekly.days},
    {"value": _SF.monthly.value,     "label": "Monthly",        "days": _SF.monthly.days},
    {"value": _SF.quarterly.value,   "label": "Quarterly",      "days": _SF.quarterly.days},
    {"value": _SF.semi_annual.value, "label": "Every 6 months", "days": _SF.semi_annual.days},
    {"value": _SF.yearly.value,      "label": "Yearly",         "days": _SF.yearly.days},
    {"value": _SF.triennial.value,   "label": "Every 3 years",  "days": _SF.triennial.days},
]

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
    id:                           str
    organization_id:              Optional[str]
    is_global:                    bool
    event_type:                   str
    label:                        str
    trigger_type:                 str
    offset_days:                  int
    trigger_on_status:            Optional[str]
    frequency:                    Optional[str]   # daily | weekly | biweekly | monthly | quarterly | semi_annual | yearly | triennial
    applicable_workflow_types:    List[str]
    applicable_categories:        List[str]
    applicable_equipment_types:   List[str]   # new — equipment type names; empty = all
    advanced_conditions:          Optional[dict]  # {"activity_types": [...specific test names...]}
    digest_columns:               Optional[List[dict]]  # [{"field":"equipment","header":"Equipment","style":""}]
    severity:                     str
    is_active:                    bool
    cts:                          Optional[str]
    mts:                          Optional[str]

    class Config:
        from_attributes = True


class ScheduleRuleCreate(BaseModel):
    event_type:                   str
    label:                        str
    trigger_type:                 str
    offset_days:                  int = 0
    trigger_on_status:            Optional[str] = None
    frequency:                    Optional[str] = None
    applicable_workflow_types:    Optional[List[str]] = None
    applicable_categories:        Optional[List[str]] = None
    applicable_equipment_types:   Optional[List[str]] = None
    advanced_conditions:          Optional[dict] = None
    digest_columns:               Optional[List[dict]] = None  # None = use system defaults
    severity:                     str = "info"
    is_active:                    bool = True


class ScheduleRuleUpdate(BaseModel):
    label:                        Optional[str] = None
    trigger_type:                 Optional[str] = None
    offset_days:                  Optional[int] = None
    trigger_on_status:            Optional[str] = None
    frequency:                    Optional[str] = None
    applicable_workflow_types:    Optional[List[str]] = None
    applicable_categories:        Optional[List[str]] = None
    applicable_equipment_types:   Optional[List[str]] = None
    advanced_conditions:          Optional[dict] = None
    digest_columns:               Optional[List[dict]] = None  # None = keep existing; [] = reset to defaults
    severity:                     Optional[str] = None
    is_active:                    Optional[bool] = None


def _srule_out(r: _NSR) -> dict:
    freq = r.frequency
    return {
        "id":                           str(r.id),
        "organization_id":              str(r.organization_id) if r.organization_id else None,
        "is_global":                    r.organization_id is None,
        "event_type":                   r.event_type,
        "label":                        r.label,
        "trigger_type":                 r.trigger_type,
        "offset_days":                  r.offset_days,
        "trigger_on_status":            r.trigger_on_status,
        "frequency":                    freq.value if hasattr(freq, "value") else freq,
        "applicable_workflow_types":    list(r.applicable_workflow_types or []),
        "applicable_categories":        list(r.applicable_categories or []),
        "applicable_equipment_types":   list(getattr(r, "applicable_equipment_types", None) or []),
        "advanced_conditions":          r.advanced_conditions,
        "digest_columns":               r.digest_columns,
        "severity":                     r.severity,
        "is_active":                    r.is_active,
        "cts":                          r.cts.isoformat() if r.cts else None,
        "mts":                          r.mts.isoformat() if r.mts else None,
    }


@router.get("/schedule-rules/digest-fields")
def get_digest_fields(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the supported field names and default column config for the
    digest table editor in the Notification Center UI.
    """
    from services.notification_service import NotificationService
    return {
        "default_columns": NotificationService.DEFAULT_DIGEST_COLUMNS,
        "supported_fields": [
            {"field": "equipment",  "label": "Equipment (UEIC)"},
            {"field": "department", "label": "Department"},
            {"field": "due_date",   "label": "Due Date"},
            {"field": "days",       "label": "Days Overdue / Remaining"},
            {"field": "request",    "label": "Request Number"},
            {"field": "status",     "label": "Status"},
            {"field": "priority",   "label": "Priority"},
            {"field": "category",   "label": "Category"},
            {"field": "assigned_to","label": "Assigned To"},
        ],
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
        "frequency_options":  FREQUENCY_OPTIONS,
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
        frequency=data.frequency or None,
        applicable_workflow_types=data.applicable_workflow_types or [],
        applicable_categories=data.applicable_categories or [],
        applicable_equipment_types=data.applicable_equipment_types or [],
        advanced_conditions=data.advanced_conditions,
        digest_columns=data.digest_columns or None,
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
    If rule_id belongs to a global (org=NULL) rule, an org-specific override copy
    is created automatically — the global default is left untouched.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    rule = db.query(_NSR).filter(_NSR.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Schedule rule not found.")

    # ── Global rule → create org-specific override ────────────────────────────
    if rule.organization_id is None:
        freq_src = rule.frequency
        freq_val = freq_src.value if hasattr(freq_src, "value") else freq_src
        override = _NSR(
            id=uuid4(),
            organization_id=org_id,
            event_type=rule.event_type,
            label=(
                data.label if data.label is not None else rule.label
            ),
            trigger_type=(
                data.trigger_type if data.trigger_type is not None else rule.trigger_type
            ),
            offset_days=(
                data.offset_days if data.offset_days is not None else rule.offset_days
            ),
            trigger_on_status=(
                data.trigger_on_status
                if data.trigger_on_status is not None
                else rule.trigger_on_status
            ),
            frequency=(
                (data.frequency or None)
                if data.frequency is not None
                else freq_val
            ),
            applicable_workflow_types=(
                data.applicable_workflow_types
                if data.applicable_workflow_types is not None
                else list(rule.applicable_workflow_types or [])
            ),
            applicable_categories=(
                data.applicable_categories
                if data.applicable_categories is not None
                else list(rule.applicable_categories or [])
            ),
            applicable_equipment_types=(
                data.applicable_equipment_types
                if data.applicable_equipment_types is not None
                else list(getattr(rule, "applicable_equipment_types", None) or [])
            ),
            advanced_conditions=(
                data.advanced_conditions
                if data.advanced_conditions is not None
                else rule.advanced_conditions
            ),
            digest_columns=(
                data.digest_columns
                if data.digest_columns is not None
                else getattr(rule, "digest_columns", None)
            ),
            severity=(
                data.severity if data.severity is not None else rule.severity
            ),
            is_active=(
                data.is_active if data.is_active is not None else True
            ),
        )
        db.add(override)
        db.commit()
        db.refresh(override)
        return _srule_out(override)

    # ── Org-specific rule: verify ownership then update in-place ──────────────
    if rule.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Cannot edit another org's schedule rule.")

    if data.label             is not None: rule.label             = data.label
    if data.trigger_type      is not None: rule.trigger_type      = data.trigger_type
    if data.offset_days       is not None: rule.offset_days       = data.offset_days
    if data.trigger_on_status is not None: rule.trigger_on_status = data.trigger_on_status
    if data.frequency         is not None: rule.frequency         = data.frequency or None
    if data.applicable_workflow_types is not None:
        rule.applicable_workflow_types = data.applicable_workflow_types
    if data.applicable_categories is not None:
        rule.applicable_categories = data.applicable_categories
    if data.applicable_equipment_types is not None:
        rule.applicable_equipment_types = data.applicable_equipment_types
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

    src_freq = source.frequency
    src_freq_val = src_freq.value if hasattr(src_freq, "value") else src_freq
    clone = _NSR(
        organization_id=org_id,
        event_type=source.event_type,
        label=data.label or f"[Override] {source.label}",
        trigger_type=data.trigger_type       or source.trigger_type,
        offset_days=data.offset_days         if data.offset_days is not None else source.offset_days,
        trigger_on_status=data.trigger_on_status or source.trigger_on_status,
        frequency=data.frequency if data.frequency is not None else src_freq_val,
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
        applicable_equipment_types=(
            data.applicable_equipment_types
            if data.applicable_equipment_types is not None
            else list(getattr(source, "applicable_equipment_types", None) or [])
        ),
        advanced_conditions=data.advanced_conditions or source.advanced_conditions,
        severity=data.severity or source.severity,
        is_active=True,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _srule_out(clone)


# ══════════════════════════════════════════════════════════════════════════════
# F)  ADMIN — Notification Log  (outbound send audit trail)
# ══════════════════════════════════════════════════════════════════════════════
#
# One row per recipient × channel × triggered event.
# The NotificationLog table is written by notification_service._dispatch_to_user()
# BEFORE the message is dispatched (status="pending") and updated to
# sent | failed | skipped | digested after delivery.
#
# Endpoints:
#   GET  /notifications/log             → paginated, filterable audit trail
#   POST /notifications/log/{id}/retry  → manually re-queue a failed send
# ══════════════════════════════════════════════════════════════════════════════

from models import NotificationLog as _NLog


class NotificationLogOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    event_type: str
    event_label: Optional[str] = None   # resolved from NotificationEventCatalogue
    channel: str
    recipient_id: Optional[UUID] = None
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None
    recipient_phone: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    status: str                          # pending | sent | failed | skipped | digested
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    source_id: Optional[UUID] = None
    source_type: Optional[str] = None
    created_at: Optional[datetime] = None   # alias for cts

    class Config:
        from_attributes = True


def _log_out(row: _NLog, event_label_map: dict, user_name_map: dict) -> dict:
    """Serialise a NotificationLog row to a dict for the API response."""
    # Build recipients list from the one-to-many child table
    recipients_out = [
        {
            "id":               str(r.id),
            "user_id":          str(r.user_id) if r.user_id else None,
            "user_name":        user_name_map.get(str(r.user_id)) if r.user_id else None,
            "email":            r.email,
            "phone":            r.phone,
            "rendered_subject": r.rendered_subject,
            "delivery_status":  r.delivery_status,
            "error_message":    r.error_message,
            "sent_at":          r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in (row.recipients or [])
    ]
    # Backward-compat scalar fields: populate from first recipient if the
    # batch-log fields are empty (legacy single-recipient logs will still have
    # recipient_email / recipient_id set directly on the log row).
    first_rcpt = next(iter(row.recipients), None) if row.recipients else None
    return {
        "id":               str(row.id),
        "organization_id":  str(row.organization_id) if row.organization_id else None,
        "event_type":       row.event_type,
        "event_label":      event_label_map.get(row.event_type, row.event_type),
        "channel":          row.channel,
        "recipient_id":     str(row.recipient_id) if row.recipient_id else (str(first_rcpt.user_id) if first_rcpt and first_rcpt.user_id else None),
        "recipient_name":   user_name_map.get(str(row.recipient_id)) if row.recipient_id else (user_name_map.get(str(first_rcpt.user_id)) if first_rcpt and first_rcpt.user_id else None),
        "recipient_email":  row.recipient_email or (first_rcpt.email if first_rcpt else None),
        "recipient_phone":  row.recipient_phone or (first_rcpt.phone if first_rcpt else None),
        "recipients":       recipients_out,
        "recipient_count":  len(recipients_out),
        "subject":          row.subject,
        "body":             row.body,
        "status":           row.status,
        "error_message":    row.error_message,
        "retry_count":      row.retry_count,
        "max_retries":      row.max_retries,
        "next_retry_at":    row.next_retry_at.isoformat() if row.next_retry_at else None,
        "sent_at":          row.sent_at.isoformat() if row.sent_at else None,
        "source_id":        str(row.source_id) if row.source_id else None,
        "source_type":      row.source_type,
        "created_at":       row.cts.isoformat() if row.cts else None,
    }


@router.get("/log")
def list_notification_log(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=200, description="Rows per page"),
    status: Optional[str] = Query(None, description="Filter: pending | sent | failed | skipped | digested"),
    event_type: Optional[str] = Query(None, description="Filter by event_type"),
    from_: Optional[datetime] = Query(None, alias="from", description="Created at ≥ this timestamp (ISO 8601)"),
    to: Optional[datetime] = Query(None, description="Created at ≤ this timestamp (ISO 8601)"),
    channel: Optional[str] = Query(None, description="Filter: email | sms | inapp"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Paginated outbound notification log for the current user's org.

    Returns one row per recipient × channel × event trigger.
    Org admins only.

    Query params
    ------------
    page, page_size : pagination (default page=1, page_size=50)
    status          : pending | sent | failed | skipped | digested
    event_type      : e.g. "eval_critical"
    from / to       : ISO 8601 timestamps for created_at range
    channel         : email | sms | inapp
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    q = db.query(_NLog).filter(_NLog.organization_id == org_id)

    if status:
        q = q.filter(_NLog.status == status)
    if event_type:
        q = q.filter(_NLog.event_type == event_type)
    if channel:
        q = q.filter(_NLog.channel == channel)
    if from_:
        q = q.filter(_NLog.cts >= from_)
    if to:
        q = q.filter(_NLog.cts <= to)

    total = q.count()

    rows = (
        q.order_by(_NLog.cts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # ── Build helper maps for enrichment (one query each, not N+1) ────────────
    # Event label map: event_type → label from NotificationEventCatalogue
    event_types_in_page = list({r.event_type for r in rows})
    label_map: dict = {}
    if event_types_in_page:
        cat_rows = (
            db.query(NotificationEventCatalogue.event_type, NotificationEventCatalogue.label)
            .filter(NotificationEventCatalogue.event_type.in_(event_types_in_page))
            .all()
        )
        label_map = {r.event_type: r.label for r in cat_rows}

    # User name map: user_id → "Firstname Lastname"
    # Collect IDs from both the legacy log.recipient_id and the new recipients table
    recipient_ids: set = set()
    for r in rows:
        if r.recipient_id:
            recipient_ids.add(str(r.recipient_id))
        for rcpt in (r.recipients or []):
            if rcpt.user_id:
                recipient_ids.add(str(rcpt.user_id))
    name_map: dict = {}
    if recipient_ids:
        from models import User as _User
        user_rows = (
            db.query(_User.id, _User.firstname, _User.lastname)
            .filter(_User.id.in_([UUID(rid) for rid in recipient_ids]))
            .all()
        )
        name_map = {
            str(u.id): f"{u.firstname or ''} {u.lastname or ''}".strip() or None
            for u in user_rows
        }

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_log_out(r, label_map, name_map) for r in rows],
    }


@router.post("/log/{log_id}/retry")
def retry_notification_log_entry(
    log_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually re-queue a single failed notification log entry for immediate retry.

    Only entries with status='failed' belonging to the current user's org can be
    retried. The retry counter is NOT incremented here — this is an admin-forced
    resend; the scheduled auto-retry limit still applies independently.

    Returns 202 Accepted with the updated log entry.
    Org admins only.
    """
    _require_admin(db, current_user)
    org_id = _get_org(current_user)

    log_row = db.query(_NLog).filter(
        _NLog.id == log_id,
        _NLog.organization_id == org_id,
    ).first()

    if not log_row:
        raise HTTPException(status_code=404, detail="Log entry not found.")

    if log_row.status not in ("failed", "skipped"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry a log entry with status='{log_row.status}'. Only 'failed' or 'skipped' entries can be retried.",
        )

    # Reset to pending so the background scheduler picks it up immediately,
    # or dispatch synchronously via the channel dispatcher right now.
    from services.notification_service import ChannelDispatcherRegistry
    dispatcher = ChannelDispatcherRegistry.get(log_row.channel)

    if dispatcher and log_row.channel != "inapp":
        # Attempt synchronous retry right now
        log_row.status = "pending"
        log_row.error_message = None
        db.commit()

        dispatcher.send(db, log_row, log_row.subject or "", log_row.body or "")
        db.commit()
    else:
        # No dispatcher (e.g. inapp or unknown channel) — just reset to pending
        # so a future scheduler run or next fire() picks it up.
        log_row.status = "pending"
        log_row.error_message = None
        log_row.next_retry_at = None
        db.commit()

    db.refresh(log_row)
    return {
        "id":      str(log_row.id),
        "status":  log_row.status,
        "message": "Notification queued for retry.",
    }
