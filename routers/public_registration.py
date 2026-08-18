"""
Public self-registration endpoint for org admins.
No authentication required — this is the sign-up flow.
"""

import logging
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
import json as _json
import re as _re
import uuid as _uuid

_log = logging.getLogger(__name__)

from database import get_db
from models import Module, Organization, OrgOnboardingSteps, OrgRole, OrgRolePermission, OrgUserRole, SystemConfig, User
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


def _provision_org_internal(
    db: Session,
    org_name: str,
    org_code: str,
    admin_email: str,
    admin_password: str,
    admin_firstname: str,
    admin_lastname: str,
    admin_phone: str,
    trial_start: datetime,
    trial_end: datetime,
    trial_days: int,
    license_server_org_id: str = None,
    upgrade_token: str = None,
):
    """
    Shared core: create org + admin + role + permissions + onboarding + welcome email.
    Returns (org, admin_user).
    """
    svc = OrganizationService(db)
    org, admin_user = svc.create_organization_with_admin(
        name=org_name,
        code=org_code,
        admin_email=admin_email,
        admin_password=admin_password,
        admin_firstname=admin_firstname,
        admin_lastname=admin_lastname,
        admin_phone=admin_phone,
        is_trial=True,
        trial_start_date=trial_start,
        trial_end_date=trial_end,
        trial_status="active",
    )

    db.add(OrgOnboardingSteps(organization_id=org.id))
    admin_user.usertype = "org_admin"

    if license_server_org_id:
        org.license_server_org_id = license_server_org_id
    if upgrade_token:
        org.upgrade_token = upgrade_token

    # Admin role + module permissions
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

    admin_role = db.query(OrgRole).filter_by(organization_id=org.id, name=default_role_name).first()
    if admin_role:
        admin_role.is_org_admin = True
        admin_role.is_active = True
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

    if modules_config.strip() == "*":
        modules = db.query(Module).filter(Module.is_active == True).all()
    else:
        try:
            module_names = _json.loads(modules_config)
        except Exception:
            module_names = [m.strip() for m in modules_config.split(",") if m.strip()]
        modules = db.query(Module).filter(Module.name.in_(module_names), Module.is_active == True).all()

    for mod in modules:
        if not db.query(OrgRolePermission).filter_by(org_role_id=admin_role.id, module_id=mod.id).first():
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

    if not db.query(OrgUserRole).filter_by(user_id=admin_user.id, org_role_id=admin_role.id).first():
        db.add(OrgUserRole(
            id=_uuid.uuid4(),
            user_id=admin_user.id,
            org_role_id=admin_role.id,
            department_id=None,
            is_active=True,
        ))

    db.commit()

    # Welcome email in background
    login_url = os.getenv("BASE_URL", "http://localhost:3000")
    def _send_welcome():
        try:
            EmailService().send_org_welcome(
                to_email=admin_email, org_name=org_name,
                admin_firstname=admin_firstname, temp_password=admin_password,
                trial_days=trial_days, login_url=login_url,
            )
        except Exception as _exc:
            _log.error("Welcome email FAILED for %s: %s", admin_email, _exc, exc_info=True)

    threading.Thread(target=_send_welcome, daemon=True).start()

    return org, admin_user


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

    try:
        org, admin_user = _provision_org_internal(
            db=db,
            org_name=payload.org_name,
            org_code=org_code,
            admin_email=payload.admin_email,
            admin_password=temp_password,
            admin_firstname=payload.admin_firstname,
            admin_lastname=payload.admin_lastname,
            admin_phone=payload.admin_phone,
            trial_start=now,
            trial_end=trial_end,
            trial_days=trial_days,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": "Organisation registered successfully. Check your email for login credentials.",
        "org_id": str(org.id),
        "trial_ends": trial_end.isoformat(),
    }


# ── License Server callback ──────────────────────────────────────────────────

class ProvisionOrgRequest(BaseModel):
    org_id: str                    # CW-KPTCL-A3F2 from license server
    org_name: str
    short_name: str = ""
    admin_email: EmailStr
    admin_first_name: str
    admin_last_name: str
    admin_phone: str = ""
    admin_password: str            # set by the org admin at enrollment
    product: str                   # e.g. TSMS_AI
    trial_days: int = 30
    valid_from: str = ""
    valid_until: str = ""
    upgrade_token: str = ""        # per-org token for the /upgrade page


