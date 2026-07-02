"""
Public self-registration endpoint for org admins.
No authentication required — this is the sign-up flow.
"""

import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
import re

from database import get_db
from models import Organization, OrgOnboardingSteps, SystemConfig
from services.organization_service import OrganizationService
from utils.email_service import EmailService

router = APIRouter(prefix="/public", tags=["public"])

_email_svc = EmailService()


def _get_config(db: Session, key: str, default):
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        return default
    if row.value_type == "int":
        return int(row.value)
    if row.value_type == "bool":
        return row.value.lower() == "true"
    return row.value


class OrgRegistrationRequest(BaseModel):
    org_name: str
    org_code: str
    admin_firstname: str
    admin_lastname: str
    admin_email: EmailStr
    admin_phone: str = ""

    @field_validator("org_name", "org_code", "admin_firstname", "admin_lastname")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be blank")
        return v.strip()

    @field_validator("org_code")
    @classmethod
    def valid_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r'^[A-Z0-9_-]{2,20}$', v):
            raise ValueError("Code must be 2-20 chars, letters/digits/dash/underscore")
        return v


@router.post("/register-org", status_code=status.HTTP_201_CREATED)
def register_org(payload: OrgRegistrationRequest, db: Session = Depends(get_db)):
    # Check registration enabled
    if not _get_config(db, "registration_enabled", True):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Self-registration is currently disabled.")

    trial_days = _get_config(db, "trial_duration_days", 30)
    temp_password = _get_config(db, "default_temp_password", "Welcome@123")

    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=trial_days)

    svc = OrganizationService(db)
    try:
        org, admin_user = svc.create_organization_with_admin(
            name=payload.org_name,
            code=payload.org_code,
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
    db.commit()

    # Send welcome email
    login_url = os.getenv("BASE_URL", "http://localhost:3000")
    try:
        _email_svc.send_org_welcome(
            to_email=payload.admin_email,
            org_name=payload.org_name,
            admin_firstname=payload.admin_firstname,
            temp_password=temp_password,
            trial_days=trial_days,
            login_url=login_url,
        )
    except Exception:
        pass  # don't fail registration if email fails

    return {
        "message": "Organisation registered successfully. Check your email for login credentials.",
        "org_id": str(org.id),
        "trial_ends": trial_end.isoformat(),
    }
