"""
Public self-registration endpoint for org admins.
No authentication required — this is the sign-up flow.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
import json as _json
import re as _re
import uuid as _uuid

_log = logging.getLogger(__name__)

from database import get_db
from models import Module, Organization, OrgOnboardingSteps, OrgRole, OrgRolePermission, OrgUserRole, SystemConfig
from services.organization_service import OrganizationService
from utils.email_service import EmailService

router = APIRouter(prefix="/public", tags=["public"])


def _get_config(db: Session, key: str, default):
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        return default
    if row.value_type == "int":
        return int(row.value)
    if row.value_type == "bool":
        return row.value.lower() == "true"
    return row.value


def _generate_org_code(org_name: str) -> str:
    """Derive a short uppercase code from the org name, max 20 chars."""
    # Take initials of each word, or first 10 chars of single word
    words = _re.sub(r'[^A-Za-z0-9 ]', '', org_name).split()
    if len(words) >= 2:
        code = ''.join(w[0] for w in words if w)[:10].upper()
    else:
        code = _re.sub(r'[^A-Z0-9]', '', org_name.upper())[:10]
    return code or 'ORG'


def _unique_org_code(db: Session, base_code: str) -> str:
    """Append a numeric suffix until the code is unique in organizations."""
    candidate = base_code[:20]
    exists = db.query(Organization).filter_by(code=candidate).first()
    if not exists:
        return candidate
    suffix = 1
    while True:
        candidate = f"{base_code[:18]}{suffix}"
        if not db.query(Organization).filter_by(code=candidate).first():
            return candidate
        suffix += 1


class OrgRegistrationRequest(BaseModel):
    org_name: str
    admin_firstname: str
    admin_lastname: str
    admin_email: EmailStr
    admin_phone: str = ""

    @field_validator("org_name", "admin_firstname", "admin_lastname")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be blank")
        return v.strip()


@router.post("/register-org", status_code=status.HTTP_201_CREATED)
def register_org(payload: OrgRegistrationRequest, db: Session = Depends(get_db)):
    # Check registration enabled
    if not _get_config(db, "registration_enabled", True):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Self-registration is currently disabled.")

    trial_days = _get_config(db, "trial_duration_days", 30)
    temp_password = _get_config(db, "default_temp_password", "Welcome@123")

    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=trial_days)

    # Auto-generate a unique org code from the name
    base_code = _generate_org_code(payload.org_name)
    org_code  = _unique_org_code(db, base_code)

    svc = OrganizationService(db)
    try:
        org, admin_user = svc.create_organization_with_admin(
            name=payload.org_name,
            code=org_code,
            admin_email=payload.admin_email,
            admin_password=temp_password,
            admin_firstname=payload.admin_firstname,
            admin_lastname=payload.admin_lastname,
            admin_phone=payload.admin_phone,
            # trial fields passed via **org_kwargs
            is_trial=True,
            trial_start_date=now,
            trial_end_date=trial_end,
            trial_status="active",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Create onboarding steps row
    steps = OrgOnboardingSteps(organization_id=org.id)
    db.add(steps)

    # Set admin usertype
    admin_user.usertype = "org_admin"

    # ── Auto-provision default admin role ─────────────────────────────────────
    # Config: default_admin_role_name (str)  — name of the auto-created role
    # Config: default_admin_role_modules (str) — "*" = all modules, or
    #         JSON array of module names e.g. '["Dashboard","Equipment","Testing"]'
    # Config: default_admin_role_permissions (str) — JSON object of flags, e.g.
    #         '{"can_view":true,"can_add":true,"can_edit":true,"can_delete":true,"can_approve":true}'
    default_role_name = _get_config(db, "default_admin_role_name", "System Administrator")
    modules_config    = _get_config(db, "default_admin_role_modules", "*")
    perms_config_raw  = _get_config(
        db, "default_admin_role_permissions",
        '{"can_view":true,"can_add":true,"can_edit":true,"can_delete":true,"can_approve":true}'
    )

    try:
        perms_flags = _json.loads(perms_config_raw)
    except Exception:
        perms_flags = {"can_view": True, "can_add": True, "can_edit": True,
                       "can_delete": True, "can_approve": True}

    # Reuse existing role if seed already created it, otherwise create fresh
    admin_role = (
        db.query(OrgRole)
        .filter_by(organization_id=org.id, name=default_role_name)
        .first()
    )
    if admin_role:
        admin_role.is_org_admin = True
        admin_role.is_active    = True
    else:
        admin_role = OrgRole(
            id=_uuid.uuid4(),
            organization_id=org.id,
            name=default_role_name,
            description="Auto-provisioned system administrator role",
            role_type="default",
            is_org_admin=True,
            is_active=True,
        )
        db.add(admin_role)
        db.flush()

    # Resolve which modules to grant
    if modules_config.strip() == "*":
        modules = db.query(Module).filter(Module.is_active == True).all()
    else:
        try:
            module_names = _json.loads(modules_config)
        except Exception:
            module_names = [m.strip() for m in modules_config.split(",") if m.strip()]
        modules = db.query(Module).filter(Module.name.in_(module_names), Module.is_active == True).all()

    for mod in modules:
        existing_perm = (
            db.query(OrgRolePermission)
            .filter_by(org_role_id=admin_role.id, module_id=mod.id)
            .first()
        )
        if not existing_perm:
            db.add(OrgRolePermission(
                id=_uuid.uuid4(),
                org_role_id=admin_role.id,
                module_id=mod.id,
                can_view=perms_flags.get("can_view", True),
                can_add=perms_flags.get("can_add", True),
                can_edit=perms_flags.get("can_edit", True),
                can_delete=perms_flags.get("can_delete", True),
                can_approve=perms_flags.get("can_approve", True),
                can_assign=perms_flags.get("can_assign", True),
                can_export=perms_flags.get("can_export", True),
                can_import=perms_flags.get("can_import", True),
            ))

    # Assign to admin user only if not already assigned
    existing_user_role = (
        db.query(OrgUserRole)
        .filter_by(user_id=admin_user.id, org_role_id=admin_role.id)
        .first()
    )
    if not existing_user_role:
        db.add(OrgUserRole(
            id=_uuid.uuid4(),
            user_id=admin_user.id,
            org_role_id=admin_role.id,
            department_id=None,
            is_active=True,
        ))
    db.commit()

    # Send welcome email (non-fatal — org is already created if this fails)
    login_url = os.getenv("BASE_URL", "http://localhost:3000")
    try:
        EmailService().send_org_welcome(
            to_email=payload.admin_email,
            org_name=payload.org_name,
            admin_firstname=payload.admin_firstname,
            temp_password=temp_password,
            trial_days=trial_days,
            login_url=login_url,
        )
        _log.info("Welcome email sent to %s for org %s", payload.admin_email, payload.org_name)
    except Exception as _exc:
        _log.error(
            "Welcome email FAILED for %s (org=%s): %s",
            payload.admin_email, payload.org_name, _exc, exc_info=True,
        )

    return {
        "message": "Organisation registered successfully. Check your email for login credentials.",
        "org_id": str(org.id),
        "trial_ends": trial_end.isoformat(),
    }