@router.post("/provision-org", status_code=status.HTTP_201_CREATED)
def provision_org(
    payload: ProvisionOrgRequest,
    db: Session = Depends(get_db),
):
    """
    Called by the CogniWatt License Server after a new org enrolls.
    Creates the Organization + default admin User in this product's DB.
    Idempotent: if license_server_org_id already exists, returns existing record.
    """
    # Idempotency: check if org already provisioned
    existing = db.query(Organization).filter_by(license_server_org_id=payload.org_id).first()
    if existing:
        existing_user = db.query(User).filter_by(organization_id=existing.id).first()
        return {
            "success": True,
            "already_exists": True,
            "organization_id": str(existing.id),
            "user_id": str(existing_user.id) if existing_user else None,
        }

    # Check for email conflict
    if db.query(User).filter_by(email=payload.admin_email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email {payload.admin_email} already exists.",
        )

    now = datetime.now(timezone.utc)

    # Use exact dates from license server when available, fall back to trial_days
    try:
        trial_start = datetime.fromisoformat(payload.valid_from).replace(tzinfo=timezone.utc) if payload.valid_from else now
        trial_end = datetime.fromisoformat(payload.valid_until).replace(tzinfo=timezone.utc) if payload.valid_until else now + timedelta(days=payload.trial_days or 30)
    except ValueError:
        trial_start = now
        trial_end = now + timedelta(days=payload.trial_days or 30)

    # Use short_name for org code if provided, else derive from org_name
    if payload.short_name:
        base_code = payload.short_name.upper().replace(" ", "")[:20]
    else:
        base_code = _generate_org_code(payload.org_name)
    org_code = _unique_org_code(db, base_code)

    try:
        org, admin_user = _provision_org_internal(
            db=db,
            org_name=payload.org_name,
            org_code=org_code,
            admin_email=payload.admin_email,
            admin_password=payload.admin_password,
            admin_firstname=payload.admin_first_name,
            admin_lastname=payload.admin_last_name,
            admin_phone=payload.admin_phone,
            trial_start=trial_start,
            trial_end=trial_end,
            trial_days=payload.trial_days or 30,
            license_server_org_id=payload.org_id,
            upgrade_token=payload.upgrade_token or None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success": True,
        "already_exists": False,
        "organization_id": str(org.id),
        "user_id": str(admin_user.id),
    }


# ── License sync callback (called by license server on upgrade approval) ──────

class SyncLicenseRequest(BaseModel):
    org_id: str          # license server org id (CW-TNEB-4F27)
    product: str
    tier: str            # STARTER | STANDARD | ENTERPRISE
    is_trial: bool = False
    valid_from: str = ""
    valid_until: str = ""
    upgrade_token: str = ""


@router.post("/sync-license", status_code=200)
def sync_license(payload: SyncLicenseRequest, db: Session = Depends(get_db)):
    """
    Called by license server when an upgrade request is approved.
    Updates org subscription/trial dates so middleware and banner stay accurate.
    """
    org = db.query(Organization).filter_by(license_server_org_id=payload.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # Verify upgrade_token — prevents anyone from arbitrarily extending their own license
    if not payload.upgrade_token or not org.upgrade_token:
        raise HTTPException(status_code=403, detail="Missing upgrade token")
    if not secrets.compare_digest(payload.upgrade_token, org.upgrade_token):
        raise HTTPException(status_code=403, detail="Invalid upgrade token")

    now = datetime.now(timezone.utc)

    try:
        valid_from  = datetime.fromisoformat(payload.valid_from).replace(tzinfo=timezone.utc) if payload.valid_from  else now
        valid_until = datetime.fromisoformat(payload.valid_until).replace(tzinfo=timezone.utc) if payload.valid_until else now + timedelta(days=365)
    except ValueError:
        valid_from  = now
        valid_until = now + timedelta(days=365)

    org.is_trial              = payload.is_trial
    org.trial_status          = "active" if payload.is_trial else None
    org.subscription_status   = None if payload.is_trial else "active"
    org.trial_end_date        = valid_until if payload.is_trial  else org.trial_end_date
    org.subscription_end_date = valid_until if not payload.is_trial else org.subscription_end_date

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "org_id": payload.org_id, "valid_until": str(valid_until)}
